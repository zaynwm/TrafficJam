"""Mouse interaction: select, axis-constrained drag, and click-to-move."""
from __future__ import annotations

import math

from trafficjam.model.board import Board
from trafficjam.model.moves import Move
from trafficjam.model.solver import reachable_positions
from trafficjam.view.iso import IsoProjector
from trafficjam.view.vehicles_draw import footprint, vehicle_height
from trafficjam.view.render import depth_key

CLICK_PIXELS = 6  # movement under this counts as a click, not a drag


def _roof_polygon(proj: IsoProjector, v):
    r0, c0, r1, c1 = footprint(v)
    h = vehicle_height(v.id)
    pts = [proj.point(r0, c0), proj.point(r0, c1),
           proj.point(r1, c1), proj.point(r1, c0)]
    return [(x, y - h) for (x, y) in pts]


def _point_in_poly(pt, poly):
    x, y = pt
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / (yj - yi + 1e-9) + xi
        ):
            inside = not inside
        j = i
    return inside


class DragController:
    def __init__(self, proj: IsoProjector):
        self.proj = proj
        self.hw = proj.hw
        self.hh = proj.hh
        self.dragging_id = None
        self.selected_id = None
        self.press_pos = None
        self.cur_cells = 0          # snapped cell offset along axis during drag
        self._range = (0, 0)        # (min_neg, max_pos) reachable cells

    def vehicle_at(self, board: Board, pos):
        # nearest (drawn last) first
        for v in sorted(board.vehicles.values(), key=depth_key, reverse=True):
            if _point_in_poly(pos, _roof_polygon(self.proj, v)):
                return v.id
        return None

    def _axis_vec(self, board, vid):
        v = board.vehicles[vid]
        return (self.hw, self.hh) if v.horizontal else (-self.hw, self.hh)

    def _reach_range(self, board, vid):
        v = board.vehicles[vid]
        pos_max = neg_max = 0
        positive = ("R",) if v.horizontal else ("D",)
        for direction, dist, _r, _c in reachable_positions(board, vid):
            if direction in positive:
                pos_max = max(pos_max, dist)
            else:
                neg_max = max(neg_max, dist)
        return -neg_max, pos_max

    # -- event handlers ---------------------------------------------------
    def on_press(self, board, pos):
        vid = self.vehicle_at(board, pos)
        self.selected_id = vid
        if vid is None:
            return
        self.dragging_id = vid
        self.press_pos = pos
        self.cur_cells = 0
        self._range = self._reach_range(board, vid)

    def on_motion(self, board, pos):
        if self.dragging_id is None:
            return
        vec = self._axis_vec(board, self.dragging_id)
        dx, dy = pos[0] - self.press_pos[0], pos[1] - self.press_pos[1]
        denom = vec[0] * vec[0] + vec[1] * vec[1]
        cells = (dx * vec[0] + dy * vec[1]) / denom
        snapped = round(cells)
        lo, hi = self._range
        self.cur_cells = max(lo, min(hi, snapped))

    def drag_offset(self, board):
        """Pixel offset to draw the dragged vehicle at its snapped cell."""
        if self.dragging_id is None:
            return None
        vec = self._axis_vec(board, self.dragging_id)
        return (vec[0] * self.cur_cells, vec[1] * self.cur_cells)

    def on_release(self, board, pos):
        """Return ``(move, is_click)``.

        ``is_click`` is True when the gesture was a click-to-move (which should
        animate); a completed drag is already at its destination, so it returns
        ``is_click=False`` and the caller skips the slide animation.
        """
        vid = self.dragging_id
        self.dragging_id = None
        if vid is None:
            return None, False
        moved_px = math.hypot(pos[0] - self.press_pos[0],
                              pos[1] - self.press_pos[1])
        v = board.vehicles[vid]

        if moved_px < CLICK_PIXELS:
            # Click: move only if exactly one reachable position exists.
            reach = reachable_positions(board, vid)
            if len(reach) == 1:
                direction, dist, _r, _c = reach[0]
                return Move(vid, direction, dist), True
            return None, True

        if self.cur_cells == 0:
            return None, False
        if v.horizontal:
            direction = "R" if self.cur_cells > 0 else "L"
        else:
            direction = "D" if self.cur_cells > 0 else "U"
        return Move(vid, direction, abs(self.cur_cells)), False
