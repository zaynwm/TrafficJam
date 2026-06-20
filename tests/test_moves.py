from trafficjam.model.moves import (
    Move,
    format_solution,
    parse_move,
    parse_solution,
)


def test_parse_and_token_roundtrip():
    for token in ["RL2", "PU1", "CU1", "HR1", "DD1", "XR5"]:
        assert parse_move(token).token() == token


def test_parse_lowercase_and_whitespace():
    assert parse_move(" rl2 ") == Move("R", "L", 2)


def test_parse_solution_and_format():
    moves = parse_solution("RL2 PU1 CU1")
    assert [m.token() for m in moves] == ["RL2", "PU1", "CU1"]
    assert format_solution(moves) == "RL2 PU1 CU1"


def test_bad_tokens_rejected():
    for bad in ["", "R", "RX2", "R2", "RL0", "ZL1"]:
        try:
            parse_move(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} should have raised")


def test_delta():
    assert Move("R", "L", 2).delta == (0, -2)
    assert Move("P", "U", 1).delta == (-1, 0)
    assert Move("D", "D", 3).delta == (3, 0)
