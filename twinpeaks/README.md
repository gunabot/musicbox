# twinpeaks

A lightweight Rust audio engine for the [musicbox](https://github.com/odk211/musicbox) project. Built for instant reverse and speed-ramped playback (Twin Peaks-style backward audio) on a Raspberry Pi 3B.

## Features

- **Reverse playback with speed ramping** — tape-style pitch shifting, smooth linear ramps between speeds
- **Lock-free real-time audio** — zero allocations or locks in the audio callback; pre-allocated PCM buffer with atomic cursors
- **Unix socket IPC** — newline-delimited JSON protocol, one connection per command
- **Background decoding** — MP3/WAV decoded in a background thread; playback starts as soon as 0.5s is buffered

## Build

```bash
cargo build --release
```

### Cross-compile for Raspberry Pi 3B

```bash
cross build --target armv7-unknown-linux-gnueabihf --release
```

## Usage

```bash
# Default socket: /tmp/twinpeaks.sock
RUST_LOG=info ./target/release/twinpeaks

# Custom socket path
RUST_LOG=info ./target/release/twinpeaks /tmp/my-socket.sock
```

## IPC protocol

Send JSON commands via the Unix socket. Every command returns `{"ok": true/false, "status": {...}}`.

| Command | Example |
|---------|---------|
| `load` | `{"cmd": "load", "path": "/music/track.mp3"}` |
| `play` | `{"cmd": "play"}` |
| `pause` | `{"cmd": "pause"}` |
| `stop` | `{"cmd": "stop"}` |
| `seek` | `{"cmd": "seek", "position": 30.5}` |
| `set_speed` | `{"cmd": "set_speed", "speed": 2.0, "direction": "reverse", "ramp_ms": 500}` |
| `set_volume` | `{"cmd": "set_volume", "volume": 75}` |
| `status` | `{"cmd": "status"}` |
| `quit` | `{"cmd": "quit"}` |

`direction` and `ramp_ms` are optional on `set_speed` — omitting `direction` preserves the current one, `ramp_ms` defaults to 0 (instant).

### Example with socat

```bash
echo '{"cmd":"load","path":"track.mp3"}' | socat - UNIX-CONNECT:/tmp/twinpeaks.sock
echo '{"cmd":"set_speed","speed":1.0,"direction":"reverse","ramp_ms":500}' | socat - UNIX-CONNECT:/tmp/twinpeaks.sock
echo '{"cmd":"status"}' | socat - UNIX-CONNECT:/tmp/twinpeaks.sock
```
