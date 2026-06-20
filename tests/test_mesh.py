import json
from collections import Counter

import numpy as np

from trafficjam.mesh import cars
from trafficjam.mesh.geometry import (
    export_gltf,
    export_obj,
    triangulate,
    vertex_normals,
)


def _non_manifold_edges(mesh):
    counts = Counter()
    for idx, _ in mesh.faces:
        for i in range(len(idx)):
            a, b = idx[i], idx[(i + 1) % len(idx)]
            counts[frozenset((a, b))] += 1
    return [e for e, c in counts.items() if c != 2]


def test_every_vehicle_mesh_is_valid():
    for vid in cars.VEHICLE_ARCHETYPE:
        mesh = cars.vehicle_mesh(vid)
        assert len(mesh.verts) > 0 and len(mesh.faces) > 0
        assert np.isfinite(mesh.verts).all()
        for idx, mat in mesh.faces:
            assert len(idx) >= 3
            assert all(0 <= i < len(mesh.verts) for i in idx)
            assert mat in ("body", "glass", "tyre")


def test_body_and_wheel_components_are_watertight():
    body = cars._build_body(cars.ARCHETYPES["sedan"])
    wheel = cars._build_wheel(0.4, 0.3, 0.2, 0.12)
    assert _non_manifold_edges(body) == []
    assert _non_manifold_edges(wheel) == []


def test_mesh_fits_its_footprint():
    for vid, arche in cars.VEHICLE_ARCHETYPE.items():
        mesh = cars.vehicle_mesh(vid)
        length = cars.ARCHETYPES[arche].length
        lo, hi = mesh.bounds()
        assert lo[2] >= -1e-6                       # nothing below ground
        assert -1e-6 <= lo[0] and hi[0] <= length + 1e-6
        assert -1e-6 <= lo[1] and hi[1] <= 1 + 1e-6  # within the 1-cell lane


def test_vertex_normals_are_unit_length():
    mesh = cars.vehicle_mesh("X")
    n = vertex_normals(mesh)
    lengths = np.linalg.norm(n, axis=1)
    assert np.allclose(lengths, 1.0, atol=1e-5)


def test_triangulate_quad():
    assert triangulate([0, 1, 2, 3]) == [(0, 1, 2), (0, 2, 3)]


def test_exports_roundtrip(tmp_path):
    mesh = cars.vehicle_mesh("Q")  # a 3-cell bus
    export_obj(mesh, tmp_path / "q.obj", body_color=(40, 70, 150))
    export_gltf(mesh, tmp_path / "q.gltf", body_color=(40, 70, 150))

    obj = (tmp_path / "q.obj").read_text()
    assert obj.count("\nv ") + obj.startswith("v ") >= len(mesh.verts) - 1
    assert "usemtl" in obj and (tmp_path / "q.mtl").exists()

    gltf = json.loads((tmp_path / "q.gltf").read_text())
    assert gltf["asset"]["version"] == "2.0"
    assert gltf["buffers"][0]["uri"].startswith("data:")
    # one primitive per material present in the mesh
    used = {m for _, m in mesh.faces}
    assert len(gltf["meshes"][0]["primitives"]) == len(used)
