# Spotify Cache Setup (Current Implementation)

## What is implemented
- Card mappings support:
  - `local`: play local file/folder under `/home/musicbox/media`
  - `spotify`: resolve Spotify URI to cached local audio, then play with MPV
- Cache index file: `config/spotify_cache_index.json`
- Default fetch script: `scripts/spotify-cache-fetch` (Spotify Web API + librespot + ffmpeg)

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
2. Add redirect URI:
   - `http://musicbox.lan:8099/api/spotify/callback`
3. In Musicbox UI:
   - Open `Settings -> Spotify`
   - Paste `client id`
   - Save
   - Click `Connect Spotify` and complete login

## Runtime knobs
- `MUSICBOX_SPOTIFY_CACHE_DIR` (default: `/home/musicbox/media/_spotify_cache`)
- `MUSICBOX_SPOTIFY_CACHE_INDEX_PATH` (default: `/home/musicbox/musicbox/config/spotify_cache_index.json`)
- `MUSICBOX_SPOTIFY_FETCH_COMMAND` (default: `/home/musicbox/musicbox/scripts/spotify-cache-fetch`)
- `MUSICBOX_SPOTIFY_OAUTH_PATH` (default: `/home/musicbox/musicbox/config/spotify_oauth.json`)
- `MUSICBOX_SPOTIFY_CAPTURE_DEVICE_NAME` (default: `musicbox-capture`)
- `MUSICBOX_SPOTIFY_CACHE_FORMAT` (default: `mp3`, options: `mp3|ogg|flac`)
- `MUSICBOX_SPOTIFY_CACHE_BITRATE` (default: `192k`, examples: `128k`, `160k`, `192k`)

## Capture flow
1. Card scan resolves `spotify:*` mapping
2. Cache lookup in `spotify_cache_index.json`
3. On miss:
   - fetch script resolves all tracks for URI using Spotify Web API
   - starts `librespot` pipe backend as temporary capture device
   - transfers playback to that device
   - captures PCM from pipe using ffmpeg, stores encoded files in cache (default: MP3 192k)
4. Resolver returns cached local path
5. MPV plays local path

## Custom resolver command
You can replace `MUSICBOX_SPOTIFY_FETCH_COMMAND` with your own script if needed. It must:
1. accepts args: `<spotify-uri> <cache-dir> <media-dir>`
2. capture audio into media storage
3. prints one final line containing a playable path (relative to media dir or absolute inside it)

The app will cache that returned path and reuse it on next scan.
