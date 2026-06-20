"""Puzzle JSON schema and validation (no external deps)."""
from __future__ import annotations

from trafficjam.data.palette import SPECS

REQUIRED_TOP = {"id", "level", "grid", "vehicles", "printed_solution"}


def validate(data: dict) -> list[str]:
    """Return a list of problems; empty list means valid."""
    errors: list[str] = []

    missing = REQUIRED_TOP - data.keys()
    if missing:
        errors.append(f"missing top-level keys: {sorted(missing)}")
        return errors

    grid = data["grid"]
    rows = grid.get("rows")
    cols = grid.get("cols")
    exit_info = grid.get("exit", {})
    exit_row = exit_info.get("row")
    if not isinstance(rows, int) or not isinstance(cols, int):
        errors.append("grid.rows / grid.cols must be integers")
        return errors
    if not isinstance(exit_row, int) or not (0 <= exit_row < rows):
        errors.append("grid.exit.row out of range")

    occupied: dict[tuple[int, int], str] = {}
    ids_seen = set()
    has_prime = False
    for v in data["vehicles"]:
        vid = v.get("id")
        if vid in ids_seen:
            errors.append(f"duplicate vehicle id {vid!r}")
        ids_seen.add(vid)
        if vid not in SPECS:
            errors.append(f"unknown vehicle id {vid!r} (not in palette)")
            continue
        spec = SPECS[vid]
        length = v.get("len")
        if length != spec.length:
            errors.append(
                f"vehicle {vid}: len {length} != palette length {spec.length}"
            )
        orient = v.get("orient")
        if orient not in ("H", "V"):
            errors.append(f"vehicle {vid}: bad orient {orient!r}")
            continue
        r, c = v.get("row"), v.get("col")
        cells = (
            [(r, c + i) for i in range(length)]
            if orient == "H"
            else [(r + i, c) for i in range(length)]
        )
        for cell in cells:
            cr, cc = cell
            if not (0 <= cr < rows and 0 <= cc < cols):
                errors.append(f"vehicle {vid}: cell {cell} out of bounds")
            elif cell in occupied:
                errors.append(
                    f"vehicle {vid} overlaps {occupied[cell]} at {cell}"
                )
            else:
                occupied[cell] = vid
        if vid == "X":
            has_prime = True
            if orient != "H" or r != exit_row:
                errors.append("prime X must be horizontal on the exit row")

    if not has_prime:
        errors.append("no prime vehicle 'X'")
    return errors
