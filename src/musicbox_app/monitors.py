import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import board
import busio
from adafruit_seesaw.seesaw import Seesaw
from evdev import InputDevice, ecodes, list_devices

try:
    import gpiod
    from gpiod.line import Bias as GpioBias
    from gpiod.line import Direction as GpioDirection
    from gpiod.line import Edge as GpioEdge
    from gpiod.line import Value as GpioValue
except Exception:  # pragma: no cover - optional runtime dependency
    gpiod = None
    GpioBias = None
    GpioDirection = None
    GpioEdge = None
    GpioValue = None

try:
    import smbus  # type: ignore
except Exception:  # pragma: no cover - optional runtime dependency
    smbus = None

from .config import (
    AUDIO_DEVICE,
    BATTERY_FULL_PERCENT,
    BATTERY_STATUS_INTERVAL_S,
    BATTERY_STATUS_PULSE_S,
    BUTTON_PINS,
    EINK_ENABLED,
    EINK_POLL_INTERVAL_S,
    HEALTH_AUDIO_SCAN_INTERVAL_S,
    HEALTH_METRICS_INTERVAL_S,
    INPUT_LOOP_INTERVAL_S,
    LED_PINS,
    LOW_BATTERY_PERCENT,
    MEDIA_DIR,
    PLAYER_BUTTON_HOLD_SECONDS,
    RECORD_BUTTON_HOLD_SECONDS,
    RECORD_LED_BLINK_S,
    RFID_NAME_HINTS,
    ROT_CLK,
    ROT_DT,
    ROT_SW,
    SEESAW_ADDR,
    STARTUP_LED_FLASH_COUNT,
    STARTUP_LED_FLASH_OFF_S,
    STARTUP_LED_FLASH_ON_S,
    STARTUP_LED_READY_DELAY_S,
    STARTUP_LED_SWEEP_STEP_S,
    STATUS_LED_GREEN_INDEX,
    STATUS_LED_RED_INDEX,
    TWINPEAKS_OUTPUT_HINT,
    UPS_ADDR,
)
from .eink import eink_worker
from .player import PlayerManager
from .recorder import RecorderManager
from .store import AppStore

_REG_SHUNTVOLTAGE = 0x01
_REG_BUSVOLTAGE = 0x02
_REG_POWER = 0x03
_REG_CURRENT = 0x04
_REG_CALIBRATION = 0x05
_CALIBRATION_VALUE = 4096
# Number of detent events we observe for one 360-degree encoder turn.
_ROTARY_STEPS_PER_TURN = 24.0


def _detect_audio_device() -> Optional[str]:
    cards = _list_alsa_cards()
    for target in _configured_audio_targets():
        target_lower = target.lower()
        for _, name, line in cards:
            if target_lower == name.lower() or target_lower in line.lower():
                return line

    for _, _, line in cards:
        lower = line.lower()
        if 'wm8960' in lower or 'jieli' in lower or 'usb audio' in lower:
            return line

    return cards[0][2] if cards else None


def _list_alsa_cards() -> list[tuple[str, str, str]]:
    try:
        output = subprocess.check_output(['aplay', '-l'], text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return []

    cards: list[tuple[str, str, str]] = []
    pattern = re.compile(r'^card\s+(\d+):\s*([^\s\[]+)')
    for raw_line in output.splitlines():
        line = raw_line.strip()
        match = pattern.search(line)
        if not match:
            continue
        cards.append((match.group(1), match.group(2).strip(), line))
    return cards


def _configured_audio_targets() -> list[str]:
    values: list[str] = []
    for raw in [
        os.environ.get('MUSICBOX_AUDIO_DEVICE', '').strip(),
        str(TWINPEAKS_OUTPUT_HINT or '').strip(),
        str(AUDIO_DEVICE or '').strip(),
    ]:
        if raw.lower().startswith('alsa/'):
            raw = raw.split('/', 1)[1].strip()
        if raw and raw not in values:
            values.append(raw)
    return values


def _audio_card_index() -> str:
    cards = _list_alsa_cards()
    for target in _configured_audio_targets():
        match = re.search(r'(?i)(?:plug)?hw:(\d+)(?:,|$)', target)
        if match:
            return match.group(1)

        target_lower = target.lower()
        if target_lower:
            for index, name, line in cards:
                if target_lower == name.lower() or target_lower in line.lower():
                    return index

    for index, _, line in cards:
        if 'wm8960' in line.lower():
            return index

    if cards:
        return cards[0][0]
    return '1'


def _apply_alsa_pcm_percent(percent: int) -> tuple[bool, str]:
    card = _audio_card_index()
    controls: list[str] = ['PCM']
    errors: list[str] = []

    def apply_control(name: str) -> bool:
        try:
            result = subprocess.run(
                ['amixer', '-c', card, 'sset', name, f'{int(percent)}%'],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
        except Exception as exc:
            errors.append(f'{name}: {exc}')
            return False
        if result.returncode == 0:
            return True
        detail = (result.stderr or '').strip() or f'exit {result.returncode}'
        errors.append(f'{name}: {detail}')
        return False

    if apply_control('PCM'):
        return True, ''

    controls = ['Speaker', 'Playback']
    applied = False
    for control in controls:
        applied = apply_control(control) or applied

    if applied:
        return True, ''
    return False, '; '.join(errors) if errors else 'no supported ALSA mixer control found'


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


def _rotary_volume_delta(store: AppStore) -> float:
    per_turn = store.get_setting('rotary_volume_per_turn', 100)
    per_turn = max(20, min(300, per_turn))
    return max(0.5, min(20.0, float(per_turn) / _ROTARY_STEPS_PER_TURN))


def _input_worker(store: AppStore, player: PlayerManager, recorder: RecorderManager) -> None:
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
        led_stop = threading.Event()
        rotary_request: object | None = None
        try:
            i2c = busio.I2C(board.SCL, board.SDA)
            seesaw = Seesaw(i2c, addr=SEESAW_ADDR)
            seesaw_lock = threading.Lock()
            with seesaw_lock:
                for pin in BUTTON_PINS:
                    seesaw.pin_mode(pin, seesaw.INPUT_PULLUP)
                for pin in LED_PINS:
                    seesaw.pin_mode(pin, seesaw.OUTPUT)
                    seesaw.digital_write(pin, False)

            store.update_health(seesaw=True)
            store.add_event('input monitor started')

            button_mask = 0
            for pin in BUTTON_PINS:
                button_mask |= 1 << pin

            def read_buttons() -> list[int]:
                with seesaw_lock:
                    bulk = seesaw.digital_read_bulk(button_mask)
                return [0 if (bulk & (1 << pin)) else 1 for pin in BUTTON_PINS]

            def line_value_to_bit(value: object) -> int:
                if GpioValue is not None and value == GpioValue.ACTIVE:
                    return 1
                if GpioValue is not None and value == GpioValue.INACTIVE:
                    return 0
                try:
                    return 1 if int(value) else 0
                except Exception:
                    return 0

            if gpiod is None or GpioDirection is None or GpioEdge is None or GpioBias is None:
                raise RuntimeError('libgpiod python bindings unavailable')

            rotary_request = gpiod.request_lines(
                '/dev/gpiochip0',
                consumer='musicbox-gpio',
                config={
                    ROT_CLK: gpiod.LineSettings(
                        direction=GpioDirection.INPUT,
                        edge_detection=GpioEdge.BOTH,
                        bias=GpioBias.PULL_UP,
                    ),
                    ROT_DT: gpiod.LineSettings(
                        direction=GpioDirection.INPUT,
                        edge_detection=GpioEdge.BOTH,
                        bias=GpioBias.PULL_UP,
                    ),
                    ROT_SW: gpiod.LineSettings(
                        direction=GpioDirection.INPUT,
                        edge_detection=GpioEdge.BOTH,
                        bias=GpioBias.PULL_UP,
                    ),
                },
            )
            start_values = rotary_request.get_values([ROT_CLK, ROT_DT, ROT_SW])
            rotary_state_cache = (line_value_to_bit(start_values[0]) << 1) | line_value_to_bit(start_values[1])
            sw_state_cache = line_value_to_bit(start_values[2])
            store.add_event('GPIO_BACKEND libgpiod')

            led_cond = threading.Condition(threading.RLock())
            led_state: Dict[str, object] = {
                'direction': None,
                'button_state': [0 for _ in LED_PINS],
                'seq': 0,
                'sweeps_pending': 0,
                'boundary': None,
                'boundary_until': 0.0,
                'override_active': False,
                'recording_active': False,
            }
            buttons_state_lock = threading.Lock()
            buttons_state = [0 for _ in LED_PINS]

            def write_led_level_unlocked(pin: int, level: int) -> None:
                seesaw.digital_write(pin, bool(level))

            def set_led_level(pin: int, level: int) -> None:
                with seesaw_lock:
                    write_led_level_unlocked(pin, level)

            def apply_led_levels(levels: Dict[int, int]) -> None:
                with seesaw_lock:
                    for led_pin in LED_PINS:
                        write_led_level_unlocked(led_pin, levels.get(led_pin, 0))

            def apply_button_leds(button_state: list[int]) -> None:
                apply_led_levels(
                    {
                        led_pin: 65535 if idx < len(button_state) and button_state[idx] == 1 else 0
                        for idx, led_pin in enumerate(LED_PINS)
                    }
                )

            def apply_boundary_leds(mode: str) -> None:
                level = 65535 if mode == 'max' else 0
                apply_led_levels({led_pin: level for led_pin in LED_PINS})

            def apply_led_pattern(active_leds: set[int], *, level: int = 65535) -> None:
                apply_led_levels({led_pin: level if led_pin in active_leds else 0 for led_pin in LED_PINS})

            def apply_idle_leds(button_state: list[int], *, force: bool = False) -> None:
                with led_cond:
                    if bool(led_state.get('override_active')) and not force:
                        return
                    boundary = str(led_state.get('boundary') or '')
                    boundary_until = float(led_state.get('boundary_until') or 0.0)
                    if boundary in {'max', 'min'} and time.monotonic() >= boundary_until:
                        led_state['boundary'] = None
                        led_state['boundary_until'] = 0.0
                        boundary = ''
                if boundary in {'max', 'min'}:
                    apply_boundary_leds(boundary)
                    return
                apply_button_leds(button_state)

            def get_buttons_state() -> list[int]:
                with buttons_state_lock:
                    return list(buttons_state)

            def set_buttons_state(new_state: list[int]) -> None:
                with buttons_state_lock:
                    buttons_state[:] = list(new_state)

            def begin_led_override() -> None:
                with led_cond:
                    led_state['seq'] = int(led_state.get('seq', 0)) + 1
                    led_state['direction'] = None
                    led_state['sweeps_pending'] = 0
                    led_state['override_active'] = True
                    led_cond.notify_all()

            def end_led_override() -> None:
                with led_cond:
                    led_state['override_active'] = False
                    led_state['seq'] = int(led_state.get('seq', 0)) + 1
                    led_cond.notify_all()
                apply_led_levels({})
                wait_led_step(0.03)
                apply_idle_leds(get_buttons_state(), force=True)

            def wait_led_step(duration_s: float) -> bool:
                remaining = max(0.0, float(duration_s))
                while remaining > 0.0 and not led_stop.is_set():
                    chunk = min(0.02, remaining)
                    time.sleep(chunk)
                    remaining -= chunk
                return not led_stop.is_set()

            def pulse_leds(led_pins: list[int], *, on_s: float, off_s: float = 0.0, repeat: int = 1) -> bool:
                active_leds = set(led_pins)
                for _ in range(max(1, int(repeat))):
                    apply_led_pattern(active_leds)
                    if not wait_led_step(on_s):
                        return False
                    apply_led_levels({})
                    if off_s > 0.0 and not wait_led_step(off_s):
                        return False
                return not led_stop.is_set()

            def pulse_all_leds(*, on_s: float, off_s: float = 0.0, repeat: int = 1) -> bool:
                return pulse_leds(list(LED_PINS), on_s=on_s, off_s=off_s, repeat=repeat)

            def chase_leds(order: list[int], *, step_s: float) -> bool:
                for led_pin in order:
                    if not pulse_leds([led_pin], on_s=step_s):
                        return False
                return not led_stop.is_set()

            def run_status_animation(animation: Callable[[], bool]) -> bool:
                with led_cond:
                    if bool(led_state.get('recording_active')):
                        return False
                begin_led_override()
                try:
                    return bool(animation())
                finally:
                    end_led_override()

            def set_recording_led(active: bool) -> None:
                with led_cond:
                    if bool(led_state.get('recording_active')) == bool(active):
                        return
                    led_state['recording_active'] = bool(active)
                    led_state['seq'] = int(led_state.get('seq', 0)) + 1
                    led_cond.notify_all()
                if not active:
                    apply_led_levels({})
                    wait_led_step(0.03)
                    apply_idle_leds(get_buttons_state(), force=True)

            def rotary_led_sweep(direction: str, button_state: list[int], state_seq: int) -> None:
                step_ms = store.get_setting('rotary_led_step_ms', 25)
                step_s = max(0.005, min(0.25, step_ms / 1000.0))
                order = LED_PINS if direction == 'CW' else list(reversed(LED_PINS))

                def wait_step_or_interrupt(duration_s: float) -> bool:
                    remaining = max(0.0, float(duration_s))
                    while remaining > 0.0 and not led_stop.is_set():
                        chunk = min(0.01, remaining)
                        time.sleep(chunk)
                        remaining -= chunk
                        with led_cond:
                            if int(led_state.get('seq', 0)) != state_seq:
                                return False
                            if str(led_state.get('direction', '')) != direction:
                                return False
                    return not led_stop.is_set()

                for led_pin in order:
                    if led_stop.is_set():
                        return
                    with led_cond:
                        if int(led_state.get('seq', 0)) != state_seq:
                            return
                        if str(led_state.get('direction', '')) != direction:
                            return
                    with seesaw_lock:
                        write_led_level_unlocked(led_pin, 65535)
                    if not wait_step_or_interrupt(step_s):
                        with seesaw_lock:
                            write_led_level_unlocked(led_pin, 0)
                        return
                    with seesaw_lock:
                        write_led_level_unlocked(led_pin, 0)
                apply_button_leds(button_state)

            def queue_led_sweep(direction: str, button_state: list[int]) -> None:
                with led_cond:
                    next_direction = str(direction)
                    previous_direction = str(led_state.get('direction') or '')
                    led_state['direction'] = next_direction
                    led_state['button_state'] = list(button_state)
                    pending = int(led_state.get('sweeps_pending', 0))
                    max_pending = max(0, min(12, store.get_setting('rotary_led_max_pending', 0)))
                    if previous_direction and previous_direction == next_direction:
                        led_state['sweeps_pending'] = min(max_pending, pending + 1)
                    else:
                        # Direction change should interrupt immediately.
                        led_state['seq'] = int(led_state.get('seq', 0)) + 1
                        led_state['sweeps_pending'] = 1
                    led_cond.notify()

            def set_led_volume_boundary(mode: str) -> None:
                boundary = 'max' if mode == 'max' else 'min'
                step_ms = store.get_setting('rotary_led_step_ms', 25)
                hold_ms = max(120, min(800, int(step_ms) * 6))
                hold_until = time.monotonic() + (hold_ms / 1000.0)
                with led_cond:
                    current_boundary = str(led_state.get('boundary') or '')
                    had_sweeps = int(led_state.get('sweeps_pending', 0)) > 0 or bool(led_state.get('direction'))
                    led_state['boundary'] = boundary
                    led_state['boundary_until'] = hold_until
                    if had_sweeps or current_boundary != boundary:
                        led_state['direction'] = None
                        led_state['sweeps_pending'] = 0
                        led_state['seq'] = int(led_state.get('seq', 0)) + 1
                    led_cond.notify()

            def clear_led_volume_boundary() -> None:
                with led_cond:
                    if led_state.get('boundary') is None:
                        return
                    led_state['boundary'] = None
                    led_state['boundary_until'] = 0.0
                    led_state['seq'] = int(led_state.get('seq', 0)) + 1
                    led_cond.notify()

            def after_volume_step(direction: str, delta: float, pos_delta: int, button_state: list[int]) -> None:
                store.set_rotary(direction=direction, pos_delta=pos_delta)
                store.add_event(f'ROTARY {direction}')
                player.add_volume(delta)

                volume_value: float | None = None
                try:
                    volume_value = float(store.get_player_value('volume'))
                except Exception:
                    volume_value = None

                volume_max = max(100, min(200, store.get_setting('player_volume_max', 130)))
                if volume_value is not None and volume_value <= 0.0:
                    set_led_volume_boundary('min')
                    return
                if volume_value is not None and volume_value >= float(volume_max):
                    set_led_volume_boundary('max')
                    return

                clear_led_volume_boundary()
                queue_led_sweep(direction, button_state)

            def led_worker() -> None:
                record_led = LED_PINS[max(0, min(len(LED_PINS) - 1, STATUS_LED_RED_INDEX - 1))]
                while not led_stop.is_set():
                    direction = ''
                    button_state = [0 for _ in LED_PINS]
                    state_seq = 0
                    with led_cond:
                        if bool(led_state.get('recording_active')):
                            blink_s = max(0.08, float(RECORD_LED_BLINK_S))
                            phase_on = int(time.monotonic() / blink_s) % 2 == 0
                            apply_led_pattern({record_led} if phase_on else set())
                            led_cond.wait(timeout=min(0.05, blink_s / 2.0))
                            continue
                        if bool(led_state.get('override_active')):
                            led_cond.wait(timeout=0.05)
                            continue
                        button_state = list(led_state.get('button_state', [0 for _ in LED_PINS]))
                        pending = int(led_state.get('sweeps_pending', 0))
                        if pending <= 0:
                            led_state['direction'] = None
                            apply_idle_leds(button_state)
                            led_cond.wait(timeout=0.05)
                            continue
                        led_state['sweeps_pending'] = max(0, pending - 1)
                        direction = str(led_state.get('direction') or '')
                        button_state = list(led_state.get('button_state', [0 for _ in LED_PINS]))
                        state_seq = int(led_state.get('seq', 0))
                    if not direction:
                        apply_idle_leds(button_state)
                        continue
                    try:
                        rotary_led_sweep(direction, button_state, state_seq)
                    except Exception:
                        pass

            threading.Thread(target=led_worker, daemon=True).start()

            last_buttons = read_buttons()
            set_buttons_state(last_buttons)
            last_sw = sw_state_cache
            last_state = rotary_state_cache
            store.set_buttons(last_buttons)
            store.set_rotary(sw=1 if last_sw == 0 else 0)
            reported_buttons = list(last_buttons)
            reported_rotary_sw = 1 if last_sw == 0 else 0
            accum = 0
            button_pressed_at: Dict[int, float] = {}
            transport_button_idx: int | None = None

            def maybe_begin_transport(idx: int, now_mono: float) -> None:
                nonlocal transport_button_idx
                if idx not in {3, 4} or transport_button_idx is not None:
                    return
                pressed_at = button_pressed_at.get(idx)
                if pressed_at is None or now_mono - pressed_at < PLAYER_BUTTON_HOLD_SECONDS:
                    return
                if player.begin_transport(reverse=(idx == 3)):
                    transport_button_idx = idx

            def release_transport(idx: int) -> bool:
                nonlocal transport_button_idx
                if transport_button_idx != idx:
                    button_pressed_at.pop(idx, None)
                    return False
                player.end_transport()
                transport_button_idx = None
                button_pressed_at.pop(idx, None)
                return True

            def maybe_begin_record(now_mono: float) -> None:
                if recorder.is_recording():
                    return
                pressed_at = button_pressed_at.get(2)
                if pressed_at is None or now_mono - pressed_at < RECORD_BUTTON_HOLD_SECONDS:
                    return
                try:
                    if recorder.start():
                        set_recording_led(True)
                except Exception as exc:
                    button_pressed_at.pop(2, None)
                    store.add_event(f'RECORD_ERR {exc}', level='error')

            def release_record() -> bool:
                if not recorder.is_recording():
                    button_pressed_at.pop(2, None)
                    return False
                set_recording_led(False)
                try:
                    relpath = recorder.stop()
                except Exception as exc:
                    store.add_event(f'RECORD_ERR {exc}', level='error')
                    button_pressed_at.pop(2, None)
                    return True
                button_pressed_at.pop(2, None)
                if not relpath:
                    return True
                try:
                    player.play(relpath)
                    store.add_event(f'RECORD_PREVIEW {relpath}')
                except Exception as exc:
                    store.add_event(f'RECORD_PREVIEW_ERR {relpath}: {exc}', level='error')
                return True

            def status_led_worker() -> None:
                try:
                    if STARTUP_LED_READY_DELAY_S > 0.0:
                        wait_led_step(STARTUP_LED_READY_DELAY_S)

                    def startup_animation() -> bool:
                        if not pulse_all_leds(
                            on_s=STARTUP_LED_FLASH_ON_S,
                            off_s=STARTUP_LED_FLASH_OFF_S,
                            repeat=STARTUP_LED_FLASH_COUNT,
                        ):
                            return False
                        if not chase_leds(list(LED_PINS), step_s=STARTUP_LED_SWEEP_STEP_S):
                            return False
                        return chase_leds(list(reversed(LED_PINS)), step_s=STARTUP_LED_SWEEP_STEP_S)

                    if run_status_animation(startup_animation):
                        store.add_event('LED_READY_ANIMATION')
                except Exception as exc:
                    store.add_event(f'LED_READY_ANIMATION_ERR {exc}', level='warning')

                next_low_alert_monotonic = time.monotonic() + BATTERY_STATUS_INTERVAL_S
                next_full_alert_monotonic = time.monotonic() + BATTERY_STATUS_INTERVAL_S
                while not led_stop.is_set():
                    low_battery = False
                    charge_complete = False
                    try:
                        pct = store.get_health_value('battery_percent')
                        charging = bool(store.get_health_value('battery_charging'))
                        current_ma = store.get_health_value('battery_current_ma')
                        pct_value = float(pct) if pct is not None else None
                        current_value = float(current_ma) if current_ma is not None else None
                        low_battery = pct_value is not None and pct_value <= LOW_BATTERY_PERCENT
                        charge_complete = (
                            pct_value is not None
                            and pct_value >= BATTERY_FULL_PERCENT
                            and not charging
                            and current_value is not None
                            and current_value >= 0.0
                        )
                    except Exception:
                        low_battery = False
                        charge_complete = False

                    now = time.monotonic()
                    if low_battery:
                        if now >= next_low_alert_monotonic:
                            try:
                                red_led = LED_PINS[max(0, min(len(LED_PINS) - 1, STATUS_LED_RED_INDEX - 1))]

                                def low_battery_animation() -> bool:
                                    return pulse_leds([red_led], on_s=BATTERY_STATUS_PULSE_S)

                                if run_status_animation(low_battery_animation):
                                    store.add_event('LED_BATTERY_LOW_PULSE')
                            except Exception as exc:
                                store.add_event(f'LED_BATTERY_LOW_ERR {exc}', level='warning')
                            next_low_alert_monotonic = now + BATTERY_STATUS_INTERVAL_S
                        next_full_alert_monotonic = 0.0
                    elif charge_complete:
                        if now >= next_full_alert_monotonic:
                            try:
                                green_led = LED_PINS[max(0, min(len(LED_PINS) - 1, STATUS_LED_GREEN_INDEX - 1))]

                                def full_battery_animation() -> bool:
                                    return pulse_leds([green_led], on_s=BATTERY_STATUS_PULSE_S)

                                if run_status_animation(full_battery_animation):
                                    store.add_event('LED_BATTERY_FULL_PULSE')
                            except Exception as exc:
                                store.add_event(f'LED_BATTERY_FULL_ERR {exc}', level='warning')
                            next_full_alert_monotonic = now + BATTERY_STATUS_INTERVAL_S
                        next_low_alert_monotonic = 0.0
                    else:
                        next_low_alert_monotonic = 0.0
                        next_full_alert_monotonic = 0.0

                    for _ in range(4):
                        if led_stop.is_set():
                            break
                        time.sleep(0.5)

            threading.Thread(target=status_led_worker, daemon=True).start()

            while True:
                buttons = read_buttons()
                now_mono = time.monotonic()
                for idx, (old, new) in enumerate(zip(last_buttons, buttons), start=1):
                    if old == new:
                        continue

                    pressed = new == 1
                    store.add_event(f"BUTTON{idx} {'PRESSED' if pressed else 'RELEASED'}")
                    set_led_level(LED_PINS[idx - 1], 65535 if pressed else 0)

                    if pressed:
                        if idx == 1:
                            player.play_pause()
                        elif idx == 2:
                            button_pressed_at[idx] = now_mono
                            player.stop()
                            store.add_event('STOP')
                        elif idx in {3, 4}:
                            button_pressed_at[idx] = now_mono
                    elif idx == 2:
                        release_record()
                    elif idx in {3, 4}:
                        was_transport = release_transport(idx)
                        if not was_transport:
                            if idx == 3:
                                player.prev()
                            else:
                                player.next()

                last_buttons = buttons
                set_buttons_state(last_buttons)
                maybe_begin_record(now_mono)
                maybe_begin_transport(3, now_mono)
                maybe_begin_transport(4, now_mono)

                try:
                    has_edges = rotary_request.wait_edge_events(timeout=INPUT_LOOP_INTERVAL_S)
                    edge_events = rotary_request.read_edge_events(max_events=256) if has_edges else []
                except Exception as exc:
                    raise RuntimeError(f'libgpiod edge read failed: {exc}') from exc

                for event in edge_events:
                    bit = 1 if event.event_type == gpiod.EdgeEvent.Type.RISING_EDGE else 0
                    if event.line_offset == ROT_CLK:
                        rotary_state_cache = (bit << 1) | (rotary_state_cache & 0x1)
                        state = rotary_state_cache
                        if state == last_state:
                            continue
                        step = trans.get((last_state, state), 0)
                        if step:
                            accum += step
                        last_state = state

                        while accum >= 4:
                            volume_delta = _rotary_volume_delta(store)
                            after_volume_step(direction='CCW', delta=-volume_delta, pos_delta=-1, button_state=buttons)
                            accum -= 4

                        while accum <= -4:
                            volume_delta = _rotary_volume_delta(store)
                            after_volume_step(direction='CW', delta=+volume_delta, pos_delta=1, button_state=buttons)
                            accum += 4
                    elif event.line_offset == ROT_DT:
                        rotary_state_cache = (rotary_state_cache & 0x2) | bit
                        state = rotary_state_cache
                        if state == last_state:
                            continue
                        step = trans.get((last_state, state), 0)
                        if step:
                            accum += step
                        last_state = state

                        while accum >= 4:
                            volume_delta = _rotary_volume_delta(store)
                            after_volume_step(direction='CCW', delta=-volume_delta, pos_delta=-1, button_state=buttons)
                            accum -= 4

                        while accum <= -4:
                            volume_delta = _rotary_volume_delta(store)
                            after_volume_step(direction='CW', delta=+volume_delta, pos_delta=1, button_state=buttons)
                            accum += 4
                    elif event.line_offset == ROT_SW:
                        sw_state_cache = bit
                        if sw_state_cache != last_sw:
                            store.add_event(f"ROTARY_SW {'PRESSED' if sw_state_cache == 0 else 'RELEASED'}")
                            last_sw = sw_state_cache

                if buttons != reported_buttons:
                    store.set_buttons(buttons)
                    reported_buttons = list(buttons)

                rotary_sw_pressed = 1 if last_sw == 0 else 0
                if rotary_sw_pressed != reported_rotary_sw:
                    store.set_rotary(sw=rotary_sw_pressed)
                    reported_rotary_sw = rotary_sw_pressed

        except Exception as exc:
            led_stop.set()
            try:
                set_recording_led(False)
            except Exception:
                pass
            try:
                recorder.cancel()
            except Exception:
                pass
            store.update_health(seesaw=False)
            store.add_event(f'INPUT_ERR {exc}', level='error')
            try:
                if rotary_request is not None:
                    rotary_request.release()
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

                    mappings = store.load_mappings(use_cache=True)
                    mapped = mappings.get(card)
                    if not mapped:
                        store.add_event(f'CARD_UNMAPPED {card}')
                        continue

                    try:
                        mapped_type = str(mapped.get('type', 'local')).strip().lower() or 'local'
                        mapped_target = str(mapped.get('target', '')).strip()
                        if not mapped_target:
                            store.add_event(f'CARD_MAPPED_ERR {card}: empty target', level='error')
                            continue

                        if mapped_type == 'spotify':
                            cached = player.play_spotify(mapped_target)
                            store.add_event(f'CARD_MAPPED {card} -> spotify:{mapped_target} ({cached})')
                        else:
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
        time.sleep(0.25)


def _health_worker(store: AppStore) -> None:
    last_applied_pcm: int | None = None
    last_pcm_error: str | None = None
    last_audio_scan_monotonic = 0.0
    audio_device: str | None = None

    while True:
        target_pcm = store.get_setting('alsa_pcm_percent', 100)
        target_pcm = max(0, min(100, int(target_pcm)))
        if target_pcm != last_applied_pcm:
            ok, err = _apply_alsa_pcm_percent(target_pcm)
            if ok:
                store.add_event(f'ALSA_PCM {target_pcm}%')
                last_applied_pcm = target_pcm
                last_pcm_error = None
            elif err and err != last_pcm_error:
                store.add_event(f'ALSA_PCM_ERR {err}', level='warning')
                last_pcm_error = err

        now_mono = time.monotonic()
        if audio_device is None or now_mono - last_audio_scan_monotonic >= HEALTH_AUDIO_SCAN_INTERVAL_S:
            audio_device = _detect_audio_device()
            last_audio_scan_monotonic = now_mono
        ups = _read_ups_metrics()
        system = _read_system_metrics()
        store.update_health(audio_device=audio_device, **ups, **system)
        time.sleep(HEALTH_METRICS_INTERVAL_S)


def start_background_monitors(store: AppStore, player: PlayerManager, recorder: RecorderManager) -> None:
    threading.Thread(target=_input_worker, args=(store, player, recorder), daemon=True).start()
    threading.Thread(target=_rfid_worker, args=(store, player), daemon=True).start()
    threading.Thread(target=_player_watchdog_worker, args=(player,), daemon=True).start()
    threading.Thread(target=_health_worker, args=(store,), daemon=True).start()
    if EINK_ENABLED:
        threading.Thread(target=eink_worker, args=(store,), daemon=True).start()
