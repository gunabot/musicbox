# Project Primer / Musicbox — Hardware Status

Updated: 2026-03-07

## Runtime state
- Host: `musicbox` (`192.168.1.192`)
- Mode: `maintenance` (overlay disabled, root on ext4 rw)
- Service: `musicbox-status.service` is active
- Primary player backend: `twinpeaks`
- Primary audio output: `wm8960soundcard`

## Detected on Pi
- I2C bus 1:
  - `0x3A` Adafruit arcade button breakout (seesaw)
  - `0x42` Waveshare UPS HAT monitor
- SPI:
  - `/dev/spidev0.0`
  - `/dev/spidev0.1`
- USB/input:
  - Sycreader USB RFID reader (`...event-kbd`)
- Audio:
  - `card 0: wm8960soundcard`
  - WM8960 service enabled and active
- Display:
  - Waveshare `3.7"` e-paper reachable through local `waveshare_epd` driver
  - live event-driven display service active in app
  - custom `musicbox_display` panel core active
  - current scenes: `status`, `album_art`
  - current render split:
    - `status -> fast_bw` with retained mono partial updates
    - `album_art -> quality_gray` for base art, mono partial overlays for stable-art metadata updates

## Verified smoke tests
- `twinpeaks` playback through WM8960 works
- RFID card launch works in app flow
- arcade buttons + rotary work in app flow
- e-paper smoke render works:
  - `/home/musicbox/musicbox-env/bin/python /home/musicbox/musicbox/scripts/test_eink.py`
- live e-paper rendering works from the service (`EINK_READY` seen in event log)
- album art scene is working for tracks with adjacent folder art

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
- WM8960 microphone capture path through red-button recorder flow
- panel-core tuning on real hardware:
  - mono partial cadence
  - scrub cadence
  - overlay region choices
- 30-minute playback and idle soak tests
- UPS low-battery behavior capture
