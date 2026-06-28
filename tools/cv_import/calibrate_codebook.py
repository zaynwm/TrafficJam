"""Regenerate the photographed-color codebook (tools/cv_import/codebook.py).

Samples every occupied cell across the reference card sheets, k-means clusters the
colors into 16 bins (one per vehicle type), and prints a ``CODEBOOK_BGR`` list to
paste into ``codebook.py``. Run after changing the sampler or reference photos:

    python -m tools.cv_import.calibrate_codebook [sheet.jpg ...]
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

from tools.cv_import import vision

DEFAULT_SHEETS = [
    "reference/rush-hour-1-10-front.jpg", "reference/rush-hour-11-20-front.jpg",
    "reference/rush-hour-21-30-front.jpg", "reference/rush-hour-31-40-front.jpg",
]


def collect(sheets):
    colors = []
    for path in sheets:
        if not Path(path).is_file():
            continue
        img = vision.load_bgr(path)
        for quad in vision.detect_cards(img):
            card = vision.rectify_card(img, quad)
            if not vision.is_face_up(card):
                continue
            try:
                corners = vision.find_grid_corners(card)
            except ValueError:
                continue
            occ, color, _ = vision.sample_board(vision.warp_board(card, corners))
            colors.extend(color[r, c] for r in range(vision.ROWS)
                          for c in range(vision.COLS) if occ[r, c])
    return np.array(colors, np.float32)


def main(argv=None) -> int:
    sheets = list(argv) if argv else DEFAULT_SHEETS
    samples = collect(sheets)
    if len(samples) < 16:
        print(f"too few samples ({len(samples)})")
        return 1
    lab = cv2.cvtColor(samples.reshape(-1, 1, 3).astype(np.uint8),
                       cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float32)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 0.2)
    _, _, centers = cv2.kmeans(lab, 16, None, crit, 8, cv2.KMEANS_PP_CENTERS)
    bgr = cv2.cvtColor(centers.reshape(-1, 1, 3).astype(np.uint8),
                       cv2.COLOR_LAB2BGR).reshape(-1, 3)
    print(f"# learned from {len(samples)} occupied cells")
    print("CODEBOOK_BGR = [")
    for i in range(0, 16, 4):
        row = ", ".join(f"({b}, {g}, {r})" for b, g, r in bgr[i:i + 4])
        print(f"    {row},")
    print("]")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
