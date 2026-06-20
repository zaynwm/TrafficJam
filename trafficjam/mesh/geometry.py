"""Engine-agnostic low-poly mesh: build, orient, and export (OBJ / glTF).

Meshes are described by float vertices and polygon faces tagged with a symbolic
material name (``"body"`` / ``"glass"`` / ``"tyre"``). The same mesh data is
consumed by the PyGame software renderer and exported to OBJ/glTF for a later
SceneKit (iOS) port — glTF converts to Apple's USDZ via Reality Converter.
"""
from __future__ import annotations

import base64
import json
import struct
from dataclasses import dataclass, field

import numpy as np

# Symbolic material -> default RGB (0-255). "body" is overridden per vehicle.
DEFAULT_MATERIALS = {
    "body": (200, 200, 205),
    "glass": (60, 72, 90),
    "tyre": (26, 26, 30),
    "trim": (40, 40, 44),
}


@dataclass
class Mesh:
    verts: np.ndarray                       # (N, 3) float
    faces: list[tuple[list[int], str]] = field(default_factory=list)

    def centroid(self) -> np.ndarray:
        return self.verts.mean(axis=0)

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        return self.verts.min(axis=0), self.verts.max(axis=0)

    def copy(self) -> "Mesh":
        return Mesh(self.verts.copy(), [(list(idx), m) for idx, m in self.faces])


class MeshBuilder:
    """Accumulate vertices and polygon faces."""

    def __init__(self):
        self._verts: list[tuple[float, float, float]] = []
        self.faces: list[tuple[list[int], str]] = []

    def vert(self, p) -> int:
        self._verts.append((float(p[0]), float(p[1]), float(p[2])))
        return len(self._verts) - 1

    def loop(self, pts) -> list[int]:
        return [self.vert(p) for p in pts]

    def face(self, idx, material: str):
        self.faces.append((list(idx), material))

    def quad(self, a, b, c, d, material: str):
        self.faces.append(([a, b, c, d], material))

    def build(self) -> Mesh:
        return Mesh(np.array(self._verts, dtype=float), self.faces)


def face_normal(verts: np.ndarray, idx) -> np.ndarray:
    p = verts[idx]
    # Newell's method — robust for non-planar polygons.
    n = np.zeros(3)
    for i in range(len(p)):
        a, b = p[i], p[(i + 1) % len(p)]
        n[0] += (a[1] - b[1]) * (a[2] + b[2])
        n[1] += (a[2] - b[2]) * (a[0] + b[0])
        n[2] += (a[0] - b[0]) * (a[1] + b[1])
    norm = np.linalg.norm(n)
    return n / norm if norm > 1e-12 else n


def orient_outward(mesh: Mesh) -> Mesh:
    """Flip faces whose normal points toward the mesh centroid.

    Correct for star-convex parts (car bodies, wheels are built per-part), which
    removes any winding guesswork from the generator.
    """
    c = mesh.centroid()
    for face in mesh.faces:
        idx, _ = face
        fc = mesh.verts[idx].mean(axis=0)
        if np.dot(face_normal(mesh.verts, idx), fc - c) < 0:
            idx.reverse()
    return mesh


def merge(meshes) -> Mesh:
    verts: list[np.ndarray] = []
    faces: list[tuple[list[int], str]] = []
    offset = 0
    for m in meshes:
        verts.append(m.verts)
        for idx, mat in m.faces:
            faces.append(([i + offset for i in idx], mat))
        offset += len(m.verts)
    return Mesh(np.vstack(verts), faces)


def triangulate(idx) -> list[tuple[int, int, int]]:
    """Fan-triangulate a convex polygon."""
    return [(idx[0], idx[i], idx[i + 1]) for i in range(1, len(idx) - 1)]


def vertex_normals(mesh: Mesh) -> np.ndarray:
    """Area-weighted smooth normals, one per vertex."""
    normals = np.zeros_like(mesh.verts)
    for idx, _ in mesh.faces:
        for a, b, c in triangulate(idx):
            tri = mesh.verts[[a, b, c]]
            n = np.cross(tri[1] - tri[0], tri[2] - tri[0])  # area-weighted
            normals[a] += n
            normals[b] += n
            normals[c] += n
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    lengths[lengths < 1e-12] = 1.0
    return normals / lengths


def resolve_materials(body_color=None) -> dict[str, tuple[int, int, int]]:
    mats = dict(DEFAULT_MATERIALS)
    if body_color is not None:
        mats["body"] = tuple(body_color)
    return mats


# -- exporters -----------------------------------------------------------------
def export_obj(mesh: Mesh, path, body_color=None) -> None:
    """Write a Wavefront OBJ + sibling .mtl."""
    from pathlib import Path

    path = Path(path)
    mats = resolve_materials(body_color)
    normals = vertex_normals(mesh)
    mtl_name = path.with_suffix(".mtl").name

    lines = [f"mtllib {mtl_name}"]
    for v in mesh.verts:
        lines.append(f"v {v[0]:.5f} {v[1]:.5f} {v[2]:.5f}")
    for n in normals:
        lines.append(f"vn {n[0]:.5f} {n[1]:.5f} {n[2]:.5f}")
    # group faces by material to minimise usemtl switches
    by_mat: dict[str, list[list[int]]] = {}
    for idx, mat in mesh.faces:
        by_mat.setdefault(mat, []).append(idx)
    for mat, polys in by_mat.items():
        lines.append(f"usemtl {mat}")
        for idx in polys:
            verts = " ".join(f"{i + 1}//{i + 1}" for i in idx)
            lines.append(f"f {verts}")
    path.write_text("\n".join(lines) + "\n")

    mtl_lines = []
    for mat, rgb in mats.items():
        r, g, b = (c / 255 for c in rgb)
        mtl_lines += [f"newmtl {mat}", f"Kd {r:.4f} {g:.4f} {b:.4f}", ""]
    path.with_suffix(".mtl").write_text("\n".join(mtl_lines))


def export_gltf(mesh: Mesh, path, body_color=None) -> None:
    """Write a self-contained .gltf (positions, normals, per-material primitives)."""
    from pathlib import Path

    path = Path(path)
    mats = resolve_materials(body_color)
    normals = vertex_normals(mesh).astype(np.float32)
    positions = mesh.verts.astype(np.float32)

    materials_order = list(mats.keys())
    # triangulated index lists per material
    index_lists: dict[str, list[int]] = {m: [] for m in materials_order}
    for idx, mat in mesh.faces:
        for tri in triangulate(idx):
            index_lists.setdefault(mat, []).extend(tri)
    index_lists = {m: v for m, v in index_lists.items() if v}

    pos_bytes = positions.tobytes()
    nrm_bytes = normals.tobytes()
    idx_blobs = {m: struct.pack(f"<{len(v)}I", *v) for m, v in index_lists.items()}

    # buffer layout: positions | normals | indices...
    buf = bytearray()
    pos_off = len(buf); buf += pos_bytes
    nrm_off = len(buf); buf += nrm_bytes
    idx_offsets = {}
    for m, blob in idx_blobs.items():
        # 4-byte align
        while len(buf) % 4:
            buf += b"\x00"
        idx_offsets[m] = len(buf)
        buf += blob

    accessors = [
        {"bufferView": 0, "componentType": 5126, "count": len(positions),
         "type": "VEC3",
         "min": positions.min(axis=0).tolist(),
         "max": positions.max(axis=0).tolist()},
        {"bufferView": 1, "componentType": 5126, "count": len(normals),
         "type": "VEC3"},
    ]
    buffer_views = [
        {"buffer": 0, "byteOffset": pos_off, "byteLength": len(pos_bytes),
         "target": 34962},
        {"buffer": 0, "byteOffset": nrm_off, "byteLength": len(nrm_bytes),
         "target": 34962},
    ]
    primitives, materials = [], []
    for m, blob in idx_blobs.items():
        bv = len(buffer_views)
        buffer_views.append({"buffer": 0, "byteOffset": idx_offsets[m],
                             "byteLength": len(blob), "target": 34963})
        acc = len(accessors)
        accessors.append({"bufferView": bv, "componentType": 5125,
                          "count": len(index_lists[m]), "type": "SCALAR"})
        r, g, b = (c / 255 for c in mats[m])
        primitives.append({
            "attributes": {"POSITION": 0, "NORMAL": 1},
            "indices": acc, "material": len(materials),
        })
        materials.append({
            "name": m,
            "pbrMetallicRoughness": {
                "baseColorFactor": [r, g, b, 1.0],
                "metallicFactor": 0.0,
                "roughnessFactor": 0.6 if m != "glass" else 0.15,
            },
        })

    gltf = {
        "asset": {"version": "2.0", "generator": "traffic-jam mesh.cars"},
        "scenes": [{"nodes": [0]}], "scene": 0,
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": primitives}],
        "materials": materials,
        "accessors": accessors,
        "bufferViews": buffer_views,
        "buffers": [{
            "byteLength": len(buf),
            "uri": "data:application/octet-stream;base64,"
                   + base64.b64encode(bytes(buf)).decode(),
        }],
    }
    path.write_text(json.dumps(gltf, indent=2))
