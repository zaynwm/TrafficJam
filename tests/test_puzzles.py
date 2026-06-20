from trafficjam.data.puzzles import list_puzzles, load_puzzle
from trafficjam.model.solver import shortest_solution, validate_solution
from tools import schema


def test_dataset_present():
    assert list_puzzles(), "no puzzles found in puzzles/"


def test_every_puzzle_valid_and_solvable():
    for path in list_puzzles():
        data = load_puzzle(path)
        errors = schema.validate(data)
        assert not errors, f"{path.name}: {errors}"
        board = data["board"]
        # The stored solution must replay and win.
        ok, msg = validate_solution(board, data["solution_moves"])
        assert ok, f"{path.name}: {msg}"
        # min_moves must equal the true BFS optimum.
        assert data["min_moves"] == len(shortest_solution(board)), path.name


def test_schema_flags_unknown_vehicle():
    bad = {
        "id": 99,
        "level": "Test",
        "grid": {"rows": 6, "cols": 6, "exit": {"row": 2, "side": "right"}},
        "vehicles": [
            {"id": "X", "row": 2, "col": 0, "len": 2, "orient": "H"},
            {"id": "Z", "row": 0, "col": 0, "len": 2, "orient": "V"},
        ],
        "printed_solution": ["XR6"],
    }
    errors = schema.validate(bad)
    assert any("unknown vehicle" in e for e in errors)
