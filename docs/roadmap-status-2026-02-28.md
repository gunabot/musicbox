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
- No dedicated Spotify research report file is currently in `docs/`.
- Not implemented yet in app.

## Next roadmap items
1. Add `docs/spotify-integration-research.md` (OAuth flow, device auth, card->playlist mapping options)
2. Implement Spotify auth + playback bridge
3. Add low-battery warning + graceful shutdown policy
4. E-ink status integration
5. Finalize power UX (ATXRaspi path)
