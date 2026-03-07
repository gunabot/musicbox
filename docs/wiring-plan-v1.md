# Project Primer — Wiring Plan v1 (Pi 3B + UPS HAT + WM8960 + E-Ink + Buttons)

## 1) Power Topology

- 8.4V charger -> UPS HAT charge input
- UPS HAT -> Pi power via 40-pin GPIO header
- Batteries stay inside UPS HAT
- Do not run normal operation by powering Pi directly through Pi micro-USB

## 2) Current assembled breakout-backed layout (2026-03-06)

- Pi 3B -> UPS HAT -> 40-pin ribbon -> thin GPIO breakout/backplane
- WM8960 Audio HAT mounted on the breakout as the full 40-pin audio device
- e-Paper connected by female Dupont wires on the breakout's top header
- rotary encoder connected by female Dupont wires on the breakout's top header
- Adafruit STEMMA QT button board connected on the breakout side clamps

Current placement intent:

- WM8960 uses the breakout as the main header destination
- e-Paper is treated as a wired SPI peripheral, not as a stacked HAT
- rotary stays on the same GPIOs as before
- STEMMA uses the side clamps for `3V3`, `GND`, `SDA`, `SCL`
- verified working on 2026-03-07 after correcting e-paper `RST` to Pi `pin 11`

## 3) USB Port Map (Pi 3B)

- USB #1: Neuftech RFID reader
- USB #2: optional / legacy USB speaker during transition
- USB #3: optional / legacy USB conference mic during transition
- USB #4: spare

## 4) E-Ink Wiring (Waveshare 3.7", SPI)

Connect from e-Paper pins to Pi GPIO via the breakout top header:

- VCC -> 3V3 (Pin 1)
- GND -> GND (Pin 6)
- DIN -> MOSI / GPIO10 (Pin 19)
- CLK -> SCLK / GPIO11 (Pin 23)
- CS -> CE0 / GPIO8 (Pin 24)
- DC -> GPIO25 (Pin 22)
- RST -> GPIO17 (Pin 11)
- BUSY -> GPIO24 (Pin 18)

Notes:

- The project uses the Waveshare display in its documented `8-wire` SPI mode.
- Do not add the stock Waveshare `GPIO18 / PWR` control pin in this build.
- `GPIO18` is already part of the WM8960 I2S audio bus, so the local driver intentionally avoids that path.
- A real bring-up failure was caused by wiring `RST` to Pi `pin 9` (`GND`) instead of `pin 11`.

## 5) Button Breakout (Adafruit 5296, I2C)

- VIN -> 3V3 (Pin 1 or 17)
- GND -> GND (Pin 6 or 9)
- SDA -> GPIO2 / SDA1 (Pin 3)
- SCL -> GPIO3 / SCL1 (Pin 5)

Arcade button signals + LEDs connect to this breakout board.
Current physical arrangement:

- STEMMA male wires land in the breakout side clamps
- current assembled pin assignment:
  - red -> Pin 1 (`3V3`)
  - blue -> Pin 3 (`SDA`)
  - yellow -> Pin 5 (`SCL`)
  - black -> Pin 6 (`GND`)
- current color convention:
  - black -> GND
  - red -> 3V3
  - blue -> SDA
  - yellow -> SCL

## 6) Rotary Encoder (KY-040)

- + / VCC -> 3V3 (Pin 17)
- GND -> GND (Pin 25)
- CLK -> GPIO5 (Pin 29)
- DT -> GPIO6 (Pin 31)
- SW -> GPIO13 (Pin 33)

Current color convention:

- black -> GND
- red -> 3V3
- blue -> CLK
- green -> DT
- yellow or white -> SW

Current physical arrangement:

- rotary female Dupont wires land on the breakout top header
- rotary mapping is intentionally unchanged from the previously confirmed working setup

## 7) Suggested Control Mapping

- Yellow: record/talk (hold)
- Green: play/resume
- Red: pause (short), stop/shutdown (long)
- Blue 1: previous/rewind
- Blue 2: next/forward
- NFC tap: toggle/launch card action + e-ink update

## 8) Software Enablement

- Enable SPI: raspi-config -> Interface Options -> SPI -> enable
- Enable I2C: raspi-config -> Interface Options -> I2C -> enable
- Reboot

Sanity checks:
- confirm ribbon `pin 1` orientation at both ends before power-up
- confirm the WM8960 is not offset by one pin on the breakout header
- i2cdetect -y 1  (button board appears)
- RFID read test (keyboard/HID input)
- speaker playback test
- mic capture test
- e-ink demo test
