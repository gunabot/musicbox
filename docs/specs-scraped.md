# Project Primer — Scraped Specs (manufacturer/docs)

Last updated: 2026-02-19

## Waveshare UPS HAT (Amazon B08C53K14G / Waveshare UPS HAT)
Sources:
- https://www.waveshare.com/wiki/UPS_HAT
- https://www.waveshare.com/ups-hat.htm

Specs found:
- Output voltage: 5V
- Continuous output current: up to 2.5A
- Charger: 8.4V / 2A (included in kit listing)
- Battery type: 18650 Li-ion, 3.7V cells x2
- Control/monitoring bus: I2C
- USB output: 5V USB-A present
- Board dimensions: 56mm x 85mm
- Mounting hole: 3.0mm
- Height when mounted on Pi: ~42.05mm (wiki FAQ)

Important notes:
- Use included charger type/spec; wrong charger can damage module (vendor note)
- Warning LEDs indicate reversed battery install

## Waveshare 3.7" e-Paper HAT (Amazon B08HK8V3H8)
Sources:
- https://www.waveshare.com/3.7inch-e-paper-hat.htm
- https://www.waveshare.com/wiki/3.7inch_e-Paper_HAT

Specs found:
- Resolution: 480 x 280
- Display colors: black/white + 4 grayscale
- Interface: SPI (3-wire/4-wire)
- Operating voltage: 3.3V/5V
- Partial refresh time: ~0.3s
- Full refresh time: ~3s
- Outline dimensions: 58.0 x 96.5mm
- Display area: 47.32 x 81.12mm
- Viewing angle: >170°
- Standby current: <0.01uA

## Adafruit LED Arcade Button 1x4 STEMMA QT I2C Breakout (5296)
Source:
- https://www.adafruit.com/product/5296

Specs found:
- Board size: about 3.0" x 0.8" (approx 76.2 x 20.3mm)
- Interface: I2C via STEMMA QT/Qwiic or header pads
- Function: reads 4 buttons + controls 4 button LEDs (PWM) via seesaw firmware
- Addressing: configurable for multiple boards via address jumpers
- Notes: board only; buttons + quick-connect cables are separate

## Adafruit Mini LED Arcade Buttons (24mm series)
Source example:
- https://www.adafruit.com/product/3432

Specs found:
- Mounting hole required: 24mm
- Panel thickness supported: up to ~15mm
- LED: dual SMD LEDs inside, each with ~1K resistor
- LED drive examples: ~10mA at 5V, lower current/dimmer at 3.3V

## Adafruit STEMMA QT cable (4209)
Source:
- https://www.adafruit.com/product/4209

Specs found:
- Length: ~150mm (6")
- JST-SH 4-pin to Dupont male headers
- Typical color map:
  - red: 3.3V
  - black: GND
  - blue: SDA
  - yellow: SCL

## Adafruit Arcade quick-connect wire pairs (1152)
Source:
- https://www.adafruit.com/product/1152

Specs found:
- Quick-connect pair for arcade tabs (0.11")
- Wire length: 20cm
- End connector: 2-pin JST-style (can be adapted/cut)

## Neuftech USB RFID Reader (B018OYOR3E)
Source:
- Amazon title + prior gathered notes

Specs confirmed/high confidence:
- USB interface
- 125kHz class reader
- EM4100/TK4100 compatibility

Behavior note:
- Beeper is hardware-based on common units; software disable usually not available

## User-provided measured dimension
- USB soundbar: 4D x 18W x 5H cm

## Still need exact physical measurements (manual, once parts arrive)
- UPS HAT connector/jack offsets from board edge
- E-ink mounting hole coordinates and hole diameter
- USB mic body dimensions and mounting method
- RFID reader case dimensions and PCB buzzer location (if muting)
- Actual lunchbox internal dimensions and wall thickness
