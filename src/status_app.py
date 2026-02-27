#!/usr/bin/env python3
import threading
import time
from collections import deque
from datetime import datetime

from flask import Flask, jsonify, Response
import RPi.GPIO as GPIO
from adafruit_seesaw.seesaw import Seesaw
import board
import busio

BUTTON_PINS = [18, 19, 20, 2]
LED_PINS = [12, 13, 0, 1]
ROT_CLK = 5
ROT_DT = 6
ROT_SW = 13

state = {
    "buttons": [0, 0, 0, 0],
    "rotary_sw": 0,
    "rotary_last": "-",
    "rotary_pos": 0,
    "events": deque(maxlen=80),
    "started": datetime.utcnow().isoformat() + "Z",
}
lock = threading.Lock()

app = Flask(__name__)


def ts():
    return datetime.utcnow().strftime("%H:%M:%S")


def add_event(msg):
    with lock:
        state["events"].appendleft(f"[{ts()}] {msg}")


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
        return [0 if (bulk & (1 << p)) else 1 for p in BUTTON_PINS]  # 1=pressed

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

    add_event("status monitor started")

    while True:
        btn = read_buttons()
        for i, (old, new) in enumerate(zip(last_btn, btn), start=1):
            if old != new:
                add_event(f"BUTTON{i} {'PRESSED' if new == 1 else 'RELEASED'}")
        last_btn = btn

        rstate = rot_state()
        if rstate != last_state:
            step = trans.get((last_state, rstate), 0)
            accum += step
            last_state = rstate
            if accum >= 4:
                with lock:
                    state["rotary_pos"] -= 1
                    state["rotary_last"] = "CCW"
                add_event("ROTARY CCW")
                accum = 0
            elif accum <= -4:
                with lock:
                    state["rotary_pos"] += 1
                    state["rotary_last"] = "CW"
                add_event("ROTARY CW")
                accum = 0

        sw = GPIO.input(ROT_SW)
        if sw != last_sw:
            add_event(f"ROTARY_SW {'PRESSED' if sw == 0 else 'RELEASED'}")
            last_sw = sw

        with lock:
            state["buttons"] = btn
            state["rotary_sw"] = 1 if sw == 0 else 0

        time.sleep(0.003)


@app.get("/api/status")
def api_status():
    with lock:
        return jsonify(
            buttons=state["buttons"],
            rotary_sw=state["rotary_sw"],
            rotary_last=state["rotary_last"],
            rotary_pos=state["rotary_pos"],
            events=list(state["events"]),
            started=state["started"],
        )


@app.get("/")
def index():
    html = """
<!doctype html><html><head><meta charset='utf-8'><title>musicbox status</title>
<style>body{font-family:system-ui;background:#111;color:#eee;padding:18px} .row{display:flex;gap:10px;flex-wrap:wrap}.card{border:1px solid #333;border-radius:10px;padding:10px 12px;background:#1b1b1b}.on{color:#3ddc97}.off{color:#888} pre{background:#0b0b0b;padding:10px;border-radius:8px;max-height:380px;overflow:auto}</style>
</head><body>
<h2>musicbox status</h2>
<div class='row'>
  <div class='card'>B1: <span id='b1'></span></div>
  <div class='card'>B2: <span id='b2'></span></div>
  <div class='card'>B3: <span id='b3'></span></div>
  <div class='card'>B4: <span id='b4'></span></div>
  <div class='card'>ROT SW: <span id='sw'></span></div>
  <div class='card'>ROT LAST: <span id='last'></span></div>
  <div class='card'>ROT POS: <span id='pos'></span></div>
</div>
<h3>events</h3><pre id='events'></pre>
<script>
async function tick(){
  const r=await fetch('/api/status'); const s=await r.json();
  for(let i=0;i<4;i++){const el=document.getElementById('b'+(i+1)); const on=s.buttons[i]===1; el.textContent=on?'PRESSED':'released'; el.className=on?'on':'off';}
  const sw=document.getElementById('sw'); const son=s.rotary_sw===1; sw.textContent=son?'PRESSED':'released'; sw.className=son?'on':'off';
  document.getElementById('last').textContent=s.rotary_last;
  document.getElementById('pos').textContent=s.rotary_pos;
  document.getElementById('events').textContent=s.events.join('\n');
}
setInterval(tick, 250); tick();
</script>
</body></html>
"""
    return Response(html, mimetype="text/html")


if __name__ == "__main__":
    t = threading.Thread(target=monitor_inputs, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=8099)
