# Spotify Integration Research — Musicbox

## Goal
Map RFID cards to Spotify content (playlist/album/track) with reliable playback on Raspberry Pi.

## Recommended approach (v1)
- Use **Spotify Connect device playback** via Web API + local token auth.
- Keep local MPV for local files; add Spotify as second playback backend.
- Card mapping model: `card_id -> {type: local|spotify, target: ...}`.

## OAuth strategy
- Use a one-time browser login flow during setup.
- Store refresh token in `/data/config/spotify.json` (or `~/musicbox/config/spotify.json` now).
- Auto-refresh access tokens in app.

## Playback control model
- Reuse current controls: play/pause/stop/prev/next + rotary volume.
- For Spotify, map controls to Web API endpoints:
  - play/resume
  - pause
  - next
  - previous
  - set volume

## Card mapping schema (proposed)
```json
{
  "0008970550": {"type": "local", "target": "John Broomhall - Transport Tycoon"},
  "1234567890": {"type": "spotify", "target": "spotify:playlist:37i9dQZF..."}
}
```

## Device handling
- Discover active Spotify devices via API.
- Prefer dedicated target device name (e.g. `musicbox-capture` for cache jobs).
- If missing, show explicit UI error and fallback to local behavior.

## Libraries/options
- `spotipy` (fastest path, mature)
- direct requests against Spotify Web API (less dependency)
- `librespot` pipe backend for first-play capture into local encoded audio (default MP3 192k)

## Risks / constraints
- Spotify Premium required for full device playback control.
- Network dependency; offline mode not available for API playback.
- Token invalidation requires re-login flow.

## Implementation plan
1. Add Spotify credentials/config page in web UI.
2. Add OAuth callback endpoint and token persistence.
3. Extend card mapping to typed targets (`local`/`spotify`).
4. Add Spotify playback backend and route controls.
5. Add status in UI: current source, track title, device.

## Recommended v1 scope
- Playlist + album URIs first.
- Track URIs supported second.
- No search UX initially; user pastes Spotify URI.

## Implementation update (2026-02-28)
- App now supports typed mappings in `config/card_mappings.json`:
  - `{"type": "local", "target": "relative/path/in/media"}`
  - `{"type": "spotify", "target": "spotify:playlist:..."}`
- Legacy string mappings still load and are treated as `local`.
- RFID flow now routes `spotify` mappings through a cache resolver, then plays cached audio with MPV.
- Web UI now supports:
  - choosing mapping type (`local` or `spotify`)
  - Spotify OAuth configuration and login
  - prefetching Spotify URI into cache
  - viewing Spotify auth/device status

## Cache-resolver model (current code)
- Spotify playback is implemented as **cache-first**:
  1. scan card mapped to Spotify URI
  2. resolve URI in local cache index (`config/spotify_cache_index.json`)
  3. on miss, run fetch command (`MUSICBOX_SPOTIFY_FETCH_COMMAND`)
  4. fetch command performs Web API track resolution + librespot pipe capture + ffmpeg encode
  5. fetch command outputs local media path
  6. MPV plays that local path
- Default fetch command is `scripts/spotify-cache-fetch` (librespot-based).
- This keeps playback controls unified because everything goes through MPV after cache resolution.

## Migration compatibility update (2026-03-01)
- Search requests now cap `limit` at 10 (Spotify Dev Mode migration behavior).
- Playlist import metadata uses `/playlists/{id}/items` and supports both:
  - new wrapper: `items[].item`
  - legacy wrapper: `items[].track`
- Token handling hardened to avoid refresh-token races:
  - web service is token refresh owner
  - capture worker uses provided access token in read-only mode

## Notes
- Spotify Premium is required for playback transfer/control.
- OAuth scope must include `streaming` for librespot access-token auth.
- You can swap `MUSICBOX_SPOTIFY_FETCH_COMMAND` to a custom resolver/capture script without changing app code.
