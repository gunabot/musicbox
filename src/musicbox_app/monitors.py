import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

import RPi.GPIO as GPIO
import board
import busio
from adafruit_seesaw.seesaw import Seesaw
from evdev import InputDevice, ecodes, list_devices

try:
    import smbus  # type: ignore
except Exception:  # pragma: no cover - optional runtime dependency
    smbus = None

from .config import (
    BUTTON_PINS,
    LED_PINS,
    MEDIA_DIR,
    RFID_NAME_HINTS,
    ROT_CLK,
    ROT_DT,
    ROT_SW,
    SEESAW_ADDR,
    UPS_ADDR,
)
from .player import PlayerManager
from .store import AppStore

_REG_SHUNTVOLTAGE = 0x01
_REG_BUSVOLTAGE = 0x02
_REG_POWER = 0x03
_REG_CURRENT = 0x04
_REG_CALIBRATION = 0x05
_CALIBRATION_VALUE = 4096


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


def _to_signed(value: int) -> int:
    return value - 65536 if value > 32767 else value


def _read_word(bus: Any, reg: int) -> int:
    data = bus.read_i2c_block_data(UPS_ADDR, reg, 2)
    return (int(data[0]) << 8) + int(data[1])


def _read_ups_metrics() -> Dict[str, Any]:
    default = {
        'ups_connected': False,
        'battery_percent': None,
        'battery_voltage': None,
        'battery_current_ma': None,
        'battery_power_w': None,
        'battery_charging': None,
    }

    if smbus is None:
        return default

    bus = None
    try:
        bus = smbus.SMBus(1)
        bus.write_i2c_block_data(UPS_ADDR, _REG_CALIBRATION, [(_CALIBRATION_VALUE >> 8) & 0xFF, _CALIBRATION_VALUE & 0xFF])

        bus_raw = _read_word(bus, _REG_BUSVOLTAGE)
        shunt_raw = _read_word(bus, _REG_SHUNTVOLTAGE)
        current_raw = _read_word(bus, _REG_CURRENT)
        power_raw = _read_word(bus, _REG_POWER)

        bus_voltage = (bus_raw >> 3) * 0.004
        shunt_voltage_v = _to_signed(shunt_raw) * 0.01 / 1000.0
        load_voltage = bus_voltage + shunt_voltage_v
        current_ma = _to_signed(current_raw) * 0.1
        power_w = _to_signed(power_raw) * 0.002

        percent = ((bus_voltage - 6.0) / 2.4) * 100.0
        percent = max(0.0, min(100.0, percent))

        return {
            'ups_connected': True,
            'battery_percent': round(percent, 1),
            'battery_voltage': round(load_voltage, 3),
            'battery_current_ma': round(current_ma, 1),
            'battery_power_w': round(power_w, 3),
            'battery_charging': current_ma > 20,
        }
    except Exception:
        return default
    finally:
        if bus is not None:
            try:
                bus.close()
            except Exception:
                pass


def _read_cpu_temp_c() -> Optional[float]:
    for path in (
        '/sys/class/thermal/thermal_zone0/temp',
        '/sys/class/hwmon/hwmon0/temp1_input',
    ):
        try:
            raw = Path(path).read_text().strip()
            value = float(raw)
            if value > 200:
                value = value / 1000.0
            return round(value, 1)
        except Exception:
            continue
    return None


def _read_system_metrics() -> Dict[str, Any]:
    metrics: Dict[str, Any] = {
        'cpu_temp_c': None,
        'uptime_s': None,
        'disk_total_bytes': None,
        'disk_free_bytes': None,
        'disk_used_pct': None,
        'load_1': None,
        'load_5': None,
        'load_15': None,
    }

    try:
        metrics['cpu_temp_c'] = _read_cpu_temp_c()
    except Exception:
        pass

    try:
        with open('/proc/uptime', 'r', encoding='utf-8') as handle:
            metrics['uptime_s'] = int(float(handle.read().split()[0]))
    except Exception:
        pass

    try:
        stat = os.statvfs(str(MEDIA_DIR))
        total = int(stat.f_frsize * stat.f_blocks)
        free = int(stat.f_frsize * stat.f_bavail)
        used = max(total - free, 0)
        used_pct = (used / total * 100.0) if total else 0.0
        metrics['disk_total_bytes'] = total
        metrics['disk_free_bytes'] = free
        metrics['disk_used_pct'] = round(used_pct, 1)
    except Exception:
        pass

    try:
        load_1, load_5, load_15 = os.getloadavg()
        metrics['load_1'] = round(load_1, 2)
        metrics['load_5'] = round(load_5, 2)
        metrics['load_15'] = round(load_15, 2)
    except Exception:
        pass

    return metrics


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
        ups = _read_ups_metrics()
        system = _read_system_metrics()
        store.update_health(audio_device=audio, **ups, **system)
        time.sleep(5)


def start_background_monitors(store: AppStore, player: PlayerManager) -> None:
    threading.Thread(target=_input_worker, args=(store, player), daemon=True).start()
    threading.Thread(target=_rfid_worker, args=(store, player), daemon=True).start()
    threading.Thread(target=_player_watchdog_worker, args=(player,), daemon=True).start()
    threading.Thread(target=_health_worker, args=(store,), daemon=True).start()
