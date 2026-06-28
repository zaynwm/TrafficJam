"""CLI: import Rush Hour cards from a photo using classical CV (+ LLM for text).

    python -m tools.cv_import photo.jpg
    python -m tools.cv_import photo.jpg --out puzzles --review needs_review
    python -m tools.cv_import photo.jpg --debug /tmp/cvdbg --dry-run
    python -m tools.cv_import photo.jpg --no-ocr        # skip number/difficulty
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tools.cv_import.metadata import DEFAULT_HOST, DEFAULT_OCR_MODEL
from tools.cv_import.pipeline import Options, process_image


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Import Rush Hour cards from one photo via classical computer "
                    "vision (number/difficulty read by a local Ollama model).")
    ap.add_argument("image", type=Path, help="photo (JPEG/PNG) of one or more cards")
    ap.add_argument("--out", default=Path("puzzles"), type=Path)
    ap.add_argument("--review", default=Path("needs_review"), type=Path)
    ap.add_argument("--ocr-model", default=DEFAULT_OCR_MODEL,
                    help=f"Ollama model for number/difficulty (default {DEFAULT_OCR_MODEL})")
    ap.add_argument("--host", default=DEFAULT_HOST,
                    help=f"Ollama daemon URL (default {DEFAULT_HOST})")
    ap.add_argument("--no-ocr", action="store_true",
                    help="skip the LLM text read (number/difficulty left blank)")
    ap.add_argument("--debug", dest="debug_dir", type=Path, default=None,
                    help="write per-stage debug overlays to this directory")
    ap.add_argument("--dry-run", action="store_true", help="don't write files")
    args = ap.parse_args(argv)

    if not args.image.is_file():
        print(f"No such image: {args.image}")
        return 1

    opts = Options(out=args.out, review=args.review, ocr_model=args.ocr_model,
                   host=args.host, no_ocr=args.no_ocr, dry_run=args.dry_run,
                   debug_dir=args.debug_dir)
    print(f"Importing cards from {args.image} …")
    results = process_image(args.image, opts)

    passed = sum(r.status == "ok" for r in results)
    for r in results:
        tag = {"ok": "OK", "review": "NEEDS REVIEW", "skipped": "SKIPPED"}[r.status]
        dest = f" -> {r.dest}" if r.dest else ""
        print(f"  card {r.index}: {tag} ({r.message}){dest}")
    print(f"Done: {passed}/{len(results)} validated. "
          f"Unverified cards are in {args.review}/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
