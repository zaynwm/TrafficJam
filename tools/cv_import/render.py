"""Render a human-checkable picture of what the importer understood per card.

Saved next to every card's JSON (passing or quarantined) so you can eyeball the
system's interpretation at a glance. Three panels under a status header:

  1. the rectified board crop (what the CV actually saw),
  2. the per-cell classification swatch (occupancy + sampled color),
  3. the parsed reconstruction (vehicles drawn in palette colors with ids + exit).
"""
from __future__ import annotations

import cv2
import numpy as np

from trafficjam.data.palette import SPECS
from tools.cv_import import vision

PANEL = 360
CELL = PANEL // vision.ROWS
HEADER = 84
STATUS_BGR = {"ok": (60, 160, 60), "review": (40, 110, 210),
              "skipped": (120, 120, 120)}


def _reconstruction(vehicles: list[dict]) -> np.ndarray:
    img = np.full((PANEL, PANEL, 3), 235, np.uint8)
    for t in range(vision.ROWS + 1):
        cv2.line(img, (t * CELL, 0), (t * CELL, PANEL), (205, 205, 205), 1)
        cv2.line(img, (0, t * CELL), (PANEL, t * CELL), (205, 205, 205), 1)
    # exit marker on the right edge at row 2
    ey = int((2 + 0.5) * CELL)
    cv2.arrowedLine(img, (PANEL - 24, ey), (PANEL - 2, ey), (40, 110, 210), 3,
                    tipLength=0.5)
    for v in vehicles:
        spec = SPECS.get(v["id"])
        bgr = tuple(int(x) for x in spec.color[::-1]) if spec else (90, 90, 90)
        r, c, length, orient = v["row"], v["col"], v["len"], v["orient"]
        if orient == "H":
            p0, p1 = (c, r), (c + length, r + 1)
        else:
            p0, p1 = (c, r), (c + 1, r + length)
        tl = (p0[0] * CELL + 5, p0[1] * CELL + 5)
        brc = (p1[0] * CELL - 5, p1[1] * CELL - 5)
        cv2.rectangle(img, tl, brc, bgr, -1)
        cv2.rectangle(img, tl, brc, (40, 40, 40), 2)
        ctr = ((tl[0] + brc[0]) // 2 - 8, (tl[1] + brc[1]) // 2 + 8)
        cv2.putText(img, v["id"], ctr, cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                    (255, 255, 255), 3)
        cv2.putText(img, v["id"], ctr, cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                    (0, 0, 0), 1)
    return img


def _label(img: np.ndarray, text: str) -> np.ndarray:
    bar = np.full((24, img.shape[1], 3), 245, np.uint8)
    cv2.putText(bar, text, (6, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1)
    return np.vstack([bar, img])


def render(board_warp, occ, color, vehicles: list[dict], record: dict,
           status: str, message: str) -> np.ndarray:
    """Return the composite BGR image (board | swatch | reconstruction + header)."""
    actual = cv2.resize(board_warp, (PANEL, PANEL)) if board_warp is not None \
        else np.full((PANEL, PANEL, 3), 40, np.uint8)
    swatch = (cv2.resize(vision.swatch(occ, color), (PANEL, PANEL))
              if occ is not None else np.full((PANEL, PANEL, 3), 40, np.uint8))
    panels = cv2.hconcat([_label(actual, "rectified board"),
                          _label(swatch, "cell classification"),
                          _label(_reconstruction(vehicles), "parsed pieces")])

    header = np.full((HEADER, panels.shape[1], 3), 30, np.uint8)
    cv2.rectangle(header, (0, 0), (10, HEADER),
                  STATUS_BGR.get(status, (120, 120, 120)), -1)
    cid = record.get("id", 0)
    line1 = (f"card #{cid if cid else '?'}  |  {record.get('level', '?')}  |  "
             f"{status.upper()}  |  min_moves={record.get('min_moves')}")
    cv2.putText(header, line1, (22, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                (255, 255, 255), 1)
    cv2.putText(header, message[:110], (22, 62), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (200, 200, 200), 1)
    return np.vstack([header, panels])
