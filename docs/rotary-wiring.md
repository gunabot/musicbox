# Musicbox — Rotary Encoder Wiring (KY-040)

Status: confirmed mapping and GPIO read test (2026-02-27)

## Canonical wiring
- KY-040 `GND` -> Pi physical pin **25** (GND)
- KY-040 `+` / `VCC` -> Pi physical pin **17** (3.3V)
- KY-040 `CLK` -> Pi physical pin **29** (GPIO5 / BCM 5)
- KY-040 `DT` -> Pi physical pin **31** (GPIO6 / BCM 6)
- KY-040 `SW` -> Pi physical pin **33** (GPIO13 / BCM 13)

## Color convention used
- Black = GND
- Red = VCC (3.3V)
- Blue = CLK
- Green = DT
- Yellow or White = SW

## Quick verification command
```bash
python3 - <<'PY'
import RPi.GPIO as GPIO
pins=[5,6,13]
GPIO.setmode(GPIO.BCM)
for p in pins:
    GPIO.setup(p, GPIO.IN, pull_up_down=GPIO.PUD_UP)
print({p:GPIO.input(p) for p in pins})
GPIO.cleanup()
PY
```
Expected idle result: `{5: 1, 6: 1, 13: 1}` (pull-ups high).
