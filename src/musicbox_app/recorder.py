from __future__ import annotations

import os
import re
import shlex
import shutil
import signal
import subprocess
import threading
import time
import wave
from array import array
from pathlib import Path

from .config import (
    AUDIO_DEVICE,
    RECORD_ARECORD_BIN,
    RECORD_CHANNELS,
    RECORD_DEVICE,
    RECORD_EDGE_FADE_MS,
    RECORD_SAMPLE_FORMAT,
    RECORD_SAMPLE_RATE,
    RECORDING_PREVIEW_NAME,
    RECORDINGS_DIR,
    RECORD_STOP_TIMEOUT_S,
)
from .media import rel_from_abs
from .store import AppStore


class RecorderManager:
    def __init__(
        self,
        store: AppStore,
        *,
        arecord_bin: str = RECORD_ARECORD_BIN,
        device: str = RECORD_DEVICE,
        recordings_dir: Path = RECORDINGS_DIR,
        preview_name: str = RECORDING_PREVIEW_NAME,
        sample_format: str = RECORD_SAMPLE_FORMAT,
        sample_rate: int = RECORD_SAMPLE_RATE,
        channels: int = RECORD_CHANNELS,
        stop_timeout_s: float = RECORD_STOP_TIMEOUT_S,
        edge_fade_ms: float = RECORD_EDGE_FADE_MS,
    ) -> None:
        self.store = store
        self.arecord_bin = str(arecord_bin).strip() or 'arecord'
        self.device = str(device).strip()
        self.recordings_dir = Path(recordings_dir)
        self.preview_name = str(preview_name).strip() or 'red-button.wav'
        self.sample_format = str(sample_format).strip() or 'S16_LE'
        self.sample_rate = max(8000, int(sample_rate))
        self.channels = max(1, min(2, int(channels)))
        self.stop_timeout_s = max(0.5, float(stop_timeout_s))
        self.edge_fade_ms = max(0.0, float(edge_fade_ms))
        self._lock = threading.RLock()
        self._proc: subprocess.Popen[bytes] | None = None
        self._started_at_mono = 0.0
        self._tmp_path = self.recordings_dir / f'.{self.preview_name}.part'
        self._final_path = self.recordings_dir / self.preview_name
        self._last_recording_relpath: str | None = None

    def is_recording(self) -> bool:
        with self._lock:
            return self._proc_alive_locked()

    def last_recording_relpath(self) -> str | None:
        with self._lock:
            return self._last_recording_relpath

    def start(self) -> bool:
        with self._lock:
            if self._proc_alive_locked():
                return False
            binary = shutil.which(self.arecord_bin)
            if not binary:
                raise FileNotFoundError(f'{self.arecord_bin} not found')

            self.recordings_dir.mkdir(parents=True, exist_ok=True)
            if self._tmp_path.exists():
                self._tmp_path.unlink()

            device = self._resolve_device()
            cmd = [
                binary,
                '-q',
                '-D',
                device,
                '-f',
                self.sample_format,
                '-r',
                str(self.sample_rate),
                '-c',
                str(self.channels),
                '-t',
                'wav',
                str(self._tmp_path),
            ]
            self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._started_at_mono = time.monotonic()
            time.sleep(0.05)
            if not self._proc_alive_locked():
                self._tmp_path.unlink(missing_ok=True)
                raise RuntimeError(f'arecord exited early for {device}')
            self.store.set_recording_state(active=True)
            self.store.add_event(f'RECORD_START {device}')
            return True

    def stop(self) -> str | None:
        with self._lock:
            proc = self._proc
            self._proc = None
            self.store.set_recording_state(active=False)
            if proc is None:
                return None

            if proc.poll() is None:
                try:
                    proc.send_signal(signal.SIGINT)
                except Exception:
                    pass
                try:
                    proc.wait(timeout=self.stop_timeout_s)
                except Exception:
                    proc.terminate()
                    try:
                        proc.wait(timeout=self.stop_timeout_s)
                    except Exception:
                        proc.kill()
                        proc.wait(timeout=self.stop_timeout_s)

            if not self._tmp_path.exists():
                self.store.add_event('RECORD_EMPTY', level='warning')
                return None

            size_bytes = 0
            try:
                size_bytes = int(self._tmp_path.stat().st_size)
            except Exception:
                size_bytes = 0
            if size_bytes <= 44:
                self._tmp_path.unlink(missing_ok=True)
                self.store.add_event('RECORD_EMPTY', level='warning')
                return None

            self._soften_edges(self._tmp_path)
            os.replace(self._tmp_path, self._final_path)
            relpath = rel_from_abs(self._final_path)
            self._last_recording_relpath = relpath
            self.store.set_recording_state(file=relpath)
            duration_s = max(0.0, time.monotonic() - self._started_at_mono)
            self.store.add_event(f'RECORD_SAVED {relpath} ({duration_s:.1f}s, {size_bytes}B)')
            return relpath

    def cancel(self) -> None:
        with self._lock:
            proc = self._proc
            self._proc = None
            self.store.set_recording_state(active=False)
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass
            self._tmp_path.unlink(missing_ok=True)

    def _resolve_device(self) -> str:
        configured = str(self.device).strip()
        if configured:
            return configured

        cards = self._list_capture_cards()
        for index, _name, line in cards:
            if 'wm8960' in line.lower():
                return f'plughw:{index},0'

        normalized = str(AUDIO_DEVICE or '').strip()
        if normalized.lower().startswith('alsa/'):
            normalized = normalized.split('/', 1)[1].strip()

        match = re.match(r'(?i)(?:plug)?hw:([^,]+)(?:,(\d+))?$', normalized)
        if match:
            card = match.group(1)
            if any(index == card for index, _name, _line in cards):
                return f'plughw:{card},0'

        if normalized:
            lower = normalized.lower()
            for index, name, line in cards:
                if lower == name.lower() or lower in line.lower():
                    return f'plughw:{index},0'

        if cards:
            return f'plughw:{cards[0][0]},0'

        return 'plughw:0,0'

    def _list_capture_cards(self) -> list[tuple[str, str, str]]:
        binary = shutil.which(self.arecord_bin)
        if not binary:
            return []
        try:
            output = subprocess.check_output([binary, '-l'], text=True, stderr=subprocess.DEVNULL)
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

    def _proc_alive_locked(self) -> bool:
        if self._proc is None:
            return False
        if self._proc.poll() is None:
            return True
        self._proc = None
        self.store.set_recording_state(active=False)
        return False

    def debug_command(self) -> str:
        binary = shutil.which(self.arecord_bin) or self.arecord_bin
        cmd = [
            binary,
            '-q',
            '-D',
            self._resolve_device(),
            '-f',
            self.sample_format,
            '-r',
            str(self.sample_rate),
            '-c',
            str(self.channels),
            '-t',
            'wav',
            str(self._tmp_path),
        ]
        return shlex.join(cmd)

    def _soften_edges(self, path: Path) -> None:
        fade_ms = self.edge_fade_ms
        if fade_ms <= 0.0:
            return
        try:
            with wave.open(str(path), 'rb') as wav_file:
                params = wav_file.getparams()
                if params.sampwidth != 2 or params.nframes <= 1:
                    return
                frame_rate = int(params.framerate)
                channels = max(1, int(params.nchannels))
                fade_frames = min(int((frame_rate * fade_ms) / 1000.0), params.nframes // 2)
                if fade_frames <= 0:
                    return
                raw_frames = wav_file.readframes(params.nframes)

            samples = array('h')
            samples.frombytes(raw_frames)
            if len(samples) != params.nframes * channels:
                return

            denom = max(1, fade_frames - 1)
            for frame_index in range(fade_frames):
                fade_in = frame_index / denom if denom else 0.0
                fade_out = (fade_frames - 1 - frame_index) / denom if denom else 0.0
                start_offset = frame_index * channels
                end_offset = (params.nframes - fade_frames + frame_index) * channels
                for channel in range(channels):
                    start_sample = samples[start_offset + channel]
                    end_sample = samples[end_offset + channel]
                    samples[start_offset + channel] = int(round(start_sample * fade_in))
                    samples[end_offset + channel] = int(round(end_sample * fade_out))

            tmp_output = path.with_suffix(path.suffix + '.fade')
            with wave.open(str(tmp_output), 'wb') as wav_file:
                wav_file.setparams(params)
                wav_file.writeframes(samples.tobytes())
            os.replace(tmp_output, path)
        except Exception:
            try:
                if 'tmp_output' in locals():
                    tmp_output.unlink(missing_ok=True)
            except Exception:
                pass
