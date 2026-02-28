#!/usr/bin/env python3
import os
import threading
import time
import subprocess
from pathlib import Path
from collections import deque
from datetime import datetime

from flask import Flask, jsonify, request, Response
import RPi.GPIO as GPIO
from adafruit_seesaw.seesaw import Seesaw
import board
import busio
from evdev import InputDevice, ecodes, list_devices

MEDIA_DIR = Path('/home/musicbox/media')
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

BUTTON_PINS = [18, 19, 20, 2]
ROT_CLK = 5
ROT_DT = 6
ROT_SW = 13

state = {
    'buttons': [0, 0, 0, 0],
    'rotary_sw': 0,
    'rotary_last': '-',
    'rotary_pos': 0,
    'events': deque(maxlen=120),
    'last_card': None,
    'player': {'status': 'stopped', 'file': None},
}
lock = threading.Lock()
player_proc = None

app = Flask(__name__)


def ts():
    return datetime.now().strftime('%H:%M:%S')


def add_event(msg):
    with lock:
        state['events'].appendleft(f"[{ts()}] {msg}")


def monitor_inputs():
    i2c = busio.I2C(board.SCL, board.SDA)
    ss = Seesaw(i2c, addr=0x3A)
    for p in BUTTON_PINS:
        ss.pin_mode(p, ss.INPUT_PULLUP)

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(ROT_CLK, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(ROT_DT, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(ROT_SW, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    def read_buttons():
        mask = 0
        for p in BUTTON_PINS:
            mask |= (1 << p)
        bulk = ss.digital_read_bulk(mask)
        return [0 if (bulk & (1 << p)) else 1 for p in BUTTON_PINS]

    def rot_state():
        return (GPIO.input(ROT_CLK) << 1) | GPIO.input(ROT_DT)

    trans = {
        (0, 1): +1, (1, 3): +1, (3, 2): +1, (2, 0): +1,
        (0, 2): -1, (2, 3): -1, (3, 1): -1, (1, 0): -1,
    }

    last_btn = read_buttons()
    last_sw = GPIO.input(ROT_SW)
    last_state = rot_state()
    accum = 0
    add_event('input monitor started')

    while True:
        btn = read_buttons()
        for i, (old, new) in enumerate(zip(last_btn, btn), start=1):
            if old != new:
                add_event(f"BUTTON{i} {'PRESSED' if new == 1 else 'RELEASED'}")
        last_btn = btn

        s = rot_state()
        if s != last_state:
            step = trans.get((last_state, s), 0)
            accum += step
            last_state = s
            if accum >= 4:
                with lock:
                    state['rotary_last'] = 'CCW'
                    state['rotary_pos'] -= 1
                add_event('ROTARY CCW')
                accum = 0
            elif accum <= -4:
                with lock:
                    state['rotary_last'] = 'CW'
                    state['rotary_pos'] += 1
                add_event('ROTARY CW')
                accum = 0

        sw = GPIO.input(ROT_SW)
        if sw != last_sw:
            add_event(f"ROTARY_SW {'PRESSED' if sw == 0 else 'RELEASED'}")
            last_sw = sw

        with lock:
            state['buttons'] = btn
            state['rotary_sw'] = 1 if sw == 0 else 0

        time.sleep(0.003)


def find_rfid_device():
    for path in list_devices():
        dev = InputDevice(path)
        if 'SYC ID&IC USB Reader' in dev.name or 'Sycreader' in dev.name:
            return dev
    return None


def monitor_rfid():
    keymap = {getattr(ecodes, f'KEY_{i}'): str(i) for i in range(10)}
    keymap[ecodes.KEY_KP0] = '0'; keymap[ecodes.KEY_KP1] = '1'; keymap[ecodes.KEY_KP2] = '2'; keymap[ecodes.KEY_KP3] = '3'; keymap[ecodes.KEY_KP4] = '4'; keymap[ecodes.KEY_KP5] = '5'; keymap[ecodes.KEY_KP6] = '6'; keymap[ecodes.KEY_KP7] = '7'; keymap[ecodes.KEY_KP8] = '8'; keymap[ecodes.KEY_KP9] = '9'

    while True:
        dev = find_rfid_device()
        if not dev:
            add_event('RFID reader not found, retrying...')
            time.sleep(3)
            continue
        add_event(f'RFID reader attached: {dev.path}')
        buf = ''
        try:
            for ev in dev.read_loop():
                if ev.type != ecodes.EV_KEY:
                    continue
                if ev.value != 1:  # key down only
                    continue
                if ev.code == ecodes.KEY_ENTER:
                    if buf:
                        with lock:
                            state['last_card'] = buf
                        add_event(f'CARD {buf}')
                        buf = ''
                    continue
                ch = keymap.get(ev.code)
                if ch is not None:
                    buf += ch
        except Exception:
            add_event('RFID device disconnected')
            time.sleep(1)


def media_list():
    exts = {'.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac'}
    files = []
    for p in MEDIA_DIR.rglob('*'):
        if p.is_file() and p.suffix.lower() in exts:
            files.append(str(p.relative_to(MEDIA_DIR)))
    files.sort()
    return files


def stop_player():
    global player_proc
    if player_proc and player_proc.poll() is None:
        player_proc.terminate()
        try:
            player_proc.wait(timeout=2)
        except Exception:
            player_proc.kill()
    player_proc = None
    with lock:
        state['player'] = {'status': 'stopped', 'file': None}


def play_file(relpath):
    global player_proc
    target = (MEDIA_DIR / relpath).resolve()
    if not str(target).startswith(str(MEDIA_DIR.resolve())):
        raise ValueError('invalid path')
    if not target.exists():
        raise FileNotFoundError(relpath)
    stop_player()
    cmd = ['mpv', '--no-video', '--really-quiet', str(target)]
    player_proc = subprocess.Popen(cmd)
    with lock:
        state['player'] = {'status': 'playing', 'file': relpath}
    add_event(f'PLAY {relpath}')


def player_watchdog():
    global player_proc
    while True:
        if player_proc and player_proc.poll() is not None:
            with lock:
                state['player'] = {'status': 'stopped', 'file': None}
            player_proc = None
        time.sleep(0.5)


@app.get('/api/status')
def api_status():
    with lock:
        return jsonify({
            'buttons': state['buttons'],
            'rotary_sw': state['rotary_sw'],
            'rotary_last': state['rotary_last'],
            'rotary_pos': state['rotary_pos'],
            'last_card': state['last_card'],
            'player': state['player'],
            'events': list(state['events']),
        })


@app.get('/api/files')
def api_files():
    return jsonify({'media_dir': str(MEDIA_DIR), 'files': media_list()})


@app.post('/api/play')
def api_play():
    data = request.get_json(force=True, silent=True) or {}
    relpath = data.get('file', '')
    try:
        play_file(relpath)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400


@app.post('/api/stop')
def api_stop():
    stop_player()
    add_event('STOP')
    return jsonify({'ok': True})


@app.get('/')
def index():
    return Response("""
<!doctype html><html><head><meta charset='utf-8'><title>musicbox</title>
<style>body{font-family:system-ui;background:#111;color:#eee;padding:14px}.row{display:flex;gap:8px;flex-wrap:wrap}.card{background:#1d1d1d;border:1px solid #333;border-radius:8px;padding:8px}.on{color:#4ade80}.off{color:#9ca3af}button{padding:6px 10px}pre{background:#0b0b0b;padding:8px;border-radius:6px;max-height:250px;overflow:auto}ul{max-height:300px;overflow:auto}</style>
</head><body>
<h2>musicbox</h2>
<div class='row'>
<div class='card'>B1 <span id=b1></span></div><div class='card'>B2 <span id=b2></span></div><div class='card'>B3 <span id=b3></span></div><div class='card'>B4 <span id=b4></span></div>
<div class='card'>ROT <span id=rot></span></div><div class='card'>SW <span id=sw></span></div><div class='card'>CARD <span id=card>-</span></div>
<div class='card'>PLAYER <span id=player>stopped</span></div>
</div>
<h3>Media</h3><button onclick='reloadFiles()'>refresh</button> <button onclick='stopPlay()'>stop</button><ul id=files></ul>
<h3>Events</h3><pre id=events></pre>
<script>
async function api(path, opts){const r=await fetch(path,opts);return await r.json()}
async function reloadFiles(){const d=await api('/api/files');const ul=document.getElementById('files');ul.innerHTML='';d.files.forEach(f=>{const li=document.createElement('li');const b=document.createElement('button');b.textContent='play';b.onclick=()=>play(f);li.textContent=f+' ';li.appendChild(b);ul.appendChild(li);});}
async function play(f){await api('/api/play',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({file:f})});}
async function stopPlay(){await api('/api/stop',{method:'POST'});}
async function tick(){const s=await api('/api/status');for(let i=0;i<4;i++){const e=document.getElementById('b'+(i+1));const on=s.buttons[i]===1;e.textContent=on?'PRESSED':'released';e.className=on?'on':'off';}
document.getElementById('rot').textContent=s.rotary_last+' '+s.rotary_pos;const sw=document.getElementById('sw');const on=s.rotary_sw===1;sw.textContent=on?'PRESSED':'released';sw.className=on?'on':'off';document.getElementById('card').textContent=s.last_card||'-';document.getElementById('player').textContent=(s.player.status||'stopped')+(s.player.file?(' '+s.player.file):'');document.getElementById('events').textContent=s.events.join('\n');}
setInterval(tick,300); tick(); reloadFiles();
</script></body></html>
""", mimetype='text/html')


if __name__ == '__main__':
    threading.Thread(target=monitor_inputs, daemon=True).start()
    threading.Thread(target=monitor_rfid, daemon=True).start()
    threading.Thread(target=player_watchdog, daemon=True).start()
    add_event('musicbox web started on :8099')
    app.run(host='0.0.0.0', port=8099)
