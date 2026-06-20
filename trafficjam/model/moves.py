"""Move notation parsing/formatting for Rush Hour.

A move is one vehicle sliding any number of free cells along its axis.
Notation matches the puzzle cards: ``<ID><Dir><N>`` where ``Dir`` is one of
``U`` (up), ``D`` (down), ``L`` (left), ``R`` (right) and ``N`` is the number
of cells moved. E.g. ``RL2`` = vehicle R, left, 2 cells.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Direction -> (d_row, d_col) per single cell.  Key from the card back:
# Up / Down / Right / Left.
DELTAS = {
    "U": (-1, 0),
    "D": (1, 0),
    "L": (0, -1),
    "R": (0, 1),
}

# Which directions are valid for each orientation.
HORIZONTAL_DIRS = ("L", "R")
VERTICAL_DIRS = ("U", "D")

_TOKEN_RE = re.compile(r"^([A-KOPQRX])([UDLR])(\d+)$")


@dataclass(frozen=True)
class Move:
    """A single slide of one vehicle."""

    vehicle_id: str
    direction: str  # one of U/D/L/R
    distance: int

    def __post_init__(self) -> None:
        if self.direction not in DELTAS:
            raise ValueError(f"bad direction {self.direction!r}")
        if self.distance <= 0:
            raise ValueError(f"distance must be positive, got {self.distance}")

    @property
    def delta(self) -> tuple[int, int]:
        dr, dc = DELTAS[self.direction]
        return dr * self.distance, dc * self.distance

    def token(self) -> str:
        return f"{self.vehicle_id}{self.direction}{self.distance}"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.token()


def parse_move(token: str) -> Move:
    """Parse a single token like ``RL2`` into a :class:`Move`."""
    m = _TOKEN_RE.match(token.strip().upper())
    if not m:
        raise ValueError(f"unparseable move token: {token!r}")
    vid, direction, dist = m.group(1), m.group(2), int(m.group(3))
    return Move(vid, direction, dist)


def parse_solution(text) -> list[Move]:
    """Parse a whitespace-separated solution string (or token list)."""
    if isinstance(text, str):
        tokens = text.split()
    else:
        tokens = list(text)
    return [parse_move(t) for t in tokens]


def format_solution(moves) -> str:
    """Format a sequence of moves back into card notation."""
    return " ".join(m.token() for m in moves)
