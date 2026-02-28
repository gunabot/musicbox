# Project Primer — Wiring Plan v1 (Pi 3B + UPS HAT + E-Ink + Buttons)

## 1) Power Topology

- 8.4V charger -> UPS HAT charge input
- UPS HAT -> Pi power via 40-pin GPIO header
- Batteries stay inside UPS HAT
- Do not run normal operation by powering Pi directly through Pi micro-USB

## 2) USB Port Map (Pi 3B)

- USB #1: Neuftech RFID reader
- USB #2: USB speaker
- USB #3: USB conference mic
- USB #4: spare

## 3) E-Ink Wiring (Waveshare 3.7", SPI)

Connect from e-Paper pins to Pi GPIO (via UPS GPIO extension pins):

- VCC -> 3V3 (Pin 1)
- GND -> GND (Pin 6)
- DIN -> MOSI / GPIO10 (Pin 19)
- CLK -> SCLK / GPIO11 (Pin 23)
- CS -> CE0 / GPIO8 (Pin 24)
- DC -> GPIO25 (Pin 22)
- RST -> GPIO17 (Pin 11)
- BUSY -> GPIO24 (Pin 18)

## 4) Button Breakout (Adafruit 5296, I2C)

- VIN -> 3V3 (Pin 1)
- GND -> GND (Pin 9 or 6)
- SDA -> GPIO2 / SDA1 (Pin 3)
- SCL -> GPIO3 / SCL1 (Pin 5)

Arcade button signals + LEDs connect to this breakout board.

## 5) Rotary Encoder (KY-040)

- + -> 3V3
- GND -> GND
- CLK -> GPIO5 (Pin 29)
- DT -> GPIO6 (Pin 31)
- SW -> GPIO16 (Pin 36)

## 6) Suggested Control Mapping

- Yellow: record/talk (hold)
- Green: play/resume
- Red: pause (short), stop/shutdown (long)
- Blue 1: previous/rewind
- Blue 2: next/forward
- NFC tap: toggle/launch card action + e-ink update

## 7) Software Enablement

- Enable SPI: raspi-config -> Interface Options -> SPI -> enable
- Enable I2C: raspi-config -> Interface Options -> I2C -> enable
- Reboot

Sanity checks:
- i2cdetect -y 1  (button board appears)
- RFID read test (keyboard/HID input)
- speaker playback test
- mic capture test
- e-ink demo test
