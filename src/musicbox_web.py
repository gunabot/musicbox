#!/usr/bin/env python3
import os
import json
import shutil
import threading
import time
import subprocess
import socket
import json as jsonlib
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
MAPPINGS_PATH = Path('/home/musicbox/musicbox/config/card_mappings.json')
MAPPINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
MPV_SOCKET = '/tmp/musicbox-mpv.sock'

BUTTON_PINS = [18, 19, 20, 2]
LED_PINS = [12, 13, 0, 1]
ROT_CLK = 5
ROT_DT = 6
ROT_SW = 13

state = {
    'buttons': [0, 0, 0, 0],
    'rotary_sw': 0,
    'rotary_last': '-',
    'rotary_pos': 0,
    'events': deque(maxlen=200),
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


def load_mappings():
    if not MAPPINGS_PATH.exists():
        return {}
    try:
        return json.loads(MAPPINGS_PATH.read_text())
    except Exception:
        return {}


def save_mappings(m):
    MAPPINGS_PATH.write_text(json.dumps(m, indent=2, sort_keys=True))


def safe_rel_to_abs(relpath: str) -> Path:
    relpath = (relpath or '').strip().lstrip('/')
    p = (MEDIA_DIR / relpath).resolve()
    if not str(p).startswith(str(MEDIA_DIR.resolve())):
        raise ValueError('invalid path')
    return p


def monitor_inputs():
    i2c = busio.I2C(board.SCL, board.SDA)
    ss = Seesaw(i2c, addr=0x3A)
    for p in BUTTON_PINS:
        ss.pin_mode(p, ss.INPUT_PULLUP)
    for p in LED_PINS:
        ss.pin_mode(p, ss.OUTPUT)
        ss.digital_write(p, False)

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

    def rotary_led_sweep(direction, btn_state):
        try:
            order = LED_PINS if direction == 'CW' else list(reversed(LED_PINS))
            for lp in order:
                ss.digital_write(lp, True)
                time.sleep(0.025)
                ss.digital_write(lp, False)
            # restore press LEDs after sweep
            for i, lp in enumerate(LED_PINS):
                ss.digital_write(lp, btn_state[i] == 1)
        except Exception:
            pass

    last_btn = read_buttons()
    last_sw = GPIO.input(ROT_SW)
    last_state = rot_state()
    accum = 0
    add_event('input monitor started')

    while True:
        btn = read_buttons()
        for i, (old, new) in enumerate(zip(last_btn, btn), start=1):
            if old != new:
                pressed = (new == 1)
                add_event(f"BUTTON{i} {'PRESSED' if pressed else 'RELEASED'}")
                try:
                    ss.digital_write(LED_PINS[i-1], pressed)
                except Exception:
                    pass
                if pressed:
                    # Physical order requested: green red blue blue
                    # BUTTON1=play/pause, BUTTON2=stop, BUTTON3=prev, BUTTON4=next
                    if i == 1:
                        player_play_pause()
                    elif i == 2:
                        stop_player(); add_event('STOP')
                    elif i == 3:
                        player_prev()
                    elif i == 4:
                        player_next()
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
                player_volume(-3)
                rotary_led_sweep('CCW', btn)
                accum = 0
            elif accum <= -4:
                with lock:
                    state['rotary_last'] = 'CW'
                    state['rotary_pos'] += 1
                add_event('ROTARY CW')
                player_volume(+3)
                rotary_led_sweep('CW', btn)
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
                if ev.value != 1:
                    continue
                if ev.code == ecodes.KEY_ENTER:
                    if buf:
                        with lock:
                            state['last_card'] = buf
                        add_event(f'CARD {buf}')

                        mappings = load_mappings()
                        mapped = mappings.get(buf)
                        if mapped:
                            try:
                                play_file(mapped)
                                add_event(f'CARD_MAPPED {buf} -> {mapped}')
                            except Exception as e:
                                add_event(f'CARD_MAPPED_ERR {buf}: {e}')
                        else:
                            add_event(f'CARD_UNMAPPED {buf}')
                        buf = ''
                    continue
                ch = keymap.get(ev.code)
                if ch is not None:
                    buf += ch
        except Exception:
            add_event('RFID device disconnected')
            time.sleep(1)


def media_files():
    exts = {'.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac'}
    files = []
    for p in MEDIA_DIR.rglob('*'):
        if p.is_file() and p.suffix.lower() in exts:
            files.append(str(p.relative_to(MEDIA_DIR)))
    files.sort()
    return files


def media_tree(base: Path = MEDIA_DIR):
    node = {'name': base.name, 'path': str(base.relative_to(MEDIA_DIR)) if base != MEDIA_DIR else '', 'type': 'dir', 'children': []}
    for child in sorted(base.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
        if child.is_dir():
            node['children'].append(media_tree(child))
        else:
            node['children'].append({'name': child.name, 'path': str(child.relative_to(MEDIA_DIR)), 'type': 'file'})
    return node


def media_entries():
    entries = []
    for p in MEDIA_DIR.rglob('*'):
        rel = str(p.relative_to(MEDIA_DIR))
        entries.append({'path': rel, 'name': p.name, 'type': 'dir' if p.is_dir() else 'file'})
    entries.sort(key=lambda e: (e['type'] == 'file', e['path'].lower()))
    return entries


def mpv_cmd(cmd):
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(0.5)
        s.connect(MPV_SOCKET)
        payload = jsonlib.dumps({'command': cmd}) + '\n'
        s.sendall(payload.encode())
        data = s.recv(4096)
        s.close()
        return data.decode(errors='ignore')
    except Exception:
        return None


def player_play_pause():
    r = mpv_cmd(['cycle', 'pause'])
    if r is not None:
        add_event('PLAY_PAUSE')
        return True
    return False


def player_next():
    r = mpv_cmd(['playlist-next', 'force'])
    if r is not None:
        add_event('NEXT')
        return True
    return False


def player_prev():
    r = mpv_cmd(['playlist-prev', 'force'])
    if r is not None:
        add_event('PREV')
        return True
    return False


def player_volume(delta: int):
    # Positive delta -> louder, negative -> quieter
    r = mpv_cmd(['add', 'volume', int(delta)])
    if r is not None:
        add_event(f'VOLUME {delta:+d}')
        return True
    return False


def stop_player():
    global player_proc
    if player_proc and player_proc.poll() is None:
        player_proc.terminate()
        try:
            player_proc.wait(timeout=2)
        except Exception:
            player_proc.kill()
    player_proc = None
    try:
        if os.path.exists(MPV_SOCKET):
            os.unlink(MPV_SOCKET)
    except Exception:
        pass
    with lock:
        state['player'] = {'status': 'stopped', 'file': None}


def _audio_files_in_dir(d: Path):
    exts = {'.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac'}
    out = []
    for p in d.rglob('*'):
        if p.is_file() and p.suffix.lower() in exts:
            out.append(p)
    return sorted(out)


def play_file(relpath):
    global player_proc
    target = safe_rel_to_abs(relpath)
    if not target.exists():
        raise FileNotFoundError(relpath)

    stop_player()

    if os.path.exists(MPV_SOCKET):
        try:
            os.unlink(MPV_SOCKET)
        except Exception:
            pass

    if target.is_dir():
        files = _audio_files_in_dir(target)
        if not files:
            raise FileNotFoundError('no audio files in folder')
        playlist = Path('/tmp/musicbox-playlist.m3u')
        playlist.write_text('\n'.join(str(p) for p in files) + '\n')
        player_proc = subprocess.Popen(['mpv', '--no-video', '--really-quiet', '--audio-device=alsa/plughw:1,0', f'--input-ipc-server={MPV_SOCKET}', f'--playlist={playlist}'])
    else:
        player_proc = subprocess.Popen(['mpv', '--no-video', '--really-quiet', '--audio-device=alsa/plughw:1,0', f'--input-ipc-server={MPV_SOCKET}', str(target)])

    with lock:
        state['player'] = {'status': 'playing', 'file': str(target.relative_to(MEDIA_DIR))}
    add_event(f'PLAY {relpath}')


def player_watchdog():
    global player_proc
    while True:
        if player_proc and player_proc.poll() is not None:
            rc = player_proc.returncode
            add_event(f'PLAYER_EXIT rc={rc}')
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
    return jsonify({'media_dir': str(MEDIA_DIR), 'files': media_files(), 'tree': media_tree(), 'entries': media_entries()})


@app.post('/api/play')
def api_play():
    data = request.get_json(force=True, silent=True) or {}
    try:
        play_file(data.get('file', ''))
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400


@app.post('/api/stop')
def api_stop():
    stop_player()
    add_event('STOP')
    return jsonify({'ok': True})


@app.post('/api/player/action')
def api_player_action():
    data = request.get_json(force=True, silent=True) or {}
    action = (data.get('action') or '').strip().lower()
    ok = False
    if action == 'playpause':
        ok = player_play_pause()
    elif action == 'next':
        ok = player_next()
    elif action == 'prev':
        ok = player_prev()
    elif action == 'stop':
        stop_player(); add_event('STOP'); ok = True
    elif action == 'volup':
        ok = player_volume(+5)
    elif action == 'voldown':
        ok = player_volume(-5)
    return jsonify({'ok': ok, 'action': action})


@app.post('/api/mkdir')
def api_mkdir():
    data = request.get_json(force=True, silent=True) or {}
    try:
        p = safe_rel_to_abs(data.get('path', ''))
        p.mkdir(parents=True, exist_ok=True)
        add_event(f'MKDIR {p.relative_to(MEDIA_DIR)}')
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400


@app.post('/api/delete')
def api_delete():
    data = request.get_json(force=True, silent=True) or {}
    try:
        p = safe_rel_to_abs(data.get('path', ''))
        if not p.exists():
            raise FileNotFoundError('not found')
        rel = str(p.relative_to(MEDIA_DIR))
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        add_event(f'DELETE {rel}')
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400


@app.post('/api/upload')
def api_upload():
    try:
        target_dir = request.form.get('dir', '').strip().lstrip('/')
        base = safe_rel_to_abs(target_dir)
        base.mkdir(parents=True, exist_ok=True)

        files = request.files.getlist('files')
        relpaths = request.form.getlist('relpath')

        if not files:
            return jsonify({'ok': False, 'error': 'no files'}), 400

        saved = []
        skipped = 0
        for i, f in enumerate(files):
            if not f or not getattr(f, 'filename', ''):
                skipped += 1
                continue

            rel = relpaths[i] if i < len(relpaths) and relpaths[i] else f.filename
            rel = rel.replace('\\', '/').lstrip('/')
            # prevent weird browser paths like C:/fakepath
            if rel.lower().startswith('c:/fakepath/'):
                rel = rel.split('/', 2)[-1]
            rel = str(Path(rel))

            if rel in ('.', ''):
                skipped += 1
                continue

            out = safe_rel_to_abs(str(Path(target_dir) / rel))
            out.parent.mkdir(parents=True, exist_ok=True)
            f.save(out)
            saved.append(str(out.relative_to(MEDIA_DIR)))

        if not saved:
            msg = 'no valid files in upload payload'
            add_event(f'UPLOAD_ERR {msg} (skipped={skipped})')
            return jsonify({'ok': False, 'error': msg}), 400

        add_event(f'UPLOAD {len(saved)} file(s), skipped={skipped}')
        return jsonify({'ok': True, 'saved': saved, 'skipped': skipped})
    except Exception as e:
        add_event(f'UPLOAD_ERR {e}')
        return jsonify({'ok': False, 'error': str(e)}), 400


@app.get('/api/mappings')
def api_mappings_get():
    return jsonify({'ok': True, 'mappings': load_mappings(), 'path': str(MAPPINGS_PATH)})


@app.post('/api/mappings')
def api_mappings_set():
    data = request.get_json(force=True, silent=True) or {}
    card = str(data.get('card', '')).strip()
    target = str(data.get('target', '')).strip().lstrip('/')
    if not card:
        return jsonify({'ok': False, 'error': 'card required'}), 400
    m = load_mappings()
    if target:
        safe_rel_to_abs(target)  # validate path traversal
        m[card] = target
        add_event(f'MAP_SET {card} -> {target}')
    else:
        m.pop(card, None)
        add_event(f'MAP_DEL {card}')
    save_mappings(m)
    return jsonify({'ok': True, 'mappings': m})


@app.get('/')
def index():
    return Response("""
<!doctype html><html><head><meta charset='utf-8'><title>musicbox</title>
<style>
body{font-family:system-ui;background:#111;color:#eee;padding:14px}
.row{display:flex;gap:8px;flex-wrap:wrap}
.card{background:#1d1d1d;border:1px solid #333;border-radius:8px;padding:8px}
.on{color:#4ade80}.off{color:#9ca3af}
button,input{padding:6px 10px;background:#222;color:#eee;border:1px solid #444;border-radius:6px}
pre{background:#0b0b0b;padding:8px;border-radius:6px;max-height:240px;overflow:auto}
ul{max-height:260px;overflow:auto}
#drop{border:2px dashed #555;border-radius:10px;padding:14px;margin:10px 0}
small{color:#9ca3af}
</style>
</head><body>
<h2>musicbox</h2>
<div class='row'>
  <div class='card'>B1 <span id=b1></span></div><div class='card'>B2 <span id=b2></span></div><div class='card'>B3 <span id=b3></span></div><div class='card'>B4 <span id=b4></span></div>
  <div class='card'>ROT <span id=rot></span></div><div class='card'>SW <span id=sw></span></div><div class='card'>CARD <span id=card>-</span></div>
  <div class='card'>PLAYER <span id=player>stopped</span></div>
</div>
<div class='row' style='margin-top:8px'>
  <button onclick="playerAction('playpause')">play/pause</button>
  <button onclick="playerAction('stop')">stop</button>
  <button onclick="playerAction('prev')">prev</button>
  <button onclick="playerAction('next')">next</button>
  <button onclick="playerAction('voldown')">vol -</button>
  <button onclick="playerAction('volup')">vol +</button>
</div>

<h3>File manager</h3>
<div class='row'>
  <input id='targetDir' placeholder='target dir under /media (e.g. kids/stories)' style='min-width:320px'>
  <button onclick='mkDir()'>create dir</button>
  <button onclick='reloadFiles()'>refresh</button>
  <button onclick='stopPlay()'>stop</button>
</div>
<div id='drop'>Drag & drop files/folders here (or use picker below)</div>
<div class='row'>
  <input id='pickFiles' type='file' multiple>
  <input id='pickFolder' type='file' webkitdirectory directory multiple>
  <button id='uploadBtn' onclick='uploadPicked()'>upload selected</button>
</div>
<div class='row'>
  <progress id='uploadProgress' value='0' max='100' style='width:320px;display:none'></progress>
  <span id='uploadStatus' class='off'>idle</span>
</div>
<small>Folder uploads preserve relative paths when browser supports it.</small>

<table id='filesTable' style='width:100%;margin-top:10px;border-collapse:collapse'>
  <thead><tr><th align='left'>Type</th><th align='left'>Path</th><th align='left'>Mapped card</th><th align='left'>Actions</th></tr></thead>
  <tbody id='files'></tbody>
</table>

<h3>Card mappings</h3>
<div class='row'>
  <input id='mapCard' placeholder='card id (scan card first to auto-fill)' style='min-width:240px'>
  <input id='mapTarget' placeholder='target file/folder under /media' style='min-width:320px'>
  <button onclick='saveMapping()'>save mapping</button>
  <button onclick='deleteMapping()'>delete mapping</button>
  <button onclick='reloadMappings()'>refresh mappings</button>
</div>
<pre id='mappings'></pre>

<h3>Events</h3><pre id=events></pre>
<script>
async function api(path, opts){ const r = await fetch(path, opts); return await r.json(); }
let mappings = {};

function invertMappings(){
  const inv = {};
  for (const [card,target] of Object.entries(mappings||{})){ inv[target]=card; }
  return inv;
}

async function reloadFiles(){
  const d = await api('/api/files');
  const tbody = document.getElementById('files');
  const inv = invertMappings();
  tbody.innerHTML='';
  (d.entries||[]).forEach(e=>{
    const tr=document.createElement('tr');
    tr.innerHTML = `<td>${e.type}</td><td>${e.path}</td><td>${inv[e.path]||''}</td>`;
    const td=document.createElement('td');

    if(e.type==='file'){
      const bPlay=document.createElement('button'); bPlay.textContent='play'; bPlay.onclick=()=>play(e.path); td.appendChild(bPlay);
      td.appendChild(document.createTextNode(' '));
    }

    const bMap=document.createElement('button'); bMap.textContent='map'; bMap.onclick=()=>{document.getElementById('mapTarget').value=e.path; if(inv[e.path]) document.getElementById('mapCard').value=inv[e.path];}; td.appendChild(bMap);
    td.appendChild(document.createTextNode(' '));

    const bDel=document.createElement('button'); bDel.textContent='delete'; bDel.onclick=()=>delPath(e.path); td.appendChild(bDel);

    tr.appendChild(td);
    tbody.appendChild(tr);
  });
}

async function play(f){ await api('/api/play',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({file:f})}); }
async function stopPlay(){ await api('/api/stop',{method:'POST'}); }
async function playerAction(action){ await api('/api/player/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action})}); }
async function delPath(p){ if(!confirm('Delete '+p+' ?')) return; await api('/api/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:p})}); await reloadFiles(); }
async function mkDir(){ const p=document.getElementById('targetDir').value.trim(); if(!p) return; await api('/api/mkdir',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:p})}); await reloadFiles(); }

async function reloadMappings(){
  const d = await api('/api/mappings');
  mappings = d.mappings || {};
  document.getElementById('mappings').textContent = JSON.stringify(mappings, null, 2);
  await reloadFiles();
}
async function saveMapping(){
  const card=document.getElementById('mapCard').value.trim();
  const target=document.getElementById('mapTarget').value.trim();
  if(!card||!target){ alert('card + target required'); return; }
  await api('/api/mappings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({card,target})});
  await reloadMappings();
}
async function deleteMapping(){
  const card=document.getElementById('mapCard').value.trim();
  if(!card){ alert('card required'); return; }
  await api('/api/mappings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({card,target:''})});
  await reloadMappings();
}

function setUploadUI(state, text, pct){
  const b=document.getElementById('uploadBtn');
  const p=document.getElementById('uploadProgress');
  const s=document.getElementById('uploadStatus');
  if(state==='idle'){
    b.disabled=false; b.textContent='upload selected';
    p.style.display='none'; p.value=0;
    s.textContent=text||'idle'; s.className='off';
    return;
  }
  b.disabled=true; b.textContent='uploading...';
  p.style.display='inline-block';
  if(typeof pct==='number') p.value=pct;
  s.textContent=text||'uploading'; s.className='on';
}

function uploadFiles(files){
  return new Promise(async (resolve)=>{
    if(!files.length){ alert('No files selected'); return resolve(); }
    const dir = document.getElementById('targetDir').value.trim();
    const fd = new FormData();
    fd.append('dir', dir);
    let count=0;
    for(const f of files){
      if(!f || !f.name) continue;
      fd.append('files', f, f.name);
      fd.append('relpath', f.webkitRelativePath || f.name);
      count++;
    }
    if(!count){ alert('No valid files selected'); return resolve(); }

    setUploadUI('busy', `Starting upload (${count} file(s))...`, 0);

    const xhr = new XMLHttpRequest();
    xhr.open('POST','/api/upload', true);
    xhr.upload.onprogress = (e)=>{
      if(e.lengthComputable){
        const pct=Math.round((e.loaded/e.total)*100);
        setUploadUI('busy', `Uploading... ${pct}%`, pct);
      } else {
        setUploadUI('busy', 'Uploading...', undefined);
      }
    };
    xhr.onload = async ()=>{
      let j={ok:false,error:'invalid response'};
      try{ j=JSON.parse(xhr.responseText||'{}'); }catch{}
      if(xhr.status>=200 && xhr.status<300 && j.ok){
        setUploadUI('busy', `Uploaded ${j.saved?.length||0} file(s)`, 100);
      } else {
        setUploadUI('busy', `Upload failed: ${j.error||xhr.statusText||'unknown'}`, 0);
        alert('Upload failed: '+(j.error||xhr.statusText||'unknown'));
      }
      await reloadFiles();
      setTimeout(()=>setUploadUI('idle','idle',0),1200);
      resolve();
    };
    xhr.onerror = ()=>{
      setUploadUI('busy','Upload failed: network error',0);
      alert('Upload failed: network error');
      setTimeout(()=>setUploadUI('idle','idle',0),1200);
      resolve();
    };
    xhr.send(fd);
  });
}

async function uploadPicked(){
  const a=[...document.getElementById('pickFiles').files];
  const b=[...document.getElementById('pickFolder').files];
  await uploadFiles([...a,...b]);
  document.getElementById('pickFiles').value='';
  document.getElementById('pickFolder').value='';
}

const drop=document.getElementById('drop');
drop.addEventListener('dragover',e=>{e.preventDefault();drop.style.borderColor='#999';});
drop.addEventListener('dragleave',e=>{drop.style.borderColor='#555';});
drop.addEventListener('drop',async e=>{e.preventDefault();drop.style.borderColor='#555'; await uploadFiles([...e.dataTransfer.files]);});

async function tick(){
  const s=await api('/api/status');
  for(let i=0;i<4;i++){const e=document.getElementById('b'+(i+1));const on=s.buttons[i]===1;e.textContent=on?'PRESSED':'released';e.className=on?'on':'off';}
  document.getElementById('rot').textContent=s.rotary_last+' '+s.rotary_pos;
  const sw=document.getElementById('sw');const on=s.rotary_sw===1;sw.textContent=on?'PRESSED':'released';sw.className=on?'on':'off';
  document.getElementById('card').textContent=s.last_card||'-';
  if (s.last_card && !document.getElementById('mapCard').value) document.getElementById('mapCard').value = s.last_card;
  document.getElementById('player').textContent=(s.player.status||'stopped')+(s.player.file?(' '+s.player.file):'');
  document.getElementById('events').textContent=s.events.join('\\n');
}
setInterval(tick,300); tick(); reloadFiles(); reloadMappings();
</script></body></html>
""", mimetype='text/html')


if __name__ == '__main__':
    threading.Thread(target=monitor_inputs, daemon=True).start()
    threading.Thread(target=monitor_rfid, daemon=True).start()
    threading.Thread(target=player_watchdog, daemon=True).start()
    add_event('musicbox web started on :8099')
    app.run(host='0.0.0.0', port=8099)
