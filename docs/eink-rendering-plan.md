# Musicbox E-Ink Rendering Plan

Updated: 2026-03-07

## Current baseline

- Hardware: Waveshare `3.7"` e-paper (`480 x 280`)
- Effective tones:
  - white
  - light gray
  - dark gray
  - black
- Current runtime path:
  - local `waveshare_epd` driver
  - service-owned status worker
  - full-screen `4-gray` refresh
- Current tradeoff:
  - image looks clean
  - whole display flashes on each update

## What should exist next

There should be two display modes, not one:

1. Fast UI mode
- for play/pause/idle/recording/status changes
- black/white only
- minimal flashing
- partial or at least non-gray redraw path

2. Quality image mode
- for album art, TTS/agent cards, simple faces, icons, prompts
- `4-gray`
- optional dithering
- full refresh is acceptable here

## Recommended rendering pipeline

For image inputs (`png`, `jpg`, generated art, agent output):

1. Load source image
2. Crop / letterbox to panel aspect ratio
3. Resize to panel resolution
4. Normalize contrast / levels
5. Optional sharpen or mild blur depending on source
6. Choose output mode
- fast mode:
  - threshold to black/white
  - optional light ordered dithering
- quality mode:
  - quantize to `4` tones
  - optional dithering to improve perceived shading
7. Send the final raster to the display

## Where rendering can happen

Not all rendering has to happen on the Pi.

Good split:

- Pi:
  - text/status layout
  - simple icons
  - immediate local updates
- off-device / agent:
  - image preprocessing
  - dithering experiments
  - art generation
  - text-to-image or TTS companion visuals
  - pre-rendered final frames

The Pi can then just receive a final prepared image and display it.

## Near-term implementation plan

1. Keep the current full-refresh `4-gray` path as the safe fallback.
2. Add a fast black/white status renderer for routine UI changes.
3. Add one image conversion helper:
- input: `png/jpg`
- output: display-ready monochrome or `4-gray` image
4. Decide on one default dithering strategy for art mode.
5. Expose a simple command/API path so an agent can push rendered frames later.

## Good future uses

- current track / idle card
- RFID prompt and feedback
- recording mode
- transcript / TTS snippets
- simple illustrations
- low-fi album art
- faces, arrows, icons, and speaking/listening states
