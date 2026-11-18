# Monke animation pipeline

## Production plates

Open [the review gallery](../../assets/monke/production/index.html) for the current versions of all 35 states. Choose Habitat state to see the actual intro and sustained loop, or choose a palette demo to replay the full sequence. The [production queue](../../assets/monke/source/production-queue.md) records the performances. The [review rules](REVIEW.md) describe blind reads, material checks and sign-off on each revision.

The production compiler uses the plates in `assets/monke/production/plates`, the exposure recipes in `cuts.json`, `work.json`, `acting.json` and `energy.json`, and the matching material-grid corrections in this directory. From the repository root with the host package on the Python path, rebuild changed states by name, run their browser checks and refresh the gallery.

```sh
python -m tools.monke.production interrupted
python -m tools.monke.batch verify --browser /path/to/chrome
python -m tools.monke.gallery
```

The gallery export command `python -m tools.monke.gallery --export` creates `assets/monke/production/monke.zip` once the whole queue passes. The archive uses Habitat's character-pack format and contains the four fur palettes. Each cut keeps its exact timing, preview GIFs, runtime SVG and review receipts together.

## Original pilot

This pilot implements **idle, coding/editing, approval, walking, and ready**.
These five previews document the original pilot. The generated pack is
a preview artifact; it is not installed, registered in the built-in catalog, or
set as the user's character automatically.

## Run

Use Python 3.10+ with `pip install -r tools/monke/requirements.txt`, from the repository root:

```sh
python -m tools.monke.pipeline build
python -m tools.monke.pipeline status
python -m unittest tools.monke.test_pipeline
```

Open `assets/monke/build/index.html` directly in a browser. It is self-contained
and needs no server. Choose fur palettes, 1x/2x/4x/6x zoom, and light/dark/gray
backgrounds. Pause and scrub individual frames. Each card includes an actual-size
preview. It honors reduced motion on initial load; exported SVGs also have a
reduced-motion rule. The separate `still.svg` is a static fallback.

Run host regression tests with `PYTHONPATH=host`:

```sh
python -m unittest discover -s host/tests -p test_habitat.py
python -m unittest discover -s host/tests -p test_monke_palettes.py
```

Optional real-browser verification (`pip install playwright`; uses an existing
Chrome/Chromium/Edge installation, no downloaded browser required):

```sh
python -m tools.monke.check_browser --browser /path/to/chrome
```

In this Windows checkout the dependencies were installed locally in
`.debug/monke-deps` and the available interpreter is
`C:/Users/giosch/AppData/Roaming/uv/python/cpython-3.13.18-windows-x86_64-none/python.exe`.
In PowerShell set `$env:PYTHONPATH = '.debug/monke-deps;host'` before using it.
These machine-specific paths are not required on another machine.

## Plate production and review

Use the [production queue](../../assets/monke/source/production-queue.md) for the
35 agreed activities and [review rules](REVIEW.md) for plate authoring, dispatch,
checks, revisions and acceptance. Approval v3 is the user-preferred example.
Subsequent plates use per-animation acceptance. The legacy pilot's manual review
command and rejection apply to that five-animation build only.

Run the standard on a local plate directory that contains candidate.json:

```sh
python -m tools.monke.plate_review assets/monke/plate-study/approval-v3 prepare
python -m tools.monke.plate_review assets/monke/plate-study/approval-v3 verify --browser /path/to/chrome
python -m tools.monke.plate_review assets/monke/plate-study/approval-v3 decide
```

The active coordinator dispatches independent art and motion reviews to
`gpt-6.2-astra` at high effort. The CLI prepares and verifies evidence, then
computes the decision from the two returned reviews. Continue revising each
animation until it meets the criteria, with no numerical limit on attempts.

## Fur-only palette contract

The material map contains exactly three recolorable roles: `fur.shadow`,
`fur.base`, and `fur.highlight`. This includes the tail. Skin, ears, muzzle, belly,
hands, feet, outline, eyes and equipment have fixed material IDs. Color equality
does not imply material equality: the keyboard repair patch deliberately uses
the exact brown of default fur, under the fixed `prop.wood` role.

`palettes.json` defines four example fur ramps and the fixed colors. Add a ramp
by supplying all three fur roles. Do not add skin or prop roles to fur palettes.
The shared reference palette is retained; the additional role for the repair
patch aliases an existing RGB value rather than introducing a new color.

SVG paths have explicit `data-material` tags. `Pack.svg` changes the `fill` only
on paths bearing a fur tag, using the pack's optional `fur_palettes` list. Legacy
packs keep their existing `colors` behavior. A pack cannot mix both recoloring
methods. Session variant selects a stable palette, cycling through the four
ramps. Runtime colors match the source RGB colors, unlike the legacy HSL ramp.

## Source, layout and exports

- `art.py`: canonical integer-grid head, torso, limb, tail, hand and prop geometry.
- `source/animations.json`: pose parameters, activity mapping, story and durations
  on a 125ms timing grid. Neutral standing body is 48px high; head is 16px,
  torso 20px, and legs/feet 12px. Action tile is 80x64. Anchor is `(40,55)`.
  Curved tails and limbs articulate; path lengths can change slightly by pose.
- `source/palettes.json`: fixed colors and three-role fur ramps.
- `build/frames`: transparent PNG frames and matching grayscale material-ID maps.
  **Material maps are data**, not grayscale artwork; `materials.json` names IDs.
- `build/svg`: animated SVGs made from exact horizontal pixel runs. CSS keyframe
  names are animation-specific so multiple inline previews cannot collide.
- `build/manifest.json`, `monke-pilot.zip`: self-contained export/install-compatible
  browser pack. Coding maps to `editing`; missing activities fall back to idle.
- `build/previews`: palette GIFs, animated overview, contact sheet, browser screenshot.
  GIFs have an opaque light background for reliable playback; PNG/SVG exports
  are transparent. The HTML preview preserves exact 125ms timing; GIF encoders
  quantize durations to their centisecond timebase.
- `build/hardware`: RLE **material IDs**, palette tables in RGB565, frame offsets
  measured in uint16 words, and per-frame durations. Each RLE pair is count/ID.
  ID zero is transparent; never interpret palette entry zero as opaque black.
  These are not the legacy RGB565 RLE headers and are not wired into firmware.
  A future device renderer must skip ID zero and look up all other IDs in the
  selected palette. This avoids duplicating geometry for every palette.
- `validation.json`, `browser-validation.json`, `agent-jobs.json`: checks, source
  hashes, and review state. Builds are deterministic and currently rebuild this
  small batch in full; dependency caching is not implemented.

Generated files can be rebuilt from source without network access or model calls.
Tests independently decode SVG pixel runs and hardware RLE and compare them to
the material frames. Validation checks clip margins, timing, palette isolation,
binary alpha, loop endpoints, movement, and an unchanging approval-button region.
The browser test checks every frame interval's visibility, pack-image decoding,
palette isolation, scrubbing, actual size and reduced motion.
