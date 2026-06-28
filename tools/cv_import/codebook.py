"""Calibrated photographed-color palette for regularizing classified cells.

The physical cards' printed colors differ from the game's render palette and shift
with lighting, so cell colors are *quantized* to this fixed 16-entry codebook —
one bin per vehicle type — learned by k-means over every occupied cell across the
reference card sheets. Snapping each cell to its nearest bin makes classification
robust and, critically, gives each distinct piece a distinct label so the parser
never merges two different-colored pieces into one.

Regenerate with ``python -m tools.cv_import.calibrate_codebook`` after changing the
sampler or the reference photos, then paste the printed ``CODEBOOK_BGR`` here.
"""
from __future__ import annotations

import cv2
import numpy as np

# 16 representative vehicle colors as photographed (BGR), one per bin.
CODEBOOK_BGR = [
    (156, 133, 148), (70, 130, 196), (194, 139, 72), (138, 124, 194),
    (138, 106, 119), (106, 146, 120), (86, 84, 91), (127, 163, 155),
    (95, 206, 212), (138, 86, 67), (75, 95, 38), (83, 167, 207),
    (173, 166, 165), (121, 65, 49), (121, 123, 87), (53, 71, 174),
]

_LAB = cv2.cvtColor(np.array([CODEBOOK_BGR], np.uint8), cv2.COLOR_BGR2LAB)[0].astype(np.float32)
# the reddest bin is the prime car X — highest a* (red-green axis)
PRIME_BIN = int(np.argmax(_LAB[:, 1]))


def quantize(bgr) -> int:
    """Snap a BGR color to the nearest codebook bin index (in CIELab)."""
    lab = cv2.cvtColor(np.array([[bgr]], np.uint8), cv2.COLOR_BGR2LAB)[0, 0].astype(np.float32)
    return int(np.argmin(np.sum((_LAB - lab) ** 2, axis=1)))
