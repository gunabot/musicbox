#!/usr/bin/env python3
import time
from datetime import datetime

import RPi.GPIO as GPIO
from adafruit_seesaw.seesaw import Seesaw
import board
import busio

# Adafruit 5296 mapping
BUTTON_PINS = [18, 19, 20, 2]      # SWITCH1..4 (active-low with pullups)
LED_PINS = [12, 13, 0, 1]          # LED1..4 outputs

# Rotary mapping (BCM)
ROT_CLK = 5
ROT_DT = 6
ROT_SW = 13


def ts():
    return datetime.now().strftime('%H:%M:%S')


def setup_seesaw(addr=0x3A):
    i2c = busio.I2C(board.SCL, board.SDA)
    ss = Seesaw(i2c, addr=addr)
    for p in BUTTON_PINS:
        ss.pin_mode(p, ss.INPUT_PULLUP)
    for p in LED_PINS:
        ss.pin_mode(p, ss.OUTPUT)
        ss.digital_write(p, False)
    return ss


def read_buttons(ss):
    mask = 0
    for p in BUTTON_PINS:
        mask |= (1 << p)
    bulk = ss.digital_read_bulk(mask)
    # active-low: 0=pressed, 1=released
    return [0 if (bulk & (1 << p)) else 1 for p in BUTTON_PINS]


def led_chase(ss):
    for i, p in enumerate(LED_PINS, start=1):
        ss.digital_write(p, True)
        print(f"[{ts()}] LED{i} ON")
        time.sleep(0.2)
        ss.digital_write(p, False)
    print(f"[{ts()}] LED test done")


def main():
    ss = setup_seesaw()

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(ROT_CLK, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(ROT_DT, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(ROT_SW, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    print("=== musicbox input test ===")
    print("Buttons: SW1..SW4 on seesaw @0x3A")
    print("Rotary: CLK=GPIO5 DT=GPIO6 SW=GPIO13")
    print("Press Ctrl+C to stop")

    led_chase(ss)

    last_btn = read_buttons(ss)
    last_clk = GPIO.input(ROT_CLK)
    last_sw = GPIO.input(ROT_SW)

    print(f"[{ts()}] Ready")

    try:
        while True:
            btn = read_buttons(ss)
            for i, (old, new) in enumerate(zip(last_btn, btn), start=1):
                if old != new:
                    state = "PRESSED" if new else "RELEASED"
                    # new=1 means pressed from mapping above
                    state = "PRESSED" if new == 1 else "RELEASED"
                    print(f"[{ts()}] BUTTON{i} {state}")
            last_btn = btn

            clk = GPIO.input(ROT_CLK)
            if clk != last_clk and clk == 1:
                dt = GPIO.input(ROT_DT)
                direction = "CW" if dt != clk else "CCW"
                print(f"[{ts()}] ROTARY {direction}")
            last_clk = clk

            sw = GPIO.input(ROT_SW)
            if sw != last_sw:
                print(f"[{ts()}] ROTARY_SW {'PRESSED' if sw == 0 else 'RELEASED'}")
            last_sw = sw

            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        for p in LED_PINS:
            try:
                ss.digital_write(p, False)
            except Exception:
                pass
        GPIO.cleanup()
        print("\nDone.")


if __name__ == '__main__':
    main()
