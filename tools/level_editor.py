"""Traffic Jam level editor.

A small pygame GUI for fixing puzzle JSON files (e.g. the auto-imported boards
in ``needs_review/``). Pick a vehicle color from the palette on the right and
paint it onto the grid; the matching reference photo (``<stem>.png`` next to the
JSON) is shown on the left so you can compare. A file list lets you jump between
every ``*.json`` in the target directory, and Save writes the board back out.

Usage::

    # GUI editor (directory, or a single file with its folder pre-loaded)
    python -m tools.level_editor needs_review
    python -m tools.level_editor needs_review/009.json

    # Headless batch validate + clean (regenerate printed_solution + min_moves,
    # normalize vehicles, drop the stale quarantine note and the import-time
    # `source` block). Works on a file or dir.
    python -m tools.level_editor needs_review --headless
    python -m tools.level_editor needs_review/009.json --headless
    python -m tools.level_editor needs_review --dry-run   # report, don't write

Headless exits non-zero if any file is unsolvable or has geometry errors
(geometry-error files are reported and left untouched, since they can't be
solved). Otherwise it rewrites only files whose cleaned content differs.

Controls
    * Click a palette swatch        -> select it as the active brush
    * Left-click a grid cell        -> paint the active vehicle there
    * Right-click a grid cell       -> erase that cell
    * Click "Erase" brush           -> left-click then erases too
    * Click a file in the list      -> load it (prompts if unsaved)
    * Arrow keys / [ ]              -> previous / next file
    * Click "Check" / press V       -> run the BFS solver, report solvability
    * Ctrl+S / "Save"               -> save (regenerates printed_solution +
                                       min_moves from the optimal solution)
    * Click EXIT arrows / side btn  -> move the exit row / change side

On save the board is solved with the project's BFS solver
(``trafficjam.model.solver.shortest_solution``): if a solution exists,
``printed_solution`` and ``min_moves`` are overwritten with the optimal one; if
the board is unsolvable the solution is cleared and the save is flagged.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")  # quiet headless output
import pygame  # noqa: E402

# Make ``trafficjam`` importable whether run as a module or a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trafficjam.data.palette import SPECS, roof_color  # noqa: E402
from trafficjam.data.puzzles import board_from_data  # noqa: E402
from trafficjam.model.solver import shortest_solution  # noqa: E402
from tools.schema import validate  # noqa: E402

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------
SCREEN_W, SCREEN_H = 1280, 800
BG = (24, 26, 34)
PANEL = (34, 37, 48)
PANEL_HI = (48, 52, 66)
LINE = (70, 75, 92)
TEXT = (228, 230, 238)
MUTED = (150, 156, 172)
ACCENT = (90, 170, 250)
GOOD = (120, 200, 130)
BAD = (235, 110, 110)

TOPBAR_H = 46
PAD = 12

FILES_W = 210                       # left file-list column
REF_W = 380                         # reference-image column
PALETTE_W = 250                     # right palette column


def lum(color: tuple[int, int, int]) -> float:
    r, g, b = color
    return 0.299 * r + 0.587 * g + 0.114 * b


def label_color(bg: tuple[int, int, int]) -> tuple[int, int, int]:
    return (20, 20, 24) if lum(bg) > 140 else (245, 245, 250)


class Button:
    def __init__(self, rect, text, cb, *, enabled=True):
        self.rect = pygame.Rect(rect)
        self.text = text
        self.cb = cb
        self.enabled = enabled

    def draw(self, surf, font):
        hover = self.rect.collidepoint(pygame.mouse.get_pos())
        bg = PANEL_HI if (hover and self.enabled) else PANEL
        pygame.draw.rect(surf, bg, self.rect, border_radius=6)
        pygame.draw.rect(surf, LINE, self.rect, 1, border_radius=6)
        col = TEXT if self.enabled else MUTED
        t = font.render(self.text, True, col)
        surf.blit(t, t.get_rect(center=self.rect.center))

    def handle(self, pos):
        if self.enabled and self.rect.collidepoint(pos):
            self.cb()
            return True
        return False


class Board:
    """Editable board state: a {(row, col): vehicle_id} cell map + grid meta."""

    def __init__(self, data: dict):
        self.data = data
        grid = data.get("grid", {})
        self.rows = int(grid.get("rows", 6))
        self.cols = int(grid.get("cols", 6))
        ex = grid.get("exit", {}) or {}
        self.exit_row = int(ex.get("row", self.rows // 2))
        self.exit_side = ex.get("side", "right")
        self.cells: dict[tuple[int, int], str] = {}
        for v in data.get("vehicles", []):
            vid = v.get("id")
            r, c = v.get("row", 0), v.get("col", 0)
            length = v.get("len", SPECS[vid].length if vid in SPECS else 2)
            orient = v.get("orient", "H")
            for i in range(length):
                cell = (r, c + i) if orient == "H" else (r + i, c)
                self.cells[cell] = vid

    # -- editing -----------------------------------------------------------
    def paint(self, cell, vid):
        if vid is None:
            self.cells.pop(cell, None)
        else:
            self.cells[cell] = vid

    # -- export ------------------------------------------------------------
    def to_vehicles(self) -> tuple[list[dict], list[str]]:
        """Rebuild the vehicle list from the cell map. Returns (vehicles, warns)."""
        groups: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for cell, vid in self.cells.items():
            groups[vid].append(cell)

        vehicles, warns = [], []
        for vid in sorted(groups):
            cells = sorted(groups[vid])
            rs = {r for r, _ in cells}
            cs = {c for _, c in cells}
            if len(cells) == 1:
                orient = "H"
                length = 1
                row, col = cells[0]
            elif len(rs) == 1:
                orient, row, col, length = "H", min(rs), min(cs), len(cs)
            elif len(cs) == 1:
                orient, row, col, length = "V", min(rs), min(cs), len(rs)
            else:
                warns.append(f"{vid}: cells are not in a single row/column")
                span_c = max(cs) - min(cs)
                span_r = max(rs) - min(rs)
                orient = "H" if span_c >= span_r else "V"
                row, col = min(rs), min(cs)
                length = (span_c if orient == "H" else span_r) + 1

            # contiguity check
            expect = (
                {(row, col + i) for i in range(length)}
                if orient == "H"
                else {(row + i, col) for i in range(length)}
            )
            if set(cells) != expect:
                warns.append(f"{vid}: cells have a gap (not contiguous)")
            if vid in SPECS and length != SPECS[vid].length:
                warns.append(
                    f"{vid}: length {length} != palette length {SPECS[vid].length}"
                )
            vehicles.append(
                {"id": vid, "row": row, "col": col, "len": length, "orient": orient}
            )
        return vehicles, warns

    def export_data(self) -> tuple[dict, list[str], list[str]]:
        """Return (out, geometry_warnings, schema_errors).

        ``out`` keeps every original field (id, level, printed_solution,
        source, ...); only grid + vehicles are rewritten from the cell map and
        the stale quarantine note is dropped.
        """
        vehicles, warns = self.to_vehicles()
        out = dict(self.data)
        out["grid"] = dict(out.get("grid", {}))
        out["grid"]["rows"] = self.rows
        out["grid"]["cols"] = self.cols
        out["grid"]["exit"] = {"row": self.exit_row, "side": self.exit_side}
        out["vehicles"] = vehicles
        errors = validate(out)
        out.pop("_validation", None)
        return out, warns, errors


def solve(out: dict):
    """Run the BFS solver on an exported board.

    Returns ``(status, moves)`` where status is one of:
        "solved"      -> moves is the optimal list[Move]
        "unsolvable"  -> no solution exists (moves is None)
        "toobig"      -> solver hit its node budget (moves is None)
        "invalid"     -> board geometry is illegal; can't build it (moves None)
    """
    try:
        board = board_from_data(out)
    except Exception:
        return "invalid", None
    moves = shortest_solution(board)
    if moves is None:
        # shortest_solution returns None both for unsolvable and budget-exceeded;
        # a 6x6 board never exceeds the 2M-node budget, so treat None as unsolvable.
        return "unsolvable", None
    return "solved", moves


def clean_board(board: "Board") -> tuple[dict, dict]:
    """Validate, normalize and (re)solve a board. Pure — no I/O, no GUI.

    Returns ``(out, report)`` where ``out`` is the cleaned puzzle dict and
    ``report`` has keys: ``status`` (one of "solved" / "unsolvable" /
    "geometry-error"), ``errors`` (schema errors), ``warns`` (geometry
    warnings), ``min_moves`` and ``solution`` (the regenerated values, or None).

    On a clean board the optimal solution overwrites ``printed_solution`` /
    ``min_moves``; an unsolvable board has them cleared; a board with geometry
    errors is left with its original solution untouched (it can't be solved).
    """
    out, warns, errors = board.export_data()
    report = {
        "status": None,
        "errors": errors,
        "warns": warns,
        "min_moves": None,
        "solution": None,
    }
    if errors:
        report["status"] = "geometry-error"
        return out, report

    status, moves = solve(out)
    if status == "solved":
        out["printed_solution"] = [m.token() for m in moves]
        out["min_moves"] = len(moves)
        report["status"] = "solved"
        report["min_moves"] = len(moves)
        report["solution"] = out["printed_solution"]
    else:  # unsolvable
        out["printed_solution"] = []
        out["min_moves"] = None
        report["status"] = "unsolvable"
    return out, report


class Editor:
    def __init__(self, directory: Path, select: Path | None = None):
        self.dir = directory
        self.files = sorted(p.resolve() for p in directory.glob("*.json"))
        if not self.files:
            raise SystemExit(f"No *.json files found in {directory}")
        start = 0
        if select is not None:
            try:
                start = self.files.index(select.resolve())
            except ValueError:
                start = 0

        pygame.init()
        pygame.display.set_caption(f"Traffic Jam — Level Editor ({directory})")
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("arial", 16)
        self.small = pygame.font.SysFont("arial", 13)
        self.bold = pygame.font.SysFont("arial", 16, bold=True)
        self.mono = pygame.font.SysFont("menlo,consolas,courier", 13)

        self.idx = -1
        self.board: Board | None = None
        self.ref_img: pygame.Surface | None = None
        self.brush: str | None = "X"     # active vehicle id, or None for erase
        self.dirty = False
        self.status = ""
        self.status_col = MUTED
        self.warns: list[str] = []
        self.file_scroll = 0
        # Solver result cache (computed on demand, never per-frame — BFS is slow).
        self.solve_msg = "press Check / Save to verify solvability"
        self.solve_col = MUTED

        self.buttons: list[Button] = []
        self.palette_rects: list[tuple[pygame.Rect, str]] = []
        self.file_rects: list[tuple[pygame.Rect, int]] = []
        self.grid_rect = pygame.Rect(0, 0, 0, 0)
        self.cell = 0

        self.load(start)

    # -- file io -----------------------------------------------------------
    def load(self, i: int):
        i = max(0, min(len(self.files) - 1, i))
        self.idx = i
        path = self.files[i]
        data = json.loads(path.read_text())
        self.board = Board(data)
        self.warns = []
        self.dirty = False
        # reference image (same stem .png)
        png = path.with_suffix(".png")
        self.ref_img = None
        if png.exists():
            try:
                self.ref_img = pygame.image.load(str(png)).convert_alpha()
            except pygame.error:
                self.ref_img = None
        self.solve_msg = "press Check / Save to verify solvability"
        self.solve_col = MUTED
        self.set_status(f"Loaded {path.name}", MUTED)

    def mark_dirty(self):
        self.dirty = True
        # Any edit invalidates the cached solver result.
        self.solve_msg = "edited — press Check / Save to re-verify solvability"
        self.solve_col = MUTED

    def check_solvable(self, out=None):
        """Solve the current board; cache + return (status, out, moves).

        Updates the on-screen solvability message. Does NOT write to disk.
        """
        if out is None:
            out, _warns, _errors = self.board.export_data()
        status, moves = solve(out)
        if status == "solved":
            self.solve_msg = f"SOLVABLE in {len(moves)} moves: " + " ".join(
                m.token() for m in moves
            )
            self.solve_col = GOOD
        elif status == "unsolvable":
            self.solve_msg = "UNSOLVABLE — no sequence frees X"
            self.solve_col = BAD
        else:  # invalid geometry
            self.solve_msg = "can't solve — fix the geometry errors first"
            self.solve_col = BAD
        return status, out, moves

    def save(self):
        if not self.board:
            return
        out, report = clean_board(self.board)
        path = self.files[self.idx]
        warns, errors = report["warns"], report["errors"]
        self.warns = errors + warns

        if report["status"] == "geometry-error":
            # Illegal geometry (overlap / out of bounds / bad len). Persist the
            # edit so progress isn't lost, but the board can't be solved and any
            # existing printed_solution is left untouched (still untrustworthy).
            self.solve_msg = "not solved — fix geometry errors first"
            self.solve_col = BAD
            path.write_text(json.dumps(out, indent=2) + "\n")
            self.dirty = False
            self.set_status(
                f"Saved {path.name} with {len(errors)} geometry error(s); "
                f"solution NOT regenerated",
                BAD,
            )
            return

        if report["status"] == "solved":
            self.solve_msg = f"SOLVABLE in {report['min_moves']} moves: " + " ".join(
                report["solution"]
            )
            self.solve_col = GOOD
            note = f"solved in {report['min_moves']} ✓"
            col = GOOD if not warns else BAD
        else:  # unsolvable
            self.solve_msg = "UNSOLVABLE — no sequence frees X"
            self.solve_col = BAD
            self.warns = self.warns + ["board is UNSOLVABLE — no solution exists"]
            note = "UNSOLVABLE — solution cleared"
            col = BAD

        path.write_text(json.dumps(out, indent=2) + "\n")
        self.dirty = False
        extra = f" ({len(warns)} warning(s))" if warns else ""
        self.set_status(f"Saved {path.name} — {note}{extra}", col)

    def goto(self, i: int):
        if i == self.idx:
            return
        if self.dirty:
            self.set_status("Unsaved changes! Ctrl+S to save, or click again to discard", BAD)
            self._pending = i
            # second click on same target discards
            if getattr(self, "_confirm", None) == i:
                self._confirm = None
                self.load(i)
            else:
                self._confirm = i
            return
        self._confirm = None
        self.load(i)

    def set_status(self, msg, col=MUTED):
        self.status = msg
        self.status_col = col

    # -- layout / drawing --------------------------------------------------
    def relayout(self):
        self.buttons.clear()
        self.palette_rects.clear()
        self.file_rects.clear()

        # Top bar buttons
        bx = SCREEN_W - PAD - 90
        self.buttons.append(Button((bx, 8, 90, 30), "Save", self.save))
        self.buttons.append(
            Button((bx - 90, 8, 84, 30), "Check", lambda: self.check_solvable())
        )
        self.buttons.append(
            Button((bx - 184, 8, 40, 30), "▶", lambda: self.goto(self.idx + 1))
        )
        self.buttons.append(
            Button((bx - 228, 8, 40, 30), "◀", lambda: self.goto(self.idx - 1))
        )

        # Grid geometry (center column)
        gx0 = FILES_W + REF_W + PAD * 2
        gx1 = SCREEN_W - PALETTE_W - PAD
        gy0 = TOPBAR_H + PAD + 40
        gy1 = SCREEN_H - PAD - 90
        avail_w = gx1 - gx0
        avail_h = gy1 - gy0
        self.cell = max(20, min(avail_w // self.board.cols, avail_h // self.board.rows))
        gw = self.cell * self.board.cols
        gh = self.cell * self.board.rows
        self.grid_rect = pygame.Rect(
            gx0 + (avail_w - gw) // 2, gy0, gw, gh
        )

        # Exit controls (under grid)
        ey = self.grid_rect.bottom + 12
        ex0 = self.grid_rect.left
        self.buttons.append(Button((ex0, ey, 110, 28), "Exit row ▲",
                                   lambda: self.move_exit(-1)))
        self.buttons.append(Button((ex0 + 118, ey, 110, 28), "Exit row ▼",
                                   lambda: self.move_exit(1)))
        self.buttons.append(Button((ex0 + 236, ey, 130, 28),
                                   f"Side: {self.board.exit_side}", self.cycle_side))

    def move_exit(self, d):
        self.board.exit_row = max(0, min(self.board.rows - 1, self.board.exit_row + d))
        self.mark_dirty()

    def cycle_side(self):
        order = ["right", "left", "top", "bottom"]
        i = order.index(self.board.exit_side) if self.board.exit_side in order else 0
        self.board.exit_side = order[(i + 1) % len(order)]
        self.mark_dirty()

    def draw(self):
        self.screen.fill(BG)
        self.relayout()
        self.draw_topbar()
        self.draw_files()
        self.draw_reference()
        self.draw_grid()
        self.draw_palette()
        for b in self.buttons:
            b.draw(self.screen, self.font)
        self.draw_status()
        pygame.display.flip()

    def draw_topbar(self):
        pygame.draw.rect(self.screen, PANEL, (0, 0, SCREEN_W, TOPBAR_H))
        pygame.draw.line(self.screen, LINE, (0, TOPBAR_H), (SCREEN_W, TOPBAR_H))
        name = self.files[self.idx].name
        flag = " *" if self.dirty else ""
        t = self.bold.render(
            f"[{self.idx + 1}/{len(self.files)}]  {name}{flag}", True, TEXT
        )
        self.screen.blit(t, (PAD, 14))

    def draw_files(self):
        x, y, w = 0, TOPBAR_H, FILES_W
        pygame.draw.rect(self.screen, PANEL, (x, y, w, SCREEN_H - y))
        pygame.draw.line(self.screen, LINE, (w, y), (w, SCREEN_H))
        hdr = self.small.render("FILES", True, MUTED)
        self.screen.blit(hdr, (PAD, y + 8))
        row_h = 24
        top = y + 30
        view_h = SCREEN_H - top - PAD
        max_vis = view_h // row_h
        if self.idx < self.file_scroll:
            self.file_scroll = self.idx
        elif self.idx >= self.file_scroll + max_vis:
            self.file_scroll = self.idx - max_vis + 1
        self.file_scroll = max(0, min(max(0, len(self.files) - max_vis), self.file_scroll))
        for vi, fi in enumerate(range(self.file_scroll,
                                       min(len(self.files), self.file_scroll + max_vis))):
            ry = top + vi * row_h
            r = pygame.Rect(4, ry, w - 8, row_h - 2)
            sel = fi == self.idx
            if sel:
                pygame.draw.rect(self.screen, PANEL_HI, r, border_radius=4)
                pygame.draw.rect(self.screen, ACCENT, r, 1, border_radius=4)
            col = TEXT if sel else MUTED
            t = self.small.render(self.files[fi].stem, True, col)
            self.screen.blit(t, (10, ry + 4))
            self.file_rects.append((r, fi))

    def draw_reference(self):
        x = FILES_W + PAD
        y = TOPBAR_H + PAD
        w = REF_W
        h = SCREEN_H - y - PAD
        pygame.draw.rect(self.screen, PANEL, (x, y, w, h), border_radius=6)
        pygame.draw.rect(self.screen, LINE, (x, y, w, h), 1, border_radius=6)
        hdr = self.small.render("REFERENCE", True, MUTED)
        self.screen.blit(hdr, (x + 8, y + 6))
        if self.ref_img is None:
            t = self.small.render("(no reference image)", True, MUTED)
            self.screen.blit(t, (x + 8, y + 28))
            return
        iw, ih = self.ref_img.get_size()
        scale = min((w - 16) / iw, (h - 30) / ih)
        sw, sh = int(iw * scale), int(ih * scale)
        img = pygame.transform.smoothscale(self.ref_img, (sw, sh))
        self.screen.blit(img, (x + (w - sw) // 2, y + 24))

    def draw_grid(self):
        gr = self.grid_rect
        b = self.board
        # cells
        for r in range(b.rows):
            for c in range(b.cols):
                rect = pygame.Rect(
                    gr.left + c * self.cell, gr.top + r * self.cell, self.cell, self.cell
                )
                vid = b.cells.get((r, c))
                if vid and vid in SPECS:
                    pygame.draw.rect(self.screen, SPECS[vid].color, rect)
                    pygame.draw.rect(self.screen, roof_color(SPECS[vid]), rect, 2)
                    lab = self.bold.render(vid, True, label_color(SPECS[vid].color))
                    self.screen.blit(lab, lab.get_rect(center=rect.center))
                elif vid:
                    pygame.draw.rect(self.screen, (120, 120, 120), rect)
                    lab = self.bold.render(vid, True, (20, 20, 20))
                    self.screen.blit(lab, lab.get_rect(center=rect.center))
                else:
                    pygame.draw.rect(self.screen, (44, 47, 60), rect)
                pygame.draw.rect(self.screen, LINE, rect, 1)
        # exit marker
        self.draw_exit_marker()
        # title
        t = self.small.render(
            f"GRID {b.rows}x{b.cols}  —  L-click paint, R-click erase", True, MUTED
        )
        self.screen.blit(t, (gr.left, gr.top - 22))

    def draw_exit_marker(self):
        gr = self.grid_rect
        b = self.board
        col = GOOD
        if b.exit_side in ("right", "left"):
            cy = gr.top + b.exit_row * self.cell + self.cell // 2
            cx = gr.right + 6 if b.exit_side == "right" else gr.left - 6
            d = 1 if b.exit_side == "right" else -1
            pts = [(cx, cy - 10), (cx, cy + 10), (cx + 16 * d, cy)]
            pygame.draw.polygon(self.screen, col, pts)
        else:
            cx = gr.left + (b.cols // 2) * self.cell + self.cell // 2
            cy = gr.top - 6 if b.exit_side == "top" else gr.bottom + 6
            d = -1 if b.exit_side == "top" else 1
            pts = [(cx - 10, cy), (cx + 10, cy), (cx, cy + 16 * d)]
            pygame.draw.polygon(self.screen, col, pts)

    def draw_palette(self):
        x = SCREEN_W - PALETTE_W
        y = TOPBAR_H
        pygame.draw.rect(self.screen, PANEL, (x, y, PALETTE_W, SCREEN_H - y))
        pygame.draw.line(self.screen, LINE, (x, y), (x, SCREEN_H))
        hdr = self.small.render("PALETTE — click to select brush", True, MUTED)
        self.screen.blit(hdr, (x + PAD, y + 8))

        # Erase brush
        er = pygame.Rect(x + PAD, y + 30, PALETTE_W - 2 * PAD, 30)
        pygame.draw.rect(self.screen, (60, 60, 70), er, border_radius=5)
        if self.brush is None:
            pygame.draw.rect(self.screen, ACCENT, er, 3, border_radius=5)
        t = self.font.render("Erase", True, TEXT)
        self.screen.blit(t, t.get_rect(center=er.center))
        self.palette_rects.append((er, "__erase__"))

        # Vehicle swatches: 2 columns
        sw_w = (PALETTE_W - 2 * PAD - 8) // 2
        sw_h = 38
        sx = x + PAD
        sy = y + 70
        for i, vid in enumerate(SPECS):
            spec = SPECS[vid]
            col_i = i % 2
            row_i = i // 2
            rect = pygame.Rect(
                sx + col_i * (sw_w + 8), sy + row_i * (sw_h + 6), sw_w, sw_h
            )
            pygame.draw.rect(self.screen, spec.color, rect, border_radius=5)
            if self.brush == vid:
                pygame.draw.rect(self.screen, ACCENT, rect, 3, border_radius=5)
            else:
                pygame.draw.rect(self.screen, LINE, rect, 1, border_radius=5)
            lc = label_color(spec.color)
            lab = self.bold.render(vid, True, lc)
            self.screen.blit(lab, (rect.left + 6, rect.centery - lab.get_height() // 2))
            meta = self.small.render(f"{spec.kind[:3]} {spec.length}", True, lc)
            self.screen.blit(meta, (rect.left + 24, rect.centery - meta.get_height() // 2))
            self.palette_rects.append((rect, vid))

        # Live validation summary
        self.draw_validation(x + PAD, sy + 8 * (sw_h + 6) + 8, PALETTE_W - 2 * PAD)

    def draw_validation(self, x, y, w):
        _out, warns, errors = self.board.export_data()
        problems = errors + warns
        hdr = self.small.render("VALIDATION", True, MUTED)
        self.screen.blit(hdr, (x, y))
        y += 18
        if not problems:
            t = self.small.render("✓ geometry valid", True, GOOD)
            self.screen.blit(t, (x, y))
            y += 17
        else:
            for p in problems[:7]:
                for line in self._wrap(p, w):
                    t = self.small.render(line, True, BAD)
                    self.screen.blit(t, (x, y))
                    y += 15
            if len(problems) > 7:
                t = self.small.render(f"... +{len(problems) - 7} more", True, MUTED)
                self.screen.blit(t, (x, y))
                y += 15

        # Cached solvability result (computed only on Check / Save).
        y += 8
        hdr2 = self.small.render("SOLVABILITY", True, MUTED)
        self.screen.blit(hdr2, (x, y))
        y += 18
        for line in self._wrap(self.solve_msg, w):
            t = self.small.render(line, True, self.solve_col)
            self.screen.blit(t, (x, y))
            y += 15

    def _wrap(self, text, w):
        words = text.split(" ")
        lines, cur = [], ""
        for word in words:
            trial = (cur + " " + word).strip()
            if self.small.size(trial)[0] <= w:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        return lines

    def draw_status(self):
        y = SCREEN_H - 26
        pygame.draw.rect(self.screen, PANEL, (FILES_W, y, SCREEN_W - FILES_W - PALETTE_W, 26))
        t = self.font.render(self.status, True, self.status_col)
        self.screen.blit(t, (FILES_W + PAD, y + 4))
        brush = "Erase" if self.brush is None else f"Brush: {self.brush}"
        bt = self.font.render(brush, True, ACCENT)
        self.screen.blit(bt, (SCREEN_W - PALETTE_W - 130, y + 4))

    # -- input -------------------------------------------------------------
    def cell_at(self, pos):
        gr = self.grid_rect
        if not gr.collidepoint(pos):
            return None
        c = (pos[0] - gr.left) // self.cell
        r = (pos[1] - gr.top) // self.cell
        if 0 <= r < self.board.rows and 0 <= c < self.board.cols:
            return (int(r), int(c))
        return None

    def on_click(self, pos, button):
        # buttons
        for b in self.buttons:
            if b.handle(pos):
                return
        # files
        for rect, fi in self.file_rects:
            if rect.collidepoint(pos):
                self.goto(fi)
                return
        # palette
        for rect, vid in self.palette_rects:
            if rect.collidepoint(pos):
                self.brush = None if vid == "__erase__" else vid
                return
        # grid
        cell = self.cell_at(pos)
        if cell is not None:
            if button == 3:                       # right-click erase
                self.board.paint(cell, None)
            else:
                self.board.paint(cell, self.brush)
            self.mark_dirty()

    def on_drag(self, pos, buttons):
        cell = self.cell_at(pos)
        if cell is None:
            return
        if buttons[0]:
            self.board.paint(cell, self.brush)
            self.mark_dirty()
        elif buttons[2]:
            self.board.paint(cell, None)
            self.mark_dirty()

    def run(self):
        while True:
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    pygame.quit()
                    return
                if e.type == pygame.MOUSEBUTTONDOWN:
                    self.on_click(e.pos, e.button)
                if e.type == pygame.MOUSEMOTION and any(e.buttons):
                    self.on_drag(e.pos, e.buttons)
                if e.type == pygame.KEYDOWN:
                    self.on_key(e)
            self.draw()
            self.clock.tick(60)

    def on_key(self, e):
        mods = pygame.key.get_mods()
        if (mods & pygame.KMOD_META or mods & pygame.KMOD_CTRL) and e.key == pygame.K_s:
            self.save()
        elif e.key in (pygame.K_RIGHT, pygame.K_RIGHTBRACKET):
            self.goto(self.idx + 1)
        elif e.key in (pygame.K_LEFT, pygame.K_LEFTBRACKET):
            self.goto(self.idx - 1)
        elif e.key == pygame.K_e:
            self.brush = None
        elif e.key == pygame.K_v:
            self.check_solvable()


def _gather(path: Path) -> list[Path]:
    """Return the *.json files for a path that may be a file or a directory."""
    if path.is_dir():
        files = sorted(path.glob("*.json"))
        if not files:
            raise SystemExit(f"No *.json files found in {path}")
        return files
    if path.is_file():
        if path.suffix != ".json":
            raise SystemExit(f"Not a .json file: {path}")
        return [path]
    raise SystemExit(f"No such file or directory: {path}")


def run_headless(path: Path, write: bool = True) -> int:
    """Validate + clean every JSON under ``path`` (a file or directory).

    Regenerates ``printed_solution`` / ``min_moves`` from the optimal solution,
    normalizes the vehicle list, and drops the stale ``_validation`` quarantine
    note and the import-time ``source`` block. Files with geometry errors are
    reported and left untouched (they can't be solved).

    Prints a per-file report and returns a process exit code: 0 when every file
    is clean and solvable, 1 if any file had errors or was unsolvable.
    """
    files = _gather(path)
    n_changed = n_clean = n_unsolved = n_error = 0

    for f in files:
        name = f.name
        try:
            data = json.loads(f.read_text())
            board = Board(data)
            out, report = clean_board(board)
        except Exception as exc:  # malformed JSON, missing keys, illegal init
            n_error += 1
            print(f"  ERROR  {name}: {exc}")
            continue

        status = report["status"]
        # Headless cleanup also drops the import provenance block.
        out.pop("source", None)
        new_text = json.dumps(out, indent=2) + "\n"
        changed = new_text != f.read_text()

        if status == "geometry-error":
            n_error += 1
            errs = "; ".join(report["errors"][:3])
            more = f" (+{len(report['errors']) - 3} more)" if len(report["errors"]) > 3 else ""
            print(f"  ERROR  {name}: geometry invalid — NOT written: {errs}{more}")
            continue

        # Describe what cleanup would do / did.
        bits = []
        old_mm, new_mm = data.get("min_moves"), out.get("min_moves")
        if status == "unsolvable":
            n_unsolved += 1
            bits.append("UNSOLVABLE — solution cleared")
        else:
            if data.get("printed_solution") != out["printed_solution"]:
                bits.append(f"solution {old_mm}->{new_mm} moves")
            else:
                bits.append(f"solved in {new_mm}")
        if "_validation" in data:
            bits.append("dropped _validation")
        if "source" in data:
            bits.append("dropped source")
        if data.get("vehicles") != out["vehicles"]:
            bits.append("normalized vehicles")
        if report["warns"]:
            bits.append(f"{len(report['warns'])} warning(s)")

        if not changed:
            n_clean += 1
            tag = "OK    " if status == "solved" else "WARN  "
            print(f"  {tag} {name}: already clean ({'; '.join(bits)})")
            continue

        n_changed += 1
        if write:
            f.write_text(new_text)
            tag = "FIXED " if status == "solved" else "WARN  "
            print(f"  {tag} {name}: {'; '.join(bits)}")
        else:
            tag = "WOULD " if status == "solved" else "WARN  "
            print(f"  {tag} {name}: would {'; '.join(bits)}")

    verb = "wrote" if write else "would change"
    print(
        f"\n{len(files)} file(s): {n_changed} {verb}, {n_clean} already clean, "
        f"{n_unsolved} unsolvable, {n_error} error(s)"
    )
    return 1 if (n_unsolved or n_error) else 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Traffic Jam level editor — GUI, or headless batch validator/cleaner."
    )
    ap.add_argument(
        "path",
        help="a puzzle .json file OR a directory of them",
    )
    ap.add_argument(
        "--headless",
        action="store_true",
        help="no GUI: validate + rewrite (regenerate solution/min_moves) for the "
        "file or every *.json in the directory",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="headless only: report what would change without writing",
    )
    args = ap.parse_args(argv)
    path = Path(args.path)

    if args.headless or args.dry_run:
        return run_headless(path, write=not args.dry_run)

    # GUI mode. A directory opens normally; a single file opens its parent
    # directory with that file pre-selected.
    if path.is_dir():
        Editor(path).run()
    elif path.is_file():
        Editor(path.parent, select=path).run()
    else:
        raise SystemExit(f"No such file or directory: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
