# Musicbox Hardware Dossier

Date: 2026-03-07

## Scope

This document covers the hardware that is either:

- already owned/installed and relevant to enclosure/layout decisions, or
- newly in hand and likely to replace the current audio path.

Generic consumables (Dual Lock, cable ties, jumper assortments, standoffs) are not the focus here unless they affect fit or routing.

## Main conclusions

- The current lunchbox is still viable with the present electronics stack.
- The cleanest stack remains `Pi 3B -> UPS HAT -> WM8960 Audio HAT`, with the live build currently using a ribbon to a breakout/backplane.
- The e-paper should remain the only major remote-mounted GPIO peripheral.
- The current USB Neuftech RFID reader works well electrically, but it is mechanically bulky.
- There is public evidence that people remove the Neuftech reader shell and glue the antenna assembly into the lid/top panel, but this should be treated as a mechanical experiment, not a guaranteed no-risk mod.
- Red is the best current candidate for `record / push-to-talk` if we want to avoid adding a fifth button right now.

## Current verified working baseline

- `twinpeaks` is the active playback backend.
- WM8960 playback is working on the Pi.
- bundled WM8960 speakers are connected and producing sound in the current prototype.
- one Adafruit 4-button seesaw board + rotary + RFID are all working in app flow.
- the 3.7" Waveshare e-paper is wired and rendering both:
  - the standalone smoke test
  - a basic live status screen from the service
- current e-paper rendering is full-screen `4-gray`, so it visibly flashes on refresh.

## Current hardware catalog

### Raspberry Pi 3 Model B

- Role: main controller
- Status: owned
- Key specs:
  - Broadcom BCM2837
  - quad-core Cortex-A53 @ 1.2GHz
  - 1GB LPDDR2
  - 4 x USB 2.0
  - 100 Mb/s Ethernet
  - 2.4GHz 802.11n Wi-Fi
  - Bluetooth 4.1 / BLE
  - 40-pin GPIO header
  - CSI + DSI connectors
  - microSD boot
  - micro-USB power
- Dimensions:
  - same board family/form factor as Pi 3B+, commonly treated as about `85 x 56mm`
- Integration notes:
  - Current project already uses USB for RFID/audio and GPIO for rotary, I2C, UPS, and LEDs.
  - GPIO pin pressure is still manageable if audio stays on the WM8960 and RFID stays USB.
- Sources:
  - Raspberry Pi 3 launch post: <https://www.raspberrypi.com/news/raspberry-pi-3-on-sale/>
  - Raspberry Pi hardware overview: <https://www.raspberrypi.com/documentation/computers/raspberry-pi.html>
  - Raspberry Pi Magazine Pi 3 specs: <https://magazine.raspberrypi.com/articles/raspberry-pi-3-specs-benchmarks>

### Waveshare UPS HAT

- Role: primary power path / battery-backed supply
- Status: installed
- Key specs:
  - 5V regulated output
  - 8.4V / 2A charger input
  - 2 x 18650 cells
  - I2C fuel-gauge / monitoring
  - up to `2.5A` continuous output on the original UPS HAT
- Connectors / interfaces:
  - 40-pin Pi header
  - 8.4V barrel charging input
  - I2C monitoring
  - 5V USB output
- Dimensions:
  - `56 x 85mm`
- Integration notes:
  - This is the board that determines where the external charging hole should go.
  - The current OS is still in maintenance mode, so the UPS gives runtime continuity but does not yet give read-only-root protection.
- Sources:
  - Waveshare UPS HAT page: <https://www.waveshare.com/ups-hat.htm>
  - Waveshare UPS HAT wiki: <https://www.waveshare.com/wiki/UPS_HAT>

### Waveshare WM8960 Audio HAT

- Role: intended replacement for USB speaker + USB mic path
- Status: in hand
- Key specs:
  - WM8960 stereo codec
  - stereo playback + stereo record
  - dual onboard MEMS microphones
  - `1W per channel` speaker driver into `8 ohm`
  - headphone output `40mW (16 ohm @ 3.3V)`
- Connectors / interfaces:
  - 40-pin Pi header
  - I2C control on `GPIO2/GPIO3`
  - I2S audio on `GPIO18/19/20/21`
  - 3.5mm headphone jack
  - speaker output via `JST-PH 4-pin` or screw terminals
- Dimensions:
  - exact physical size is not clearly text-listed on the official page
  - reseller listings commonly report about `65 x 30mm`
- In-hand observation:
  - your board has passthrough, which makes it stackable over the UPS HAT
- Integration notes:
  - This is a much better candidate to stack than the e-paper.
  - It does not conflict with the current rotary GPIOs (`5/6/13`).
  - It does share I2C with the button boards and UPS, which is fine.
- Sources:
  - Waveshare WM8960 wiki: <https://www.waveshare.com/wiki/WM8960_Audio_HAT>
  - TinyTronics product page: <https://www.tinytronics.nl/en/audio/amplifiers/waveshare-wm8960-audio-hat-including-speaker-set-for-raspberry-pi>

### Bundled Waveshare speakers for the WM8960

- Role: default passive stereo speakers for the WM8960 HAT
- Status: in hand
- Key specs:
  - `8 ohm`
  - `5W` each
- Connectors:
  - bundled to match the WM8960 HAT's speaker connection
- Dimensions:
  - reseller report: about `100 x 45 x 21mm` each
- Integration notes:
  - This is the main packaging problem in the current lunchbox.
  - They are likely oversized for the enclosure even though the electronics stack fits.
- Sources:
  - Waveshare FAQ on speaker rating: <https://www.waveshare.com/wiki/WM8960_Audio_HAT>
  - MakerFocus reseller listing with speaker dimensions: <https://www.makerfocus.com/products/wm8960-i2s-expansion-board-amplifier-module-with-2pcs-arduino-speaker-for-raspberry-pi>

### Waveshare 3.7" e-Paper HAT

- Role: future display / now the main lid-space consumer
- Status: owned
- Key specs:
  - `480 x 280`
  - black/white
  - 4 gray levels
  - partial refresh support
  - full refresh about `3s`
  - partial refresh about `0.3s`
- Connectors / interfaces:
  - SPI
  - control pins for `CS`, `DC`, `RST`, `BUSY`
  - onboard level shifting for `3.3V / 5V`
- Dimensions:
  - driver board outline: `58.0 x 96.5mm`
  - panel outline: `54.9 x 93.3 x 0.78mm`
  - display area: `47.32 x 81.12mm`
- In-hand observation:
  - your e-paper board has no passthrough
- Integration notes:
  - This should be remote-wired and mounted in the lid/window.
  - The FPC and mounting arrangement are fragile enough that repeated rework should be minimized.
- Sources:
  - Waveshare product page: <https://www.waveshare.com/3.7inch-e-paper-hat.htm>
  - Waveshare manual: <https://www.waveshare.com/wiki/3.7inch_e-Paper_HAT_Manual>

### Neuftech USB RFID Reader (EM4100 / TK4100 class)

- Role: current tag input
- Status: owned / installed
- Key specs from Neuftech:
  - USB powered
  - USB interface
  - `125kHz`
  - supports `TK4100` and `EM4100`
  - LED + buzzer
  - cable length about `130cm`
  - keyboard-wedge style output
- Dimensions:
  - Neuftech's own page does not currently list physical dimensions
  - generic readers in this class are commonly around `94 x 60 x 10mm` to `104 x 68 x 10mm`
- Mechanical mod evidence:
  - there is at least one public Phoniebox build referencing this exact Neuftech Amazon model and explicitly saying to remove the case and glue the antenna to the top of the enclosure
- Integration notes:
  - This is the current mechanical troublemaker in the lid/top area.
  - A de-casing experiment is plausible.
  - I would expect the antenna coil and the small controller PCB to be separable enough to re-position, but that is an inference, not a confirmed Neuftech teardown guide.
  - The safest next step is to open one, photograph the insides, and test read range through your cardboard before committing to relocation.
- Sources:
  - Neuftech product page: <https://neuftech.net/products/40>
  - generic keyboard-emulation LF reader specs: <https://www.findsupply.com/products/rfid-reader-keyboard-emulation-read-only-khz-usb-rs/>
  - community Phoniebox case note: <https://3dgo.app/models/thingiverse/6581305>
  - Phoniebox project still recommending this reader family: <https://github.com/MiczFlor/RPi-Jukebox-RFID>

### EM4100 / TK4100 cards and keyfobs

- Role: current media triggers
- Status: owned
- Key specs:
  - `125kHz`
  - read-only ID style tags for the current USB reader path
- Integration notes:
  - These remain the simplest "common denominator" for the current system.
  - They work well with the Neuftech keyboard-emulation reader, but do not solve "tag present / tag removed" sensing.
- Sources:
  - Neuftech product page: <https://neuftech.net/products/40>
  - Phoniebox RFID notes: <https://github.com/MiczFlor/RPi-Jukebox-RFID>

### Adafruit LED Arcade Button 1x4 STEMMA QT board (x2 in hand)

- Role: current and future lit-button controller
- Status: one installed, second board in hand
- Key specs:
  - reads 4 buttons and drives 4 button LEDs
  - default I2C address `0x3A`
  - seesaw microcontroller handles button input and LED PWM
  - up to `16` boards on one I2C bus with address jumpers
- Connectors / interfaces:
  - STEMMA QT / Qwiic I2C
  - `8 x JST XH` sockets for 4 switch+LED button pairs
- Dimensions:
  - `76.3 x 21.5 x 13.0mm`
- Integration notes:
  - This is a very good way to scale from 4 to 8 lit buttons without consuming more Pi GPIO.
  - If you later want a dedicated yellow `PTT/REC` arcade button with matching light, the second board is the clean way to do it.
- Sources:
  - Adafruit product page: <https://www.adafruit.com/product/5296>
  - Adafruit guide: <https://learn.adafruit.com/adafruit-led-arcade-button-qt/featured_products>

### Adafruit mini 24mm LED arcade buttons

- Role: current main controls
- Status: owned / installed
- Key specs:
  - `24mm` mounting hole
  - panel thickness up to about `15mm`
  - built-in LED with parallel resistors
  - around `10mA` at `5V`, around `2mA` at `3.3V` but dimmer
- Connectors:
  - switch terminals + separate LED terminals
  - mini buttons use the smaller quick-connect size family
- Integration notes:
  - Re-using red for `record/PTT` is the cleanest no-new-hole option right now.
  - Blue left/right remain the best fit for previous/next and hold-to-scrub.
- Sources:
  - Green button page: <https://www.adafruit.com/product/3433>
  - Red button page: <https://www.adafruit.com/product/3430>
  - Adafruit arcade button guide: <https://cdn-learn.adafruit.com/downloads/pdf/arcade-buttons.pdf>

### Adafruit STEMMA QT cable (4209)

- Role: I2C breakout / quick hookup from JST-SH to Dupont
- Status: owned
- Key specs:
  - length about `150mm`
  - JST-SH 4-pin on one side, Dupont male headers on the other
  - color order:
    - black = GND
    - red = V+
    - blue = SDA
    - yellow = SCL
- Integration notes:
  - This is useful for daisy-chaining or breaking out the second seesaw board.
  - It does not magically add an extra button to the current 4-button board; it is only a cable.
- Sources:
  - Adafruit product page: <https://www.adafruit.com/category/619>
  - Adafruit STEMMA QT specs: <https://learn.adafruit.com/introducing-adafruit-stemma-qt/technical-specs>

### KY-040 rotary encoder

- Role: current volume / transport control
- Status: owned / installed
- Current project wiring:
  - `CLK -> GPIO5`
  - `DT -> GPIO6`
  - `SW -> GPIO13`
  - `3.3V` + `GND`
- Integration notes:
  - Treat `GPIO13` as canonical for the switch; one older doc still mentions `GPIO16`, but the live code and dedicated wiring doc use `GPIO13`.
- Sources:
  - local confirmed wiring: `docs/rotary-wiring.md`

### USB conference mic

- Role: current working microphone path
- Status: installed
- Known facts:
  - USB plug-and-play
  - omnidirectional
  - mute button
- Integration notes:
  - This is currently the known-good recording input.
  - Once the WM8960 is proven on-device, this becomes optional.
- Source:
  - current inventory/listing notes: `docs/inventory.md`

### USB mini soundbar speaker

- Role: current working playback path
- Status: owned
- Known facts:
  - USB-powered playback path currently works on-device
- Integration notes:
  - This is the safe fallback until the WM8960 path is fully proven in the enclosure.
- Source:
  - current inventory/listing notes: `docs/inventory.md`

## RFID reader mechanical note

### What seems realistic

- Keeping the current Neuftech reader is still the lowest-risk software path.
- Removing the outer shell and re-positioning the antenna/coil assembly is plausible.
- The public Phoniebox example using this same Neuftech Amazon listing suggests this is not a crazy idea.

### What is still unknown

- How much of the reader is one rigid PCB versus a coil + controller assembly.
- Whether the buzzer is on the same board and easy to relocate or mute.
- How much read range you lose if you sandwich the antenna behind thicker cardboard or near metal hardware.

### Recommended next step

1. Open the Neuftech reader.
2. Photograph the internals.
3. Measure the antenna/coil area.
4. Test read range through the lunchbox wall material before permanent mounting.

## Compact speaker shortlist

These are the most relevant smaller alternatives I found for a lunchbox build.

### Option A: DFRobot FIT0502

- `70 x 30 x 16mm`
- `8 ohm`
- `3W`
- JST-PH 2.0 lead
- easiest ready-made compact speaker module I found from a reputable hobby vendor
- Still larger than tiny raw drivers, but much smaller than the bundled Waveshare pair.
- If you want stereo, you would need two suitable compact speakers or an equivalent paired product.
- Source: <https://www.dfrobot.com/product-1506.html>

### Option B: Visaton K 28.40 - 8 Ohm

- `28 x 40 x 11.7mm`
- `8 ohm`
- `2W rated / 3W max`
- solder lugs, no enclosure, no plug
- best "small but still real speaker" option from a known speaker brand
- likely good if you are willing to do custom mounting and wiring
- Source: <https://www.visaton.de/en/products/drivers/miniature-speakers/k-2840-8-ohm>

### Option C: Soberton WSP-4012Y

- `40.2 x 28.2 x 11.8mm`
- `8 ohm`
- `1W rated / 2W max`
- waterproof miniature driver
- no plug-ready enclosure
- best if you care more about compact size than loudness
- Source: <https://www.digikey.com/htmldatasheets/production/4963118/0/0/1/wsp-4012y.pdf>

## Speaker compatibility note for the WM8960

- The WM8960 HAT is specified for `1W per channel into 8 ohm`.
- That means:
  - `8 ohm` matters more than chasing a huge wattage number.
  - A `2W` or `3W` `8 ohm` speaker is fine and just gives headroom.
  - Moving to `4 ohm` speakers is not my recommended default unless the board documentation explicitly supports it.

## Recommended common-denominator hardware direction

For the next iteration, the least chaotic path looks like this:

1. Keep the current lunchbox.
2. Stack `Pi + UPS + WM8960`.
3. Remote-mount only the e-paper.
4. Keep USB RFID for now, but explore a de-cased antenna mount.
5. Re-use the red arcade button as `record / PTT`.
6. Replace the bundled WM8960 speakers with smaller `8 ohm` speakers instead of moving to a larger box immediately.

## Open follow-ups

- Identify the exact USB conference mic model if we want full physical specs in this dossier.
- Identify the exact USB mini soundbar model if we want enclosure dimensions in this dossier.
- Open the Neuftech reader and document the internal antenna geometry.
- Compare actual lunchbox interior dimensions against:
  - Pi+UPS+WM8960 stack height
  - e-paper lid depth
  - candidate speaker footprints
