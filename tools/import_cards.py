"""Build the puzzle dataset from card photos using Claude vision.

Pipeline per card:
  1. Discover front/back image pairs (``rush-hour-<N>-front.jpg`` / ``-back.jpg``).
  2. Send both images to Claude (claude-opus-4-8) with the vehicle legend and the
     move-notation key, requesting strict JSON (board layout + solution tokens).
  3. Validate the JSON against the schema, then replay the printed solution with
     the BFS solver and compute the true minimum-move count.
  4. Passing puzzles -> puzzles/<NNN>.json ; failures -> needs_review/.

Import-time only — the game itself never needs the API. Requires an
``ANTHROPIC_API_KEY`` and the ``anthropic`` + ``pillow`` packages.

Usage:
    python -m tools.import_cards --dir reference --out puzzles --review needs_review
    python -m tools.import_cards --only 34 --dry-run
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import re
import sys
from pathlib import Path

from trafficjam.data.palette import SPECS
from trafficjam.data.puzzles import board_from_data
from trafficjam.model.moves import parse_solution
from trafficjam.model.solver import min_moves, validate_solution
from tools import schema

MODEL = "claude-opus-4-8"
MAX_IMAGE_DIM = 1400  # downscale before upload to cut tokens
PAIR_RE = re.compile(r"rush-hour-(\d+)-(front|back)\.(jpe?g|png)$", re.IGNORECASE)

# Static instructions — cached across the whole deck so we don't re-pay tokens.
SYSTEM_PROMPT = """You read Rush Hour puzzle cards and output structured JSON.

The board is a 6x6 grid. row 0 is the top, row 5 the bottom; col 0 is the left,
col 5 the right. The exit is a gap on the RIGHT edge at row 2; the red prime car
"X" must reach it. A vehicle is identified by a letter and has a fixed length and
type (do not change these — use the legend below):

{legend}

Each vehicle is horizontal ("H", occupying consecutive columns in one row) or
vertical ("V", occupying consecutive rows in one column). row/col is the
top-most / left-most cell it occupies.

You are given two photos of one card:
- BACK: the board with a letter printed on each vehicle (authoritative for
  placement) plus the printed solution sequence and the puzzle number/level.
- FRONT: the same board with colored, unlabeled vehicles (use to cross-check
  colors/types against the legend).

The solution sequence is read left-to-right, top-to-bottom, between the small
red triangle (start) and the red dot (end). Each move is <ID><Dir><N> where
Dir is U(up)/D(down)/L(left)/R(right) and N is the number of cells moved. The
final move drives X off the right edge.

Return ONLY the vehicle placements from the BACK board and the ordered solution
tokens. Do not solve or optimize — transcribe exactly what is printed."""

# json_schema for output_config.format — guarantees parseable JSON.
OUTPUT_SCHEMA = {
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
                    "id": {"type": "string"},
                    "row": {"type": "integer"},
                    "col": {"type": "integer"},
                    "len": {"type": "integer"},
                    "orient": {"type": "string", "enum": ["H", "V"]},
                },
                "required": ["id", "row", "col", "len", "orient"],
            },
        },
        "printed_solution": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["id", "level", "vehicles", "printed_solution"],
}


def legend_text() -> str:
    lines = []
    for spec in SPECS.values():
        lines.append(
            f"  {spec.id}: {spec.name} ({spec.kind}, length {spec.length})"
        )
    return "\n".join(lines)


def discover_pairs(directory: Path) -> dict[int, dict[str, Path]]:
    pairs: dict[int, dict[str, Path]] = {}
    for path in directory.iterdir():
        m = PAIR_RE.search(path.name)
        if m:
            num = int(m.group(1))
            pairs.setdefault(num, {})[m.group(2).lower()] = path
    return dict(sorted(pairs.items()))


def encode_image(path: Path) -> tuple[str, str]:
    """Downscale and return (media_type, base64 data)."""
    from PIL import Image

    img = Image.open(path).convert("RGB")
    img.thumbnail((MAX_IMAGE_DIM, MAX_IMAGE_DIM))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return "image/jpeg", base64.standard_b64encode(buf.getvalue()).decode()


def call_claude(client, front: Path, back: Path, number: int) -> dict:
    system = [{
        "type": "text",
        "text": SYSTEM_PROMPT.format(legend=legend_text()),
        "cache_control": {"type": "ephemeral"},  # reused across every card
    }]
    content = [{"type": "text", "text": f"Card number {number}. FRONT photo:"}]
    for label, p in (("FRONT", front), ("BACK", back)):
        media, data = encode_image(p)
        content.append({"type": "text", "text": f"{label} photo:"})
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media, "data": data},
        })
    content.append({
        "type": "text",
        "text": "Transcribe this card to JSON per the schema.",
    })

    resp = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=system,
        output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
        messages=[{"role": "user", "content": content}],
    )
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


def build_record(raw: dict, number: int, front: Path, back: Path) -> dict:
    return {
        "id": raw.get("id", number),
        "level": raw.get("level", "Unknown"),
        "grid": {"rows": 6, "cols": 6, "exit": {"row": 2, "side": "right"}},
        "vehicles": raw["vehicles"],
        "printed_solution": raw["printed_solution"],
        "min_moves": None,
        "source": {"front": str(front), "back": str(back)},
    }


def validate_record(record: dict) -> tuple[bool, str]:
    """Schema-check, then replay the printed solution and compute par."""
    errors = schema.validate(record)
    if errors:
        return False, "; ".join(errors)
    try:
        board = board_from_data(record)
    except Exception as e:  # overlaps/bounds the schema missed
        return False, f"board build failed: {e}"
    moves = parse_solution(record["printed_solution"])
    ok, msg = validate_solution(board, moves)
    if not ok:
        return False, f"printed solution invalid: {msg}"
    record["min_moves"] = min_moves(board)
    return True, "ok"


def process(client, number, pair, out_dir, review_dir, dry_run) -> bool:
    if "front" not in pair or "back" not in pair:
        print(f"  card {number}: missing front/back image — skipped")
        return False
    print(f"  card {number}: querying Claude…", flush=True)
    try:
        raw = call_claude(client, pair["front"], pair["back"], number)
    except Exception as e:
        print(f"  card {number}: API error: {e}")
        return False

    record = build_record(raw, number, pair["front"], pair["back"])
    ok, msg = validate_record(record)
    target_dir = out_dir if ok else review_dir
    if not ok:
        record["_validation"] = f"QUARANTINED: {msg}"
    dest = target_dir / f"{record['id']:03d}.json"
    status = "OK" if ok else f"NEEDS REVIEW ({msg})"
    print(f"  card {number}: {status} -> {dest}")
    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)
        with open(dest, "w") as fh:
            json.dump(record, fh, indent=2)
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(description="Import Rush Hour cards via Claude vision.")
    ap.add_argument("--dir", default="reference", type=Path)
    ap.add_argument("--out", default="puzzles", type=Path)
    ap.add_argument("--review", default="needs_review", type=Path)
    ap.add_argument("--only", type=int, help="import only this card number")
    ap.add_argument("--dry-run", action="store_true", help="don't write files")
    args = ap.parse_args(argv)

    pairs = discover_pairs(args.dir)
    if args.only is not None:
        pairs = {k: v for k, v in pairs.items() if k == args.only}
    if not pairs:
        print("No card image pairs found.")
        return 1

    try:
        import anthropic
    except ImportError:
        print("The 'anthropic' package is required: pip install anthropic")
        return 1
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY

    print(f"Importing {len(pairs)} card(s) from {args.dir}/ …")
    passed = 0
    for number, pair in pairs.items():
        if process(client, number, pair, args.out, args.review, args.dry_run):
            passed += 1
    print(f"Done: {passed}/{len(pairs)} validated. "
          f"Quarantined imports are in {args.review}/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
