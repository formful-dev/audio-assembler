"""Reading and writing audio through ffmpeg. Audio is held as float32 arrays of shape (frames, channels)."""

from __future__ import annotations

import functools
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from .errors import AssemblerError, AudioError

AUDIO_EXTENSIONS = (".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".aif", ".aiff")

Progress = Callable[[float, str], None]


@dataclass
class Audio:
    samples: np.ndarray  # float32, shape (frames, channels)
    rate: int
    source_rate: int
    source_channels: int

    @property
    def channels(self) -> int:
        return self.samples.shape[1]

    @property
    def duration(self) -> float:
        return self.samples.shape[0] / self.rate

    def mono(self) -> np.ndarray:
        if self.channels == 1:
            return self.samples[:, 0]
        return self.samples.mean(axis=1, dtype=np.float32)


def _popen_kwargs() -> dict:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


@functools.lru_cache(maxsize=1)
def find_ffmpeg() -> str:
    exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    candidates: list[Path] = []
    env = os.environ.get("AUDIO_ASSEMBLER_FFMPEG")
    if env:
        candidates.append(Path(env))
    if getattr(sys, "frozen", False):
        bundle = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidates += [bundle / "ffmpeg" / exe, Path(sys.executable).parent / "ffmpeg" / exe]
    # Source checkout: <repo>/vendor/ffmpeg/
    candidates.append(Path(__file__).resolve().parents[3] / "vendor" / "ffmpeg" / exe)
    for c in candidates:
        if c.is_file():
            return str(c)
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise AssemblerError(
        "The audio engine (ffmpeg) was not found.",
        "Reinstall the app. If you run it from source code, install ffmpeg and check that "
        "the 'ffmpeg' command works in a terminal.",
    )


def _run_ffmpeg_read(args: list[str]) -> tuple[bytes, str, int]:
    cmd = [find_ffmpeg(), "-nostdin", "-hide_banner", *args]
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, **_popen_kwargs())
        out = proc.stdout.read()
        proc.stdout.close()
        code = proc.wait()
        err.seek(0)
        return out, err.read().decode("utf-8", "replace"), code


def _parse_wav(buf: bytes) -> tuple[np.ndarray, int, int]:
    if len(buf) < 12 or buf[:4] != b"RIFF" or buf[8:12] != b"WAVE":
        raise ValueError("not a WAV stream")
    pos, channels, rate, data = 12, None, None, None
    while pos + 8 <= len(buf):
        cid = buf[pos:pos + 4]
        size = int.from_bytes(buf[pos + 4:pos + 8], "little")
        body = pos + 8
        if cid == b"fmt ":
            _tag, channels, rate = struct.unpack("<HHI", buf[body:body + 8])
        elif cid == b"data":
            end = len(buf) if size == 0xFFFFFFFF or body + size > len(buf) else body + size
            data = memoryview(buf)[body:end]
            break
        pos = body + size + (size & 1)
    if channels is None or data is None or not channels:
        raise ValueError("incomplete WAV stream")
    usable = len(data) - len(data) % (4 * channels)
    samples = np.frombuffer(data[:usable], dtype="<f4").reshape(-1, channels)
    return samples, rate, channels


def decode(path: str, rate: int | None = None, channels: int | None = None) -> tuple[np.ndarray, int, int]:
    args = ["-loglevel", "error", "-i", path, "-vn", "-map", "0:a:0"]
    if rate:
        args += ["-ar", str(rate)]
    if channels:
        args += ["-ac", str(channels)]
    args += ["-c:a", "pcm_f32le", "-f", "wav", "pipe:1"]
    out, err, code = _run_ffmpeg_read(args)
    name = Path(path).name
    if code != 0 or not out:
        raise AudioError(
            f"Could not read the audio file '{name}'.",
            "Check that the file is a working audio file (for example WAV or MP3): "
            "try playing it in a media player. If it plays, convert it to WAV and try again.",
            details=[err.strip().splitlines()[-1]] if err.strip() else None,
        )
    try:
        samples, r, ch = _parse_wav(out)
    except ValueError:
        raise AudioError(f"Could not read the audio file '{name}'.",
                         "Convert the file to WAV and try again.") from None
    if samples.shape[0] == 0:
        raise AudioError(f"The audio file '{name}' is empty.", "Choose a file that contains audio.")
    return samples, r, ch


def check_input_file(path: str, what: str) -> None:
    p = Path(path)
    if not str(path).strip():
        raise AssemblerError(f"No {what} is selected.", f"Choose the {what}.")
    if not p.is_file():
        raise AssemblerError(f"The {what} '{p.name}' was not found.",
                             "Check that the file still exists and choose it again.")


def load_pair(path_a: str, path_b: str, progress: Progress | None = None) -> tuple[Audio, Audio]:
    """Decode two files and convert both to one common format:
    the higher sample rate and the higher channel count (at most stereo)."""
    report = progress or (lambda f, m: None)
    report(0.0, f"Reading {Path(path_a).name}")
    sa, ra, ca = decode(path_a)
    report(0.5, f"Reading {Path(path_b).name}")
    sb, rb, cb = decode(path_b)
    rate = max(ra, rb)
    channels = min(2, max(ca, cb))
    if (ra, ca) != (rate, channels):
        sa_c, _, _ = decode(path_a, rate, channels)
    else:
        sa_c = sa
    if (rb, cb) != (rate, channels):
        sb_c, _, _ = decode(path_b, rate, channels)
    else:
        sb_c = sb
    report(1.0, "Audio loaded")
    return Audio(sa_c, rate, ra, ca), Audio(sb_c, rate, rb, cb)


def mp3_bitrate_kbps(rate: int) -> int:
    """Highest MP3 bitrate allowed at this sample rate."""
    if rate >= 32000:
        return 320
    if rate >= 16000:
        return 160
    return 64


def encode(samples: np.ndarray, rate: int, path: str, fmt: str, progress: Progress | None = None) -> str:
    """Write audio to `path` safely: write a temporary file first, then rename.
    Returns a short description of the written format."""
    report = progress or (lambda f, m: None)
    out = Path(path)
    channels = samples.shape[1]
    if fmt == "mp3":
        out_rate = rate if rate <= 48000 else 48000
        kbps = mp3_bitrate_kbps(out_rate)
        codec = ["-c:a", "libmp3lame", "-b:a", f"{kbps}k", "-ar", str(out_rate), "-f", "mp3"]
        desc = f"MP3, {kbps} kbps, {out_rate} Hz"
    elif fmt == "wav":
        codec = ["-c:a", "pcm_s16le", "-f", "wav"]
        desc = f"WAV, 16-bit, {rate} Hz"
    else:
        raise ValueError(fmt)
    desc += ", mono" if channels == 1 else ", stereo"

    fd, tmp = tempfile.mkstemp(prefix=".~", suffix=".part", dir=str(out.parent))
    os.close(fd)
    cmd = [find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
           "-f", "f32le", "-ar", str(rate), "-ac", str(channels), "-i", "pipe:0",
           *codec, tmp]
    data = np.ascontiguousarray(samples, dtype="<f4")
    raw = memoryview(data).cast("B")
    chunk = 1 << 22
    try:
        with tempfile.TemporaryFile() as err:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=err,
                                    **_popen_kwargs())
            try:
                for i in range(0, len(raw), chunk):
                    proc.stdin.write(raw[i:i + chunk])
                    report(min(1.0, (i + chunk) / max(1, len(raw))), "Saving")
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            code = proc.wait()
            err.seek(0)
            msg = err.read().decode("utf-8", "replace").strip()
        if code != 0:
            raise AudioError(f"Could not save the finished file '{out.name}'.",
                             "Check that the output folder exists, that you can write to it, "
                             "and that the disk is not full.",
                             details=[msg.splitlines()[-1]] if msg else None)
        try:
            os.replace(tmp, out)
        except PermissionError:
            raise AudioError(f"Could not save '{out.name}' because the file is open in another program.",
                             "Close the file in your media player or other program and try again.") from None
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return desc


def measure_loudness(path: str) -> float | None:
    """Integrated loudness (LUFS, EBU R128) of the first audio stream, or None if unmeasurable."""
    _, err, code = _run_ffmpeg_read(["-nostats", "-i", path, "-vn", "-map", "0:a:0",
                                     "-af", "ebur128=framelog=quiet", "-f", "null", "-"])
    if code != 0:
        return None
    matches = re.findall(r"I:\s+(-?[\d.]+|-inf)\s+LUFS", err)
    if not matches or matches[-1] == "-inf":
        return None
    return float(matches[-1])
