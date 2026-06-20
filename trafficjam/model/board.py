"""Rush Hour board model: vehicles, legal slides, win detection.

Coordinates: ``row`` 0..rows-1 top->bottom, ``col`` 0..cols-1 left->right.
A vehicle's anchor is its top-most / left-most occupied cell.  The exit is on
the right edge at ``exit_row``; the prime vehicle ``X`` wins by sliding off the
board through it.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from .moves import DELTAS, HORIZONTAL_DIRS, VERTICAL_DIRS, Move

PRIME_ID = "X"


@dataclass(frozen=True)
class Vehicle:
    id: str
    row: int
    col: int
    length: int
    orient: str  # "H" or "V"

    @property
    def horizontal(self) -> bool:
        return self.orient == "H"

    def cells(self) -> list[tuple[int, int]]:
        if self.horizontal:
            return [(self.row, self.col + i) for i in range(self.length)]
        return [(self.row + i, self.col) for i in range(self.length)]

    def moved(self, d_row: int, d_col: int) -> "Vehicle":
        return replace(self, row=self.row + d_row, col=self.col + d_col)

    def allows(self, direction: str) -> bool:
        if self.horizontal:
            return direction in HORIZONTAL_DIRS
        return direction in VERTICAL_DIRS


class Board:
    """Mutable board holding vehicles by id."""

    def __init__(self, rows: int, cols: int, exit_row: int, vehicles):
        self.rows = rows
        self.cols = cols
        self.exit_row = exit_row
        self.vehicles: dict[str, Vehicle] = {v.id: v for v in vehicles}
        self._validate_initial()

    # -- construction / cloning ------------------------------------------
    def clone(self) -> "Board":
        return Board(self.rows, self.cols, self.exit_row, self.vehicles.values())

    def _in_exit_lane(self, r: int, c: int) -> bool:
        """Cells off the right edge on the exit row — the prime's exit tunnel."""
        return r == self.exit_row and c >= self.cols

    def _validate_initial(self) -> None:
        seen: dict[tuple[int, int], str] = {}
        for v in self.vehicles.values():
            for cell in v.cells():
                r, c = cell
                if v.id == PRIME_ID and self._in_exit_lane(r, c):
                    continue  # prime is partway/fully through the exit
                if not (0 <= r < self.rows and 0 <= c < self.cols):
                    raise ValueError(f"vehicle {v.id} out of bounds at {cell}")
                if cell in seen:
                    raise ValueError(
                        f"vehicles {seen[cell]} and {v.id} overlap at {cell}"
                    )
                seen[cell] = v.id
        if PRIME_ID not in self.vehicles:
            raise ValueError("board has no prime vehicle 'X'")
        x = self.vehicles[PRIME_ID]
        if not x.horizontal or x.row != self.exit_row:
            raise ValueError("prime vehicle must be horizontal on the exit row")

    # -- occupancy --------------------------------------------------------
    def occupied(self, ignore: str | None = None) -> set[tuple[int, int]]:
        cells: set[tuple[int, int]] = set()
        for v in self.vehicles.values():
            if v.id == ignore:
                continue
            cells.update(v.cells())
        return cells

    def cell_free(self, r: int, c: int, occ: set[tuple[int, int]]) -> bool:
        return 0 <= r < self.rows and 0 <= c < self.cols and (r, c) not in occ

    # -- moves ------------------------------------------------------------
    def can_apply(self, move: Move) -> bool:
        v = self.vehicles.get(move.vehicle_id)
        if v is None or not v.allows(move.direction):
            return False
        dr, dc = DELTAS[move.direction]
        occ = self.occupied(ignore=v.id)
        cur = v
        for _ in range(move.distance):
            cur = cur.moved(dr, dc)
            lead = cur.cells()[-1] if move.direction in ("D", "R") else cur.cells()[0]
            lr, lc = lead
            # The prime vehicle may slide off the right edge through the exit.
            if (
                v.id == PRIME_ID
                and move.direction == "R"
                and lr == self.exit_row
                and lc >= self.cols
            ):
                continue
            if not self.cell_free(lr, lc, occ):
                return False
        return True

    def apply(self, move: Move) -> None:
        """Apply a move in place (assumes it is legal)."""
        if not self.can_apply(move):
            raise ValueError(f"illegal move {move.token()}")
        v = self.vehicles[move.vehicle_id]
        dr, dc = move.delta
        self.vehicles[v.id] = v.moved(dr, dc)

    # -- win --------------------------------------------------------------
    def solved(self) -> bool:
        """True once the prime vehicle has left the board via the exit."""
        x = self.vehicles[PRIME_ID]
        return x.col >= self.cols  # left edge past the last column

    def signature(self) -> tuple:
        """Hashable canonical state for search/visited sets."""
        return tuple(
            (vid, v.row, v.col)
            for vid, v in sorted(self.vehicles.items())
        )
