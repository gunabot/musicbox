# Spotify Cache Setup (Current Implementation)

## Purpose (cache-only)
- Spotify is used only to import/cache content into local audio files.
- Normal playback is always from local files via MPV.
- This is not a general Spotify streaming player in day-to-day playback.

See also:
- `docs/spotify-web-api-notes.md` for token behavior, endpoint list, and migration compatibility notes.

## What is implemented
- Card mappings support:
  - `local`: play local file/folder under `/home/musicbox/media`
  - `spotify`: resolve Spotify URI to cached local audio, then play with MPV
- Cache index canonical store: SQLite `config/musicbox.db` (`spotify_cache` table)
- Default fetch script: `scripts/spotify-cache-fetch` (Spotify Web API + librespot + ffmpeg)
- Capture/import jobs are serialized by a single worker queue (one active Spotify capture/import job at a time).
- Settings/mappings/OAuth are also stored in SQLite.
- Legacy JSON files are auto-migrated to SQLite on startup and archived as `*.legacy-migrated-<timestamp>.json`.

## Install dependencies
```bash
cd ~/musicbox
source ~/musicbox-env/bin/activate

# system tools
sudo apt-get install -y ffmpeg

# librespot (Debian package is not available on this image)
source ~/.cargo/env
cargo install --locked librespot --version 0.8.0
```

## Mapping examples
```json
{
  "0008970550": {"type": "local", "target": "John Broomhall - Transport Tycoon"},
  "1234567890": {"type": "spotify", "target": "spotify:playlist:37i9dQZF1DX4WYpdgoIcn6"},
  "1234567891": {"type": "spotify", "target": "https://open.spotify.com/album/2up3OPMp9Tb4dAKM2erWXQ"}
}
```

## Spotify app setup (required)
1. Create a Spotify app in Spotify Developer Dashboard.
2. Add redirect URI(s) exactly as used in the browser:
   - `http://musicbox.lan:8099/api/spotify/callback`
   - `http://localhost:8099/api/spotify/callback`
   - `http://127.0.0.1:8099/api/spotify/callback`
3. In Musicbox UI:
   - Open `Settings -> Spotify`
   - Paste `client id`
   - Save
   - Click `Connect Spotify` and complete login

## Local tunnel (when browsing from laptop)
```bash
ssh -N -L 8099:127.0.0.1:8099 musicbox@192.168.1.192
```
Then open `http://localhost:8099` in the browser.

## Runtime knobs
- `MUSICBOX_SPOTIFY_IMPORT_ROOT` (default: media root, e.g. `/data/media`)
- `MUSICBOX_SPOTIFY_CACHE_DIR` (legacy alias for import root)
- `MUSICBOX_SPOTIFY_CACHE_INDEX_PATH` (default: `/home/musicbox/musicbox/config/spotify_cache_index.json`)
- `MUSICBOX_DB_PATH` (default: `/home/musicbox/musicbox/config/musicbox.db`)
- `MUSICBOX_SPOTIFY_FETCH_COMMAND` (default: `/home/musicbox/musicbox/scripts/spotify-cache-fetch`)
- `MUSICBOX_SPOTIFY_OAUTH_PATH` (default: `/home/musicbox/musicbox/config/spotify_oauth.json`)
- `MUSICBOX_SPOTIFY_CAPTURE_DEVICE_NAME` (default: `musicbox-capture`)
- `MUSICBOX_SPOTIFY_CACHE_FORMAT` (default: `mp3`, options: `mp3|ogg|flac`)
- `MUSICBOX_SPOTIFY_CACHE_BITRATE` (default: `192k`, examples: `128k`, `160k`, `192k`)
- `MUSICBOX_SPOTIFY_ENABLE_REFRESH` (default: `0` in worker mode via resolver env; keeps refresh ownership in web service)

## Capture flow
1. Card scan resolves `spotify:*` mapping
2. Cache lookup in SQLite (`spotify_cache` table)
3. On miss:
   - fetch script resolves all tracks for URI using Spotify Web API
   - starts `librespot` pipe backend as temporary capture device
   - transfers playback to that device
   - captures PCM from pipe using ffmpeg and imports to normal library layout:
     - album: `Artist - Year - Album/01 - Artist - Track.mp3`
     - playlist: `Playlist - Name/01 - Artist - Track.mp3`
     - single track: `Singles/Artist - Track.mp3`
   - uses `.importing/` staging and atomic move into final folder/file
   - playlist imports mirror source order and can be refreshed by re-importing
4. Resolver returns cached local path
5. MPV plays local path

## Playlist sync behavior
- Spotify tab action for playlists is `Sync Playlist`.
- Sync behavior is mirror mode:
  - track order matches current Spotify playlist order
  - removed tracks are removed from local playlist folder on next sync
  - new tracks are imported on next sync
- If two playlists share the same title, imports are collision-safe (folder disambiguation by source URI), so one playlist cannot overwrite another.

## Card mapping UX (current)
- In **Library**, select a file/folder and click:
  - `Map To Card Form` to prefill the Cards tab form, or
  - `Map Last Scanned Card` to bind immediately without tab switching.
- Row-level actions in Library also include `Map Last Card` for one-click mapping.

## Custom resolver command
You can replace `MUSICBOX_SPOTIFY_FETCH_COMMAND` with your own script if needed. It must:
1. accepts args: `<spotify-uri> <import-root> <media-dir>`
2. capture audio into media storage
3. prints one final line containing a playable path (relative to media dir or absolute inside it)

The app will cache that returned path and reuse it on next scan.
