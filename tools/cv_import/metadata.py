"""Read a card's printed number + difficulty with a small local Ollama model.

This is the only non-CV step: the layout is recovered deterministically by
``vision``/``pieces``; here a multimodal model just transcribes two short text
fields from the rectified card image. It degrades gracefully — if the daemon or
model is unavailable, both fields come back ``None`` and the card is routed to
review for a human to label.
"""
from __future__ import annotations

import base64
import io
import json
import os

import cv2

DEFAULT_OCR_MODEL = "gemma4:e4b"
DEFAULT_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

PROMPT = """This image is one Rush Hour puzzle card. Read ONLY the printed text:
- the puzzle NUMBER (the large numeral below the grid), and
- the DIFFICULTY / level word printed on the colored band at the bottom
  (e.g. Beginner, Intermediate, Advanced, Expert).
Return JSON. Use null for a field you cannot read. Do not describe the board."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "number": {"type": ["integer", "null"]},
        "difficulty": {"type": ["string", "null"]},
    },
    "required": ["number", "difficulty"],
}


COUNT_PROMPT = """This photo shows one or more Rush Hour puzzle cards laid on a
surface, usually in a tidy grid. Count them and report the grid layout. Return
JSON: count (total cards), rows, cols (the grid arrangement; for a single row use
rows=1). Estimate your best layout even if cards touch or overlap slightly."""

COUNT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "count": {"type": ["integer", "null"]},
        "rows": {"type": ["integer", "null"]},
        "cols": {"type": ["integer", "null"]},
    },
    "required": ["count", "rows", "cols"],
}


def _encode(bgr, max_w: int = 1100) -> str:
    if bgr.shape[1] > max_w:
        scale = max_w / bgr.shape[1]
        bgr = cv2.resize(bgr, (max_w, int(bgr.shape[0] * scale)))
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        raise ValueError("failed to encode image")
    return base64.standard_b64encode(buf.tobytes()).decode()


def count_cards(image_bgr, model: str = DEFAULT_OCR_MODEL,
                host: str = DEFAULT_HOST) -> dict:
    """Ask the model how many cards and their grid layout (never raises).

    A backstop for the CV segmenter: returns ``{count, rows, cols}`` with
    ``None`` values if the model/daemon is unavailable.
    """
    blank = {"count": None, "rows": None, "cols": None}
    try:
        import ollama
    except ImportError:
        return blank
    try:
        client = ollama.Client(host=host)
        resp = client.chat(
            model=model, format=COUNT_SCHEMA, options={"temperature": 0},
            messages=[{"role": "user", "content": COUNT_PROMPT,
                       "images": [_encode(image_bgr)]}],
        )
        data = json.loads(resp["message"]["content"])
        return {"count": data.get("count"), "rows": data.get("rows"),
                "cols": data.get("cols")}
    except Exception:
        return blank


def read_metadata(card_bgr, model: str = DEFAULT_OCR_MODEL,
                  host: str = DEFAULT_HOST) -> dict:
    """Return ``{"number": int|None, "difficulty": str|None}`` (never raises)."""
    blank = {"number": None, "difficulty": None}
    try:
        import ollama
    except ImportError:
        return blank
    try:
        client = ollama.Client(host=host)
        resp = client.chat(
            model=model,
            format=SCHEMA,
            options={"temperature": 0},
            messages=[{"role": "user", "content": PROMPT,
                       "images": [_encode(card_bgr)]}],
        )
        data = json.loads(resp["message"]["content"])
        return {"number": data.get("number"), "difficulty": data.get("difficulty")}
    except Exception:
        return blank
