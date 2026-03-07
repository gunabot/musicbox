# Project Primer — Build Checklist v1 (Cardboard Lunchbox)

Last synced: 2026-03-07

## Mechanical
- [ ] Mount Pi+UPS stack with standoffs (no direct PCB-to-cardboard contact)
- [ ] Place speaker and mic on opposite sides (10-15cm separation if possible)
- [ ] Create charger port opening aligned to UPS charge jack
- [ ] Install arcade buttons through panel holes, lock rings tightened
- [ ] Add cable strain relief (zip ties + tie mounts)

## Power
- [ ] Insert 2 matching 18650 Li-ion cells
- [ ] Verify polarity before first power-up
- [ ] First power-up through UPS path only
- [ ] Verify charger powers + charges via UPS HAT

## Connectivity
- [x] USB: RFID connected
- [x] GPIO: e-ink wired (SPI pins)
- [x] I2C button breakout wired
- [x] Rotary wired
- [x] WM8960 wired and detected

## OS/Software
- [x] Enable SPI
- [x] Enable I2C
- [x] Reboot
- [x] Test speaker output
- [ ] Test mic input on WM8960 path
- [x] Test RFID read events
- [x] Test e-ink sample render
- [x] Test each button event + LED

## UX
- [ ] NFC beep mitigation decided (accept / tape / buzzer removal)
- [x] Button actions mapped for current player flow
- [x] E-ink status screen baseline set
- [ ] Record / PTT UX finalized

## Stability
- [ ] 30-minute playback test
- [ ] 30-minute idle test
- [x] quick reboot/restart test
- [ ] low-battery behavior observed and documented

## Evidence (2026-03-07)
- `i2cdetect -y 1` shows `0x3A` (Adafruit seesaw) and `0x42` (UPS HAT).
- `/dev/spidev0.0` and `/dev/spidev0.1` are present.
- `wm8960soundcard` is detected and used by `twinpeaks`.
- `musicbox/scripts/test_eink.py` rendered successfully on the 3.7" panel.
- Multiple reboot cycles completed while switching overlay modes.
