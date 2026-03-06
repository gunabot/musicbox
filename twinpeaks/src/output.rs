use std::sync::Arc;

use anyhow::{Context, Result};
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use cpal::{SampleRate, Stream, StreamConfig};

use crate::types::{PcmBuffer, PlaybackState, State};

pub fn build_output_stream(buffer: Arc<PcmBuffer>, playback: Arc<PlaybackState>) -> Result<Stream> {
    let host = cpal::default_host();
    let device = select_output_device(&host)?;

    log::info!("Output device: {}", device.name().unwrap_or_default());

    let config = StreamConfig {
        channels: buffer.channels,
        sample_rate: SampleRate(buffer.sample_rate),
        buffer_size: cpal::BufferSize::Default,
    };

    let stream = device
        .build_output_stream(
            &config,
            move |data: &mut [f32], _: &cpal::OutputCallbackInfo| {
                audio_callback(data, &buffer, &playback);
            },
            |err| {
                log::error!("Audio output error: {}", err);
            },
            None,
        )
        .context("Failed to build output stream")?;

    stream.play().context("Failed to start output stream")?;
    Ok(stream)
}

fn select_output_device(host: &cpal::Host) -> Result<cpal::Device> {
    let preferred = std::env::var("MUSICBOX_TWINPEAKS_OUTPUT_HINT")
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty());

    if let Some(hint) = preferred {
        let devices = host
            .output_devices()
            .context("Failed to enumerate output devices")?;
        let hint_lower = hint.to_ascii_lowercase();
        let mut best_match: Option<(i32, cpal::Device)> = None;
        let mut seen_names: Vec<String> = Vec::new();

        for device in devices {
            let name = device.name().unwrap_or_default();
            seen_names.push(name.clone());
            let score = device_match_score(&name, &hint_lower);
            if score <= 0 {
                continue;
            }
            match &best_match {
                Some((best_score, _)) if *best_score >= score => {}
                _ => best_match = Some((score, device)),
            }
        }

        if let Some((_, device)) = best_match {
            return Ok(device);
        }

        log::warn!(
            "No output device matched hint '{}'. Available devices: {}",
            hint,
            seen_names.join(", ")
        );
    }

    host.default_output_device()
        .context("No default output device")
}

fn device_match_score(name: &str, hint_lower: &str) -> i32 {
    let normalized = name.trim().to_ascii_lowercase();
    if normalized.is_empty() || !normalized.contains(hint_lower) {
        return 0;
    }

    let mut score = 10;
    if normalized.starts_with("plughw:") {
        score += 50;
    } else if normalized.starts_with("sysdefault:") {
        score += 40;
    } else if normalized.starts_with("front:") {
        score += 30;
    } else if normalized.starts_with("hw:") {
        score += 20;
    }
    if normalized.contains("pipewire") || normalized == "default" || normalized == "null" {
        score -= 100;
    }
    score
}

/// The real-time audio callback. No allocations, no locks.
fn audio_callback(data: &mut [f32], buffer: &PcmBuffer, playback: &PlaybackState) {
    let channels = buffer.channels as usize;

    // Auto-start: Loading → Playing once enough data is buffered
    let mut state = playback.state();
    if state == State::Loading {
        let min_frames = buffer.sample_rate as usize / 2;
        if buffer.frames_written() >= min_frames || buffer.is_decode_complete() {
            playback.set_state(State::Playing);
            state = State::Playing;
        }
    }
    if state != State::Playing {
        data.fill(0.0);
        return;
    }

    // Read decode_done FIRST: if true, mark_decode_complete's Release
    // synchronizes with our Acquire, guaranteeing written_frames is final.
    let decode_done = buffer.is_decode_complete();
    let written_frames = buffer.frames_written();
    let volume = playback.volume.load();

    let original_cursor = playback.cursor.load();
    let mut cursor = original_cursor;
    let mut rate = playback.rate.load();
    let target_rate = playback.target_rate.load();
    let rate_delta = playback.rate_delta.load();
    let speed_gen = playback.speed_gen();
    let mut written_samples = 0usize;

    for frame in data.chunks_exact_mut(channels) {
        // Per-sample speed ramping
        if rate_delta != 0.0 && rate != target_rate {
            rate += rate_delta;
            if (rate_delta > 0.0 && rate > target_rate)
                || (rate_delta < 0.0 && rate < target_rate)
            {
                rate = target_rate;
            }
        }

        let frame_idx = cursor.floor() as i64;

        if frame_idx < 0 {
            playback.set_state(State::Paused);
            cursor = 0.0;
            break;
        }

        let frame_idx = frame_idx as usize;

        if frame_idx >= written_frames {
            if decode_done {
                playback.set_state(State::Stopped);
            }
            break;
        }

        // Linear interpolation between adjacent frames
        let frac = (cursor - cursor.floor()) as f32;
        let next_idx = (frame_idx + 1).min(written_frames.saturating_sub(1));

        for (ch, sample) in frame.iter_mut().enumerate() {
            let s0 = buffer.read_sample(frame_idx * channels + ch);
            let s1 = buffer.read_sample(next_idx * channels + ch);
            *sample = (s0 + (s1 - s0) * frac) * volume;
        }

        written_samples += channels;
        cursor += rate;
    }

    if written_samples < data.len() {
        data[written_samples..].fill(0.0);
    }

    // CAS cursor writeback: only update if no seek occurred during this callback.
    let _ = playback.cursor.compare_exchange(original_cursor, cursor);

    // Generation-guarded speed writeback: only update if no set_speed occurred
    // during this callback. If delta was 0, the main thread owns the speed atomic.
    if rate_delta != 0.0 && playback.speed_gen() == speed_gen {
        playback.rate.store(rate);
        if rate == target_rate {
            playback.rate_delta.store(0.0);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::audio_callback;
    use crate::types::{PcmBuffer, PlaybackState, State};

    use super::device_match_score;

    #[test]
    fn callback_outputs_silence_when_not_playing() {
        let buffer = PcmBuffer::new(16, 8_000, 1);
        buffer.push_samples(&[1.0, 1.0, 1.0, 1.0]);

        let playback = PlaybackState::new();
        playback.set_state(State::Paused);

        let mut out = vec![0.5f32; 8];
        audio_callback(&mut out, &buffer, &playback);

        assert!(out.iter().all(|v| *v == 0.0));
    }

    #[test]
    fn callback_writes_samples_and_zeroes_tail() {
        let buffer = PcmBuffer::new(16, 8_000, 1);
        assert!(buffer.push_samples(&[0.0, 1.0]));
        buffer.mark_decode_complete();

        let playback = PlaybackState::new();
        playback.volume.store(1.0);
        playback.cursor.store(0.0);
        playback.rate.store(1.0);
        playback.target_rate.store(1.0);
        playback.rate_delta.store(0.0);
        playback.set_state(State::Playing);

        let mut out = vec![9.0f32; 4];
        audio_callback(&mut out, &buffer, &playback);

        assert!((out[0] - 0.0).abs() < 1e-6);
        assert!((out[1] - 1.0).abs() < 1e-6);
        assert!((out[2] - 0.0).abs() < 1e-6);
        assert!((out[3] - 0.0).abs() < 1e-6);
        assert_eq!(playback.state(), State::Stopped);
    }

    #[test]
    fn device_match_score_prefers_real_alsa_outputs() {
        assert!(
            device_match_score("plughw:CARD=UACDemoV10,DEV=0", "uacdemov10")
                > device_match_score("default", "uacdemov10")
        );
        assert_eq!(device_match_score("default", "uacdemov10"), 0);
        assert_eq!(device_match_score("null", "uacdemov10"), 0);
    }
}
