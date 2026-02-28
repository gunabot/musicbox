import subprocess
import threading
import time
from typing import Optional

import RPi.GPIO as GPIO
import board
import busio
from adafruit_seesaw.seesaw import Seesaw
from evdev import InputDevice, ecodes, list_devices

from .config import (
    BUTTON_PINS,
    LED_PINS,
    RFID_NAME_HINTS,
    ROT_CLK,
    ROT_DT,
    ROT_SW,
    SEESAW_ADDR,
)
from .player import PlayerManager
from .store import AppStore


def _detect_audio_device() -> Optional[str]:
    try:
        output = subprocess.check_output(['aplay', '-l'], text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return None

    for line in output.splitlines():
        lower = line.lower()
        if 'jieli' in lower or 'usb audio' in lower:
            return line.strip()
    return None


def _find_rfid_device() -> Optional[InputDevice]:
    for path in list_devices():
        dev = InputDevice(path)
        name_lc = dev.name.lower()
        if any(hint.lower() in name_lc for hint in RFID_NAME_HINTS):
            return dev
    return None


def _input_worker(store: AppStore, player: PlayerManager) -> None:
    trans = {
        (0, 1): +1,
        (1, 3): +1,
        (3, 2): +1,
        (2, 0): +1,
        (0, 2): -1,
        (2, 3): -1,
        (3, 1): -1,
        (1, 0): -1,
    }

    while True:
        try:
            i2c = busio.I2C(board.SCL, board.SDA)
            seesaw = Seesaw(i2c, addr=SEESAW_ADDR)
            for pin in BUTTON_PINS:
                seesaw.pin_mode(pin, seesaw.INPUT_PULLUP)
            for pin in LED_PINS:
                seesaw.pin_mode(pin, seesaw.OUTPUT)
                seesaw.digital_write(pin, False)

            GPIO.setmode(GPIO.BCM)
            GPIO.setup(ROT_CLK, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.setup(ROT_DT, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.setup(ROT_SW, GPIO.IN, pull_up_down=GPIO.PUD_UP)

            store.update_health(seesaw=True)
            store.add_event('input monitor started')

            def read_buttons() -> list[int]:
                mask = 0
                for pin in BUTTON_PINS:
                    mask |= 1 << pin
                bulk = seesaw.digital_read_bulk(mask)
                return [0 if (bulk & (1 << pin)) else 1 for pin in BUTTON_PINS]

            def rot_state() -> int:
                return (GPIO.input(ROT_CLK) << 1) | GPIO.input(ROT_DT)

            def rotary_led_sweep(direction: str, button_state: list[int]) -> None:
                step_ms = store.get_setting('rotary_led_step_ms', 25)
                step_s = max(0.005, min(0.25, step_ms / 1000.0))
                order = LED_PINS if direction == 'CW' else list(reversed(LED_PINS))
                for led_pin in order:
                    seesaw.digital_write(led_pin, True)
                    time.sleep(step_s)
                    seesaw.digital_write(led_pin, False)
                for idx, led_pin in enumerate(LED_PINS):
                    seesaw.digital_write(led_pin, button_state[idx] == 1)

            last_buttons = read_buttons()
            last_sw = GPIO.input(ROT_SW)
            last_state = rot_state()
            accum = 0

            while True:
                buttons = read_buttons()
                for idx, (old, new) in enumerate(zip(last_buttons, buttons), start=1):
                    if old == new:
                        continue

                    pressed = new == 1
                    store.add_event(f"BUTTON{idx} {'PRESSED' if pressed else 'RELEASED'}")
                    seesaw.digital_write(LED_PINS[idx - 1], pressed)

                    if pressed:
                        if idx == 1:
                            player.play_pause()
                        elif idx == 2:
                            player.stop()
                            store.add_event('STOP')
                        elif idx == 3:
                            player.prev()
                        elif idx == 4:
                            player.next()

                last_buttons = buttons

                state = rot_state()
                if state != last_state:
                    step = trans.get((last_state, state), 0)
                    accum += step
                    last_state = state

                    if accum >= 4:
                        store.set_rotary(direction='CCW', pos_delta=-1)
                        store.add_event('ROTARY CCW')
                        player.add_volume(-3)
                        rotary_led_sweep('CCW', buttons)
                        accum = 0
                    elif accum <= -4:
                        store.set_rotary(direction='CW', pos_delta=1)
                        store.add_event('ROTARY CW')
                        player.add_volume(+3)
                        rotary_led_sweep('CW', buttons)
                        accum = 0

                sw = GPIO.input(ROT_SW)
                if sw != last_sw:
                    store.add_event(f"ROTARY_SW {'PRESSED' if sw == 0 else 'RELEASED'}")
                    last_sw = sw

                store.set_buttons(buttons)
                store.set_rotary(sw=1 if sw == 0 else 0)
                time.sleep(0.003)

        except Exception as exc:
            store.update_health(seesaw=False)
            store.add_event(f'INPUT_ERR {exc}', level='error')
            try:
                GPIO.cleanup()
            except Exception:
                pass
            time.sleep(2)


def _rfid_worker(store: AppStore, player: PlayerManager) -> None:
    keypad_codes = {getattr(ecodes, f'KEY_{i}'): str(i) for i in range(10)}
    keypad_codes.update({
        ecodes.KEY_KP0: '0',
        ecodes.KEY_KP1: '1',
        ecodes.KEY_KP2: '2',
        ecodes.KEY_KP3: '3',
        ecodes.KEY_KP4: '4',
        ecodes.KEY_KP5: '5',
        ecodes.KEY_KP6: '6',
        ecodes.KEY_KP7: '7',
        ecodes.KEY_KP8: '8',
        ecodes.KEY_KP9: '9',
    })

    rfid_missing_logged = False

    while True:
        device = _find_rfid_device()
        if device is None:
            store.update_health(rfid_device=None)
            if not rfid_missing_logged:
                store.add_event('RFID reader not found, retrying...')
                rfid_missing_logged = True
            time.sleep(3)
            continue

        rfid_missing_logged = False
        store.update_health(rfid_device=device.name)
        store.add_event(f'RFID reader attached: {device.path}')
        buffer = ''

        try:
            for event in device.read_loop():
                if event.type != ecodes.EV_KEY or event.value != 1:
                    continue

                if event.code == ecodes.KEY_ENTER:
                    if not buffer:
                        continue

                    card = buffer
                    buffer = ''
                    store.set_last_card(card)
                    store.add_event(f'CARD {card}')

                    mappings = store.load_mappings()
                    mapped_target = mappings.get(card)
                    if not mapped_target:
                        store.add_event(f'CARD_UNMAPPED {card}')
                        continue

                    try:
                        player.play(mapped_target)
                        store.add_event(f'CARD_MAPPED {card} -> {mapped_target}')
                    except Exception as exc:
                        store.add_event(f'CARD_MAPPED_ERR {card}: {exc}', level='error')
                    continue

                char = keypad_codes.get(event.code)
                if char is not None:
                    buffer += char
        except Exception:
            store.update_health(rfid_device=None)
            store.add_event('RFID device disconnected', level='warning')
            time.sleep(1)


def _player_watchdog_worker(player: PlayerManager) -> None:
    while True:
        player.watchdog_tick()
        time.sleep(0.5)


def _health_worker(store: AppStore) -> None:
    while True:
        audio = _detect_audio_device()
        store.update_health(audio_device=audio)
        time.sleep(5)


def start_background_monitors(store: AppStore, player: PlayerManager) -> None:
    threading.Thread(target=_input_worker, args=(store, player), daemon=True).start()
    threading.Thread(target=_rfid_worker, args=(store, player), daemon=True).start()
    threading.Thread(target=_player_watchdog_worker, args=(player,), daemon=True).start()
    threading.Thread(target=_health_worker, args=(store,), daemon=True).start()
