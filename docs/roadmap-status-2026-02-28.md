# Musicbox Roadmap Status (2026-03-07)

## Current state
- Hardware I/O prototype working (RFID, arcade buttons, rotary, LEDs)
- Web UI running (status + file manager + mappings + player controls)
- `twinpeaks` is the primary playback backend
- WM8960 playback path is working
- E-ink smoke render, live status, album-art scene, and custom panel-core path are working
- Tailscale + SSH operational

## OverlayFS state
- Overlay tooling installed (`/usr/local/bin/musicbox`)
- Current mode: **maintenance** (`overlayroot disabled`)
- Runtime root currently RW ext4 (`overlay_active=False`)
- Helper service `musicbox-rwdata.service` is enabled+active

## Docs present on Pi
- `docs/build-checklist-v1.md`
- `docs/wiring-plan-v1.md`
- `docs/inventory.md`
- `docs/hardware-status.md`
- `docs/rotary-wiring.md`
- `docs/overlayfs-runbook.md`

## Spotify integration status
- `docs/spotify-integration-research.md` present.
- Initial Spotify integration implemented:
  - typed card mappings (`local` / `spotify`)
  - RFID routing for Spotify mappings
  - cache-resolver backend (`config/spotify_cache_index.json`)
  - default fetch script `scripts/spotify-cache-fetch` (librespot capture)
  - UI supports mapping type selection and Spotify-target playback
  - UI Spotify OAuth config/connect/status/caching controls
- Added setup/runbook: `docs/spotify-cache-setup.md`

## Next roadmap items
1. Tune the e-ink panel-core policy on real hardware:
  - overlay region choices
  - scrub cadence
  - mode-switch behavior between grayscale and mono partial updates
2. Validate WM8960 microphone/recording path and design `record / PTT` UX
3. Tune `twinpeaks` transport feel further (ramp / return / higher-speed stages)
4. Finalize enclosure layout for speakers, RFID, charge port, and display
5. Return the box to overlay/appliance mode after hardware churn settles

## Foundation updates (2026-03-01)
- Persistence upgraded to SQLite (`config/musicbox.db`) with automatic legacy JSON migration.
- Spotify async imports moved to a single queue worker (no thread-per-job burst).
- Library API no longer computes recursive audio list by default (`/api/files` lighter on Pi CPU/SD I/O).
- Rotary handling improved:
  - larger fallback transition catch-up window
  - LED sweep moved off critical rotary path (reduced missed turns at fast rotation)
- Library/Card UX simplified:
  - no tree-only dependency for navigation
  - one-click `Map Last Scanned Card` flow from Library.

## Hardware integration updates (2026-03-07)
- `Pi -> UPS -> ribbon -> breakout -> WM8960 + wired peripherals` is the current working stack.
- The 3.7" Waveshare panel is running through a minimal local driver, not the full vendor repo.
- The runtime now has:
  - an event-driven display service
  - a custom panel core
  - retained mono overlay planning
  - vendor-C-derived region partial updates in the local Python driver
- Current e-ink split is:
  - `status` -> fast mono, with partial updates when possible
  - `album_art` -> full-screen `4-gray` for new art, mono overlay updates when the art base is stable
