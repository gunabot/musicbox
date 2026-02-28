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
- Prefer dedicated target device name (e.g. `musicbox`).
- If missing, show explicit UI error and fallback to local behavior.

## Libraries/options
- `spotipy` (fastest path, mature)
- direct requests against Spotify Web API (less dependency)

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
