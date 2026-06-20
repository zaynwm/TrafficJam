"""Load puzzle JSON into Board objects."""
from __future__ import annotations

import json
from pathlib import Path

from trafficjam.model.board import Board, Vehicle
from trafficjam.model.moves import parse_solution

PUZZLE_DIR = Path(__file__).resolve().parents[2] / "puzzles"


def board_from_data(data: dict) -> Board:
    grid = data["grid"]
    vehicles = [
        Vehicle(v["id"], v["row"], v["col"], v["len"], v["orient"])
        for v in data["vehicles"]
    ]
    return Board(grid["rows"], grid["cols"], grid["exit"]["row"], vehicles)


def load_puzzle(path) -> dict:
    with open(path) as fh:
        data = json.load(fh)
    data["board"] = board_from_data(data)
    data["solution_moves"] = parse_solution(data["printed_solution"])
    return data


def list_puzzles(directory=PUZZLE_DIR) -> list[Path]:
    return sorted(Path(directory).glob("*.json"))
