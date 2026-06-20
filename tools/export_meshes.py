"""Export generated vehicle meshes to OBJ / glTF for external tools and the
eventual SceneKit (iOS) port.

glTF is the portable interchange; convert to Apple's USDZ with Reality Converter
(or a USD exporter) for SceneKit. Meshes are fully generated from parameters in
``trafficjam/mesh/cars.py`` — no images or third-party geometry.

    python -m tools.export_meshes --out assets/meshes
    python -m tools.export_meshes --archetypes --format gltf
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from trafficjam.data.palette import SPECS
from trafficjam.mesh import cars
from trafficjam.mesh.geometry import export_gltf, export_obj


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Export vehicle meshes.")
    ap.add_argument("--out", default="assets/meshes", type=Path)
    ap.add_argument("--format", choices=["obj", "gltf", "both"], default="both")
    ap.add_argument("--archetypes", action="store_true",
                    help="export one mesh per archetype instead of per vehicle")
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    if args.archetypes:
        items = [(name, cars.build_car(spec), None)
                 for name, spec in cars.ARCHETYPES.items()]
    else:
        items = [(vid, cars.vehicle_mesh(vid), SPECS[vid].color)
                 for vid in cars.VEHICLE_ARCHETYPE]

    count = 0
    for name, mesh, color in items:
        if args.format in ("obj", "both"):
            export_obj(mesh, args.out / f"{name}.obj", body_color=color)
        if args.format in ("gltf", "both"):
            export_gltf(mesh, args.out / f"{name}.gltf", body_color=color)
        count += 1
        print(f"  exported {name} ({len(mesh.verts)} verts, {len(mesh.faces)} faces)")
    print(f"Wrote {count} mesh(es) to {args.out}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
