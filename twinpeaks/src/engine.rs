use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;

use anyhow::{Context, Result};
use cpal::Stream;

use crate::decoder;
use crate::output;
use crate::types::{Direction, PcmBuffer, PlaybackState, State, StatusResponse};

pub struct Engine {
    playback: Arc<PlaybackState>,
    buffer: Option<Arc<PcmBuffer>>,
    stream: Option<Stream>,
    decode: Option<(Arc<AtomicBool>, thread::JoinHandle<()>)>,
    duration_secs: f64,
}

impl Engine {
    pub fn new() -> Self {
        Self {
            playback: Arc::new(PlaybackState::new()),
            buffer: None,
            stream: None,
            decode: None,
            duration_secs: 0.0,
        }
    }

    /// Load a track. Returns immediately — the audio callback handles
    /// the Loading → Playing transition once enough data is buffered.
    pub fn load(&mut self, path: &str) -> Result<()> {
        self.stop_internal();

        match self.load_track(path) {
            Ok(()) => Ok(()),
            Err(e) => {
                self.stop_internal();
                Err(e)
            }
        }
    }

    fn load_track(&mut self, path: &str) -> Result<()> {
        log::info!("Loading: {}", path);

        let decode_session = decoder::DecodeSession::open(path).context("Failed to probe file")?;
        let meta = decode_session.metadata;
        log::info!(
            "Track: {}Hz, {}ch, {:.1}s, {} frames",
            meta.sample_rate,
            meta.channels,
            meta.duration_secs,
            meta.total_frames
        );

        self.duration_secs = meta.duration_secs;

        // Allocate buffer with 20% headroom (VBR MP3s can exceed n_frames estimate).
        // Saturating arithmetic + cap prevents overflow on 32-bit ARM.
        const MAX_BUFFER_SAMPLES: usize = 128 * 1024 * 1024; // 512 MB of f32
        let estimated_frames = if meta.total_frames > 0 {
            (meta.total_frames as f64 * 1.2) as usize
        } else {
            (meta.sample_rate as usize).saturating_mul(600)
        };
        let estimated_samples = estimated_frames
            .saturating_mul(meta.channels as usize)
            .min(MAX_BUFFER_SAMPLES);

        let buffer = Arc::new(PcmBuffer::new(
            estimated_samples,
            meta.sample_rate,
            meta.channels,
        ));

        // Reset playback state
        self.playback.cursor.store(0.0);
        self.playback.rate.store(1.0);
        self.playback.target_rate.store(1.0);
        self.playback.rate_delta.store(0.0);
        self.playback.set_state(State::Loading);

        // Create output stream BEFORE spawning decode — if this fails, nothing to clean up
        let stream = output::build_output_stream(Arc::clone(&buffer), Arc::clone(&self.playback))
            .context("Failed to create audio output")?;

        // Spawn decode thread
        let cancel = Arc::new(AtomicBool::new(false));
        let decode_buffer = Arc::clone(&buffer);
        let decode_cancel = Arc::clone(&cancel);

        let handle = thread::spawn(move || {
            // Drop guard: mark_decode_complete fires on normal exit, error, AND panic.
            // Without this, a panic in symphonia would leave the callback stalled forever.
            struct Done(Arc<PcmBuffer>);
            impl Drop for Done {
                fn drop(&mut self) {
                    self.0.mark_decode_complete();
                }
            }
            let _done = Done(Arc::clone(&decode_buffer));

            match decode_session.decode_into(&decode_buffer, &decode_cancel) {
                Ok(()) => log::info!(
                    "Decode complete: {} samples ({:.1}s)",
                    decode_buffer.written(),
                    decode_buffer.buffered_secs()
                ),
                Err(e) => log::error!("Decode error: {}", e),
            }
        });

        self.buffer = Some(buffer);
        self.stream = Some(stream);
        self.decode = Some((cancel, handle));

        Ok(())
    }

    pub fn play(&self) {
        if self.buffer.is_some() {
            self.playback.set_state(State::Playing);
        }
    }

    pub fn pause(&self) {
        let state = self.playback.state();
        if state == State::Playing || state == State::Loading {
            self.playback.set_state(State::Paused);
        }
    }

    pub fn stop(&mut self) {
        self.stop_internal();
    }

    pub fn seek(&self, position_sec: f64) {
        if let Some(ref buffer) = self.buffer {
            let frame = (position_sec * buffer.sample_rate as f64).max(0.0);
            let max_frame = buffer.frames_written().saturating_sub(1) as f64;
            self.playback.cursor.store(frame.min(max_frame));
        }
    }

    pub fn set_speed(&self, speed: f64, direction: Option<Direction>, ramp_ms: u32) {
        let speed = speed.clamp(0.1, 10.0);
        let current_rate = self.playback.rate.load();
        let current_target = self.playback.target_rate.load();
        let sign = match direction {
            Some(Direction::Forward) => 1.0,
            Some(Direction::Reverse) => -1.0,
            None if current_rate < 0.0 || (current_rate == 0.0 && current_target < 0.0) => -1.0,
            None => 1.0,
        };
        let target_rate = speed * sign;

        self.playback.bump_speed_gen();
        self.playback.target_rate.store(target_rate);

        if ramp_ms == 0 {
            self.playback.rate.store(target_rate);
            self.playback.rate_delta.store(0.0);
        } else if let Some(ref buffer) = self.buffer {
            let current = self.playback.rate.load();
            let ramp_frames = (buffer.sample_rate as f64 * ramp_ms as f64 / 1000.0).max(1.0);
            self.playback.rate_delta.store((target_rate - current) / ramp_frames);
        }
    }

    pub fn set_volume(&self, percent: u32) {
        self.playback.volume.store(percent.min(200) as f32 / 100.0);
    }

    pub fn status(&self) -> StatusResponse {
        let (position_sec, buffer_sec, duration_sec) = match self.buffer.as_ref() {
            Some(buf) => {
                let pos = (self.playback.cursor.load() / buf.sample_rate as f64).max(0.0);
                let buffered = buf.buffered_secs();
                let duration = if buf.is_decode_complete() {
                    buffered
                } else {
                    self.duration_secs.max(buffered)
                };
                (pos.min(duration), buffered, duration)
            }
            None => (0.0, 0.0, 0.0),
        };

        StatusResponse {
            state: self.playback.state(),
            position_sec,
            buffer_sec,
            duration_sec,
            speed: self.playback.speed(),
            direction: self.playback.direction(),
            volume: self.playback.volume_percent(),
        }
    }

    /// Idempotent cleanup: sets Stopped, joins decode, drops stream + buffer.
    fn stop_internal(&mut self) {
        // Set state first — any in-flight audio callback sees Stopped
        // and outputs silence, before we drop the stream and buffer.
        self.playback.set_state(State::Stopped);
        self.playback.cursor.store(0.0);
        self.playback.rate.store(1.0);
        self.playback.target_rate.store(1.0);
        self.playback.rate_delta.store(0.0);

        if let Some((cancel, handle)) = self.decode.take() {
            cancel.store(true, Ordering::Release);
            let _ = handle.join();
        }

        self.stream = None;
        self.buffer = None;
        self.duration_secs = 0.0;
    }
}

impl Drop for Engine {
    fn drop(&mut self) {
        self.stop_internal();
    }
}
