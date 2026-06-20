"""BFS solver and helpers for Rush Hour.

Provides:
- ``reachable_positions`` — all alternative anchor positions a vehicle can slide
  to (powers click-to-move and drag clamping).
- ``shortest_solution`` — breadth-first optimal solution (the scoring "par").
- ``validate_solution`` — confirm a printed solution is legal and wins.
"""
from __future__ import annotations

from collections import deque

from .board import PRIME_ID, Board, Vehicle
from .moves import DELTAS, Move


def reachable_positions(board: Board, vehicle_id: str) -> list[tuple[int, int, int]]:
    """Return ``(direction_distance...)`` reachable anchors for one vehicle.

    Result is a list of ``(d_row, d_col, distance)`` tuples? No — we return a
    list of ``(direction, distance, anchor_row, anchor_col)`` describing each
    distinct slide target, ordered outward in both directions.
    """
    v = board.vehicles[vehicle_id]
    occ = board.occupied(ignore=vehicle_id)
    results: list[tuple[str, int, int, int]] = []
    dirs = ("L", "R") if v.horizontal else ("U", "D")
    for direction in dirs:
        dr, dc = DELTAS[direction]
        cur = v
        dist = 0
        while True:
            cur = cur.moved(dr, dc)
            dist += 1
            lead = cur.cells()[-1] if direction in ("D", "R") else cur.cells()[0]
            lr, lc = lead
            in_lane = (
                vehicle_id == PRIME_ID
                and direction == "R"
                and board._in_exit_lane(lr, lc)
            )
            if not in_lane and not board.cell_free(lr, lc, occ):
                break
            # Only record valid resting positions: fully on-board, or (for the
            # prime sliding right) fully off the board through the exit. The
            # prime may not rest half off the edge.
            if vehicle_id == PRIME_ID and direction == "R":
                if cur.col >= board.cols:
                    results.append((direction, dist, cur.row, cur.col))
                    break
                if cur.col + v.length - 1 < board.cols:
                    results.append((direction, dist, cur.row, cur.col))
            else:
                results.append((direction, dist, cur.row, cur.col))
    return results


def legal_moves(board: Board) -> list[Move]:
    moves: list[Move] = []
    for vid in board.vehicles:
        for direction, dist, _r, _c in reachable_positions(board, vid):
            moves.append(Move(vid, direction, dist))
    return moves


def shortest_solution(board: Board, max_nodes: int = 2_000_000):
    """Return the optimal move list, or ``None`` if unsolved within budget."""
    start = board.clone()
    if start.solved():
        return []
    visited = {start.signature()}
    queue: deque[tuple[Board, list[Move]]] = deque([(start, [])])
    nodes = 0
    while queue:
        state, path = queue.popleft()
        nodes += 1
        if nodes > max_nodes:
            return None
        for move in legal_moves(state):
            nxt = state.clone()
            nxt.apply(move)
            sig = nxt.signature()
            if sig in visited:
                continue
            new_path = path + [move]
            if nxt.solved():
                return new_path
            visited.add(sig)
            queue.append((nxt, new_path))
    return None


def min_moves(board: Board) -> int | None:
    sol = shortest_solution(board)
    return None if sol is None else len(sol)


def validate_solution(board: Board, moves) -> tuple[bool, str]:
    """Replay ``moves`` from ``board``; return (ok, message).

    Confirms every move is legal and the sequence ends with X off the board.
    """
    state = board.clone()
    for i, move in enumerate(moves, 1):
        if move.vehicle_id not in state.vehicles:
            return False, f"move {i} {move.token()}: unknown vehicle"
        if state.solved():
            return False, f"move {i} {move.token()}: puzzle already solved"
        if not state.can_apply(move):
            return False, f"move {i} {move.token()}: illegal slide"
        state.apply(move)
    if not state.solved():
        return False, "sequence does not end with X exiting"
    return True, "ok"
