"""Generated test audio: speech-like sound with known pauses, segments and cut silences."""

from __future__ import annotations

import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class Track:
    samples: np.ndarray          # float32 (frames, channels)
    rate: int
    segments: list[tuple[int, int]] = field(default_factory=list)   # true sound ranges, samples
    natural_pauses: list[float] = field(default_factory=list)
    cut_pauses: list[float] = field(default_factory=list)


def _syllable(rate: int, dur: float, f0: float, rng: np.random.Generator) -> np.ndarray:
    n = int(dur * rate)
    t = np.arange(n) / rate
    tone = sum(np.sin(2 * np.pi * f0 * k * t + rng.uniform(0, 6.28)) / k for k in range(1, 6))
    env = np.hanning(n) ** 0.5   # quick rise like a real onset, but no hard edge
    return (0.25 * tone * env).astype(np.float32)


def _word(rate: int, rng: np.random.Generator) -> np.ndarray:
    parts = []
    for i in range(int(rng.integers(1, 4))):
        if i:
            parts.append(np.zeros(int(0.03 * rate), np.float32))  # tiny gap inside a word
        parts.append(_syllable(rate, rng.uniform(0.08, 0.16), rng.uniform(110, 240), rng))
    return np.concatenate(parts)


def make_track(segment_words: list[int], cut_pause, natural_pause, rate: int = 16000,
               lead: float = 0.5, trail: float = 0.5, noise_db: float = -70.0,
               channels: int = 1, seed: int = 1, level: float = 1.0) -> Track:
    """segment_words: number of words in each segment.
    cut_pause / natural_pause: seconds, or a callable(rng) -> seconds."""
    rng = np.random.default_rng(seed)

    def pick(v):
        return v(rng) if callable(v) else v

    out: list[np.ndarray] = [np.zeros(int(lead * rate), np.float32)]
    pos = len(out[0])
    track = Track(np.zeros((0, 1)), rate)
    for si, words in enumerate(segment_words):
        if si:
            p = pick(cut_pause)
            track.cut_pauses.append(p)
            out.append(np.zeros(int(p * rate), np.float32))
            pos += len(out[-1])
        start = pos
        for wi in range(words):
            if wi:
                p = pick(natural_pause)
                track.natural_pauses.append(p)
                out.append(np.zeros(int(p * rate), np.float32))
                pos += len(out[-1])
            w = _word(rate, rng) * level
            out.append(w)
            pos += len(w)
        track.segments.append((start, pos))
    out.append(np.zeros(int(trail * rate), np.float32))
    mono = np.concatenate(out)
    if noise_db is not None:
        mono = mono + rng.normal(0, 10 ** (noise_db / 20), len(mono)).astype(np.float32)
    samples = np.repeat(mono[:, None], channels, axis=1) if channels > 1 else mono[:, None]
    track.samples = samples.astype(np.float32)
    return track


def write_wav(path: Path, samples: np.ndarray, rate: int) -> Path:
    data = np.clip(samples, -1, 1)
    pcm = (data * 32767).round().astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(samples.shape[1])
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return path


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        rate, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        pcm = np.frombuffer(w.readframes(n), dtype="<i2").reshape(-1, ch)
    return pcm.astype(np.float32) / 32767, rate


def write_order(path: Path, rows: list[tuple], header: str = "order,language,segment,gap_seconds",
                sep: str = ",", bom: bool = False, decimal_comma: bool = False) -> Path:
    lines = [header] if header else []
    for r in rows:
        cells = [str(c) for c in r]
        if decimal_comma:
            cells = [c.replace(".", ",") for c in cells]
        lines.append(sep.join(cells))
    text = "\n".join(lines) + "\n"
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
    return path
