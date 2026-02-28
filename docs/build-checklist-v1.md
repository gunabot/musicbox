# Project Primer — Build Checklist v1 (Cardboard Lunchbox)

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
- [ ] USB: RFID + speaker + mic connected
- [ ] GPIO: e-ink wired (SPI pins)
- [ ] I2C button breakout wired
- [ ] Rotary wired

## OS/Software
- [ ] Enable SPI
- [ ] Enable I2C
- [ ] Reboot
- [ ] Test speaker output
- [ ] Test mic input
- [ ] Test RFID read events
- [ ] Test e-ink sample render
- [ ] Test each button event + LED

## UX
- [ ] NFC beep mitigation decided (accept / tape / buzzer removal)
- [ ] Button actions mapped (play/pause/stop/record/next/prev)
- [ ] E-ink status screens set (idle/listening/speaking/playing)

## Stability
- [ ] 30-minute playback test
- [ ] 30-minute idle test
- [ ] quick reboot/restart test
- [ ] low-battery behavior observed and documented
