"""Assemble a classified 6x6 grid into vehicle records.

Adjacent occupied cells of similar color are grouped into blobs; each blob must
be a straight run of 2 (car) or 3 (truck/bus) cells. The prime ``X`` is the red
horizontal pair on the exit row. Remaining blobs get palette ids by nearest
color within their length class — note that for non-prime pieces the exact id is
only cosmetic (it sets the rendered color), so a near miss never breaks the
puzzle; geometry and the identity of ``X`` are what must be right.
"""
from __future__ import annotations

import cv2
import numpy as np

from trafficjam.data.palette import SPECS

EXIT_ROW = 2
CAR_IDS = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K"]
BIG_IDS = ["O", "P", "Q", "R"]  # trucks + buses (length 3)
# A candidate piece may only group cells within this CIELab distance of each
# other. Adjacent same-piece cells measure mostly <~35 (median 2-5, glossy pieces
# up to ~34); adjacent different pieces measure >~40 — so this blocks merging
# dissimilar colors while tolerating within-piece lighting/gloss variation.
HOMOGENEITY = 36.0


def _lab(bgr) -> np.ndarray:
    arr = np.uint8([[list(bgr)]])
    return cv2.cvtColor(arr, cv2.COLOR_BGR2LAB)[0, 0].astype(float)


# Palette reference colors in Lab (printed colors differ from these, so matches
# are best-effort — fine because non-prime identity is cosmetic).
_PAL_LAB = {vid: _lab(spec.color[::-1]) for vid, spec in SPECS.items()}  # RGB->BGR


def _candidates(occupied: set, color: np.ndarray):
    """Straight 2/3-cell runs within ``occupied`` that are color-HOMOGENEOUS.

    Runs whose cells span more than ``HOMOGENEITY`` Lab are dropped, so the tiler
    can never form a piece out of dissimilar colors. The remaining color spread is
    the cost (color-consistent tilings win).
    """
    cands = []  # (cells, orient, length, cost)
    for (r, c) in occupied:
        for length in (2, 3):
            for cells in ([(r, c + i) for i in range(length)],
                          [(r + i, c) for i in range(length)]):
                if not all(x in occupied for x in cells):
                    continue
                spread = _spread(cells, color)
                if spread <= HOMOGENEITY:
                    orient = "H" if cells[0][0] == cells[1][0] else "V"
                    cands.append((cells, orient, length, spread))
    return cands


def _is_red(bgr) -> bool:
    """True for the prime car's vivid red (high a*), excluding orange (high b*)."""
    lab = _lab(bgr)
    a, b = lab[1] - 128, lab[2] - 128
    return a > 20 and (a - b) > 8


def _find_x_cells(occ: np.ndarray, color: np.ndarray):
    """Locate the prime X as a horizontal pair of red cells (prefers exit row)."""
    rows, cols = occ.shape
    pairs = []
    for r in range(rows):
        for c in range(cols - 1):
            if (occ[r, c] and occ[r, c + 1]
                    and _is_red(color[r, c]) and _is_red(color[r, c + 1])):
                a = (_lab(color[r, c])[1] + _lab(color[r, c + 1])[1]) / 2 - 128
                pairs.append((r == EXIT_ROW, a, r, c))
    if not pairs:
        return None
    pairs.sort(reverse=True)  # exit-row first, then reddest
    _, _, r, c = pairs[0]
    return [(r, c), (r, c + 1)]


def _spread(cells, color) -> float:
    """Largest color step between ADJACENT cells of a run (cells are in order).

    Using the adjacent step, not the end-to-end distance, lets a long piece with a
    gentle lighting gradient stay together (each step is small) while still
    rejecting a run that crosses a real color boundary (one big step).
    """
    labs = [_lab(color[y, x]) for y, x in cells]
    return max(np.linalg.norm(labs[i] - labs[i + 1]) for i in range(len(labs) - 1))


def _exact_cover(occupied: set, cands: list):
    """Minimum-color-cost exact tiling of the occupied cells (branch & bound).

    Every cell must be covered by exactly one straight 2/3-piece; among all such
    tilings we return the one whose pieces are most color-consistent (real pieces
    are monochrome, so the natural tiling wins). ``None`` if no perfect tiling
    exists (i.e. the occupancy was misread).
    """
    by_cell: dict = {cell: [] for cell in occupied}
    for cand in cands:
        for cell in cand[0]:
            by_cell[cell].append(cand)

    best: list = [None, float("inf")]  # [pieces, total_cost]

    def solve(remaining: set, acc: float, chosen: list) -> None:
        if acc >= best[1]:
            return  # prune: can't beat the best cover found so far
        if not remaining:
            best[0], best[1] = list(chosen), acc
            return
        cell = min(remaining, key=lambda c: len(by_cell[c]))  # most constrained
        options = sorted((p for p in by_cell[cell] if set(p[0]) <= remaining),
                         key=lambda p: p[3])
        for piece in options:
            chosen.append(piece)
            solve(remaining - set(piece[0]), acc + piece[3], chosen)
            chosen.pop()

    solve(set(occupied), 0.0, [])
    return best[0]


def _greedy_cover(occupied: set, cands: list):
    """Best-effort tiling when no exact cover exists (e.g. an isolated stray cell
    in the blob). Longer pieces are placed first so a 3-cell truck is never split
    into a 2-car plus an orphan; ties break toward color consistency. Returns
    ``(pieces, leftover)``.
    """
    used: set = set()
    chosen = []
    for cand in sorted(cands, key=lambda p: (-p[2], p[3])):  # length desc, spread asc
        if all(cell not in used for cell in cand[0]):
            chosen.append(cand)
            used.update(cand[0])
    return chosen, occupied - used


def _components(cells: set) -> list[set]:
    """4-connected blobs of occupied cells (color-agnostic)."""
    seen: set = set()
    comps = []
    for start in cells:
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        comp = set()
        while stack:
            y, x = stack.pop()
            comp.add((y, x))
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (y + dy, x + dx)
                if n in cells and n not in seen:
                    seen.add(n)
                    stack.append(n)
        comps.append(comp)
    return comps


def assemble(occ: np.ndarray, color: np.ndarray):
    """Return ``(vehicles, warnings)``.

    Occupied cells are tiled into straight length-2/3 pieces by exact cover over
    color-HOMOGENEOUS candidates only, so a piece is always a single color and
    dissimilar colors are never merged. Each piece's color is then regularized to
    the palette codebook for its id. Untileable strays are flagged for review.
    """
    warnings: list[str] = []
    occupied = {(r, c) for r in range(occ.shape[0]) for c in range(occ.shape[1])
                if occ[r, c]}

    used: set[str] = set()
    vehicles = []

    # Prime X is vivid red and always a horizontal pair on the exit row. Detect
    # it directly by color and carve it out before tiling.
    x_cells = _find_x_cells(occ, color)
    if x_cells is not None:
        (r, c), _ = x_cells
        vehicles.append({"id": "X", "row": r, "col": c, "len": 2, "orient": "H"})
        used.add("X")
        occupied -= set(x_cells)

    # Tile each 4-connected blob independently so one un-coverable stray cell
    # can't wreck the tiling of the rest of the board.
    leftovers: list = []
    cover = []
    for comp in _components(occupied):
        cands = _candidates(comp, color)
        part = _exact_cover(comp, cands)
        if part is None:
            part, stray = _greedy_cover(comp, cands)
            leftovers += sorted(stray)
        cover += part
    if leftovers:
        warnings.append(f"{len(leftovers)} cell(s) could not be tiled "
                        f"(dissimilar/noisy colors): {leftovers}")
    pieces = []  # (orient, length, row, col, mean_bgr)
    for cells, orient, length, _ in cover:
        row = min(r for r, _ in cells)
        col = min(c for _, c in cells)
        mean_bgr = np.median([color[y, x] for y, x in cells], 0)
        pieces.append((orient, length, row, col, mean_bgr))

    if "X" not in used:
        # Fallback: no red pair detected — take the reddest horizontal car pair.
        cars = [p for p in pieces if p[1] == 2 and p[0] == "H"]
        cars.sort(key=lambda p: (p[2] == EXIT_ROW, _lab(p[4])[1]), reverse=True)
        if cars:
            o, l, row, col, _ = cars[0]
            vehicles.append({"id": "X", "row": row, "col": col, "len": 2,
                             "orient": o})
            used.add("X")
            pieces.remove(cars[0])
        else:
            warnings.append("no horizontal car found for prime X")

    # Regularize each piece's color to the palette and assign an id within the
    # right length class (cosmetic for non-prime pieces; geometry is what matters).
    for orient, length, row, col, mean_bgr in pieces:
        pool = CAR_IDS if length == 2 else BIG_IDS
        lab = _lab(mean_bgr)
        ranked = sorted(pool, key=lambda vid: np.linalg.norm(lab - _PAL_LAB[vid]))
        vid = next((v for v in ranked if v not in used), None)
        if vid is None:
            warnings.append(f"ran out of ids for length-{length} piece at "
                            f"({row},{col})")
            continue
        used.add(vid)
        vehicles.append({"id": vid, "row": row, "col": col,
                         "len": length, "orient": orient})
    return vehicles, warnings
