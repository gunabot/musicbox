import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_DIR = Path(os.environ.get('MUSICBOX_BASE_DIR', '/home/musicbox/musicbox')).resolve()
MEDIA_DIR = Path(os.environ.get('MUSICBOX_MEDIA_DIR', '/home/musicbox/media')).resolve()
CONFIG_DIR = Path(os.environ.get('MUSICBOX_CONFIG_DIR', str(BASE_DIR / 'config'))).resolve()
LOG_DIR = Path(os.environ.get('MUSICBOX_LOG_DIR', str(BASE_DIR / 'logs'))).resolve()
DB_PATH = Path(os.environ.get('MUSICBOX_DB_PATH', str(CONFIG_DIR / 'musicbox.db'))).resolve()
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

AUDIO_DEVICE = 'alsa/plughw:1,0'
TWINPEAKS_SOCKET = os.environ.get('MUSICBOX_TWINPEAKS_SOCKET', '/tmp/twinpeaks.sock').strip() or '/tmp/twinpeaks.sock'
TWINPEAKS_BINARY = os.environ.get('MUSICBOX_TWINPEAKS_BIN', '').strip()
TWINPEAKS_OUTPUT_HINT = os.environ.get('MUSICBOX_TWINPEAKS_OUTPUT_HINT', '').strip()
TWINPEAKS_BINARY_CANDIDATES = tuple(
    dict.fromkeys(
        str(path)
        for path in [
            TWINPEAKS_BINARY,
            BASE_DIR / 'twinpeaks' / 'target' / 'release' / 'twinpeaks',
            REPO_ROOT / 'twinpeaks' / 'target' / 'release' / 'twinpeaks',
            BASE_DIR / 'twinpeaks' / 'target' / 'debug' / 'twinpeaks',
            REPO_ROOT / 'twinpeaks' / 'target' / 'debug' / 'twinpeaks',
        ]
        if str(path).strip()
    )
)
TWINPEAKS_STARTUP_TIMEOUT_S = max(1.0, float(os.environ.get('MUSICBOX_TWINPEAKS_STARTUP_TIMEOUT_S', '5.0')))
SPOTIFY_FETCH_TIMEOUT_S = max(60, int(os.environ.get('MUSICBOX_SPOTIFY_FETCH_TIMEOUT_S', '900')))

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
    'rotary_led_max_pending': 0,
    'rotary_volume_per_turn': 100,
    'alsa_pcm_percent': 100,
    'player_volume_max': 130,
}
EVENTS_MAX = 400

INPUT_LOOP_INTERVAL_S = max(0.002, float(os.environ.get('MUSICBOX_INPUT_LOOP_INTERVAL_S', '0.01')))
HEALTH_METRICS_INTERVAL_S = max(2.0, float(os.environ.get('MUSICBOX_HEALTH_METRICS_INTERVAL_S', '5.0')))
HEALTH_AUDIO_SCAN_INTERVAL_S = max(5.0, float(os.environ.get('MUSICBOX_HEALTH_AUDIO_SCAN_INTERVAL_S', '30.0')))
PLAYER_BUTTON_HOLD_SECONDS = max(0.1, float(os.environ.get('MUSICBOX_PLAYER_BUTTON_HOLD_SECONDS', '0.4')))
PLAYER_TRANSPORT_TARGET_SPEED = max(1.0, float(os.environ.get('MUSICBOX_PLAYER_TRANSPORT_TARGET_SPEED', '1.5')))
PLAYER_TRANSPORT_RAMP_MS = max(0, int(os.environ.get('MUSICBOX_PLAYER_TRANSPORT_RAMP_MS', '2000')))
PLAYER_TRANSPORT_RETURN_MS = max(0, int(os.environ.get('MUSICBOX_PLAYER_TRANSPORT_RETURN_MS', '700')))
LOW_BATTERY_PERCENT = max(2.0, min(30.0, float(os.environ.get('MUSICBOX_LOW_BATTERY_PERCENT', '10.0'))))
BATTERY_FULL_PERCENT = max(90.0, min(100.0, float(os.environ.get('MUSICBOX_BATTERY_FULL_PERCENT', '99.0'))))
BATTERY_STATUS_INTERVAL_S = max(15.0, float(os.environ.get('MUSICBOX_BATTERY_STATUS_INTERVAL_S', '60.0')))
BATTERY_STATUS_PULSE_S = max(0.2, float(os.environ.get('MUSICBOX_BATTERY_STATUS_PULSE_S', '1.0')))
STATUS_LED_RED_INDEX = max(1, min(4, int(os.environ.get('MUSICBOX_STATUS_LED_RED_INDEX', '2'))))
STATUS_LED_GREEN_INDEX = max(1, min(4, int(os.environ.get('MUSICBOX_STATUS_LED_GREEN_INDEX', '4'))))
STARTUP_LED_FLASH_COUNT = max(1, min(4, int(os.environ.get('MUSICBOX_STARTUP_LED_FLASH_COUNT', '2'))))
STARTUP_LED_FLASH_ON_S = max(0.12, float(os.environ.get('MUSICBOX_STARTUP_LED_FLASH_ON_S', '0.45')))
STARTUP_LED_FLASH_OFF_S = max(0.05, float(os.environ.get('MUSICBOX_STARTUP_LED_FLASH_OFF_S', '0.18')))
STARTUP_LED_SWEEP_STEP_S = max(0.08, float(os.environ.get('MUSICBOX_STARTUP_LED_SWEEP_STEP_S', '0.24')))
STARTUP_LED_READY_DELAY_S = max(0.0, float(os.environ.get('MUSICBOX_STARTUP_LED_READY_DELAY_S', '0.35')))

MEDIA_EXTENSIONS = {'.mp3', '.wav'}
