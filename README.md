# Traffic Jam

A digital take on the classic **Rush Hour** sliding-block puzzle, rendered in an
isometric "2.5D" perspective with [PyGame](https://www.pygame.org/). Slide the
cars and trucks out of the way and drive the red prime car `X` out the exit.

Vehicles are drawn as colored extruded prisms matching the original game's
colors, lengths, and types (see `reference/vehicles.md`) — light-green Civic,
orange Lamborghini, electric-blue Tesla, semi-trailer trucks, city buses, and so
on.

## Features

- **Isometric 2.5D board** — a 6×6 tray drawn in a 2:1 dimetric projection, with
  depth-sorted vehicle prisms, an exit lane + arrow, and optional letter labels.
- **Natural interaction** — click-and-drag a vehicle along its axis, or single-
  click a piece that has exactly one legal destination to send it there.
- **Undo** (button, `Ctrl+Z`, or `U`), **Reset**, and a **Levels** menu.
- **HUD** — a live move counter, the optimal-solution par, and a **move log** in
  the same notation printed on the cards (`RL2 PU1 CU1 HR1 DD1 …`) that grows
  with each move and shrinks on undo.
- **Win celebration** — the prime car drives out, a fireworks particle system
  fires, then a summary panel shows your move count, the best-possible count, a
  **star rating**, and a **score**.
- **Built-in solver** — a BFS shortest-path solver computes the par for scoring
  and validates every puzzle (and every card import) before it's accepted.
- **Card importer** — a local Ollama-vision tool that turns photos of the physical
  game cards into solver-validated puzzle data.

## Install & run

```bash
pip install -r requirements.txt
python -m trafficjam.main
```

Only `pygame` is needed to play. The `opencv-python-headless`, `ollama`, and
`pillow` packages are used solely by the card importers (which run offline,
talking to a local Ollama daemon for any text/vision the CV stage doesn't cover).

## How to play

| Action | How |
| --- | --- |
| Move a vehicle | Drag it along its axis (horizontal pieces left/right, vertical up/down) and release to snap |
| Quick-move | Single-click a vehicle that has exactly one reachable position |
| Undo | **Undo** button, `Ctrl+Z`, or `U` |
| Restart level | **Reset** button |
| Pick a level | **Levels** button, or `Esc` |

A move is one vehicle sliding any number of free cells — exactly like the cards,
the move counter ticks up **once per slide** regardless of distance. Win by
sliding the red `X` car off the right-hand exit.

### Scoring

`par` is the true minimum number of moves (from the BFS solver).

- **Score** = `round(1000 × par / your_moves)` — 1000 for an optimal solve.
- **Stars** = 3 if you match par, 2 if within 25% of par, otherwise 1.

## Project layout

```
trafficjam/
  main.py            game loop + state machine (menu → play → win)
  model/             pure logic, no pygame — fully unit-tested
    board.py         Board, Vehicle, legal slides, apply/undo, win check
    moves.py         Move dataclass, card-notation parse/format
    solver.py        BFS shortest solution, reachable positions, validation
  mesh/              generated low-poly vehicle geometry (engine-agnostic)
    geometry.py      Mesh/MeshBuilder, normals, OBJ + glTF export
    cars.py          parametric car generator + archetype presets
  view/              rendering
    iso.py           isometric projection + depth sorting
    render.py        floor tiles, exit, depth-sorted vehicles
    vehicles_draw.py software-3D pass: project / shade / paint the meshes
    hud.py           move counter, undo/reset/levels buttons, move log
    particles.py     fireworks particle system
    summary.py       win panel + score/stars
    menu.py          level select
  controller/
    input.py         mouse: select, axis-constrained drag, click-to-move
  data/
    palette.py       vehicle colors / types / lengths
    puzzles.py       puzzle JSON loader

tools/
  cv_import/         classical-CV card importer (detect→rectify→grid→classify)
  import_cards.py    local Ollama-vision card importer (alternative)
  export_meshes.py   export vehicle meshes to OBJ / glTF
  schema.py          puzzle JSON schema + validation

puzzles/             puzzle dataset (JSON) — every entry BFS-verified
needs_review/        imports the solver could not verify (quarantined)
tests/               pytest suite (model, solver, schema, dataset)
reference/           vehicle spec (vehicles.md)
```

## Puzzle format

Each puzzle is a JSON file describing the 6×6 grid, the vehicle placements, the
printed solution, and the solver-computed `min_moves` (the scoring par):

```json
{
  "id": 2,
  "level": "Intermediate",
  "grid": { "rows": 6, "cols": 6, "exit": { "row": 2, "side": "right" } },
  "vehicles": [
    { "id": "X", "row": 2, "col": 1, "len": 2, "orient": "H" },
    { "id": "A", "row": 0, "col": 0, "len": 2, "orient": "V" }
  ],
  "printed_solution": ["XL1", "BD1", "...", "XR6"],
  "min_moves": 13
}
```

Coordinates use `row` 0–5 top→bottom and `col` 0–5 left→right; the exit is on the
right edge at `row 2`. A move token is `<ID><Dir><N>` with `Dir` ∈ `U/D/L/R`.

Every puzzle in `puzzles/` is solver-verified: the printed solution must replay
legally and end with `X` exiting, and `min_moves` must equal the BFS optimum. The
bundled levels `001`–`003` were authored by design and BFS-verified.

## Importing cards from photos

Two importers turn a **single photo** of one or more physical cards into puzzle
JSON. Both run fully offline and both end with the same safety gate — the **BFS
solver must solve** each extracted board (storing its optimal solution and
`min_moves`); face-down cards are skipped and anything that can't be verified (or
has no detected card number) is quarantined to `needs_review/`, so `puzzles/`
only ever contains winnable boards.

### Recommended: classical computer vision (`tools/cv_import`)

A deterministic OpenCV pipeline — fast, inspectable, no per-pixel guessing:

1. **Detect** — segment cards from the background and split a single card, a
   touching row/column, or a touching **2-D grid** into individual cards by the
   card aspect ratio — every split (auto or hinted) is scored by how close the
   resulting cards are to a ~1.45 portrait, so a distorted layout is never chosen.
   Thresholds loosen progressively until the split is clean; if the CV count
   disagrees with the Ollama model's count, the model's row×col layout is tried
   too, but adopted only if it keeps the cards well-shaped (LLM backstop).
2. **Rectify** — perspective-warp each card upright (logo at top).
3. **Locate the 6×6 grid by its corners** — each grid corner is the vertex where
   three quadrants are smooth **gray wall** and the fourth is the textured grid
   (the grayness gate rejects false corners on the white card edge, the colored
   difficulty band, or the printed number). The four corners are reconciled into
   the **axis-aligned, square** rectangle that best fits — so the warp is always an
   orthogonal projection (square cells), never a skewed trapezoid — then warped.
4. **Classify cells** — occupancy from *texture* (the molded 3-D pieces are busy;
   the pebble board is smooth). Each cell's color is sampled robustly (white
   balance + discard specular glare/shadow, then the median of the most-chromatic
   body pixels) and **regularized to a calibrated 16-color codebook** — the
   photographed vehicle palette learned by k-means over the reference cards
   (regenerate with `python -m tools.cv_import.calibrate_codebook`).
5. **Find the prime X & assemble** — the vivid-red **X** is detected directly by
   color (and used to snap the grid to the exit row if it landed a row off). The
   remaining cells are tiled into straight 2/3-length pieces per 4-connected blob,
   where a candidate piece may only group **color-homogeneous** cells — so two
   different-colored pieces are never merged into one. Cells that can't be tiled
   (occupancy noise / dissimilar colors) are flagged for review.
6. **Read text** — only the card number + difficulty go to a small local Ollama
   model (`gemma4:e4b`); everything else is pure CV.

For **every** card (passing or quarantined) a `.png` is written next to its JSON
showing the system's understanding — the rectified board, the per-cell
classification, and the parsed pieces side by side — so you can eyeball
correctness at a glance.

```bash
pip install opencv-python-headless ollama   # import-time only; never needed to play
ollama pull gemma4:e4b                       # one-time; for reading number/difficulty

python -m tools.cv_import photo.jpg --out puzzles --review needs_review
python -m tools.cv_import photo.jpg --debug /tmp/cvdbg --dry-run   # extra per-stage overlays
python -m tools.cv_import photo.jpg --no-ocr                       # skip number/difficulty
```

Each result's `.png` (e.g. `puzzles/001.png`, `needs_review/<name>.png`) is the
quickest way to verify; `--debug DIR` adds per-stage overlays (card detection,
rectified cards with the detected grid corners) for tuning against your photos.

### Alternative: multimodal LLM (`tools/import_cards.py`)

Sends the photo to a **local Ollama vision model** (default `gemma4:26b`) to
detect/crop cards and transcribe each board by a fixed color vocabulary:

```bash
pip install ollama pillow
ollama pull gemma4:26b                       # vision-capable model

python -m tools.import_cards photo.jpg --out puzzles --review needs_review
python -m tools.import_cards photo.jpg --margin 0.08 --save-crops /tmp/crops
python -m tools.import_cards photo.jpg --model gemma4:26b --host http://localhost:11434 --dry-run
```

## Vehicle meshes

Vehicles are **procedurally generated low-poly meshes** — no images or
third-party geometry. Each is built from a small parameter vector (`CarSpec`: a
side-profile roofline, body width, ride height, glass-cabin range, wheel
placement) by lofting rounded cross-sections along the body and adding wheels as
separate cylinders. Archetype presets (sedan, coupe, wedge, hatch, SUV, pickup,
bus, semi) give silhouettes *evocative of* each vehicle class without copying any
real, branded design; `palette.py` supplies the colors. PyGame renders them with
a small software-3D pass (project → flat-shade → painter's sort) through the same
isometric projection as the board.

The mesh data is engine-agnostic and exports to OBJ and glTF, so the same assets
can drive a future GPU/SceneKit (iOS) port — convert the glTF to Apple's USDZ
with Reality Converter.

```bash
python -m tools.export_meshes --out assets/meshes              # per vehicle (OBJ+glTF)
python -m tools.export_meshes --archetypes --format gltf       # one per archetype
```

To restyle a vehicle, edit its archetype in `trafficjam/mesh/cars.py` (or map a
vehicle id to a different archetype) — the change flows to both the in-game
render and the exported assets.

## Development

Run the test suite (model, solver, schema, and a check that every shipped puzzle
is valid and solvable):

```bash
python -m pytest -q
```
