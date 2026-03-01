import os
from pathlib import Path

BASE_DIR = Path(os.environ.get('MUSICBOX_BASE_DIR', '/home/musicbox/musicbox')).resolve()
MEDIA_DIR = Path(os.environ.get('MUSICBOX_MEDIA_DIR', '/home/musicbox/media')).resolve()
CONFIG_DIR = Path(os.environ.get('MUSICBOX_CONFIG_DIR', str(BASE_DIR / 'config'))).resolve()
LOG_DIR = Path(os.environ.get('MUSICBOX_LOG_DIR', str(BASE_DIR / 'logs'))).resolve()
SPOTIFY_IMPORT_ROOT = Path(
    os.environ.get(
        'MUSICBOX_SPOTIFY_IMPORT_ROOT',
        os.environ.get('MUSICBOX_SPOTIFY_CACHE_DIR', str(MEDIA_DIR)),
    )
).resolve()
# Backward-compatible alias used by existing modules/UI.
SPOTIFY_CACHE_DIR = SPOTIFY_IMPORT_ROOT
SPOTIFY_CACHE_INDEX_PATH = Path(
    os.environ.get('MUSICBOX_SPOTIFY_CACHE_INDEX_PATH', str(CONFIG_DIR / 'spotify_cache_index.json'))
).resolve()
SPOTIFY_OAUTH_PATH = Path(os.environ.get('MUSICBOX_SPOTIFY_OAUTH_PATH', str(CONFIG_DIR / 'spotify_oauth.json'))).resolve()
SPOTIFY_FETCH_COMMAND = os.environ.get(
    'MUSICBOX_SPOTIFY_FETCH_COMMAND',
    str(BASE_DIR / 'scripts' / 'spotify-cache-fetch'),
).strip()
SPOTIFY_CAPTURE_DEVICE_NAME = os.environ.get('MUSICBOX_SPOTIFY_CAPTURE_DEVICE_NAME', 'musicbox-capture').strip() or 'musicbox-capture'
SPOTIFY_CACHE_FORMAT = os.environ.get('MUSICBOX_SPOTIFY_CACHE_FORMAT', 'mp3').strip().lower() or 'mp3'
SPOTIFY_CACHE_BITRATE = os.environ.get('MUSICBOX_SPOTIFY_CACHE_BITRATE', '192k').strip().lower() or '192k'
SPOTIFY_SCOPE = (
    'user-read-private '
    'user-read-email '
    'user-read-playback-state '
    'user-modify-playback-state '
    'user-read-currently-playing '
    'streaming'
)

MAPPINGS_PATH = CONFIG_DIR / 'card_mappings.json'
SETTINGS_PATH = CONFIG_DIR / 'settings.json'

MPV_SOCKET = '/tmp/musicbox-mpv.sock'
PLAYLIST_PATH = Path('/tmp/musicbox-playlist.m3u')
AUDIO_DEVICE = 'alsa/plughw:1,0'

SEESAW_ADDR = 0x3A
UPS_ADDR = 0x42

BUTTON_PINS = [18, 19, 20, 2]
LED_PINS = [12, 13, 0, 1]
ROT_CLK = 5
ROT_DT = 6
ROT_SW = 13

RFID_NAME_HINTS = ('SYC ID&IC USB Reader', 'Sycreader')
DEFAULT_SETTINGS = {
    'rotary_led_step_ms': 25,
    'rotary_volume_per_turn': 100,
}
EVENTS_MAX = 400

MEDIA_EXTENSIONS = {'.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac'}
