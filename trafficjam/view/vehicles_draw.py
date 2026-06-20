"""Render generated low-poly vehicle meshes with a small software-3D pass.

The mesh is placed in board world-space, projected through the same isometric
projection used for the floor, depth-sorted by face (painter's algorithm) and
flat-shaded by a fixed directional light. Static pieces are cached as 2D draw
ops at their board anchor, then translated by the live drag/animation offset.
"""
from __future__ import annotations

import numpy as np
import pygame

from trafficjam.data.palette import SPECS
from trafficjam.mesh.cars import vehicle_mesh
from trafficjam.mesh.geometry import DEFAULT_MATERIALS, face_normal
from trafficjam.model.board import Vehicle
from .iso import IsoProjector

Z_SCALE = 38.0            # pixels per cell of height
LIGHT = np.array([-0.42, -0.30, 0.86])
LIGHT = LIGHT / np.linalg.norm(LIGHT)
AMBIENT = 0.42
SHADOW = (150, 152, 160)  # on top of the floor tiles


def footprint(v: Vehicle) -> tuple[int, int, int, int]:
    """(r0, c0, r1, c1) grid-corner rectangle for depth sorting / hit tests."""
    if v.horizontal:
        return v.row, v.col, v.row + 1, v.col + v.length
    return v.row, v.col, v.row + v.length, v.col + 1


def vehicle_height(vehicle_id: str) -> float:
    return float(vehicle_mesh(vehicle_id).verts[:, 2].max() * Z_SCALE)


def _materials(vehicle_id):
    mats = dict(DEFAULT_MATERIALS)
    mats["body"] = SPECS[vehicle_id].color
    return mats


def _place(verts: np.ndarray, v: Vehicle) -> np.ndarray:
    lx, ly, lz = verts[:, 0], verts[:, 1], verts[:, 2]
    if v.horizontal:
        wc, wr = v.col + lx, v.row + ly
    else:
        wc, wr = v.col + ly, v.row + lx
    return np.stack([wc, wr, lz], axis=1)


def _project(proj: IsoProjector, world: np.ndarray) -> np.ndarray:
    wc, wr, h = world[:, 0], world[:, 1], world[:, 2]
    sx = proj.ox + (wc - wr) * proj.hw
    sy = proj.oy + (wc + wr) * proj.hh - h * Z_SCALE
    return np.stack([sx, sy], axis=1)


def _tint(rgb, f):
    return tuple(max(0, min(255, int(c * f))) for c in rgb)


def _convex_hull(points):
    pts = sorted(set(map(tuple, points)))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


class _Ops:
    __slots__ = ("faces", "shadow", "label_pos", "hull")

    def __init__(self, faces, shadow, label_pos, hull):
        self.faces = faces            # list of (polygon_pts, fill, edge)
        self.shadow = shadow          # ground shadow polygon
        self.label_pos = label_pos    # roof-centre screen point
        self.hull = hull              # silhouette outline


def _build_ops(proj: IsoProjector, v: Vehicle) -> _Ops:
    mesh = vehicle_mesh(v.id)
    mats = _materials(v.id)
    world = _place(mesh.verts, v)
    screen = _project(proj, world)
    depth_w = 2 * proj.hh / Z_SCALE

    faces = []
    for idx, mat in mesh.faces:
        centroid = world[idx].mean(axis=0)
        depth = (centroid[0] + centroid[1]) + depth_w * centroid[2]
        n = face_normal(world, idx)
        shade = AMBIENT + (1 - AMBIENT) * max(0.0, float(np.dot(n, LIGHT)))
        base = mats[mat]
        fill = _tint(base, shade)
        poly = [tuple(screen[i]) for i in idx]
        faces.append((depth, poly, fill, _tint(fill, 0.72)))
    faces.sort(key=lambda f: f[0])  # far first
    draw_faces = [(p, fill, edge) for _d, p, fill, edge in faces]

    # ground shadow: the footprint rectangle at z=0, slightly inset
    r0, c0, r1, c1 = footprint(v)
    pad = 0.12
    shadow_world = np.array([
        [c0 + pad, r0 + pad, 0], [c1 - pad, r0 + pad, 0],
        [c1 - pad, r1 - pad, 0], [c0 + pad, r1 - pad, 0],
    ], dtype=float)
    shadow = [tuple(p) for p in _project(proj, shadow_world)]

    top_z = mesh.verts[:, 2].max()
    # roof centre in local space (length along x, width 0.5) -> world -> screen
    cl = np.array([[v.length / 2, 0.5, top_z]])
    label_pos = tuple(_project(proj, _place(cl, v))[0])

    hull = _convex_hull([tuple(p) for p in screen])
    return _Ops(draw_faces, shadow, label_pos, hull)


_CACHE: dict[tuple, _Ops] = {}


def clear_mesh_cache():
    _CACHE.clear()


def draw_vehicle(surface, proj: IsoProjector, v: Vehicle,
                 *, selected: bool = False, label: bool = True,
                 alpha: int = 255, offset=(0, 0), font=None):
    key = (v.id, v.row, v.col, v.orient)
    ops = _CACHE.get(key)
    if ops is None:
        ops = _build_ops(proj, v)
        _CACHE[key] = ops
    ox, oy = offset

    def shift(poly):
        return [(x + ox, y + oy) for (x, y) in poly]

    target = surface
    layer = None
    if alpha < 255:
        layer = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        target = layer

    # ground shadow
    pygame.draw.polygon(target, SHADOW, shift(ops.shadow))
    # body faces, back-to-front
    for poly, fill, edge in ops.faces:
        pts = shift(poly)
        pygame.draw.polygon(target, fill, pts)
        pygame.draw.polygon(target, edge, pts, 1)

    if selected:
        pygame.draw.polygon(target, (255, 255, 255), shift(ops.hull), 3)

    if label and font is not None:
        lx, ly = ops.label_pos
        txt = font.render(v.id, True, (245, 245, 248))
        sh = font.render(v.id, True, (20, 20, 24))
        rect = txt.get_rect(center=(lx + ox, ly + oy))
        target.blit(sh, sh.get_rect(center=(lx + ox + 1, ly + oy + 1)))
        target.blit(txt, rect)

    if layer is not None:
        layer.set_alpha(alpha)
        surface.blit(layer, (0, 0))


def projected_hull(proj: IsoProjector, v: Vehicle):
    """Silhouette polygon (at the board anchor) for click hit-testing."""
    key = (v.id, v.row, v.col, v.orient)
    ops = _CACHE.get(key)
    if ops is None:
        ops = _build_ops(proj, v)
        _CACHE[key] = ops
    return ops.hull
