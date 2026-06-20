import pytest

from trafficjam.model.board import Board, Vehicle
from trafficjam.model.moves import Move


def make(vs):
    return Board(6, 6, 2, [Vehicle(*v) for v in vs])


def test_cells_horizontal_and_vertical():
    assert Vehicle("X", 2, 0, 2, "H").cells() == [(2, 0), (2, 1)]
    assert Vehicle("O", 0, 4, 3, "V").cells() == [(0, 4), (1, 4), (2, 4)]


def test_overlap_rejected():
    with pytest.raises(ValueError):
        make([("X", 2, 0, 2, "H"), ("A", 2, 1, 2, "V")])


def test_out_of_bounds_rejected():
    with pytest.raises(ValueError):
        make([("X", 2, 0, 2, "H"), ("O", 0, 4, 3, "H")])


def test_prime_must_be_on_exit_row():
    with pytest.raises(ValueError):
        make([("X", 3, 0, 2, "H")])


def test_legal_and_illegal_slides():
    b = make([("X", 2, 0, 2, "H"), ("C", 2, 3, 2, "V")])
    assert b.can_apply(Move("X", "R", 1))  # into (2,2)
    assert not b.can_apply(Move("X", "R", 2))  # blocked by C at (2,3)
    assert not b.can_apply(Move("X", "U", 1))  # horizontal can't move vertically
    assert not b.can_apply(Move("C", "U", 3))  # would leave the board


def test_apply_and_blocked_path():
    b = make([("X", 2, 0, 2, "H"), ("C", 2, 4, 2, "V")])
    # cannot jump over C even though a cell beyond is free
    assert not b.can_apply(Move("X", "R", 4))
    b.apply(Move("C", "D", 1))  # C -> (3,4),(4,4) clears row 2
    assert b.can_apply(Move("X", "R", 6))


def test_prime_exits_off_board():
    b = make([("X", 2, 0, 2, "H")])
    assert not b.solved()
    b.apply(Move("X", "R", 6))
    assert b.solved()


def test_signature_changes_with_state():
    b = make([("X", 2, 0, 2, "H")])
    s1 = b.signature()
    b.apply(Move("X", "R", 1))
    assert b.signature() != s1
