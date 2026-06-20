"""Draw vehicles as extruded isometric prisms tinted per the palette."""
from __future__ import annotations

import pygame

from trafficjam.data.palette import SPECS, roof_color, shade_color, tint
from trafficjam.model.board import Vehicle
from .iso import IsoProjector

CAR_HEIGHT = 26
TALL_HEIGHT = 34  # trucks / buses


def vehicle_height(vehicle_id: str) -> int:
    return TALL_HEIGHT if SPECS[vehicle_id].length >= 3 else CAR_HEIGHT


def _raise(points, h):
    return [(x, y - h) for (x, y) in points]


def footprint(v: Vehicle) -> tuple[int, int, int, int]:
    """Return (r0, c0, r1, c1) grid-corner rectangle for the vehicle."""
    if v.horizontal:
        return v.row, v.col, v.row + 1, v.col + v.length
    return v.row, v.col, v.row + v.length, v.col + 1


def draw_vehicle(surface, proj: IsoProjector, v: Vehicle,
                 *, selected: bool = False, label: bool = True,
                 alpha: int = 255, offset=(0, 0), font=None):
    """Render one vehicle prism. ``offset`` shifts it (for drag/animation)."""
    spec = SPECS[v.id]
    r0, c0, r1, c1 = footprint(v)
    ox, oy = offset
    h = vehicle_height(v.id)

    A = proj.point(r0, c0)
    B = proj.point(r0, c1)
    C = proj.point(r1, c1)
    D = proj.point(r1, c0)
    floor = [A, B, C, D]
    floor = [(x + ox, y + oy) for (x, y) in floor]
    roof = _raise(floor, h)

    base = spec.color
    roof_c = roof_color(spec)
    east = shade_color(spec)            # col+ face
    south = tint(spec.color, 0.58)      # row+ face (darker)

    # Side faces (drawn before roof).
    east_face = [roof[1], roof[2], floor[2], floor[1]]
    south_face = [roof[3], roof[2], floor[2], floor[3]]

    def poly(color, pts, width=0):
        s = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        pygame.draw.polygon(s, (*color, alpha), pts)
        if width:
            pygame.draw.polygon(s, (*tint(color, 0.5), alpha), pts, width)
        surface.blit(s, (0, 0))

    poly(south, south_face)
    poly(east, east_face)
    poly(roof_c, roof)
    # Roof outline + a window strip for readability.
    outline = (*tint(base, 0.4), alpha)
    os = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    pygame.draw.polygon(os, outline, roof, 2)
    # cabin/window: a smaller inset quad on the roof
    cx = sum(p[0] for p in roof) / 4
    cy = sum(p[1] for p in roof) / 4
    inset = [((p[0] + cx) / 2, (p[1] + cy) / 2) for p in roof]
    pygame.draw.polygon(os, (*tint(roof_c, 1.25), min(alpha, 200)), inset)
    surface.blit(os, (0, 0))

    if selected:
        hs = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        pygame.draw.polygon(hs, (255, 255, 255, 220), roof, 3)
        surface.blit(hs, (0, 0))

    if label and font is not None:
        txt = font.render(v.id, True, (20, 20, 20))
        rect = txt.get_rect(center=(cx, cy))
        surface.blit(txt, rect)
