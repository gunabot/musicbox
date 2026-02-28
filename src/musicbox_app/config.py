import os
from pathlib import Path

BASE_DIR = Path(os.environ.get('MUSICBOX_BASE_DIR', '/home/musicbox/musicbox')).resolve()
MEDIA_DIR = Path(os.environ.get('MUSICBOX_MEDIA_DIR', '/home/musicbox/media')).resolve()
CONFIG_DIR = Path(os.environ.get('MUSICBOX_CONFIG_DIR', str(BASE_DIR / 'config'))).resolve()
LOG_DIR = Path(os.environ.get('MUSICBOX_LOG_DIR', str(BASE_DIR / 'logs'))).resolve()

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
DEFAULT_SETTINGS = {'rotary_led_step_ms': 25}
EVENTS_MAX = 400

MEDIA_EXTENSIONS = {'.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac'}
