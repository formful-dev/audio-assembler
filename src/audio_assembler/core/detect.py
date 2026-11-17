"""Finding cut silences and the segments between them.

How it works:
1. The file is split into 10 ms frames and the loudness of each frame is measured.
2. Silence level (automatic): set between the background noise and the speech level.
3. Every stretch of silence inside the file is a pause. Silence at the very start and end is ignored.
4. Cut length (automatic): the pause lengths are sorted and the biggest jump between neighbouring
   lengths separates natural speech pauses from cut pauses. If there is no clear jump, the order
   list (when given) may settle it; otherwise detection stops and asks for a manual value.
5. Each segment is trimmed to its sound, keeping a safety margin of silence on both sides.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .errors import DetectionError

FRAME_SECONDS = 0.01
MIN_PAUSE_SECONDS = 0.15     # shorter gaps are inside words, never cut candidates
CLICK_SECONDS = 0.02         # sound bursts this short inside silence are ignored when finding cuts
MIN_CUT_SECONDS = 0.3        # automatic mode never picks cut pauses shorter than this
CLEAR_RATIO = 2.0            # cut pauses must be at least this many times longer than speech pauses
DOMINANCE = 1.5              # the best jump must beat a second candidate jump by this factor
CONFIRM_RATIO = 1.5          # weaker jump accepted only when it matches the order list
SHORT_SEGMENT_SECONDS = 0.06  # shorter segments are probably clicks, not speech
NOISE_FLOOR_LIMIT_DB = -90.0
MIN_RANGE_DB = 12.0


@dataclass
class DetectionSettings:
    min_cut_seconds: float | None = None   # None = automatic
    silence_level_db: float | None = None  # None = automatic
    margin_seconds: float = 0.1


@dataclass
class Segment:
    number: int
    start: int          # first sample to copy (includes safety margin)
    end: int            # one past the last sample to copy
    sound_start: int    # first sample of sound
    sound_end: int      # one past the last sample of sound
    near_edge: bool = False  # sound touches the copied edge (possible clipping in the source)


@dataclass
class Detection:
    rate: int
    length: int
    noise_floor_db: float
    speech_level_db: float
    silence_level_db: float
    silence_level_auto: bool
    min_cut_seconds: float
    cut_method: str                       # human-readable description of how the cut length was set
    cut_auto: bool
    pauses: list[float]                   # all inside pauses, seconds, in file order
    cuts: list[tuple[int, int]]           # cut silences, sample ranges
    leading_silence: float
    trailing_silence: float
    segments: list[Segment]
    warnings: list[str] = field(default_factory=list)

    @property
    def cut_lengths(self) -> list[float]:
        return [(b - a) / self.rate for a, b in self.cuts]

    @property
    def longest_speech_pause(self) -> float:
        inside = [p for p in self.pauses if p < self.min_cut_seconds]
        return max(inside) if inside else 0.0


def frame_levels(mono: np.ndarray, rate: int) -> tuple[np.ndarray, int]:
    hop = max(1, round(rate * FRAME_SECONDS))
    n = math.ceil(len(mono) / hop)
    padded = np.zeros(n * hop, dtype=np.float64)
    padded[:len(mono)] = mono
    power = (padded.reshape(n, hop) ** 2).mean(axis=1)
    return 10.0 * np.log10(np.maximum(power, 1e-12)), hop


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """(start, end) index pairs of consecutive True values."""
    if mask.size == 0:
        return []
    m = np.concatenate(([False], mask, [False])).astype(np.int8)
    d = np.diff(m)
    return list(zip(np.flatnonzero(d == 1).tolist(), np.flatnonzero(d == -1).tolist()))


def _ignore_clicks(silent: np.ndarray, max_frames: int) -> np.ndarray:
    out = silent.copy()
    for a, b in _runs(~silent):
        if b - a <= max_frames and a > 0 and b < len(silent):
            out[a:b] = True
    return out


def _fmt_pauses(pauses: list[float], limit: int = 15) -> str:
    longest = sorted(pauses, reverse=True)[:limit]
    return ", ".join(f"{p:.2f}" for p in longest) + " s"


def _choose_cut_length(pauses: list[float], expected_segments: int | None, name: str) -> tuple[float, str]:
    """Return (min_cut_seconds, method) or raise DetectionError."""
    d = sorted(pauses)
    n = len(d)
    candidates = []  # (ratio, threshold, segment_count)
    for i in range(n - 1):
        lo, hi = d[i], d[i + 1]
        if hi >= MIN_CUT_SECONDS:
            candidates.append((hi / lo, math.sqrt(lo * hi), n - i))
    strong = sorted((c for c in candidates if c[0] >= CLEAR_RATIO), reverse=True)

    if strong and (len(strong) == 1 or strong[0][0] >= DOMINANCE * strong[1][0]):
        return strong[0][1], "automatic"

    if expected_segments is not None:
        # Also consider "every pause is a cut" and "no pause is a cut".
        options = list(candidates)
        if d and d[0] >= MIN_CUT_SECONDS:
            options.append((d[0] / MIN_PAUSE_SECONDS, d[0] * 0.8, n + 1))
        options.append((math.inf, (d[-1] * 1.25 if d else 1.0), 1))
        matching = [c for c in options if c[2] == expected_segments and c[0] >= CONFIRM_RATIO]
        if len(matching) == 1:
            return matching[0][1], "automatic, matched to the order list"
        if len(strong) > 1:
            matching = [c for c in strong if c[2] == expected_segments]
            if len(matching) == 1:
                return matching[0][1], "automatic, matched to the order list"

    if not d:
        return 1.0, "automatic"  # no pauses at all: one segment

    reason = ("there are two different groups of long pauses" if len(strong) > 1
              else "the cut pauses are not clearly longer than the normal speech pauses")
    raise DetectionError(
        f"Could not find the cut points automatically in '{name}': {reason}.",
        "Open Advanced and set 'Minimum silence for a cut' manually. Pick a value between the "
        "normal speech pauses and the longer cut pauses shown above.",
        details=[f"Longest pauses found: {_fmt_pauses(d)}", f"Number of pauses found: {n}"],
        pause_lengths=d,
    )


def detect_segments(mono: np.ndarray, rate: int, settings: DetectionSettings,
                    expected_segments: int | None = None, name: str = "audio") -> Detection:
    db, hop = frame_levels(mono, rate)
    n_frames = len(db)

    # Silence level
    # Background noise: the quiet end of the file. Speech: the typical level of frames clearly above it.
    # (Files can be mostly silence, so plain percentiles of all frames are not reliable for speech.)
    floor_used = max(float(np.percentile(db, 5)), NOISE_FLOOR_LIMIT_DB)
    loud = db[db > floor_used + MIN_RANGE_DB]
    speech = float(np.median(loud)) if loud.size else float(np.max(db))
    if settings.silence_level_db is None:
        if speech < -60:
            raise DetectionError(f"The audio file '{name}' seems to be silent or almost silent.",
                                 "Check that you selected the right file.")
        if loud.size < 10:
            raise DetectionError(
                f"Could not tell speech from background noise in '{name}'.",
                "Open Advanced and set the silence level manually, for example -45 dB.",
                details=[f"Background noise: {floor_used:.1f} dB, loudest sound: {speech:.1f} dB"],
            )
        level = floor_used + float(np.clip(0.25 * (speech - floor_used), 6.0, 25.0))
        level_auto = True
    else:
        level = float(settings.silence_level_db)
        level_auto = False

    silent = db < level
    if silent.all():
        raise DetectionError(f"No sound was found in '{name}' at the silence level {level:.1f} dB.",
                             "Choose Automatic silence level, or set a lower (more negative) value.")
    silent_for_cuts = _ignore_clicks(silent, round(CLICK_SECONDS / FRAME_SECONDS))

    runs = _runs(silent_for_cuts)
    leading = trailing = 0.0
    inner: list[tuple[int, int]] = []
    for a, b in runs:
        if a == 0:
            leading = min(b * hop, len(mono)) / rate
        elif b == n_frames:
            trailing = (len(mono) - a * hop) / rate
        else:
            inner.append((a, b))
    pause_runs = [(a, b) for a, b in inner if (b - a) * FRAME_SECONDS >= MIN_PAUSE_SECONDS - 1e-9]
    pauses = [(b - a) * hop / rate for a, b in pause_runs]

    # Cut length
    if settings.min_cut_seconds is None:
        min_cut, method = _choose_cut_length(pauses, expected_segments, name)
        cut_auto = True
    else:
        min_cut, method, cut_auto = float(settings.min_cut_seconds), "manual", False

    cut_runs = [(a, b) for (a, b), p in zip(pause_runs, pauses) if p >= min_cut - 1e-9]

    # Segments between cuts
    sound_lo = runs[0][1] if runs and runs[0][0] == 0 else 0
    sound_hi = runs[-1][0] if runs and runs[-1][1] == n_frames else n_frames
    bounds = [sound_lo]
    for a, b in cut_runs:
        bounds += [a, b]
    bounds.append(sound_hi)
    margin = round(settings.margin_seconds * rate)
    total = len(mono)

    segments: list[Segment] = []
    warnings: list[str] = []
    for i in range(0, len(bounds), 2):
        fa, fb = bounds[i], bounds[i + 1]
        sound = np.flatnonzero(~silent[fa:fb])
        if sound.size:
            fa, fb = fa + int(sound[0]), fa + int(sound[-1]) + 1
        s0, s1 = fa * hop, min(fb * hop, total)
        lo_limit = bounds[i - 1] * hop if i > 0 else 0
        hi_limit = min(bounds[i + 2] * hop, total) if i + 2 < len(bounds) else total
        start, end = max(lo_limit, s0 - margin), min(hi_limit, s1 + margin)
        near = (s0 - start) < hop or (end - s1) < hop
        seg = Segment(len(segments) + 1, start, end, s0, s1, near)
        segments.append(seg)
        if near and margin > 0:
            where = "start" if s0 - start < hop else "end"
            warnings.append(f"Segment {seg.number} of '{name}' has sound right at its {where}, with no "
                            "silence around it, so speech may already be cut off in the original file. "
                            "Listen to it in the result.")
        if (s1 - s0) / rate < SHORT_SEGMENT_SECONDS:
            warnings.append(f"Segment {seg.number} of '{name}' is very short ({(s1 - s0) / rate:.2f} s). "
                            "It may be a noise or click rather than speech.")

    det = Detection(
        rate=rate, length=total, noise_floor_db=floor_used, speech_level_db=speech,
        silence_level_db=level, silence_level_auto=level_auto, min_cut_seconds=min_cut,
        cut_method=method, cut_auto=cut_auto, pauses=pauses,
        cuts=[(a * hop, min(b * hop, total)) for a, b in cut_runs],
        leading_silence=leading, trailing_silence=trailing, segments=segments, warnings=warnings,
    )
    det.warnings += _cut_length_warnings(det.cut_lengths, name)
    return det


def _cut_length_warnings(lengths: list[float], name: str) -> list[str]:
    if len(lengths) < 2:
        return []
    median = float(np.median(lengths))
    odd = [(i + 1, x) for i, x in enumerate(lengths) if x < 0.6 * median or x > median / 0.6]
    if not odd:
        return []
    items = ", ".join(f"cut {i} is {x:.2f} s" for i, x in odd)
    return [f"In '{name}', some cut silences differ a lot from the usual {median:.2f} s: {items}. "
            "Check that these are real cut points."]
