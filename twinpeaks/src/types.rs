use serde::{Deserialize, Serialize};
use std::sync::atomic::{
    AtomicBool, AtomicU32, AtomicU64, AtomicU8, AtomicUsize, Ordering,
};

// --- Atomic wrappers for f64/f32 (bit-punned through integer atomics) ---

pub struct AtomicF64(AtomicU64);

impl AtomicF64 {
    pub fn new(v: f64) -> Self {
        Self(AtomicU64::new(v.to_bits()))
    }
    pub fn load(&self) -> f64 {
        f64::from_bits(self.0.load(Ordering::Relaxed))
    }
    pub fn store(&self, v: f64) {
        self.0.store(v.to_bits(), Ordering::Relaxed);
    }
    /// CAS: stores `new` only if current value is still `expected` (bitwise).
    pub fn compare_exchange(&self, expected: f64, new: f64) -> Result<f64, f64> {
        self.0
            .compare_exchange(
                expected.to_bits(),
                new.to_bits(),
                Ordering::Relaxed,
                Ordering::Relaxed,
            )
            .map(f64::from_bits)
            .map_err(f64::from_bits)
    }
}

pub struct AtomicF32(AtomicU32);

impl AtomicF32 {
    pub fn new(v: f32) -> Self {
        Self(AtomicU32::new(v.to_bits()))
    }
    pub fn load(&self) -> f32 {
        f32::from_bits(self.0.load(Ordering::Relaxed))
    }
    pub fn store(&self, v: f32) {
        self.0.store(v.to_bits(), Ordering::Relaxed);
    }
}

// --- IPC types ---

#[derive(Debug, Deserialize)]
#[serde(tag = "cmd", rename_all = "snake_case")]
pub enum Command {
    Load {
        path: String,
    },
    Play,
    Pause,
    Stop,
    Seek {
        position: f64,
    },
    SetSpeed {
        speed: f64,
        direction: Option<Direction>,
        #[serde(default)]
        ramp_ms: u32,
    },
    SetVolume {
        volume: u32,
    },
    Status,
    Quit,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Direction {
    Forward,
    Reverse,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
#[repr(u8)]
pub enum State {
    Stopped = 0,
    Playing = 1,
    Paused = 2,
    Loading = 3,
}

impl State {
    pub fn from_u8(v: u8) -> Self {
        match v {
            1 => State::Playing,
            2 => State::Paused,
            3 => State::Loading,
            _ => State::Stopped,
        }
    }
}

#[derive(Debug, Serialize)]
pub struct StatusResponse {
    pub state: State,
    pub position_sec: f64,
    pub buffer_sec: f64,
    pub duration_sec: f64,
    pub speed: f64,
    pub direction: Direction,
    pub volume: u32,
}

#[derive(Debug, Serialize)]
pub struct Response {
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    pub status: StatusResponse,
}

// --- PCM buffer (lock-free, single-producer single-consumer) ---
//
// The decode thread writes samples via push_samples() (advances write_cursor with Release).
// The audio thread reads via read_sample() (loads write_cursor with Acquire).
// Raw pointers avoid UnsafeCell aliasing — no &mut/& references to the data coexist.

pub struct PcmBuffer {
    data_ptr: *mut f32,
    data_len: usize,
    _data: Vec<f32>, // owns the heap allocation; never accessed after construction
    write_cursor: AtomicUsize,
    decode_complete: AtomicBool,
    overflow_warned: AtomicBool,
    pub sample_rate: u32,
    pub channels: u16,
}

unsafe impl Sync for PcmBuffer {}
unsafe impl Send for PcmBuffer {}

impl PcmBuffer {
    pub fn new(capacity_samples: usize, sample_rate: u32, channels: u16) -> Self {
        let mut data = vec![0.0f32; capacity_samples];
        let data_ptr = data.as_mut_ptr();
        let data_len = data.len();
        Self {
            data_ptr,
            data_len,
            _data: data,
            write_cursor: AtomicUsize::new(0),
            decode_complete: AtomicBool::new(false),
            overflow_warned: AtomicBool::new(false),
            sample_rate,
            channels,
        }
    }

    /// Append decoded samples. Called only from the decode thread.
    /// Returns true while the buffer still has free capacity after the write.
    pub fn push_samples(&self, samples: &[f32]) -> bool {
        let cursor = self.write_cursor.load(Ordering::Relaxed);
        let end = (cursor + samples.len()).min(self.data_len);
        let count = end - cursor;
        if count < samples.len() && !self.overflow_warned.swap(true, Ordering::Relaxed) {
            log::warn!(
                "PCM buffer full: dropping samples (capacity {}, at {}); further drop warnings suppressed for this track",
                self.data_len,
                cursor
            );
        }
        unsafe {
            std::ptr::copy_nonoverlapping(samples.as_ptr(), self.data_ptr.add(cursor), count);
        }
        self.write_cursor.store(end, Ordering::Release);
        end < self.data_len
    }

    /// Read one sample by index. Called only from the audio thread.
    pub fn read_sample(&self, index: usize) -> f32 {
        if index < self.data_len {
            unsafe { self.data_ptr.add(index).read() }
        } else {
            0.0
        }
    }

    pub fn written(&self) -> usize {
        self.write_cursor.load(Ordering::Acquire)
    }

    pub fn frames_written(&self) -> usize {
        self.written() / self.channels as usize
    }

    pub fn buffered_secs(&self) -> f64 {
        self.frames_written() as f64 / self.sample_rate as f64
    }

    pub fn is_decode_complete(&self) -> bool {
        self.decode_complete.load(Ordering::Acquire)
    }

    pub fn mark_decode_complete(&self) {
        self.decode_complete.store(true, Ordering::Release);
    }
}

// --- Playback state (all atomics, readable from the real-time audio callback) ---

pub struct PlaybackState {
    pub cursor: AtomicF64,
    pub rate: AtomicF64,
    pub target_rate: AtomicF64,
    pub rate_delta: AtomicF64,
    pub volume: AtomicF32,
    state: AtomicU8,
    speed_gen: AtomicU32,
}

impl PlaybackState {
    pub fn new() -> Self {
        Self {
            cursor: AtomicF64::new(0.0),
            rate: AtomicF64::new(1.0),
            target_rate: AtomicF64::new(1.0),
            rate_delta: AtomicF64::new(0.0),
            volume: AtomicF32::new(0.75),
            state: AtomicU8::new(State::Stopped as u8),
            speed_gen: AtomicU32::new(0),
        }
    }

    pub fn state(&self) -> State {
        State::from_u8(self.state.load(Ordering::Relaxed))
    }

    pub fn set_state(&self, s: State) {
        self.state.store(s as u8, Ordering::Relaxed);
    }

    pub fn direction(&self) -> Direction {
        let rate = self.rate.load();
        if rate < 0.0 {
            Direction::Reverse
        } else if rate > 0.0 {
            Direction::Forward
        } else if self.target_rate.load() < 0.0 {
            Direction::Reverse
        } else {
            Direction::Forward
        }
    }

    pub fn speed(&self) -> f64 {
        self.rate.load().abs()
    }

    pub fn volume_percent(&self) -> u32 {
        (self.volume.load() * 100.0).round().clamp(0.0, 200.0) as u32
    }

    pub fn speed_gen(&self) -> u32 {
        self.speed_gen.load(Ordering::Relaxed)
    }

    pub fn bump_speed_gen(&self) {
        self.speed_gen.fetch_add(1, Ordering::Relaxed);
    }
}

#[cfg(test)]
mod tests {
    use super::PcmBuffer;

    #[test]
    fn pcm_buffer_push_and_read_bounds() {
        let buf = PcmBuffer::new(4, 48_000, 1);

        assert!(buf.push_samples(&[0.1, 0.2, 0.3]));
        assert_eq!(buf.written(), 3);
        assert!((buf.read_sample(1) - 0.2).abs() < 1e-6);

        assert!(!buf.push_samples(&[0.4, 0.5, 0.6]));
        assert_eq!(buf.written(), 4);
        assert!((buf.read_sample(3) - 0.4).abs() < 1e-6);
        assert_eq!(buf.read_sample(999), 0.0);
    }
}
