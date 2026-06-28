"""Classical computer-vision front end for the card importer.

Pure OpenCV/NumPy. Given a photo of one or more Rush Hour cards, this module:

  * ``detect_cards``  — segment cards from the background and split touching
    strips into individual card quads (handles a single card, a row, or a grid
    whose rows are separated by a gap).
  * ``rectify_card``  — perspective-warp a quad to an upright canonical card and
    fix the 180° flip using the logo (the most saturated short edge is the top).
  * ``is_face_up``    — gate plain card backs out of the pipeline.
  * ``find_grid_corners`` / ``warp_board`` — anchor the 6x6 grid on its corners
    (smooth wall in 3 quadrants, grid in the 4th) and warp it to a clean square
    so every cell is exactly ``CELL`` px and the surrounding wall is excluded.
  * ``sample_board``  — per-cell occupancy (texture + chroma) and body color.

Tuning constants are grouped at the top; every stage can emit a debug overlay
through :class:`Debug`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

# --- tuning constants ---------------------------------------------------------
WORK_W = 1600            # width the detection stage runs at
TARGET_AR = 1.45         # card height/width (portrait), used to split strips
CW, CH = 600, 870        # canonical rectified-card size (px)
LOGO_SAT_MIN = 0.22      # top-strip saturated fraction below which it isn't a logo
BOARD_PX = 480           # warped board size; CELL = BOARD_PX/6
ROWS = COLS = 6
CELL = BOARD_PX // ROWS

MIN_CARD_AREA_FRAC = 0.01   # ignore foreground specks smaller than this
# Progressive (v_min, s_max) thresholds for "bright + desaturated" card pixels,
# tried from strict to loose until the components tile cleanly into cards.
MASK_PROFILES = [(120, 90), (108, 105), (135, 75), (95, 125), (150, 70)]
TEXTURE_REL = 3.0           # cell is occupied if texture > TEXTURE_REL * board ref
TEXTURE_MIN = 500.0         # ...but never below this absolute floor
CHROMA_OCC = 30.0           # ...or if its color is clearly non-gray

# Grid-corner detection: a grid corner is a vertex with smooth gray "wall" in 3
# quadrants and the textured grid in the 4th. Wall is smooth (low std) AND gray
# (the consistent board color) — the grayness gate is what stops false corners on
# the white card edge, the colored difficulty band, or the printed number.
STD_WIN = 9              # window for the local-texture (std) map
QUAD = 26               # quadrant probe size around a candidate corner
WALL_STD_MAX = 7.0      # a quadrant counts as smooth wall below this std
GRID_STD_MIN = 8.0      # ...and as grid (pebble cells or pieces) above this std
WALL_S_MAX = 50         # wall is desaturated (gray), not a colored band/piece
WALL_V_LO, WALL_V_HI = 130, 218   # wall value band: darker than white card, gray
GRID_AR = 1.0           # the 6x6 grid is square; used to pick a consistent rect
GRID_AR_TOL = 0.20      # accept rectangles within this of square
# Per-corner search regions as (x0, x1, y0, y1) fractions of the card; the top
# corners start below the decorative slot.
CORNER_REGIONS = {
    "TL": (0.04, 0.46, 0.18, 0.56), "TR": (0.54, 0.96, 0.18, 0.56),
    "BL": (0.04, 0.46, 0.50, 0.80), "BR": (0.54, 0.96, 0.50, 0.80),
}


@dataclass
class Debug:
    """Collects named BGR images for optional dumping by the pipeline."""
    enabled: bool = False
    images: dict = field(default_factory=dict)

    def add(self, name: str, img) -> None:
        if self.enabled:
            self.images[name] = img.copy()


# --- card detection -----------------------------------------------------------

def load_bgr(path) -> np.ndarray:
    img = cv2.imread(str(path))
    if img is None:
        raise FileNotFoundError(f"could not read image: {path}")
    return img


def _aspect_residual(lx: float, ly: float, nr: int, nc: int) -> float:
    """How far an ``nr`` x ``nc`` tiling of a block strays from portrait cards.

    0 ≈ each resulting card is a perfect ~1.45 portrait; large values mean the
    cards would be distorted (wrong aspect or landscape). This is the single
    constraint that keeps every split — auto OR externally forced — geometrically
    sane.
    """
    cw, ch = lx / nc, ly / nr
    res = abs(max(cw, ch) / min(cw, ch) - TARGET_AR)
    if ch < cw:                 # cards should be portrait, not landscape
        res += 0.5
    return res + 0.01 * (nr * nc)   # gently prefer fewer pieces on ties


def _grid_shape(lx: float, ly: float, maxn: int = 6) -> tuple[int, int, float]:
    """Best ``(n_rows, n_cols, residual)`` tiling a block into ~1.45 portrait cards.

    Handles a single card (1x1), a row/column strip, or a full 2-D grid. ``lx`` is
    the block's horizontal extent, ``ly`` the vertical extent.
    """
    best = (1, 1, 1e9)
    for nr in range(1, maxn + 1):
        for nc in range(1, maxn + 1):
            res = _aspect_residual(lx, ly, nr, nc)
            if res < best[2]:
                best = (nr, nc, res)
    return best


def _edges(box: np.ndarray):
    """Return (origin, horizontal_edge, vertical_edge) of a 4-corner rect."""
    e1, e2 = box[1] - box[0], box[3] - box[0]
    if abs(e1[0]) >= abs(e2[0]):
        return box[0], e1, e2
    return box[0], e2, e1


def _split_grid(box: np.ndarray, nr: int, nc: int) -> list[np.ndarray]:
    """Tile a rect (4 corners) into an ``nr`` x ``nc`` grid of card quads."""
    o, ex, ey = _edges(box)
    cards = []
    for i in range(nr):
        for j in range(nc):
            p = o + ex * (j / nc) + ey * (i / nr)
            cards.append(np.array([p, p + ex / nc, p + ex / nc + ey / nr,
                                   p + ey / nr], dtype=np.float32))
    return cards


def _segment(small: np.ndarray, v_min: int, s_max: int) -> list[np.ndarray]:
    """Foreground component rects (4 corners each) for one threshold profile."""
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    s, v = hsv[:, :, 1], hsv[:, :, 2]
    mask = (((v > v_min) & (s < s_max)) * 255).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    area = small.shape[0] * small.shape[1]
    rects = []
    for c in cnts:
        if cv2.contourArea(c) < MIN_CARD_AREA_FRAC * area:
            continue
        w, h = cv2.minAreaRect(c)[1]
        if min(w, h) >= 1:
            rects.append(cv2.boxPoints(cv2.minAreaRect(c)))
    return rects


def _split_components(rects, arrangement) -> tuple[list[np.ndarray], float]:
    """Split each component into a card grid; return (cards, mean grid residual).

    If ``arrangement`` (n_rows, n_cols) is given and there's a single dominant
    component, that layout is tried — but it is scored by the SAME aspect residual
    as an auto split, so a geometrically wrong hint (e.g. a transposed 5x2) loses
    to the sane auto tiling instead of producing distorted cards.
    """
    cards, residuals = [], []
    big = max(rects, key=lambda r: cv2.contourArea(r.astype(np.float32))) \
        if rects else None
    for r in rects:
        lx = np.linalg.norm(_edges(r)[1])
        ly = np.linalg.norm(_edges(r)[2])
        auto_nr, auto_nc, auto_res = _grid_shape(lx, ly)
        if arrangement and r is big and len(rects) == 1:
            nr, nc = arrangement
            res = _aspect_residual(lx, ly, nr, nc)
            if res > auto_res:          # the hint would distort the cards — ignore it
                nr, nc, res = auto_nr, auto_nc, auto_res
        else:
            nr, nc, res = auto_nr, auto_nc, auto_res
        cards += _split_grid(r, nr, nc)
        residuals.append(res)
    return cards, (float(np.mean(residuals)) if residuals else 1e9)


def well_shaped(cards: list[np.ndarray]) -> bool:
    """True if the cards' median aspect is a plausible portrait card (~1.45)."""
    if not cards:
        return False
    ars = []
    for q in cards:
        lx = max(np.linalg.norm(_edges(q)[1]), 1)
        ly = np.linalg.norm(_edges(q)[2])
        ars.append(ly / lx)
    return 1.25 <= float(np.median(ars)) <= 1.75


def detect_cards(img: np.ndarray, debug: Debug | None = None,
                 arrangement: tuple[int, int] | None = None) -> list[np.ndarray]:
    """Return card quads (full-res, 4 corners each), top->bottom, left->right.

    Tries progressively looser bright/desaturated thresholds and keeps the
    profile whose components tile most cleanly into ~1.45 portrait cards (handles
    rows, columns, and touching 2-D grids). ``arrangement`` optionally forces an
    ``(n_rows, n_cols)`` layout when an external backstop knows it.
    """
    h0, w0 = img.shape[:2]
    scale = WORK_W / w0
    small = cv2.resize(img, (int(w0 * scale), int(h0 * scale)))

    best_cards, best_score = [], 1e18
    for v_min, s_max in MASK_PROFILES:
        rects = _segment(small, v_min, s_max)
        if not rects:
            continue
        cards, residual = _split_components(rects, arrangement)
        # prefer clean grids (low residual); break ties toward more coverage
        covered = sum(cv2.contourArea(r.astype(np.float32)) for r in rects)
        score = residual - 1e-7 * covered
        if score < best_score:
            best_cards, best_score = cards, score
        if residual < 0.06:   # already a clean tiling — stop loosening
            break

    cards = [q / scale for q in best_cards]
    if cards:
        heights = [max(np.linalg.norm(_edges(q)[2]), 1) for q in cards]
        row_h = 0.6 * float(np.median(heights))
        cards.sort(key=lambda q: (round(q.mean(0)[1] / row_h), q.mean(0)[0]))

    if debug is not None and debug.enabled:
        vis = small.copy()
        for i, q in enumerate(cards, 1):
            cv2.polylines(vis, [(q * scale).astype(int)], True, (0, 255, 0), 3)
            cc = (q * scale).mean(0).astype(int)
            cv2.putText(vis, str(i), tuple(cc), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                        (0, 0, 255), 3)
        debug.add("1_detect", vis)
    return cards


# --- rectification + orientation ---------------------------------------------

def _order_quad(pts: np.ndarray) -> np.ndarray:
    pts = np.array(pts, dtype=np.float32)
    s = pts.sum(1)
    d = pts[:, 0] - pts[:, 1]
    return np.array([pts[np.argmin(s)], pts[np.argmax(d)],
                     pts[np.argmax(s)], pts[np.argmin(d)]], dtype=np.float32)


def _saturated_frac(strip: np.ndarray) -> float:
    hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
    return float(((hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 60)).mean())


def rectify_card(img: np.ndarray, quad: np.ndarray) -> np.ndarray:
    """Warp a card quad to an upright CW x CH image (logo at top)."""
    q = _order_quad(quad)
    wlen = np.linalg.norm(q[1] - q[0])
    hlen = np.linalg.norm(q[3] - q[0])
    if wlen > hlen:  # detected sideways -> map so the long edge becomes height
        dst = np.array([[CW, 0], [CW, CH], [0, CH], [0, 0]], dtype=np.float32)
    else:
        dst = np.array([[0, 0], [CW, 0], [CW, CH], [0, CH]], dtype=np.float32)
    card = cv2.warpPerspective(img, cv2.getPerspectiveTransform(q, dst), (CW, CH))
    # 180° check. The "RUSH HOUR" logo end is always densely saturated (top strip
    # fraction >= ~0.28 across every sample card), so only flip when the top is
    # clearly NOT a logo — otherwise a vivid difficulty band (e.g. the blue
    # ADVANCED bar) that out-saturates the logo would spuriously invert the card.
    e = int(0.12 * CH)
    top, bottom = _saturated_frac(card[:e]), _saturated_frac(card[-e:])
    if top < LOGO_SAT_MIN and bottom > top:
        card = cv2.rotate(card, cv2.ROTATE_180)  # genuinely upside down
    return card


def is_face_up(card: np.ndarray) -> bool:
    """Face-up cards have a colorful grid; backs are near-uniform."""
    mid = card[int(0.20 * CH):int(0.80 * CH), int(0.08 * CW):int(0.92 * CW)]
    hsv = cv2.cvtColor(mid, cv2.COLOR_BGR2HSV)
    colorful = float(((hsv[:, :, 1] > 70) & (hsv[:, :, 2] > 60)).mean())
    hue_spread = float(np.std(hsv[:, :, 0][hsv[:, :, 1] > 70])) if colorful else 0.0
    return colorful > 0.04 and hue_spread > 15


# --- grid localization (corner-anchored) --------------------------------------

def _std_map(card: np.ndarray) -> np.ndarray:
    """Local intensity std: ~0 on the smooth gray wall, high on the busy grid."""
    g = cv2.cvtColor(card, cv2.COLOR_BGR2GRAY).astype(np.float32)
    mean = cv2.boxFilter(g, -1, (STD_WIN, STD_WIN))
    sq = cv2.boxFilter(g * g, -1, (STD_WIN, STD_WIN))
    return np.sqrt(np.maximum(sq - mean * mean, 0))


def _corner_candidates(card: np.ndarray) -> dict:
    """Find each grid corner: 3 quadrants smooth GRAY wall, 1 quadrant textured grid."""
    h, w = card.shape[:2]
    half = QUAD // 2
    hsv = cv2.cvtColor(card, cv2.COLOR_BGR2HSV)
    grayish = ((hsv[:, :, 1] < WALL_S_MAX) & (hsv[:, :, 2] > WALL_V_LO)
               & (hsv[:, :, 2] < WALL_V_HI)).astype(np.float32)
    std = _std_map(card)
    sb = cv2.boxFilter(std, -1, (QUAD, QUAD))            # mean texture / quadrant
    wallq = cv2.boxFilter(((std < WALL_STD_MAX) & (grayish > 0)).astype(np.float32),
                          -1, (QUAD, QUAD))              # wall-ness / quadrant
    gridq = cv2.boxFilter((std > GRID_STD_MIN).astype(np.float32), -1, (QUAD, QUAD))

    def d4(a):
        R = lambda dy, dx: np.roll(np.roll(a, dy, 0), dx, 1)
        return {"br": R(-half, -half), "tl": R(half, half),
                "tr": R(half, -half), "bl": R(-half, half)}

    St, Wq, Gq = d4(sb), d4(wallq), d4(gridq)
    # per corner: the three wall quadrants + the single grid quadrant
    spec = {"TL": (("tl", "tr", "bl"), "br"), "TR": (("tl", "tr", "br"), "bl"),
            "BL": (("tl", "bl", "br"), "tr"), "BR": (("tr", "bl", "br"), "tl")}

    corners = {}
    for name, (walls, grid) in spec.items():
        x0, x1, y0, y1 = CORNER_REGIONS[name]
        region = np.zeros((h, w), bool)
        region[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)] = True
        resp = St[grid] - sum(St[k] for k in walls) / 3.0
        for wall_min, grid_min in ((0.55, 0.45), (0.4, 0.3), (0.25, 0.2)):
            valid = (Gq[grid] > grid_min)
            for k in walls:
                valid = valid & (Wq[k] > wall_min)
            scored = np.where(valid & region, resp, -1e9)
            if scored.max() > -1e9:
                yy, xx = np.unravel_index(int(np.argmax(scored)), scored.shape)
                corners[name] = (int(xx), int(yy))
                break
    return corners


def find_grid_corners(card: np.ndarray) -> np.ndarray:
    """Locate the 6x6 grid as an AXIS-ALIGNED rectangle; return ``[TL, TR, BR, BL]``.

    Each grid corner is the vertex where three quadrants are smooth gray wall and
    the fourth is the textured grid. Because the grid is square (6x6 square cells),
    the four corners are reconciled into the axis-aligned rectangle whose aspect is
    closest to square — this rejects a single drifted corner and, crucially,
    guarantees the warped board is an ORTHOGONAL projection (square cells), never a
    skewed trapezoid.
    """
    c = _corner_candidates(card)
    if len(c) < 4:
        raise ValueError(f"grid corners not found ({sorted(c)})")
    x_left = {c["TL"][0], c["BL"][0]}
    x_right = {c["TR"][0], c["BR"][0]}
    y_top = {c["TL"][1], c["TR"][1]}
    y_bottom = {c["BL"][1], c["BR"][1]}

    best = None
    for xl in x_left:
        for xr in x_right:
            for yt in y_top:
                for yb in y_bottom:
                    bw, bh = xr - xl, yb - yt
                    if bw < 100 or bh < 100 or abs(bw / bh - GRID_AR) > GRID_AR_TOL:
                        continue
                    penalty = abs(bw / bh - GRID_AR)
                    if best is None or penalty < best[0]:
                        best = (penalty, (xl, yt, xr, yb))
    if best is None:   # corners too inconsistent to form a square grid
        raise ValueError("grid corners do not form a square rectangle")
    xl, yt, xr, yb = best[1]
    return np.array([[xl, yt], [xr, yt], [xr, yb], [xl, yb]], dtype=np.float32)


def warp_board(card: np.ndarray, corners: np.ndarray) -> np.ndarray:
    """Warp the grid (given as ``[TL, TR, BR, BL]``) to a clean square board."""
    dst = np.array([[0, 0], [BOARD_PX, 0], [BOARD_PX, BOARD_PX], [0, BOARD_PX]],
                   dtype=np.float32)
    return cv2.warpPerspective(card, cv2.getPerspectiveTransform(corners, dst),
                               (BOARD_PX, BOARD_PX))


# --- per-cell sampling --------------------------------------------------------

def white_balance(board: np.ndarray) -> np.ndarray:
    """Neutralize the lighting cast using the board's own gray as a reference.

    The empty pebble cells are achromatic, so the median of the least-saturated
    pixels is "true gray". Scaling each channel to equalize it makes the pale
    piece colors far more consistent and separable.
    """
    hsv = cv2.cvtColor(board, cv2.COLOR_BGR2HSV)
    gray_pixels = board[hsv[:, :, 1] < 40].reshape(-1, 3).astype(np.float32)
    if len(gray_pixels) < 100:
        return board
    ref = np.median(gray_pixels, 0)
    ref[ref < 1] = 1
    gain = ref.mean() / ref
    return np.clip(board.astype(np.float32) * gain, 0, 255).astype(np.uint8)


def sample_board(board: np.ndarray):
    """Return ``(occupancy 6x6 bool, color 6x6x3 BGR, texture 6x6)``.

    Occupancy uses texture (the molded 3D pieces are busy; the pebble board is
    smooth) with an adaptive per-card threshold, OR a clear color cast. The cell
    color is the median of the most-chromatic 40% of the central patch (the piece
    body, ignoring gray show-through and specular highlights).
    """
    board = white_balance(board)
    lab = cv2.cvtColor(board, cv2.COLOR_BGR2LAB).astype(np.float32)
    hsv = cv2.cvtColor(board, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(board, cv2.COLOR_BGR2GRAY)
    lap = cv2.Laplacian(gray, cv2.CV_32F, ksize=3)
    half = int(0.28 * CELL)

    texture = np.zeros((ROWS, COLS))
    chroma = np.zeros((ROWS, COLS))
    color = np.zeros((ROWS, COLS, 3), np.uint8)
    for r in range(ROWS):
        for c in range(COLS):
            cy, cx = r * CELL + CELL // 2, c * CELL + CELL // 2
            ys, xs = slice(cy - half, cy + half), slice(cx - half, cx + half)
            L = lab[ys, xs].reshape(-1, 3)
            bgr = board[ys, xs].reshape(-1, 3)
            V = hsv[ys, xs].reshape(-1, 3)[:, 2]
            ch = np.sqrt((L[:, 1] - 128) ** 2 + (L[:, 2] - 128) ** 2)
            texture[r, c] = lap[ys, xs].var()
            chroma[r, c] = np.percentile(ch, 85)
            color[r, c] = _body_color(bgr, ch, V)

    board_ref = float(np.percentile(texture, 25))  # quiet (empty) cells
    occ = (texture > max(TEXTURE_REL * board_ref, TEXTURE_MIN)) | (chroma > CHROMA_OCC)
    return occ, color, texture


def _body_color(bgr: np.ndarray, chroma: np.ndarray, value: np.ndarray):
    """Robust piece-body color from a cell patch.

    Discards specular glare (near-white highlights) and shadow/groove pixels, then
    takes the median of the most-chromatic remaining pixels — the molded piece
    body — so the result is insensitive to lighting, gloss and gray show-through.
    """
    keep = (value > 70) & (value < 232)
    if keep.sum() < 20:
        keep = np.ones(len(value), bool)
    ch = np.where(keep, chroma, -1.0)
    n = int(keep.sum())
    idx = np.argsort(ch)[-max(20, n // 2):]   # most-chromatic half of kept pixels
    return np.median(bgr[idx], 0).astype(np.uint8)


def swatch(occ: np.ndarray, color: np.ndarray) -> np.ndarray:
    """Render the classified grid, each occupied cell regularized to the palette.

    Occupied cells are snapped to their nearest codebook color so the panel shows
    the *regularized* classification (the 16 known vehicle colors), making misreads
    easy to spot at a glance.
    """
    from tools.cv_import import codebook

    img = np.zeros((BOARD_PX, BOARD_PX, 3), np.uint8)
    for r in range(ROWS):
        for c in range(COLS):
            if occ[r, c]:
                cell = codebook.CODEBOOK_BGR[codebook.quantize(color[r, c])]
            else:
                cell = (50, 50, 50)
            img[r * CELL:(r + 1) * CELL, c * CELL:(c + 1) * CELL] = cell
            cv2.rectangle(img, (c * CELL, r * CELL),
                          ((c + 1) * CELL, (r + 1) * CELL), (0, 0, 0), 1)
    return img
