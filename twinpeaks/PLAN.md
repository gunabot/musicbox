# twinpeaks — Rust MP3/WAV Audio Engine

## What This Is

A purpose-built audio engine for the [musicbox](../musicbox/) project — an RFID card-tap music box with arcade buttons on a Raspberry Pi 3B (1GB RAM). Replaces MPV with a Rust engine that decodes audio to a PCM buffer, enabling instant reverse/speed playback (Twin Peaks-style backward audio). MPV cannot do reverse playback well.

The engine is "dumb" — it plays, scrubs, and reports status. All button logic (hold timers, track navigation, prev/next) lives in the Pi-side Python controller.

## Architecture

```
musicbox controller (Python) ──Unix socket JSON──▶ twinpeaks (Rust)
                                                     ├─ main thread: socket listener + command dispatch
                                                     ├─ decode thread: MP3/WAV → PCM buffer (background)
                                                     └─ audio thread: cpal callback → ALSA output
```

**Three threads, one shared buffer:**
- Main thread handles IPC, mutates playback state via atomics
- Decode thread writes PCM samples into a pre-allocated buffer (lock-free via atomic write cursor)
- Audio callback reads from the buffer, applies interpolation + speed + volume

## Module Structure

```
src/
├── main.rs       — CLI arg parsing, signal handling (sigwait), spawn socket listener
├── types.rs      — AtomicF64/F32 wrappers, Command/Response, PcmBuffer, PlaybackState
├── decoder.rs    — probe_file() for metadata, decode_streaming() into shared buffer
├── output.rs     — cpal stream setup, audio callback with interpolation + ramping
├── engine.rs     — orchestrates decode thread + audio output, implements all commands
└── ipc.rs        — Unix socket server, JSON protocol, command dispatch
```

## Key Design Decisions

1. **Non-blocking load**: `load()` returns immediately with `state: "loading"`. The audio callback auto-transitions to `"playing"` once 0.5s of data is buffered. IPC stays responsive throughout.

2. **Lock-free audio callback**: Pre-allocated `Vec<f32>` with an atomic write cursor (`Release`/`Acquire` ordering). The audio callback does no allocations and holds no locks.

3. **Speed = tape effect**: Pitch changes with speed (no pitch correction). Linear interpolation between samples for fractional positions. Smooth per-sample speed ramping via `ramp_ms` parameter.

4. **Software volume**: Gain 0.0–1.0 applied in the audio callback. No boost = no clipping.

5. **One track in memory**: `load()` replaces whatever is playing. ~100MB for a 10-min stereo 44.1kHz track. Fine for 1GB RAM.

6. **Graceful error handling**: Stream is created before spawning the decode thread — if stream creation fails, nothing to clean up. `load()` rolls back all state on error. `mark_decode_complete()` is always called (success or error) so the audio callback never waits forever.

## Dependencies

| Crate | Version | Purpose |
|-------|---------|---------|
| symphonia | 0.5 | Audio decode (features: mp3, wav, pcm) |
| cpal | 0.15 | Audio output via ALSA |
| serde + serde_json | 1 | JSON serialization |
| anyhow | 1 | Error handling |
| log + env_logger | 0.4 / 0.11 | Logging (controlled by RUST_LOG) |
| libc | 0.2 | Signal handling (sigwait/pthread_sigmask) |

No async runtime — just `std::thread`.

## IPC Protocol

Unix socket at `/tmp/twinpeaks.sock` (configurable via CLI arg). Newline-delimited JSON. One connection per command (matches musicbox's existing pattern).

**Commands:**
```json
{"cmd": "load", "path": "/path/to/track.mp3"}
{"cmd": "play"}
{"cmd": "pause"}
{"cmd": "stop"}
{"cmd": "seek", "position": 30.5}
{"cmd": "set_speed", "speed": 2.0}
{"cmd": "set_speed", "speed": 2.0, "direction": "reverse", "ramp_ms": 500}
{"cmd": "set_volume", "volume": 75}
{"cmd": "status"}
{"cmd": "quit"}
```

Notes:
- `set_speed`: `direction` is optional — omitting it preserves the current direction. `ramp_ms` defaults to 0 (instant).
- `load` returns immediately with `"state": "loading"`. Poll `status` to see when it transitions to `"playing"`.

**Response (every command):**
```json
{"ok": true, "status": {"state": "playing", "position_sec": 12.5, "buffer_sec": 45.0, "duration_sec": 180.0, "speed": 1.0, "direction": "forward", "volume": 75}}
```

Error responses include an `"error"` field:
```json
{"ok": false, "error": "Cannot open /bad/path.mp3: No such file or directory", "status": {...}}
```

## Buffer Design

```
PcmBuffer {
    data: UnsafeCell<Vec<f32>>     // pre-allocated, zero-filled
    write_cursor: AtomicUsize      // decode thread advances with Release
    decode_complete: AtomicBool    // set when decode finishes (success OR error)
    sample_rate: u32               // immutable after creation
    channels: u16                  // immutable after creation
}
```

The decode thread writes `data[cursor..cursor+n]` then advances `write_cursor` with `Release`. The audio callback loads `write_cursor` with `Acquire` and only reads `data[0..write_cursor]`. No overlap, no data race.

Buffer is allocated with 20% headroom over the probe estimate to handle VBR MP3s. If it fills up, excess samples are dropped with a warning log.

## Playback State (all atomics)

```
PlaybackState {
    cursor: AtomicF64          // fractional frame position
    speed: AtomicF64           // current speed (may be mid-ramp)
    target_speed: AtomicF64    // speed to ramp toward
    speed_delta: AtomicF64     // per-frame speed change (pre-calculated)
    volume: AtomicF32          // gain 0.0–1.0
    direction: AtomicI8        // +1 forward, -1 reverse
    state: AtomicU8            // 0=stopped, 1=playing, 2=paused, 3=loading
}
```

`AtomicF64`/`AtomicF32` are thin wrappers around `AtomicU64`/`AtomicU32` that handle the `to_bits()`/`from_bits()` conversion.

## Load Flow

```
load("track.mp3")
  ├─ stop_internal()                    // cancel old decode, drop old stream
  ├─ probe_file()                       // fast metadata read (~10ms)
  ├─ allocate PcmBuffer                 // pre-allocated, zero-filled
  ├─ reset PlaybackState                // cursor=0, speed=1, state=Loading
  ├─ build_output_stream()              // cpal stream (outputs silence while Loading)
  ├─ spawn decode thread                // fills buffer in background
  └─ return Ok(())                      // IPC responds immediately

audio callback (runs at ~5ms intervals):
  ├─ state == Loading?
  │   ├─ enough data buffered (0.5s) or decode complete?
  │   │   └─ set state = Playing, fall through
  │   └─ else: output silence, return
  ├─ state == Playing: interpolate + volume + advance cursor
  ├─ cursor < 0 (reverse hit start): set state = Paused
  └─ cursor >= end + decode complete: set state = Stopped

decode thread:
  ├─ decode packets → buffer.push_samples()
  ├─ on finish: buffer.mark_decode_complete()
  └─ on error: log, buffer.mark_decode_complete() (so callback doesn't wait forever)
```

On any error during load, `stop_internal()` is called to clean up partial state.

## Audio Callback Detail

Per output frame (~1/48000s at 48kHz):
1. **Speed ramp**: if `speed_delta != 0`, adjust `speed` toward `target_speed`
2. **Boundary check**: cursor < 0 → pause at start; cursor >= end → stop
3. **Interpolate**: linear interpolation between `floor(cursor)` and `ceil(cursor)` for each channel
4. **Volume**: multiply by gain
5. **Advance**: `cursor += speed * direction_sign`

## Building and Running

```bash
# Build
cargo build --release

# Run (default socket: /tmp/twinpeaks.sock)
RUST_LOG=info ./target/release/twinpeaks

# Run with custom socket path
RUST_LOG=info ./target/release/twinpeaks /tmp/my-socket.sock

# Test with socat
echo '{"cmd":"load","path":"track.mp3"}' | socat - UNIX-CONNECT:/tmp/twinpeaks.sock
echo '{"cmd":"status"}' | socat - UNIX-CONNECT:/tmp/twinpeaks.sock
echo '{"cmd":"set_speed","speed":1.0,"direction":"reverse","ramp_ms":500}' | socat - UNIX-CONNECT:/tmp/twinpeaks.sock
echo '{"cmd":"quit"}' | socat - UNIX-CONNECT:/tmp/twinpeaks.sock

# Cross-compile for Pi 3B (deferred to integration testing)
cross build --target armv7-unknown-linux-gnueabihf --release
```

## Not In Scope (v1)

- Playlist/track navigation (controller's job)
- Hold-timer acceleration logic (controller's job)
- FLAC/AAC support (easy to add via symphonia feature flags)
- Gapless playback
- Audio mixing (no TTS overlay yet)
- Output sample rate negotiation/resampling (cpal gets the track's native rate; if the device doesn't support it, it errors — acceptable for a music box that only plays MP3/WAV)
- Cross-compilation setup

## Reference Files

- `../vocode/src/recorder.rs` — cpal 0.15 patterns, linear interpolation resampling
- `../musicbox/src/musicbox_app/player.py` — Unix socket IPC pattern (one-connection-per-command)
