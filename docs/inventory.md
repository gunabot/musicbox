# Project Primer — Inventory & Specs (v1)

Last updated: 2026-02-28

## Status Legend
- owned = physically in hand
- ordered = purchased, in transit
- planned = not purchased yet
- installed = owned and currently wired/active in build

## Core Hardware

1) Raspberry Pi 3B
- Status: owned
- Notes: 4x USB ports available for NFC + speaker + mic

2) USB Speaker
- URL: https://www.amazon.de/dp/B089W5PS29
- Product: SoundBar Mini USB Speaker
- Status: owned
- Interface: USB

3) RFID Cards (125kHz)
- URL: https://www.amazon.de/dp/B07TQCTHRZ
- Product: TK4100/EM4100/EM4200 cards, 50 pack
- Status: owned
- Frequency: 125kHz

4) USB RFID Reader
- URL: https://www.amazon.de/dp/B018OYOR3E
- Product: Neuftech USB RFID Reader (EM4100)
- Status: owned
- Notes: hardware beeper cannot reliably be disabled in software; can be physically muted/removed

5) KY-040 Rotary Encoder (pack)
- URL: https://www.amazon.de/dp/B09726Y8RB
- Product: KY-040 modules
- Status: owned

6) USB-C Panel Mount Extension
- URL: https://www.amazon.de/dp/B0D17K3CCY
- Product: USB-C panel extension cable (30cm)
- Status: owned
- Note: passthrough cable only, not a power controller

7) Powerbank
- URL: https://www.amazon.de/dp/B08XQ43HZT
- Product: Baseus 20000mAh powerbank
- Status: owned

8) Micro-USB cable (short)
- URL: https://www.amazon.de/dp/B0CGRG7F2Q
- Product: USB-A to Micro-USB short braided cable
- Status: owned

## Newly Ordered / Confirmed

9) Waveshare UPS HAT
- URL: https://www.amazon.de/dp/B08C53K14G
- Status: installed
- Key specs (from listing):
  - 5V UPS for Raspberry Pi
  - battery monitoring via I2C
  - charge + power output supported simultaneously
  - includes 8.4V charger
  - compatible boards include Pi 3B/3B+

10) 3.7" Waveshare e-Paper HAT
- URL: https://www.amazon.de/dp/B08HK8V3H8
- Status: owned
- Key specs:
  - 480x280
  - B/W + 4 gray levels
  - SPI interface

11) Jumper wire kit
- URL: https://www.amazon.de/dp/B0DGBYR2YL
- Status: ordered
- Key specs:
  - 120 pieces total
  - 10cm + 20cm
  - M-M, M-F, F-F

12) USB Conference Mic
- URL: https://www.amazon.de/dp/B0CP7ZSJK9
- Status: installed
- Key specs:
  - USB plug-and-play
  - omnidirectional
  - mute button

13) M2.5 standoff kit
- URL: https://www.amazon.de/dp/B0C1FZ8F4N
- Status: ordered
- Key specs:
  - brass standoffs + screws + nuts assortment

14) 3M Dual Lock
- URL: https://www.amazon.de/dp/B00LUL1T80
- Status: ordered
- Key specs:
  - 25mm x 1.25m
  - strong removable fastening

15) Velcro cable ties
- URL: https://www.amazon.de/dp/B0BX9ZV2MV
- Status: ordered

16) 18650 cells (Digitec)
- URL: https://www.digitec.ch/de/s1/product/samsung-inr18650-35e-1-pcs-18650-3500-mah-batteries-31216222
- Status: planned/ordering via Digitec
- Required: 2x identical cells
- Required type: 18650 Li-ion, flat-top, matching pair

## Adafruit Parts Referenced (button system)

- 4209: STEMMA QT / Qwiic JST SH 4-pin to male headers cable
- 3432: Mini LED Arcade Button (blue)
- 3429: Mini LED Arcade Button (clear)
- 3430: Mini LED Arcade Button (red)
- 3433: Mini LED Arcade Button (green)
- 3431: Mini LED Arcade Button (yellow)
- 1152: Arcade Button quick-connect wire pairs
- 5296: Adafruit LED Arcade Button 1x4 STEMMA QT I2C breakout

Tutorial refs:
- http://www.adafruit.com/product/4209#tutorials
- http://www.adafruit.com/product/3432#tutorials
- http://www.adafruit.com/product/3429#tutorials
- http://www.adafruit.com/product/3430#tutorials
- http://www.adafruit.com/product/3433#tutorials
- http://www.adafruit.com/product/3431#tutorials
- http://www.adafruit.com/product/1152#tutorials
- http://www.adafruit.com/product/5296#tutorials

## Integration Constraints (important)

- UPS HAT must be primary power path (charger into HAT, Pi powered via GPIO/HAT)
- Current USB RFID reader is 125kHz EM4100 class (tap events; no robust tag-present sensing)
- e-Paper + button/rotary wiring should use GPIO extension pins exposed by UPS HAT
- Keep mic physically separated from speaker (~10-15cm if possible)
