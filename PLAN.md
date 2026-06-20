# Traffic Jam — Rush Hour in PyGame (2.5D Isometric)

Implementation plan for a digital Rush Hour clone with an isometric "2.5D" view,
programmatically-rendered vehicles matching `reference/vehicles.md`, and a
Claude-vision card-import tool that builds the puzzle dataset from card photos.

---

## 1. Game domain model

### Board & coordinates
- **Grid:** 6×6. `row` 0–5 top→bottom, `col` 0–5 left→right.
- **Exit:** right edge at `row 2` (standard Rush Hour; matches the side notch on
  card 34, where the prime car `X` sits). Modeled as virtual cells beyond `col 5`
  on `row 2` so `X` can slide *off* the board to win (e.g. `XR5`).
- **Vehicle:** `id` (letter), `len` (2=car, 3=truck/bus), `orient` (`H`/`V`),
  `row`,`col` = anchor (top-most / left-most occupied cell). Color & type come
  from the palette table (below).
- Horizontal vehicles occupy `(row, col..col+len-1)`; vertical occupy
  `(row..row+len-1, col)`.

### Moves
- Notation: `<ID><Dir><N>` — `Dir ∈ {U,D,L,R}` (Up=row−1, Down=row+1,
  Left=col−1, Right=col+1), `N` = cells moved. Key from card back:
  **U**p **D**own **R**ight **L**eft.
- One move = sliding one vehicle any number of free cells along its axis
  (matches Rush Hour scoring: the move counter increments **once per slide**,
  regardless of distance — exactly the card's token-per-move convention).
- H-vehicles only L/R; V-vehicles only U/D. A slide requires every intermediate
  cell to be empty (no jumping).
- `moves.py`: `Move` dataclass + `parse("RL2")`/`format(move)` round-trip,
  and `distance/direction` derived from anchor deltas after a drag.

### Win condition
- `X` is horizontal on the exit row and slides right until its left cell passes
  `col 5` (fully off-board through the exit). Detected both on click-to-move and
  mid-drag.

---

## 2. Palette / vehicle table (`data/palette.py`)

Authoritative table keyed by letter, built from `reference/vehicles.md` **and** the
Color-Code card (which now agree). Each entry: `{id, name, type, length,
base_color, roof_tint, window_tint}`. Notes:
- 16 IDs: `X, A–K, O, P, Q, R`.
- Cars (len 2): X red, A light-green Civic, B orange Lambo, C electric-blue
  Tesla 3, D light-pink Miata, E purple Ferrari, F medium-green Defender,
  G dark-gray Mercedes, H taupe Camry, I yellow Wrangler, J white Model Y,
  K dark-green Toyota Tacoma.
- Long (len 3): O dark-yellow semi, P light-purple semi, Q dark-blue bus,
  R green bus.

---

## 3. Project layout

```
traffic-jam/
  trafficjam/
    main.py              # entry; game-state machine MENU→PLAY→WIN
    model/
      board.py           # Board, Vehicle, legal-slide, apply/undo, win check
      moves.py           # Move dataclass, parse()/format(), notation helpers
      solver.py          # BFS shortest solution; reachable-positions helper
    view/
      iso.py             # grid<->screen isometric projection + depth sort
      render.py          # draw floor tiles, exit gap, vehicles, labels
      vehicles_draw.py   # programmatic extruded-prism vehicle drawing
      hud.py             # move counter, move-log strip, undo button
      particles.py       # fireworks particle system
      summary.py         # win panel: moves / par / score / stars
      menu.py            # level-select grid
    controller/
      input.py           # click vs drag, axis-constrained drag, click-to-move
    data/
      palette.py         # vehicle color/type table
      puzzles.py         # load/validate puzzle JSON dataset
  tools/
    import_cards.py      # Claude-vision import pipeline (batch)
    schema.py            # puzzle JSON schema + validate()
  puzzles/               # 001.json … NNN.json  (generated dataset)
  needs_review/          # imports that failed solver validation
  assets/fonts/          # bundled font
  tests/                 # pytest: model, moves, solver, schema, import round-trip
  reference/             # provided card photos + vehicles.md
  requirements.txt       # pygame, anthropic, pillow, pytest
  PLAN.md
```

---

## 4. Puzzle dataset (JSON schema)

`puzzles/034.json`:
```json
{
  "id": 34,
  "level": "Expert",
  "grid": { "rows": 6, "cols": 6, "exit": { "row": 2, "side": "right" } },
  "vehicles": [
    { "id": "X", "row": 2, "col": 1, "len": 2, "orient": "H" },
    { "id": "A", "row": 0, "col": 0, "len": 2, "orient": "V" }
  ],
  "printed_solution": ["RL2","PU1","CU1","HR1","DD1", "...", "XR5"],
  "min_moves": 0,
  "source": { "front": "reference/rush-hour-34-front.jpg",
              "back":  "reference/rush-hour-34-back.jpg" }
}
```
- `printed_solution` = tokens transcribed from the card back (between `▶` and `●`).
- `min_moves` = BFS optimum computed at import time (the printed solution is *a*
  solution, not necessarily optimal; scoring uses the BFS par).
- `schema.validate()` enforces in-bounds, non-overlapping, exactly one `X`,
  X on the exit row, lengths/orients consistent.

---

## 5. Solver (`model/solver.py`)

- State = tuple of vehicle anchors (canonical, hashable). BFS over moves where
  each neighbor = one vehicle slid to one reachable position (one BFS edge per
  slide, matching move-counting). Goal = `X` off the exit.
- Used for: (1) **validating** every imported puzzle (printed solution is legal &
  actually wins), (2) computing authoritative **`min_moves`** (par) for scoring,
  (3) a "hint"/auto-solve dev aid.
- `reachable_positions(board, vehicle)` — the free runs in both axis directions;
  also powers **click-to-move** (move only when exactly one alternative position
  exists).

---

## 6. Isometric rendering (`view/iso.py`, `render.py`, `vehicles_draw.py`)

### Projection (dimetric 2:1)
```
sx = origin_x + (col - row) * (TILE_W / 2)
sy = origin_y + (col + row) * (TILE_H / 2)        # TILE_W : TILE_H = 2 : 1
```
- Floor drawn as diamond tiles back-to-front (sort by `row+col`).
- Each vehicle = an **extruded prism**: top face (roof tint) offset up by
  `VEHICLE_H`, plus the two visible side faces (shaded body color), spanning
  2 or 3 cells along its axis. Windows/wheels = lighter/darker accent polys.
- **Depth sort** vehicles by `max(row+col)` over occupied cells so nearer pieces
  correctly overlap farther ones; redraw each frame.
- Exit rendered as a gap + arrow on the right edge at `row 2`.
- Optional letter-label overlay (toggle) drawn on each roof for parity with the
  card back; IDs are always tracked internally regardless of label visibility.

---

## 7. Interaction (`controller/input.py`)

- **Drag:** mouse-down on a vehicle → drag constrained to its axis; the piece
  follows the cursor (projected onto the axis), clamped to the free run; snap to
  nearest cell on release. Live win-check while dragging `X` past the exit.
- **Click (no drag):** if `reachable_positions` has **exactly one** alternative
  anchor, slide there with a short tween. (≥2 options ⇒ require a drag.)
- **Undo button:** pops the last move from the stack, restores anchors,
  decrements the counter, drops the last move-log token. Also `Ctrl+Z`.
- Click-vs-drag disambiguated by a small pixel/time threshold.
- Every committed slide pushes a `Move`, increments the counter, and appends a
  notation token (`ID+Dir+N`) to the move log.

---

## 8. HUD (`view/hud.py`)

- **Move counter** (top of HUD).
- **Undo button** (clickable; disabled when stack empty).
- **Move log** — small-font strip at the bottom, space-separated tokens in card
  format (`RL2 PU1 CU1 HR1 DD1 …`); grows per move, shrinks on undo; wraps/scrolls
  when long.

---

## 9. Win flow (`view/particles.py`, `summary.py`)

1. `X` slides out the exit (drive-out tween off the right edge).
2. **Fireworks** particle system: timed multi-burst, radial particles with
   gravity, fade/shrink over lifetime, additive-ish bright colors.
3. **Summary panel:** moves taken, par (`min_moves`), star rating, score, and
   Replay / Next buttons.

### Scoring
- `par = min_moves` (BFS optimum).
- `stars = 3 if player <= par else 2 if player <= round(par*1.25) else 1`.
- `score = max(0, round(1000 * par / player))` (1000 at optimal play).
- (Both par and the printed solution length are stored, so the summary can also
  show "printed solution: N moves".)

---

## 10. Card-import tool (`tools/import_cards.py`) — Claude vision

Builds the puzzle dataset from card photos. **Import-time only** (no API needed to
play). Recommended model: **`claude-opus-4-8`** for vision accuracy
(`claude-sonnet-4-6` as a cheaper batch option).

**Pipeline per card:**
1. Discover pairs `rush-hour-<N>-front.jpg` / `-back.jpg`; downscale with Pillow.
2. One Messages-API call with **both images** + a fixed system prompt containing
   the vehicle legend, the Color-Code letter→color map, and the move-notation key.
   Ask for **strict JSON**: vehicle placements + ordered solution tokens.
   - The **back** image is the source of truth: letters are printed on each
     vehicle (unambiguous placement) and the solution block is right there
     (`▶ … ●`).
   - The **front** image cross-checks colors / vehicle types.
   - Use **prompt caching** on the static legend/instructions to cut cost across
     the whole deck.
3. Parse JSON → `schema.validate()`.
4. **Solver validation:** apply `printed_solution` from the initial layout — every
   token must be a legal slide and the sequence must end with `X` exiting. Compute
   `min_moves` via BFS.
5. Pass → write `puzzles/<NNN>.json`. Fail/mismatch → write to `needs_review/`
   with a diff of what was inconsistent.
- Flags: `--only <id>`, `--dry-run`, `--model`, resumable & idempotent.
- **Bootstrapping:** card 34 is hand-authored first (so game dev isn't blocked),
  then used as the importer's golden test — the tool must reproduce that JSON.

---

## 11. Build phases / milestones

1. **Model + tests** — board, vehicles, moves, legal slides, win check.
2. **Solver** — BFS shortest path, `reachable_positions`, validation.
3. **Schema + loader** — hand-author `puzzles/034.json`; `puzzles.py` loader.
4. **Import tool** — Claude-vision pipeline; regenerate 034 and diff vs. golden.
5. **Iso renderer** — projection, floor, exit, vehicle prisms, depth sort (static).
6. **Interaction + HUD** — drag, click-to-move, undo, counter, move log.
7. **Win flow** — drive-out tween, fireworks, summary + scoring.
8. **Menu + polish** — level select, packaging, `requirements.txt`, README.

## 12. Dependencies (`requirements.txt`)
`pygame`, `anthropic` (import tool only), `pillow` (image prep), `pytest` (tests).

## 13. Key risks / decisions
- **Vision accuracy** on dense/expert boards → mitigated by solver validation +
  `needs_review/` quarantine; never trust an import the solver can't verify.
- **Click-to-move ambiguity** → strictly "exactly one reachable position".
- **Unknown vehicle ID from vision** → quarantine to `needs_review/` (general guard).
- **Printed solution may be non-optimal** → scoring uses BFS par, not token count.
