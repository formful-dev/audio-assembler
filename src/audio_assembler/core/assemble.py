"""Single-lesson pipeline: prepare (read, detect, validate) then export (join, save, report)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from . import audio_io
from .audio_io import Audio, Progress
from .detect import Detection, DetectionSettings, detect_segments
from .errors import AssemblerError, OrderListError
from .naming import shared_base_name
from .orderlist import OrderList, read_order_list
from .settings import Settings


@dataclass
class Job:
    audio_a: str
    audio_b: str
    order_list: str
    label_a: str
    label_b: str
    settings: Settings = field(default_factory=Settings)
    output_dir: str | None = None     # default: folder of audio A
    output_name: str | None = None    # without extension; default: <shared base>_FINAL


@dataclass
class Track:
    letter: str
    label: str
    path: str
    audio: Audio
    detection: Detection
    loudness_lufs: float | None = None
    gain_db: float = 0.0


@dataclass
class Plan:
    job: Job
    tracks: list[Track]
    order: OrderList
    warnings: list[str]
    output_path: Path
    report_path: Path
    duration: float

    @property
    def rate(self) -> int:
        return self.tracks[0].audio.rate

    @property
    def channels(self) -> int:
        return self.tracks[0].audio.channels

    def track(self, label: str) -> Track:
        key = label.casefold()
        return next(t for t in self.tracks if t.label.casefold() == key)


@dataclass
class ExportResult:
    output_path: Path
    report_path: Path
    duration: float
    format_description: str
    warnings: list[str]


def _noop(_f: float, _m: str) -> None:
    pass


def _scaled(progress: Progress, lo: float, hi: float) -> Progress:
    return lambda f, m: progress(lo + (hi - lo) * f, m)


def output_paths(job: Job) -> tuple[Path, Path]:
    fmt = job.settings.output_format
    folder = Path(job.output_dir) if job.output_dir else Path(job.audio_a).parent
    name = job.output_name or f"{shared_base_name(job.audio_a, job.audio_b)}_FINAL"
    return folder / f"{name}.{fmt}", folder / f"{name}_report.txt"


def prepare(job: Job, progress: Progress | None = None) -> Plan:
    """Read everything, detect segments and check the order list. Raises AssemblerError on any problem.
    Nothing is written."""
    progress = progress or _noop
    s = job.settings
    s.validate()
    audio_io.check_input_file(job.audio_a, "audio file A")
    audio_io.check_input_file(job.audio_b, "audio file B")
    audio_io.check_input_file(job.order_list, "order list")

    label_a, label_b = job.label_a.strip(), job.label_b.strip()
    if not label_a or not label_b:
        raise AssemblerError("A track label is empty.",
                             "Type a label for each audio file, matching the labels in the order list (for example LV and EN).")
    if label_a.casefold() == label_b.casefold():
        raise AssemblerError(f"Both audio files have the same label '{label_a}'.",
                             "Give each audio file its own label, matching the labels in the order list.")

    out_path, report_path = output_paths(job)
    for p in (job.audio_a, job.audio_b, job.order_list):
        if Path(p).resolve() == out_path.resolve():
            raise AssemblerError("The finished file would overwrite one of the input files.",
                                 "Choose a different output name or folder.")
    if not out_path.parent.is_dir():
        raise AssemblerError(f"The output folder '{out_path.parent}' does not exist.",
                             "Choose an existing output folder.")

    progress(0.02, "Reading the order list")
    order = read_order_list(job.order_list)
    known = {label_a.casefold(), label_b.casefold()}
    unknown = sorted({r.label for r in order.rows if r.label.casefold() not in known})
    if unknown:
        rows = [f"Row {r.row} uses the label '{r.label}'" for r in order.rows if r.label in unknown][:10]
        raise OrderListError(
            f"The order list uses label(s) {', '.join(repr(u) for u in unknown)}, but the audio files are "
            f"labelled '{label_a}' and '{label_b}'.",
            "Change the track labels so they match the labels in the order list, or correct the order list.",
            rows,
        )

    audio_a, audio_b = audio_io.load_pair(job.audio_a, job.audio_b, _scaled(progress, 0.05, 0.6))

    det_settings = DetectionSettings(s.min_cut_seconds, s.silence_level_db, s.margin_seconds)
    tracks = []
    for letter, label, path, audio, frac in (("A", label_a, job.audio_a, audio_a, 0.65),
                                             ("B", label_b, job.audio_b, audio_b, 0.75)):
        progress(frac, f"Finding cut points in {Path(path).name}")
        expected = order.max_segment(label) or None
        det = detect_segments(audio.mono(), audio.rate, det_settings, expected, Path(path).name)
        tracks.append(Track(letter, label, path, audio, det))

    # Every row must point to an existing segment.
    counts = {t.label.casefold(): len(t.detection.segments) for t in tracks}
    missing = [r for r in order.rows if r.segment > counts[r.label.casefold()]]
    if missing:
        details = []
        for r in missing[:20]:
            t = next(t for t in tracks if t.label.casefold() == r.label.casefold())
            n = len(t.detection.segments)
            details.append(f"Row {r.row} (order {r.order_text}): {t.label} segment {r.segment} does not exist. "
                           f"{t.label} has only {n} segment{'s' if n != 1 else ''}.")
        if len(missing) > 20:
            details.append(f"... and {len(missing) - 20} more rows.")
        for t in tracks:
            if any(r.label.casefold() == t.label.casefold() for r in missing):
                d = t.detection
                cuts = ", ".join(f"{x:.2f}" for x in d.cut_lengths) or "none"
                details.append(f"{t.label}: {len(d.segments)} segments found, using cut silences of "
                               f"{d.min_cut_seconds:.2f} s or longer ({d.cut_method}). Cut silence lengths: {cuts} s.")
        raise OrderListError(
            "The order list asks for segments that do not exist.",
            "Check that the order list belongs to these audio files and that the segment numbers are right. "
            "If a cut point was missed, set 'Minimum silence for a cut' in Advanced to a lower value.",
            details,
        )

    warnings: list[str] = []
    for t in tracks:
        warnings += t.detection.warnings
        used = order.used_segments(t.label)
        unused = [seg.number for seg in t.detection.segments if seg.number not in used]
        if not used:
            warnings.append(f"The order list never uses the {t.label} audio file.")
        elif unused:
            warnings.append(f"{t.label}: {len(unused)} segment(s) are never used in the order list: "
                            f"{_ranges(unused)}.")

    if s.match_loudness:
        progress(0.85, "Measuring loudness")
        for t in tracks:
            t.loudness_lufs = audio_io.measure_loudness(t.path)
        if all(t.loudness_lufs is not None for t in tracks):
            target = min(t.loudness_lufs for t in tracks)
            for t in tracks:
                t.gain_db = target - t.loudness_lufs
        else:
            warnings.append("Loudness could not be measured, so the tracks were not matched.")

    plan = Plan(job, tracks, order, warnings, out_path, report_path, 0.0)
    total = 0
    for r in order.rows:
        seg = _segment(plan.track(r.label), r.segment)
        total += seg.end - seg.start + round(r.gap * plan.rate)
    plan.duration = total / plan.rate
    progress(1.0, "Checked")
    return plan


def _segment(track: Track, number: int):
    return track.detection.segments[number - 1]


def _ranges(nums: list[int]) -> str:
    parts, start, prev = [], None, None
    for n in nums + [None]:
        if start is None:
            start = prev = n
        elif n is not None and n == prev + 1:
            prev = n
        else:
            parts.append(f"{start}" if start == prev else f"{start}-{prev}")
            start = prev = n
    return ", ".join(parts)


def _fade(length: int, fade: int) -> tuple[np.ndarray, np.ndarray]:
    fade = min(fade, length // 2)
    if fade <= 0:
        return np.ones(0, np.float32), np.ones(0, np.float32)
    ramp = (0.5 - 0.5 * np.cos(np.pi * np.arange(fade) / fade)).astype(np.float32)
    return ramp, ramp[::-1]


def build_audio(plan: Plan) -> np.ndarray:
    rate, ch = plan.rate, plan.channels
    fade = round(plan.job.settings.fade_ms / 1000 * rate)
    pieces = []
    total = 0
    for r in plan.order.rows:
        t = plan.track(r.label)
        seg = _segment(t, r.segment)
        gap = round(r.gap * rate)
        pieces.append((t, seg, gap))
        total += (seg.end - seg.start) + gap
    out = np.zeros((total, ch), dtype=np.float32)
    pos = 0
    for t, seg, gap in pieces:
        chunk = t.audio.samples[seg.start:seg.end].copy()
        if t.gain_db:
            chunk *= np.float32(10 ** (t.gain_db / 20))
        fade_in, fade_out = _fade(len(chunk), fade)
        if fade_in.size:
            chunk[:fade_in.size] *= fade_in[:, None]
            chunk[-fade_out.size:] *= fade_out[:, None]
        out[pos:pos + len(chunk)] = chunk
        pos += len(chunk) + gap
    return out


def export(plan: Plan, progress: Progress | None = None) -> ExportResult:
    """Join the segments and save the finished file and the report."""
    from .report import build_report  # local import keeps report formatting separate

    progress = progress or _noop
    progress(0.0, "Joining segments")
    audio = build_audio(plan)
    desc = audio_io.encode(audio, plan.rate, str(plan.output_path), plan.job.settings.output_format,
                           _scaled(progress, 0.1, 0.95))
    duration = audio.shape[0] / plan.rate
    plan.report_path.write_text(build_report(plan, desc, duration), encoding="utf-8")
    progress(1.0, "Done")
    return ExportResult(plan.output_path, plan.report_path, duration, desc, plan.warnings)


def assemble(job: Job, confirm_warnings: Callable[[list[str]], bool] | None = None,
             progress: Progress | None = None) -> ExportResult | None:
    """Prepare and export in one call. If there are warnings, `confirm_warnings` decides whether to
    continue (default: continue). Returns None if the user declined."""
    progress = progress or _noop
    plan = prepare(job, _scaled(progress, 0.0, 0.5))
    if plan.warnings and confirm_warnings is not None and not confirm_warnings(plan.warnings):
        return None
    return export(plan, _scaled(progress, 0.5, 1.0))
