"""Orchestrate the CV import: photo -> per-card puzzle JSON.

Detect cards -> rectify -> gate face-up -> locate+warp board -> sample cells ->
assemble vehicles -> read number/difficulty (LLM) -> validate (schema + BFS
solver) -> write to ``out`` or ``review``. Optional debug overlays per card.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import cv2

from trafficjam.data.puzzles import board_from_data
from trafficjam.model.solver import shortest_solution
from tools import schema
from tools.cv_import import render, vision
from tools.cv_import.metadata import (DEFAULT_HOST, DEFAULT_OCR_MODEL,
                                      count_cards, read_metadata)
from tools.cv_import.pieces import EXIT_ROW, assemble, _find_x_cells

GRID = {"rows": 6, "cols": 6, "exit": {"row": 2, "side": "right"}}


@dataclass
class Options:
    out: Path = Path("puzzles")
    review: Path = Path("needs_review")
    ocr_model: str = DEFAULT_OCR_MODEL
    host: str = DEFAULT_HOST
    no_ocr: bool = False
    dry_run: bool = False
    debug_dir: Path | None = None


@dataclass
class CardResult:
    index: int
    status: str           # "ok" | "review" | "skipped"
    message: str
    dest: Path | None = None
    record: dict | None = None


def _finalize(record: dict, warnings: list[str]) -> tuple[bool, str]:
    """Schema-check, solve to fill par/solution, and fold in assembly warnings."""
    errors = schema.validate(record)
    if errors:
        return False, "; ".join(errors)
    try:
        board = board_from_data(record)
    except Exception as e:
        return False, f"board build failed: {e}"
    solution = shortest_solution(board)
    if solution is None:
        return False, "no solution found (layout likely misread or unsolvable)"
    record["printed_solution"] = [m.token() for m in solution]
    record["min_moves"] = len(solution)
    if warnings:
        return False, "assembly warnings: " + "; ".join(warnings)
    if record["id"] <= 0:
        return False, "no card number detected - assign manually"
    return True, "ok"


def _aligned_board(card, corners):
    """Warp + sample; if the red prime car lands off the exit row, snap the grid
    vertically so it sits on row 2 (X is always on the exit row) and re-sample."""
    board = vision.warp_board(card, corners)
    occ, color, _ = vision.sample_board(board)
    x_cells = _find_x_cells(occ, color)
    if x_cells and x_cells[0][0] != EXIT_ROW:
        shift = EXIT_ROW - x_cells[0][0]
        cell_vec = (corners[3] - corners[0]) / 6.0   # one grid row, TL->BL
        snapped = (corners - shift * cell_vec).astype("float32")
        b2 = vision.warp_board(card, snapped)
        o2, c2, _ = vision.sample_board(b2)
        x2 = _find_x_cells(o2, c2)
        if x2 and x2[0][0] == EXIT_ROW:   # accept only if it actually fixed it
            return b2, o2, c2
    return board, occ, color


def _dump_debug(opts: Options, img_stem: str, idx: int, card, corners) -> None:
    d = opts.debug_dir
    d.mkdir(parents=True, exist_ok=True)
    vis = card.copy()
    cv2.polylines(vis, [corners.astype(int)], True, (0, 255, 0), 2)
    for x, y in corners.astype(int):
        cv2.circle(vis, (int(x), int(y)), 6, (0, 0, 255), -1)
    cv2.imwrite(str(d / f"{img_stem}-card{idx:02d}-rect.png"), vis)


def process_image(image_path: Path, opts: Options) -> list[CardResult]:
    img = vision.load_bgr(image_path)
    debug = vision.Debug(enabled=opts.debug_dir is not None)
    quads = vision.detect_cards(img, debug)

    # LLM backstop: if the CV count disagrees with the model's card count, retry
    # the split forced into the model's row x col layout and keep it if it matches.
    if not opts.no_ocr:
        hint = count_cards(img, opts.ocr_model, opts.host)
        if (hint["count"] and hint["count"] != len(quads)
                and hint["rows"] and hint["cols"]):
            guided = vision.detect_cards(img, debug,
                                         arrangement=(hint["rows"], hint["cols"]))
            # Only adopt the hint's layout if it matches the model's count AND the
            # cards stay well-shaped — never let a bad hint distort the segmenter.
            if len(guided) == hint["count"] and vision.well_shaped(guided):
                quads = guided

    stem = image_path.stem
    results: list[CardResult] = []

    for idx, quad in enumerate(quads, 1):
        board = occ = color = None
        vehicles: list[dict] = []
        try:
            card = vision.rectify_card(img, quad)
            if not vision.is_face_up(card):
                results.append(CardResult(idx, "skipped", "face-down"))
                continue
            corners = vision.find_grid_corners(card)
            board, occ, color = _aligned_board(card, corners)
            vehicles, warnings = assemble(occ, color)
            meta = ({"number": None, "difficulty": None} if opts.no_ocr
                    else read_metadata(card, opts.ocr_model, opts.host))
            if opts.debug_dir is not None:
                _dump_debug(opts, stem, idx, card, corners)
        except Exception as e:
            record = {"id": 0, "level": "Unknown", "min_moves": None}
            _write_card(opts, image_path, stem, idx, record, "review", board,
                        occ, color, vehicles)
            results.append(CardResult(idx, "review", f"processing error: {e}"))
            continue

        num = meta.get("number")
        record = {
            "id": num if isinstance(num, int) and num > 0 else 0,
            "level": meta.get("difficulty") or "Unknown",
            "grid": dict(GRID),
            "vehicles": vehicles,
            "printed_solution": [],
            "min_moves": None,
            "source": {"image": str(image_path), "card_index": idx,
                       "method": "cv"},
        }
        ok, msg = _finalize(record, warnings)
        if not ok:
            record["_validation"] = f"QUARANTINED: {msg}"
        status = "ok" if ok else "review"
        dest = _write_card(opts, image_path, stem, idx, record, status, board,
                           occ, color, vehicles, msg)
        results.append(CardResult(idx, status, msg, dest, record))

    if debug.enabled:
        opts.debug_dir.mkdir(parents=True, exist_ok=True)
        for name, im in debug.images.items():
            cv2.imwrite(str(opts.debug_dir / f"{stem}-{name}.png"), im)
    return results


def _write_card(opts: Options, image_path: Path, stem: str, idx: int,
                record: dict, status: str, board, occ, color, vehicles,
                message: str = "") -> Path:
    """Write a card's JSON and its understanding-render PNG (unless dry-run)."""
    target = opts.out if status == "ok" else opts.review
    name = (f"{record['id']:03d}" if record.get("id", 0) > 0
            else f"{stem}-card{idx:02d}")
    dest = target / f"{name}.json"
    if not opts.dry_run:
        target.mkdir(parents=True, exist_ok=True)
        if "grid" in record:
            with open(dest, "w") as fh:
                json.dump(record, fh, indent=2)
        png = render.render(board, occ, color, vehicles, record, status, message)
        cv2.imwrite(str(dest.with_suffix(".png")), png)
    return dest
