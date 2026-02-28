# Project Primer / Musicbox — Hardware Status

Updated: 2026-02-28

## Detected on Pi (`192.168.1.192`)
- I2C:
  - `0x3A` Adafruit arcade button breakout
  - `0x42` Waveshare UPS HAT monitor
- SPI:
  - `/dev/spidev0.0`
  - `/dev/spidev0.1`
- USB:
  - Sycreader RFID USB reader
  - Jieli USB audio device (playback + capture)

## Input test script installed
- Path: `~/musicbox/scripts/test_inputs.py`
- Run:
  - `~/musicbox-env/bin/python -u ~/musicbox/scripts/test_inputs.py`

## What it tests
- Arcade button board on I2C (`0x3A`)
  - Button press/release events (BUTTON1..BUTTON4)
  - LED chase test (LED1..LED4)
- Rotary encoder on GPIO
  - Rotation direction events (`ROTARY CW/CCW`)
  - Push switch events (`ROTARY_SW PRESSED/RELEASED`)

## Rotary canonical mapping used
- GND -> pin 25
- VCC -> pin 17
- CLK -> pin 29 (GPIO5)
- DT -> pin 31 (GPIO6)
- SW -> pin 33 (GPIO13)
