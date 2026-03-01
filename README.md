# musicbox

Project Musicbox (RPi storybox): NFC + buttons + rotary + e-ink + audio.

## Dev quickstart

cd ~/musicbox
source ~/musicbox-env/bin/activate

## Spotify cache integration

- Card mappings now support `local` and `spotify` targets.
- Spotify settings UI supports OAuth connect/disconnect and device selection.
- Spotify mappings resolve to local cache via Web API + librespot capture (default `mp3` at `192k`) and then play through MPV.
- Setup details: `docs/spotify-cache-setup.md`

## tmux

 tmux new -s musicbox
 detach: Ctrl-b d
 reattach: tmux attach -t musicbox
