"""Vehicle palette table — colors, types and lengths.

Built from ``reference/vehicles.md`` and the Color-Code card (which agree).
Colors are RGB; ``roof``/``shade`` are derived tints used by the isometric
renderer for the top face and shaded sides.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VehicleSpec:
    id: str
    name: str
    kind: str  # "car", "truck", "bus"
    length: int
    color: tuple[int, int, int]


# id -> spec
SPECS: dict[str, VehicleSpec] = {
    "X": VehicleSpec("X", "Prime passenger car", "car", 2, (214, 40, 40)),
    "A": VehicleSpec("A", "Honda Civic", "car", 2, (144, 214, 132)),
    "B": VehicleSpec("B", "Lamborghini", "car", 2, (243, 146, 55)),
    "C": VehicleSpec("C", "Tesla Model 3", "car", 2, (66, 153, 225)),
    "D": VehicleSpec("D", "Mazda Miata", "car", 2, (244, 178, 198)),
    "E": VehicleSpec("E", "Ferrari", "car", 2, (150, 111, 214)),
    "F": VehicleSpec("F", "Land Rover Defender", "car", 2, (76, 160, 99)),
    "G": VehicleSpec("G", "Mercedes sedan", "car", 2, (90, 96, 104)),
    "H": VehicleSpec("H", "Toyota Camry", "car", 2, (179, 162, 142)),
    "I": VehicleSpec("I", "Jeep Wrangler", "car", 2, (240, 214, 56)),
    "J": VehicleSpec("J", "Tesla Model Y", "car", 2, (238, 238, 240)),
    "K": VehicleSpec("K", "Toyota Tacoma", "car", 2, (38, 110, 72)),
    "O": VehicleSpec("O", "Semi-trailer truck", "truck", 3, (200, 168, 40)),
    "P": VehicleSpec("P", "Semi-trailer truck", "truck", 3, (190, 160, 224)),
    "Q": VehicleSpec("Q", "City bus", "bus", 3, (40, 70, 150)),
    "R": VehicleSpec("R", "City bus", "bus", 3, (60, 150, 90)),
}


def _clamp(v: int) -> int:
    return max(0, min(255, v))


def tint(color: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    """Lighten (factor>1) or darken (factor<1) a color."""
    return tuple(_clamp(int(c * factor)) for c in color)  # type: ignore[return-value]


def roof_color(spec: VehicleSpec) -> tuple[int, int, int]:
    return tint(spec.color, 1.18)


def shade_color(spec: VehicleSpec) -> tuple[int, int, int]:
    return tint(spec.color, 0.72)


def expected_length(vehicle_id: str) -> int:
    return SPECS[vehicle_id].length
