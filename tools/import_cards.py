"""Build puzzle data from ONE photo of physical cards using a local Ollama model.

The input is a single JPEG containing one or more Rush Hour cards lying on a
surface; each card may be face-up (puzzle grid visible) or face-down (plain
back). The pipeline runs **fully offline** against a local Ollama daemon:

  1. Send the whole photo to the vision model (default ``gemma4:26b``) and ask it
     to locate every card: a bounding box (normalised 0..1) and whether each is
     face-up or face-down.
  2. For each face-up card, crop its bounding box from the source image (expanded
     by a configurable ``--margin``) and send the close-up back to the model,
     asking for the starting layout — every piece identified by its STANDARD
     COLOR NAME (a fixed vocabulary, for consistency) with grid row/col/orient.
  3. Map color names -> palette vehicle ids, then validate: schema-check the
     board and confirm the BFS solver can solve it (storing the optimal solution
     as the puzzle's ``printed_solution`` and ``min_moves``).
  4. Solver-verified cards -> puzzles/<NNN>.json ; everything else (face-down is
     skipped) that can't be verified -> needs_review/.

Import-time only — the game itself never needs a model. Requires the ``ollama``
+ ``pillow`` packages and a vision-capable model pulled locally
(``ollama pull gemma4:26b``).

Usage:
    python -m tools.import_cards photo.jpg
    python -m tools.import_cards photo.jpg --out puzzles --review needs_review
    python -m tools.import_cards photo.jpg --margin 0.08 --save-crops /tmp/crops
    python -m tools.import_cards photo.jpg --model gemma4:26b --dry-run
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
from pathlib import Path

from trafficjam.data.palette import SPECS
from trafficjam.data.puzzles import board_from_data
from trafficjam.model.solver import shortest_solution
from tools import schema

# Default to a vision-capable Ollama tag. Override with --model for whatever you
# have pulled locally (`ollama list`).
DEFAULT_MODEL = "gemma4:26b"
DEFAULT_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
MAX_IMAGE_DIM = 1400  # downscale uploads to cut tokens / latency
DEFAULT_MARGIN = 0.06  # expand each detected bbox by this fraction of its size

# Standard color name for every palette piece — a fixed vocabulary so the model
# names pieces the same way across cards. Type (car/bus/truck) disambiguates the
# several blues/greens. Keep these in sync with reference/vehicles.md.
LABELS: dict[str, str] = {
    "X": "red car",
    "A": "light green car",
    "B": "orange car",
    "C": "blue car",
    "D": "pink car",
    "E": "purple car",
    "F": "forest green car",
    "G": "gray car",
    "H": "tan car",
    "I": "yellow car",
    "J": "white car",
    "K": "dark green car",
    "O": "yellow truck",
    "P": "lavender truck",
    "Q": "blue bus",
    "R": "green bus",
}
LABEL_TO_ID = {label: vid for vid, label in LABELS.items()}

# --- Pass 1: locate the cards --------------------------------------------------

DETECT_PROMPT = """You are a vision system that locates Rush Hour puzzle cards in a photo.

The photo shows one or more physical cards on a surface. Each card is either
FACE-UP (showing a 6x6 grid with colored toy vehicles) or FACE-DOWN (showing the
plain printed card back, with no grid).

Return one entry per card with:
- a bounding box as fractions of the image size in [0,1]: left, top, right,
  bottom, where (0,0) is the TOP-LEFT corner and (1,1) the bottom-right. Make the
  box tight but include the whole card.
- face: "up" if the puzzle grid is visible, otherwise "down".

Report every card you can see, including partially-cut-off ones."""

DETECT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "left": {"type": "number"},
                    "top": {"type": "number"},
                    "right": {"type": "number"},
                    "bottom": {"type": "number"},
                    "face": {"type": "string", "enum": ["up", "down"]},
                },
                "required": ["left", "top", "right", "bottom", "face"],
            },
        }
    },
    "required": ["cards"],
}

# --- Pass 2: transcribe one card ----------------------------------------------

TRANSCRIBE_PROMPT = """You read ONE face-up Rush Hour puzzle card and output its starting layout as JSON.

The board is a 6x6 grid. row 0 is the top, row 5 the bottom; col 0 is the left,
col 5 the right. The exit is a gap on the RIGHT edge at row 2; the red prime car
must reach it.

Identify every vehicle by its STANDARD COLOR NAME. Use EXACTLY one of these names
(do not invent new ones); the type distinguishes same-color pieces:

{legend}

Each vehicle is horizontal ("H", occupying consecutive columns in one row) or
vertical ("V", occupying consecutive rows in one column). row/col is the
top-most / left-most cell it occupies. Cars are 2 cells long; trucks and buses
are 3 cells long.

If the card prints a puzzle number and a difficulty/level, include them. Output
ONLY the JSON. Transcribe exactly what you see — do not solve or optimize."""

TRANSCRIBE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "id": {"type": "integer"},
        "level": {"type": "string"},
        "vehicles": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "color": {"type": "string", "enum": list(LABELS.values())},
                    "row": {"type": "integer"},
                    "col": {"type": "integer"},
                    "orient": {"type": "string", "enum": ["H", "V"]},
                },
                "required": ["color", "row", "col", "orient"],
            },
        },
    },
    "required": ["id", "level", "vehicles"],
}


def legend_text() -> str:
    lines = []
    for vid, label in LABELS.items():
        spec = SPECS[vid]
        note = " (the prime target car that must exit)" if vid == "X" else ""
        lines.append(f"  {label} — {spec.kind}, {spec.length} cells long{note}")
    return "\n".join(lines)


# --- Image helpers -------------------------------------------------------------

def load_image(path: Path):
    from PIL import Image

    return Image.open(path).convert("RGB")


def encode(img) -> str:
    """Downscale a copy and return base64-encoded JPEG (Ollama image input)."""
    im = img.copy()
    im.thumbnail((MAX_IMAGE_DIM, MAX_IMAGE_DIM))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=88)
    return base64.standard_b64encode(buf.getvalue()).decode()


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def crop_card(img, bbox: dict, margin: float):
    """Crop the normalised bbox (expanded by ``margin``) from a full-res image.

    Returns ``None`` for a degenerate box.
    """
    w, h = img.size
    x0, y0 = bbox["left"] * w, bbox["top"] * h
    x1, y1 = bbox["right"] * w, bbox["bottom"] * h
    if x1 <= x0 or y1 <= y0:
        return None
    mx, my = margin * (x1 - x0), margin * (y1 - y0)
    box = (
        int(_clamp(x0 - mx, 0, w)), int(_clamp(y0 - my, 0, h)),
        int(_clamp(x1 + mx, 0, w)), int(_clamp(y1 + my, 0, h)),
    )
    return img.crop(box)


# --- Model calls ---------------------------------------------------------------

def detect_cards(client, model: str, img) -> list[dict]:
    resp = client.chat(
        model=model,
        format=DETECT_SCHEMA,
        options={"temperature": 0},
        messages=[
            {"role": "system", "content": DETECT_PROMPT},
            {
                "role": "user",
                "content": "Locate every Rush Hour card in this photo.",
                "images": [encode(img)],
            },
        ],
    )
    return json.loads(resp["message"]["content"]).get("cards", [])


def transcribe_card(client, model: str, crop) -> dict:
    resp = client.chat(
        model=model,
        format=TRANSCRIBE_SCHEMA,
        options={"temperature": 0},
        messages=[
            {"role": "system",
             "content": TRANSCRIBE_PROMPT.format(legend=legend_text())},
            {
                "role": "user",
                "content": "Transcribe this card's starting layout to JSON.",
                "images": [encode(crop)],
            },
        ],
    )
    return json.loads(resp["message"]["content"])


# --- Record building / validation ---------------------------------------------

def build_record(raw: dict, image_path: Path, bbox: dict, margin: float) -> dict:
    vehicles = []
    for v in raw.get("vehicles", []):
        vid = LABEL_TO_ID.get(v.get("color"))
        spec = SPECS.get(vid)
        vehicles.append({
            "id": vid,
            "row": v.get("row"),
            "col": v.get("col"),
            "len": spec.length if spec else 0,
            "orient": v.get("orient"),
        })
    cid = raw.get("id")
    return {
        "id": cid if isinstance(cid, int) and cid > 0 else 0,
        "level": raw.get("level") or "Unknown",
        "grid": {"rows": 6, "cols": 6, "exit": {"row": 2, "side": "right"}},
        "vehicles": vehicles,
        "printed_solution": [],
        "min_moves": None,
        "source": {"image": str(image_path), "bbox": bbox, "margin": margin},
    }


def finalize(record: dict) -> tuple[bool, str]:
    """Schema-check the layout, then solve it to fill the par/solution."""
    errors = schema.validate(record)
    if errors:
        return False, "; ".join(errors)
    try:
        board = board_from_data(record)
    except Exception as e:  # overlaps/bounds the schema missed
        return False, f"board build failed: {e}"
    solution = shortest_solution(board)
    if solution is None:
        return False, "no solution found (layout likely misread or unsolvable)"
    record["printed_solution"] = [m.token() for m in solution]
    record["min_moves"] = len(solution)
    if record["id"] <= 0:
        return False, "valid layout but no card number detected — assign manually"
    return True, "ok"


# --- Per-card driver -----------------------------------------------------------

def process_card(client, model, img, card, index, image_path, args) -> bool:
    label = f"card {index + 1}"
    if card.get("face") == "down":
        print(f"  {label}: face-down — skipped")
        return False

    crop = crop_card(img, card, args.margin)
    if crop is None:
        print(f"  {label}: degenerate bounding box — skipped")
        return False
    if args.save_crops:
        args.save_crops.mkdir(parents=True, exist_ok=True)
        crop.save(args.save_crops / f"{image_path.stem}-card{index + 1:02d}.jpg")

    print(f"  {label}: transcribing with {model}…", flush=True)
    try:
        raw = transcribe_card(client, model, crop)
    except Exception as e:
        print(f"  {label}: model error: {e}")
        return False

    record = build_record(raw, image_path, card, args.margin)
    ok, msg = finalize(record)
    target_dir = args.out if ok else args.review
    if not ok:
        record["_validation"] = f"QUARANTINED: {msg}"

    if ok or record["id"] > 0:
        name = f"{record['id']:03d}"
    else:
        name = f"{image_path.stem}-card{index + 1:02d}"
    dest = target_dir / f"{name}.json"

    status = "OK" if ok else f"NEEDS REVIEW ({msg})"
    print(f"  {label}: {status} -> {dest}")
    if not args.dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)
        with open(dest, "w") as fh:
            json.dump(record, fh, indent=2)
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Import Rush Hour cards from one photo via a local Ollama "
                    "vision model."
    )
    ap.add_argument("image", type=Path, help="photo (JPEG) of one or more cards")
    ap.add_argument("--out", default=Path("puzzles"), type=Path)
    ap.add_argument("--review", default=Path("needs_review"), type=Path)
    ap.add_argument("--model", default=DEFAULT_MODEL,
                    help=f"Ollama model tag (default {DEFAULT_MODEL})")
    ap.add_argument("--host", default=DEFAULT_HOST,
                    help=f"Ollama daemon URL (default {DEFAULT_HOST})")
    ap.add_argument("--margin", type=float, default=DEFAULT_MARGIN,
                    help="expand each detected card box by this fraction "
                         f"(default {DEFAULT_MARGIN})")
    ap.add_argument("--save-crops", type=Path, default=None,
                    help="also write each card's cropped image to this dir")
    ap.add_argument("--dry-run", action="store_true", help="don't write files")
    args = ap.parse_args(argv)

    if not args.image.is_file():
        print(f"No such image: {args.image}")
        return 1

    try:
        import ollama
    except ImportError:
        print("The 'ollama' package is required: pip install ollama")
        return 1
    client = ollama.Client(host=args.host)

    img = load_image(args.image)
    print(f"Locating cards in {args.image} via {args.model} @ {args.host} …")
    try:
        cards = detect_cards(client, args.model, img)
    except Exception as e:
        print(f"Card detection failed: {e}")
        return 1
    if not cards:
        print("No cards detected.")
        return 1

    print(f"Detected {len(cards)} card(s).")
    passed = 0
    for index, card in enumerate(cards):
        if process_card(client, args.model, img, card, index, args.image, args):
            passed += 1
    print(f"Done: {passed}/{len(cards)} validated. "
          f"Quarantined / unverified cards are in {args.review}/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
