# Project Primer / Musicbox — Hardware Status

Updated: 2026-02-28

## Runtime state
- Host: `musicbox` (`192.168.1.192`)
- Mode: `maintenance` (overlay disabled, root on ext4 rw)
- Service: `musicbox-status.service` is active

## Detected on Pi
- I2C bus 1:
  - `0x3A` Adafruit arcade button breakout (seesaw)
  - `0x42` Waveshare UPS HAT monitor
- SPI:
  - `/dev/spidev0.0`
  - `/dev/spidev0.1`
- USB/input:
  - Sycreader USB RFID reader (`...event-kbd`)
  - Jieli USB audio device (playback + capture)

## Verified smoke tests
- Audio playback command succeeds:
  - `aplay /usr/share/sounds/alsa/Front_Center.wav`
- Audio capture command succeeds:
  - `arecord -d 2 -f S16_LE -r 16000 -c 1 /tmp/musicbox-mic-test.wav`

## Input test script
- Path: `~/musicbox/scripts/test_inputs.py`
- Run:
  - `~/musicbox-env/bin/python -u ~/musicbox/scripts/test_inputs.py`
- Covers:
  - Arcade buttons press/release + LED chase
  - Rotary CW/CCW + switch press/release

## Rotary canonical mapping used
- GND -> pin 25
- VCC -> pin 17
- CLK -> pin 29 (GPIO5)
- DT -> pin 31 (GPIO6)
- SW -> pin 33 (GPIO13)

## Pending validation
- One live RFID tag read event in app flow
- E-ink sample render on Waveshare panel
- 30-minute playback and idle soak tests
- UPS low-battery behavior capture
