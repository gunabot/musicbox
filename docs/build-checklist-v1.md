# Project Primer — Build Checklist v1 (Cardboard Lunchbox)

Last synced: 2026-02-28

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
- [x] USB: RFID + speaker + mic connected
- [ ] GPIO: e-ink wired (SPI pins)
- [x] I2C button breakout wired
- [x] Rotary wired

## OS/Software
- [x] Enable SPI
- [x] Enable I2C
- [x] Reboot
- [x] Test speaker output
- [x] Test mic input
- [ ] Test RFID read events (device present; live tag read still pending)
- [ ] Test e-ink sample render
- [ ] Test each button event + LED

## UX
- [ ] NFC beep mitigation decided (accept / tape / buzzer removal)
- [ ] Button actions mapped (play/pause/stop/record/next/prev)
- [ ] E-ink status screens set (idle/listening/speaking/playing)

## Stability
- [ ] 30-minute playback test
- [ ] 30-minute idle test
- [x] quick reboot/restart test
- [ ] low-battery behavior observed and documented

## Evidence (2026-02-28)
- `i2cdetect -y 1` shows `0x3A` (Adafruit seesaw) and `0x42` (UPS HAT).
- `/dev/spidev0.0` and `/dev/spidev0.1` are present.
- `aplay /usr/share/sounds/alsa/Front_Center.wav` completed successfully.
- `arecord -d 2 -f S16_LE -r 16000 -c 1 /tmp/musicbox-mic-test.wav` completed successfully.
- Multiple reboot cycles completed while switching overlay modes.
