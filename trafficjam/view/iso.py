"""Isometric (2:1 dimetric) projection helpers.

Grid points use ``(grid_row, grid_col)`` where integers fall on cell corners.
Cell ``(r, c)`` is the diamond whose corners are the grid points
``(r,c) (r,c+1) (r+1,c+1) (r+1,c)``.  Increasing ``col`` moves down-right on
screen; increasing ``row`` moves down-left.
"""
from __future__ import annotations

TILE_W = 76
TILE_H = 38
HALF_W = TILE_W // 2
HALF_H = TILE_H // 2


class IsoProjector:
    def __init__(self, origin_x: float, origin_y: float,
                 tile_w: int = TILE_W, tile_h: int = TILE_H):
        self.ox = origin_x
        self.oy = origin_y
        self.hw = tile_w // 2
        self.hh = tile_h // 2

    def point(self, gr: float, gc: float) -> tuple[float, float]:
        """Project a grid corner point to screen coordinates."""
        sx = self.ox + (gc - gr) * self.hw
        sy = self.oy + (gc + gr) * self.hh
        return sx, sy

    def cell_center(self, r: float, c: float) -> tuple[float, float]:
        return self.point(r + 0.5, c + 0.5)

    def tile_corners(self, r: int, c: int) -> list[tuple[float, float]]:
        return [
            self.point(r, c),
            self.point(r, c + 1),
            self.point(r + 1, c + 1),
            self.point(r + 1, c),
        ]


def fit_projector(rows: int, cols: int, surface_w: int, surface_h: int,
                  top_margin: int = 130) -> IsoProjector:
    """Centre a rows x cols board within a surface."""
    # Board spans (cols+rows) tiles wide visually; centre horizontally.
    ox = surface_w / 2 - HALF_W * (cols - rows) / 2
    oy = top_margin
    return IsoProjector(ox, oy)
