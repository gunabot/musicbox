# Musicbox Roadmap Status (2026-02-28)

## Current state
- Hardware I/O prototype working (RFID, arcade buttons, rotary, LEDs)
- Web UI running (status + file manager + mappings + player controls)
- MPV playback working (file/folder mapping)
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
1. Validate first full playlist capture on-device and tune track timing gaps
2. Optional: background prefetch queue (capture while first cached track plays)
3. Add low-battery warning + graceful shutdown policy
4. E-ink status integration
5. Finalize power UX (ATXRaspi path)

## Foundation updates (2026-03-01)
- Persistence upgraded to SQLite (`config/musicbox.db`) with JSON compatibility mirrors.
- Spotify async imports moved to a single queue worker (no thread-per-job burst).
- Library API no longer computes recursive audio list by default (`/api/files` lighter on Pi CPU/SD I/O).
- Rotary handling improved:
  - larger fallback transition catch-up window
  - LED sweep moved off critical rotary path (reduced missed turns at fast rotation)
- Library/Card UX simplified:
  - no tree-only dependency for navigation
  - one-click `Map Last Scanned Card` flow from Library.
