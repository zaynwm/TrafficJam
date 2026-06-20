"""Parametric, generative low-poly vehicle meshes — evocative of types, not copies.

A vehicle is described by a small parameter vector (``CarSpec``): a side-profile
roofline, body width, ride height, cabin (glass) range and wheel placement. The
body is built by lofting rounded cross-sections along the length; wheels are
separate low-poly cylinders. Everything is generated from numbers — no images,
no scanned or copyrighted geometry.

Local space: length along +x in ``[0, length]``, width along +y within the unit
cell ``[0, 1]`` (centred), height along +z from the ground (0) up.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .geometry import Mesh, MeshBuilder, merge, orient_outward

PROFILE_POINTS = 8  # vertices per lofted cross-section


@dataclass(frozen=True)
class CarSpec:
    length: float = 2.0                 # cells along the driving axis
    width: float = 0.78                 # body width (within the 1-cell lane)
    floor: float = 0.16                 # underbody height above ground
    roof_inset: float = 0.12            # how much narrower the greenhouse is
    corner: float = 0.05                # cross-section corner rounding
    nose_taper: float = 0.18            # plan-view narrowing toward the ends
    # side roofline: (fraction_along_length, top_height) front -> back
    profile: tuple[tuple[float, float], ...] = (
        (0.0, 0.30), (0.16, 0.34), (0.33, 0.37),
        (0.42, 0.52), (0.66, 0.53), (0.80, 0.40), (1.0, 0.34),
    )
    cabin: tuple[float, float] = (0.40, 0.70)   # glass band along the length
    wheel_radius: float = 0.20
    wheel_width: float = 0.12
    wheel_inset: float = 0.04                    # in from the body side
    wheel_x: tuple[float, float] = (0.22, 0.80)  # axle positions (fraction)
    stations: int = 9


def _interp_profile(profile, frac: float) -> float:
    xs = [p[0] for p in profile]
    zs = [p[1] for p in profile]
    return float(np.interp(frac, xs, zs))


def _plan_width(spec: CarSpec, frac: float) -> float:
    # taper toward the nose/tail for a rounded plan view
    t = abs(frac - 0.5) * 2.0
    return spec.width * (1.0 - spec.nose_taper * t * t)


def _section(cy: float, w: float, z0: float, z1: float,
             inset: float, r: float) -> list[tuple[float, float]]:
    """An 8-point rounded, top-inset cross-section in the (y, z) plane."""
    hw = w / 2.0
    htw = max(0.04, hw - inset)
    r = min(r, hw * 0.5, (z1 - z0) * 0.4)
    return [
        (cy - hw, z0 + r),
        (cy - hw + r, z0),
        (cy + hw - r, z0),
        (cy + hw, z0 + r),
        (cy + htw, z1 - r),
        (cy + htw - r, z1),
        (cy - htw + r, z1),
        (cy - htw, z1 - r),
    ]


def _build_body(spec: CarSpec) -> Mesh:
    b = MeshBuilder()
    cy = 0.5
    loops: list[list[int]] = []
    fracs = np.linspace(0.0, 1.0, spec.stations)
    cabin_lo, cabin_hi = spec.cabin
    for frac in fracs:
        x = frac * spec.length
        z1 = _interp_profile(spec.profile, frac)
        w = _plan_width(spec, frac)
        in_cabin = cabin_lo <= frac <= cabin_hi
        inset = spec.roof_inset if in_cabin else spec.roof_inset * 0.35
        pts2d = _section(cy, w, spec.floor, z1, inset, spec.corner)
        loops.append(b.loop([(x, y, z) for (y, z) in pts2d]))

    # loft consecutive sections; upper-band side quads over the cabin are glass
    glass_edges = {4, 5, 6}  # upper perimeter edges (see _section ordering)
    for s in range(spec.stations - 1):
        frac_mid = (fracs[s] + fracs[s + 1]) / 2.0
        in_cabin = cabin_lo <= frac_mid <= cabin_hi
        a, c = loops[s], loops[s + 1]
        for e in range(PROFILE_POINTS):
            e2 = (e + 1) % PROFILE_POINTS
            mat = "glass" if (in_cabin and e in glass_edges) else "body"
            b.quad(a[e], a[e2], c[e2], c[e], mat)
    # end caps
    b.face(list(reversed(loops[0])), "body")
    b.face(loops[-1], "body")
    return orient_outward(b.build())


def _build_wheel(cx: float, cy: float, r: float, width: float,
                 segments: int = 12) -> Mesh:
    b = MeshBuilder()
    y0, y1 = cy - width / 2, cy + width / 2
    ring0, ring1 = [], []
    for i in range(segments):
        a = 2 * math.pi * i / segments
        x = cx + math.cos(a) * r
        z = r + math.sin(a) * r  # centre at z=r so the wheel rests on z=0
        ring0.append(b.vert((x, y0, z)))
        ring1.append(b.vert((x, y1, z)))
    for i in range(segments):
        j = (i + 1) % segments
        b.quad(ring0[i], ring0[j], ring1[j], ring1[i], "tyre")
    b.face(ring0, "tyre")
    b.face(list(reversed(ring1)), "tyre")
    return orient_outward(b.build())


def build_car(spec: CarSpec) -> Mesh:
    parts = [_build_body(spec)]
    half = spec.width / 2 - spec.wheel_inset
    for fx in spec.wheel_x:
        cx = fx * spec.length
        for cy in (0.5 - half, 0.5 + half):
            parts.append(_build_wheel(cx, cy, spec.wheel_radius,
                                      spec.wheel_width))
    return merge(parts)


# -- archetypes (generic silhouettes; evoke a class, copy nothing) -------------
def _spec(length, **kw) -> CarSpec:
    return CarSpec(length=length, **kw)


ARCHETYPES = {
    "sedan": _spec(2.0),
    "coupe": _spec(2.0, floor=0.14, profile=(
        (0.0, 0.27), (0.16, 0.32), (0.34, 0.36),
        (0.46, 0.49), (0.64, 0.49), (0.82, 0.38), (1.0, 0.31)),
        cabin=(0.42, 0.66)),
    "wedge": _spec(2.0, width=0.80, floor=0.12, roof_inset=0.16, profile=(
        (0.0, 0.22), (0.18, 0.26), (0.40, 0.30),
        (0.52, 0.44), (0.66, 0.44), (0.84, 0.34), (1.0, 0.27)),
        cabin=(0.46, 0.70), wheel_radius=0.21),
    "hatch": _spec(2.0, profile=(
        (0.0, 0.29), (0.16, 0.34), (0.34, 0.38),
        (0.44, 0.53), (0.74, 0.53), (0.88, 0.47), (1.0, 0.42)),
        cabin=(0.42, 0.78)),
    "suv": _spec(2.0, width=0.80, floor=0.22, profile=(
        (0.0, 0.34), (0.14, 0.44), (0.26, 0.60),
        (0.40, 0.62), (0.80, 0.62), (0.92, 0.52), (1.0, 0.46)),
        cabin=(0.34, 0.82), wheel_radius=0.23, wheel_x=(0.20, 0.82)),
    "pickup": _spec(2.0, floor=0.20, profile=(
        (0.0, 0.30), (0.14, 0.36), (0.28, 0.56),
        (0.48, 0.56), (0.54, 0.36), (0.80, 0.36), (1.0, 0.36)),
        cabin=(0.30, 0.50), wheel_radius=0.22),
    "bus": _spec(3.0, width=0.82, floor=0.16, roof_inset=0.10, profile=(
        (0.0, 0.50), (0.05, 0.64), (0.95, 0.64), (1.0, 0.50)),
        cabin=(0.05, 0.95), wheel_radius=0.20, wheel_x=(0.14, 0.86)),
    "semi": _spec(3.0, width=0.82, floor=0.18, roof_inset=0.10, profile=(
        (0.0, 0.34), (0.08, 0.52), (0.22, 0.64), (0.30, 0.54),
        (0.34, 0.60), (1.0, 0.60)),
        cabin=(0.06, 0.26), wheel_radius=0.21, wheel_x=(0.16, 0.82)),
}

# vehicle id -> archetype (palette supplies the colour)
VEHICLE_ARCHETYPE = {
    "X": "coupe", "A": "hatch", "B": "wedge", "C": "sedan", "D": "wedge",
    "E": "wedge", "F": "suv", "G": "sedan", "H": "sedan", "I": "suv",
    "J": "suv", "K": "pickup", "O": "semi", "P": "semi", "Q": "bus", "R": "bus",
}

_CACHE: dict[str, Mesh] = {}


def vehicle_mesh(vehicle_id: str) -> Mesh:
    """Cached local-space mesh for a vehicle id."""
    if vehicle_id not in _CACHE:
        arche = VEHICLE_ARCHETYPE.get(vehicle_id, "sedan")
        _CACHE[vehicle_id] = build_car(ARCHETYPES[arche])
    return _CACHE[vehicle_id]
