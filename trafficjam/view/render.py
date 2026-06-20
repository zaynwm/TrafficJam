"""Render the board floor, exit and depth-sorted vehicles."""
from __future__ import annotations

import pygame

from trafficjam.model.board import Board, Vehicle
from .iso import IsoProjector
from .vehicles_draw import footprint, draw_vehicle

FLOOR_LIGHT = (208, 210, 216)
FLOOR_DARK = (190, 192, 200)
FLOOR_EDGE = (150, 152, 160)
TRAY = (120, 122, 132)
EXIT_GLOW = (120, 200, 120)


def depth_key(v: Vehicle) -> float:
    """Nearer vehicles (larger row+col of their near corner) draw later."""
    r0, c0, r1, c1 = footprint(v)
    return (r1 - 1) + (c1 - 1)


def draw_floor(surface, proj: IsoProjector, board: Board):
    # Tray border (one ring outside the grid).
    ring = [
        proj.point(-0.25, -0.25),
        proj.point(-0.25, board.cols + 0.25),
        proj.point(board.rows + 0.25, board.cols + 0.25),
        proj.point(board.rows + 0.25, -0.25),
    ]
    pygame.draw.polygon(surface, TRAY, ring)

    for r in range(board.rows):
        for c in range(board.cols):
            corners = proj.tile_corners(r, c)
            color = FLOOR_LIGHT if (r + c) % 2 == 0 else FLOOR_DARK
            pygame.draw.polygon(surface, color, corners)
            pygame.draw.polygon(surface, FLOOR_EDGE, corners, 1)

    _draw_exit(surface, proj, board)


def _draw_exit(surface, proj: IsoProjector, board: Board):
    er = board.exit_row
    # Highlight the exit lane: outer tile beyond the right edge on the exit row.
    lane = [
        proj.point(er, board.cols),
        proj.point(er, board.cols + 1),
        proj.point(er + 1, board.cols + 1),
        proj.point(er + 1, board.cols),
    ]
    s = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    pygame.draw.polygon(s, (*EXIT_GLOW, 90), lane)
    surface.blit(s, (0, 0))
    # Arrow pointing out.
    mid = proj.cell_center(er + 0.5, board.cols + 0.5)
    a = (mid[0] + 14, mid[1])
    b = (mid[0] - 6, mid[1] - 10)
    d = (mid[0] - 6, mid[1] + 10)
    pygame.draw.polygon(surface, (40, 130, 60), [a, b, d])


def draw_board(surface, proj: IsoProjector, board: Board, *,
               selected_id=None, label=True, font=None,
               drag_offset=None, drag_id=None):
    draw_floor(surface, proj, board)
    for v in sorted(board.vehicles.values(), key=depth_key):
        offset = drag_offset if (drag_id and v.id == drag_id) else (0, 0)
        draw_vehicle(surface, proj, v,
                     selected=(v.id == selected_id),
                     label=label, font=font, offset=offset or (0, 0))
