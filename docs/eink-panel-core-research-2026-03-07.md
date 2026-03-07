# Musicbox E-Ink Panel Core Research

Updated: 2026-03-07

## Goal

Build a panel-specific display core for the Waveshare `3.7"` e-paper panel that:

- keeps the current app-side display service simple
- supports deliberate full grayscale refreshes
- supports deliberate mono partial updates
- avoids unnecessary full-screen flashing on small state changes
- stays tight and testable instead of becoming a generic UI framework

This is not a generic display abstraction. It is a serious driver/manager for one known panel.

## Hardware and controller baseline

- Panel: Waveshare `3.7inch e-Paper HAT`
- Resolution: `480 x 280`
- Effective tones: `4` total (`white`, `light gray`, `dark gray`, `black`)
- Controller: `SSD1677`

Official sources:

- Product page: <https://www.waveshare.com/3.7inch-e-paper-hat.htm>
- Manual/wiki: <https://www.waveshare.com/wiki/3.7inch_e-Paper_HAT_Manual>
- Official Python driver: <https://raw.githubusercontent.com/waveshareteam/e-Paper/master/RaspberryPi_JetsonNano/python/lib/waveshare_epd/epd3in7.py>
- Official C driver: <https://raw.githubusercontent.com/waveshareteam/e-Paper/master/RaspberryPi_JetsonNano/c/lib/e-Paper/EPD_3in7.c>
- Official C header: <https://raw.githubusercontent.com/waveshareteam/e-Paper/master/RaspberryPi_JetsonNano/c/lib/e-Paper/EPD_3in7.h>
- SSD1677 datasheet: <https://files.waveshare.com/upload/2/2a/SSD1677_1.0.pdf>

## What the hardware can actually do

Waveshare advertises this panel with:

- `4 grey scales`
- `3s` full refresh
- `0.3s` partial refresh support

That statement is about the panel and controller capability.

The official Python driver does not expose that capability completely. For this panel it only provides:

- full-screen `4-gray` refresh
- full-screen `1-gray` refresh

The official C driver for this exact panel exposes one more important path:

- `EPD_3IN7_1Gray_Display_Part(...)`

That means the missing feature is not in the hardware. It is missing in the current Python wrapper.

## Current local gap

The local code already has:

- scene planning in [src/musicbox_app/eink.py](/home/nuc/clawd/projects/musicbox/src/musicbox_app/eink.py)
- event-driven display orchestration via `DisplayService`
- a local panel driver in [src/waveshare_epd/epd3in7.py](/home/nuc/clawd/projects/musicbox/src/waveshare_epd/epd3in7.py)

But it still stops at vendor-style full-frame rendering:

- status path: full-frame mono
- album-art path: full-frame grayscale

That explains the current behavior:

- text-only/status updates are acceptable
- grayscale art transitions still flash hard
- same-art same-album track changes still redraw too much because the app does not yet own retained overlay state or region updates

## Low-level controller model

These are the commands that matter for a custom panel core.

### General initialization

- `0x12`: software reset
- `0x01`: gate setting
- `0x03`: gate voltage
- `0x04`: source voltage
- `0x11`: data entry mode
- `0x3C`: border setting
- `0x0C`: booster strength
- `0x18`: internal temperature sensor
- `0x2C`: VCOM
- `0x37`: display option register

### Frame memory and addressing

- `0x44`: RAM X window start/end
- `0x45`: RAM Y window start/end
- `0x4E`: RAM X cursor
- `0x4F`: RAM Y cursor
- `0x24`: BW RAM write
- `0x26`: second RAM plane write

### Update execution

- `0x32`: LUT write
- `0x22`: display update control
- `0x20`: master activation
- `0x10`: deep sleep

## What Waveshare actually does

### Full grayscale refresh

The official driver:

1. initializes grayscale mode
2. writes one plane to `0x24`
3. writes a second plane to `0x26`
4. loads grayscale LUT through `0x32`
5. sets update control
6. activates with `0x20`

Implication:

- `4-gray` is fundamentally a full-screen composed update in the vendor flow
- it is the right path for art and composed “hero” screens

### Full mono refresh

The official C driver uses `lut_1Gray_DU` for full mono display.

The local Python driver had been using the `A2` LUT for full mono, which is not what the official C path does.

Implication:

- the new panel core should use the official full-mono waveform for full mono refresh
- partial mono should use the partial waveform, not the same one as full mono

### Region mono partial refresh

The official C function `EPD_3IN7_1Gray_Display_Part(...)` does this:

1. program `0x44` with region X start/end
2. program `0x45` with region Y start/end
3. set the RAM cursor with `0x4E` and `0x4F`
4. write only region bytes via `0x24`
5. load LUT `3`, which is `lut_1Gray_A2`
6. activate with `0x20`

Important note from the C source:

- `Xstart must be a multiple of 8`

Implication:

- partial updates are real and implementable
- they are mono only
- they have alignment constraints

## Practical constraints that matter to us

### 1. Partial refresh is not permanent mode

Waveshare explicitly warns that repeated partial refreshes will accumulate residue/ghosting.

The manual says:

- do not use partial refresh indefinitely
- do periodic full refreshes
- if repeated partial refresh makes text lighter, reduce the partial area and clear/full-refresh after around `5` partial rounds

Implication:

- partial updates need a budget
- the core needs an explicit scrub/full-refresh policy

### 2. Deep sleep does not retain controller state

After deep sleep, the panel/controller must be reinitialized before the next update.

Implication:

- the panel core must treat sleep as a full state reset
- retained host-side state can survive, controller-side state cannot

### 3. The current landscape orientation rotates panel memory

The current app renders a `480 x 280` landscape canvas.

The vendor driver rotates that into the panel’s native `280 x 480` memory layout:

- `panel_x = canvas_y`
- `panel_y = 479 - canvas_x`

Implication:

- the partial-update alignment rule applies to the canvas `top/bottom` edges, not the canvas `left/right` edges
- overlay rectangles need a panel-aware alignment helper

## Architecture decision

The right architecture is:

1. `DisplayService`
- store-driven orchestration
- settle/coalesce logic
- retry and logging

2. `DisplayCoordinator`
- scene selection
- Pillow drawing
- album-art resolution

3. `PanelCore`
- owns driver lifecycle
- owns render-mode switching
- owns retained overlay state
- owns full vs partial decision execution
- owns scrub cadence

4. `UpdatePlanner`
- compares the new frame against the retained frame
- chooses:
  - `skip`
  - `full_mono`
  - `partial_mono`
  - `full_gray`

This keeps the app-facing surface stable while moving the hard panel logic into one place.

## Chosen rendering model

The core model is not “art vs non-art”.

The core model is:

- `full_canvas`: the complete desired screen
- `overlay surfaces`: small mono surfaces that are safe to update separately

That gives us a retained two-level screen model:

- stable base
- changing overlays

This is general enough for:

- album art + track text
- battery/status bars
- recording overlays
- TTS/agent prompts
- future cards or faces

without building a giant scene graph.

Implementation contract:

- anything that must be correct after a mono partial update must be represented by an overlay surface
- the planner compares overlay surfaces, not arbitrary pixels in the full grayscale canvas
- if a scene cannot describe its mutable content as overlays, it should fall back to a full refresh path

## Why overlays instead of dirty diff on the whole screen

If the entire screen is diffed as one image, two unrelated changes become one giant bounding box.

Example:

- top header changes
- right metadata pane changes

A single full-screen diff box could easily cover most of the screen.

Instead, the scene should expose multiple overlay surfaces with explicit bounds, for example:

- `header`
- `metadata`
- `status_body`

Then the planner can diff each surface independently and update only the changed regions.

That is the simplest reliable way to avoid “all-white, then redraw” behavior when the art itself did not change.

## Initial policy

### Full grayscale

Use for:

- new album art
- mode changes into an art-heavy screen
- scrub/full cleanup after too many partials on a grayscale scene

### Full mono

Use for:

- initial mono status screen
- fallback when changed area is too large
- scrub/full cleanup after too many mono partials

### Partial mono

Use for:

- changed overlay surfaces
- only when the base scene is stable
- only when the dirty region area is still small enough to be worth it
- only for scenes that actually emit overlay surfaces for the mutable pixels

## Chosen simplicity limits

This first serious version should deliberately avoid:

- generic multi-panel abstractions
- a separate IPC daemon
- arbitrary scene graphs
- “any widget can directly touch the panel”
- dozens of fragmented dirty rectangles

Instead:

- one panel
- one retained state machine
- a few named overlay surfaces
- aggressive merge/fallback rules

## Concrete implementation plan

### Phase 1: panel core

Add a new package:

- `src/musicbox_display/types.py`
- `src/musicbox_display/planner.py`
- `src/musicbox_display/panel.py`

Responsibilities:

- geometry and update types
- retained overlay planner
- panel-aware render execution

### Phase 2: low-level driver cleanup

Extend [src/waveshare_epd/epd3in7.py](/home/nuc/clawd/projects/musicbox/src/waveshare_epd/epd3in7.py) with:

- explicit mono-full path using the official full-mono LUT
- explicit mono-partial region path
- window/cursor helpers

This keeps the local driver honest to the vendor C implementation.

### Phase 3: app integration

Keep stable:

- `DisplayService`
- `DisplayPlan`
- `eink_worker`

Move rendering internals to the new panel core.

### Phase 4: tests and lab script

Add tests for:

- rect alignment
- canvas-to-panel mapping
- dirty region planning
- overlay removal / disappearance
- scrub cadence
- no-op update skipping

Add a lab script to exercise:

- full mono
- partial mono on named overlays
- full grayscale
- repeated partials and scrub fallback

## Expected first wins

1. Same-art same-album track changes can stop doing a full grayscale refresh.
2. Header/text updates can be constrained to known overlay regions.
3. The vendor C path is finally available from Python.
4. The display logic becomes testable as a state machine instead of a pile of side effects.

## What this still will not do

Even with a serious panel core:

- grayscale still requires obvious full refreshes
- partial updates still need periodic cleanup
- ghosting will not disappear completely
- the panel remains the slow component, not the CPU

So the goal is not “zero flicker”.

The goal is:

- fewer unnecessary full refreshes
- correct, intentional use of the panel’s real capabilities
- a clean base for future UI, art, and agent-driven content

## Final decision

Build the custom panel core in Python first.

Reason:

- fastest hardware iteration
- easiest to inspect and tune on-device
- easiest to keep close to the existing app
- easy to port later if the command/state model proves worth freezing in Rust

The correct next step is to implement that Python panel core now, not to keep adding more app-side debounce around the current vendor-style full-frame path.
