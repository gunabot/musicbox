use std::fs::File;
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};

use anyhow::{Context, Result};
use symphonia::core::audio::SampleBuffer;
use symphonia::core::codecs::{Decoder, DecoderOptions};
use symphonia::core::formats::{FormatOptions, FormatReader};
use symphonia::core::io::MediaSourceStream;
use symphonia::core::meta::MetadataOptions;
use symphonia::core::probe::Hint;

use crate::types::PcmBuffer;

#[derive(Clone, Copy)]
pub struct TrackMetadata {
    pub sample_rate: u32,
    pub channels: u16,
    pub duration_secs: f64,
    pub total_frames: u64,
}

pub struct DecodeSession {
    pub metadata: TrackMetadata,
    format: Box<dyn FormatReader>,
    decoder: Box<dyn Decoder>,
    track_id: u32,
    sample_buf: Option<SampleBuffer<f32>>,
}

fn hint_from_path(path: &str) -> Hint {
    let mut hint = Hint::new();
    if let Some(ext) = Path::new(path).extension().and_then(|e| e.to_str()) {
        hint.with_extension(ext);
    }
    hint
}

impl DecodeSession {
    /// Open and probe an audio track once, returning metadata + prepared decoder state.
    pub fn open(path: &str) -> Result<Self> {
        let file = File::open(path).with_context(|| format!("Cannot open {}", path))?;
        let mss = MediaSourceStream::new(Box::new(file), Default::default());

        let probed = symphonia::default::get_probe()
            .format(
                &hint_from_path(path),
                mss,
                &FormatOptions::default(),
                &MetadataOptions::default(),
            )
            .context("Failed to probe file")?;

        let format = probed.format;
        let (track_id, metadata, decoder) = {
            let track = format.default_track().context("No default track found")?;
            let params = &track.codec_params;

            let sample_rate = params.sample_rate.unwrap_or(44100);
            let channels = params.channels.map(|c| c.count() as u16).unwrap_or(2);
            anyhow::ensure!(sample_rate > 0, "Invalid sample rate: 0");
            anyhow::ensure!(channels > 0, "Invalid channel count: 0");

            let total_frames = params.n_frames.unwrap_or(0);
            let duration_secs = if total_frames > 0 {
                total_frames as f64 / sample_rate as f64
            } else {
                0.0
            };

            let decoder = symphonia::default::get_codecs()
                .make(params, &DecoderOptions::default())
                .context("Failed to create decoder")?;

            (
                track.id,
                TrackMetadata {
                    sample_rate,
                    channels,
                    duration_secs,
                    total_frames,
                },
                decoder,
            )
        };

        Ok(Self {
            metadata,
            format,
            decoder,
            track_id,
            sample_buf: None,
        })
    }

    /// Decode audio into the shared PcmBuffer. Runs on the calling thread.
    /// The caller is responsible for calling `buffer.mark_decode_complete()` afterward.
    pub fn decode_into(mut self, buffer: &PcmBuffer, cancel: &AtomicBool) -> Result<()> {
        loop {
            if cancel.load(Ordering::Acquire) {
                log::info!("Decode cancelled");
                return Ok(());
            }

            let packet = match self.format.next_packet() {
                Ok(p) => p,
                Err(symphonia::core::errors::Error::IoError(ref e))
                    if e.kind() == std::io::ErrorKind::UnexpectedEof =>
                {
                    return Ok(());
                }
                Err(e) => return Err(e.into()),
            };

            if packet.track_id() != self.track_id {
                continue;
            }

            let decoded = match self.decoder.decode(&packet) {
                Ok(d) => d,
                Err(symphonia::core::errors::Error::DecodeError(_)) => continue,
                Err(e) => return Err(e.into()),
            };

            if self.sample_buf.is_none() {
                self.sample_buf = Some(SampleBuffer::new(
                    decoded.capacity() as u64,
                    *decoded.spec(),
                ));
            }

            let buf = self.sample_buf.as_mut().unwrap();
            buf.copy_interleaved_ref(decoded);
            if !buffer.push_samples(buf.samples()) {
                log::warn!(
                    "PCM buffer reached capacity ({:.1}s), truncating decode",
                    buffer.buffered_secs()
                );
                return Ok(());
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::sync::atomic::AtomicBool;
    use std::time::{SystemTime, UNIX_EPOCH};

    use super::DecodeSession;
    use crate::types::PcmBuffer;

    fn unique_wav_path() -> std::path::PathBuf {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock went backwards")
            .as_nanos();
        std::env::temp_dir().join(format!(
            "twinpeaks_test_{}_{}.wav",
            std::process::id(),
            nanos
        ))
    }

    fn write_pcm16_wav(path: &std::path::Path, sample_rate: u32, channels: u16, samples: &[i16]) {
        let bytes_per_sample = 2u16;
        let block_align = channels * bytes_per_sample;
        let byte_rate = sample_rate * block_align as u32;
        let data_size = (samples.len() * 2) as u32;
        let riff_size = 4 + (8 + 16) + (8 + data_size);

        let mut out = Vec::with_capacity((44 + data_size) as usize);
        out.extend_from_slice(b"RIFF");
        out.extend_from_slice(&riff_size.to_le_bytes());
        out.extend_from_slice(b"WAVE");

        out.extend_from_slice(b"fmt ");
        out.extend_from_slice(&16u32.to_le_bytes());
        out.extend_from_slice(&1u16.to_le_bytes()); // PCM
        out.extend_from_slice(&channels.to_le_bytes());
        out.extend_from_slice(&sample_rate.to_le_bytes());
        out.extend_from_slice(&byte_rate.to_le_bytes());
        out.extend_from_slice(&block_align.to_le_bytes());
        out.extend_from_slice(&16u16.to_le_bytes()); // bits per sample

        out.extend_from_slice(b"data");
        out.extend_from_slice(&data_size.to_le_bytes());
        for s in samples {
            out.extend_from_slice(&s.to_le_bytes());
        }

        fs::write(path, out).expect("failed to write test wav");
    }

    #[test]
    fn decode_session_opens_and_decodes_wav() {
        let path = unique_wav_path();
        write_pcm16_wav(&path, 8000, 1, &[0, 1000, -1000, 2000, -2000, 0, 500, -500]);

        let session = DecodeSession::open(path.to_str().expect("utf8 path")).expect("open failed");
        assert_eq!(session.metadata.sample_rate, 8000);
        assert_eq!(session.metadata.channels, 1);
        assert!(session.metadata.duration_secs >= 0.0);

        let buffer = PcmBuffer::new(64, session.metadata.sample_rate, session.metadata.channels);
        let cancel = AtomicBool::new(false);
        session
            .decode_into(&buffer, &cancel)
            .expect("decode failed");

        assert!(buffer.written() > 0);
        assert_eq!(buffer.frames_written(), 8);

        fs::remove_file(path).ok();
    }

    #[test]
    fn decode_session_honors_pre_set_cancel() {
        let path = unique_wav_path();
        write_pcm16_wav(&path, 8000, 1, &[1, 2, 3, 4, 5, 6, 7, 8]);

        let session = DecodeSession::open(path.to_str().expect("utf8 path")).expect("open failed");
        let buffer = PcmBuffer::new(64, session.metadata.sample_rate, session.metadata.channels);
        let cancel = AtomicBool::new(true);

        session
            .decode_into(&buffer, &cancel)
            .expect("decode with cancel failed");
        assert_eq!(buffer.written(), 0);

        fs::remove_file(path).ok();
    }
}
