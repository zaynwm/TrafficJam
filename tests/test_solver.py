from trafficjam.model.board import Board, Vehicle
from trafficjam.model.moves import Move
from trafficjam.model.solver import (
    reachable_positions,
    shortest_solution,
    validate_solution,
)


def make(vs):
    return Board(6, 6, 2, [Vehicle(*v) for v in vs])


def test_reachable_prime_can_drive_out():
    b = make([("X", 2, 0, 2, "H")])
    dirs = {(d, dist) for (d, dist, _r, _c) in reachable_positions(b, "X")}
    # may rest at cols 1..4, then fully exit at distance 6 (anchor col 6)
    assert ("R", 6) in dirs
    assert ("R", 5) not in dirs  # half-off resting position is not allowed


def test_reachable_blocked_both_sides():
    b = make([("X", 2, 1, 2, "H"), ("A", 2, 0, 2, "V"), ("C", 2, 3, 2, "V")])
    assert reachable_positions(b, "X") == []


def test_shortest_trivial():
    b = make([("X", 2, 0, 2, "H")])
    assert [m.token() for m in shortest_solution(b)] == ["XR6"]


def test_shortest_requires_clearing():
    b = make([("X", 2, 0, 2, "H"), ("C", 2, 3, 2, "V")])
    sol = shortest_solution(b)
    assert sol is not None
    # replaying the solution wins
    ok, msg = validate_solution(b, sol)
    assert ok, msg


def test_validate_rejects_illegal():
    b = make([("X", 2, 0, 2, "H"), ("C", 2, 3, 2, "V")])
    ok, msg = validate_solution(b, [Move("X", "R", 6)])
    assert not ok


def test_validate_rejects_non_winning():
    b = make([("X", 2, 0, 2, "H"), ("C", 2, 3, 2, "V")])
    ok, msg = validate_solution(b, [Move("C", "D", 1)])
    assert not ok and "exiting" in msg
