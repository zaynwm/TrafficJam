"""Tests for the classical-CV card importer (tools/cv_import).

These exercise the deterministic pieces of the pipeline:
  * the assembly/tiling + prime-X logic, on synthetic perfect input;
  * card detection on the bundled sample sheet (10 cards);
  * the full pipeline runs end-to-end and fails safe (no crashes).

They intentionally do NOT assert pixel-perfect extraction of the sample cards —
cell-level color/occupancy accuracy on the pale printed pieces is best-effort and
guarded at runtime by the BFS-solver validation, which routes anything it can't
verify to needs_review/.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("cv2")  # CV importer is optional; skip if OpenCV absent

from trafficjam.data.palette import SPECS  # noqa: E402
from tools.cv_import import vision  # noqa: E402
from tools.cv_import.pieces import assemble  # noqa: E402

SAMPLE = Path(__file__).resolve().parents[1] / "reference" / "rush-hour-1-10-front.jpg"

# Puzzle 001's layout — used to build a synthetic, perfectly-classified board.
P001 = [
    ("X", 2, 1, 2, "H"), ("A", 0, 2, 2, "V"), ("O", 0, 3, 3, "H"),
    ("C", 1, 3, 2, "V"), ("D", 1, 4, 2, "V"), ("Q", 3, 2, 3, "H"),
    ("E", 3, 5, 2, "V"), ("F", 5, 3, 2, "H"),
]


def _synthetic_board():
    occ = np.zeros((6, 6), bool)
    color = np.full((6, 6, 3), (180, 180, 180), np.uint8)  # gray elsewhere
    for vid, r, c, length, orient in P001:
        bgr = tuple(int(x) for x in SPECS[vid].color[::-1])  # RGB -> BGR
        for i in range(length):
            rr, cc = (r, c + i) if orient == "H" else (r + i, c)
            occ[rr, cc] = True
            color[rr, cc] = bgr
    return occ, color


def test_assemble_recovers_geometry_and_prime():
    occ, color = _synthetic_board()
    vehicles, warnings = assemble(occ, color)
    assert warnings == []
    assert len(vehicles) == len(P001)

    got = {(v["row"], v["col"], v["len"], v["orient"]) for v in vehicles}
    expect = {(r, c, length, orient) for _, r, c, length, orient in P001}
    assert got == expect  # geometry is exact; ids beyond X may differ (cosmetic)

    x = next(v for v in vehicles if v["id"] == "X")
    assert (x["row"], x["col"], x["orient"]) == (2, 1, "H")


def test_detect_finds_ten_cards():
    img = vision.load_bgr(SAMPLE)
    cards = vision.detect_cards(img)
    assert len(cards) == 10


def test_detect_handles_touching_2d_grid():
    sheet = SAMPLE.parent / "rush-hour-21-30-front.jpg"
    if not sheet.exists():
        pytest.skip("2-D grid sample sheet not present")
    img = vision.load_bgr(sheet)
    assert len(vision.detect_cards(img)) == 10


def test_find_prime_x_by_red_off_exit_row():
    from tools.cv_import.pieces import _find_x_cells

    occ = np.zeros((6, 6), bool)
    color = np.full((6, 6, 3), (180, 180, 180), np.uint8)
    red = tuple(int(x) for x in SPECS["X"].color[::-1])  # BGR
    occ[1, 0] = occ[1, 1] = True          # a horizontal red pair on row 1
    color[1, 0] = color[1, 1] = red
    assert _find_x_cells(occ, color) == [(1, 0), (1, 1)]


def test_codebook_separates_distinct_colors():
    from tools.cv_import import codebook

    red = codebook.quantize((40, 40, 214))    # BGR red
    blue = codebook.quantize((200, 120, 40))  # BGR blue
    green = codebook.quantize((60, 170, 90))  # BGR green
    assert len({red, blue, green}) == 3       # distinct colors -> distinct bins
    assert red == codebook.PRIME_BIN          # vivid red is the prime (X) bin


def test_assemble_never_merges_dissimilar_colors():
    from tools.cv_import.pieces import assemble

    occ = np.zeros((6, 6), bool)
    color = np.full((6, 6, 3), (150, 150, 150), np.uint8)
    occ[0, 0] = occ[0, 1] = True
    color[0, 0] = (40, 40, 214)    # red
    color[0, 1] = (200, 120, 40)   # blue — must NOT join the red cell
    vehicles, _ = assemble(occ, color)
    merged = [v for v in vehicles
              if v["row"] == 0 and v["col"] == 0 and v["len"] == 2
              and v["orient"] == "H"]
    assert not merged


def test_pipeline_runs_and_fails_safe():
    from tools.cv_import.pipeline import Options, process_image

    opts = Options(no_ocr=True, dry_run=True)
    results = process_image(SAMPLE, opts)
    assert len(results) == 10
    assert all(r.status in {"ok", "review", "skipped"} for r in results)


def test_grid_corners_are_axis_aligned_square():
    img = vision.load_bgr(SAMPLE)
    for quad in vision.detect_cards(img):
        card = vision.rectify_card(img, quad)
        if not vision.is_face_up(card):
            continue
        tl, tr, br, bl = vision.find_grid_corners(card)
        # axis-aligned => warp is an orthogonal projection (square cells), never skewed
        assert tl[1] == tr[1] and bl[1] == br[1]   # top/bottom edges horizontal
        assert tl[0] == bl[0] and tr[0] == br[0]   # left/right edges vertical
        w, h = tr[0] - tl[0], bl[1] - tl[1]
        assert 0.85 < w / h < 1.2                  # ~square grid
        assert tl[0] > 0.05 * vision.CW and tr[0] < 0.95 * vision.CW  # wall excluded


def test_renders_a_png_per_processed_card(tmp_path):
    from tools.cv_import.pipeline import Options, process_image

    opts = Options(out=tmp_path / "out", review=tmp_path / "rev", no_ocr=True)
    results = process_image(SAMPLE, opts)
    processed = [r for r in results if r.status in {"ok", "review"}]
    assert processed
    for r in processed:
        assert r.dest.with_suffix(".png").exists()
