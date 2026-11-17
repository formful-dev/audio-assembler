"""Plain-text report saved next to the finished file."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from .. import __version__

if TYPE_CHECKING:
    from .assemble import Plan


def fmt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    if h >= 1:
        return f"{int(h)}:{int(m):02d}:{s:05.2f}"
    return f"{int(m)}:{s:05.2f}"


def _channels(n: int) -> str:
    return {1: "mono", 2: "stereo"}.get(n, f"{n} channels")


def build_report(plan: "Plan", format_description: str, duration: float) -> str:
    s = plan.job.settings
    L: list[str] = []
    L.append(f"Audio Assembler {__version__} report")
    L.append(f"Created: {datetime.now():%Y-%m-%d %H:%M}")
    L.append("")
    L.append(f"Finished file: {plan.output_path}")
    L.append(f"Format: {format_description}")
    L.append(f"Total duration: {fmt_time(duration)} ({duration:.2f} s)")
    L.append("")
    L.append("Input files")
    for t in plan.tracks:
        a = t.audio
        L.append(f"  {t.letter} [{t.label}] {t.path}")
        L.append(f"      {a.source_rate} Hz, {_channels(a.source_channels)}, {fmt_time(a.duration)}")
    L.append(f"  Order list: {plan.order.path}")
    L.append(f"      {len(plan.order.rows)} rows, separator '{plan.order.separator}'")
    L.append(f"  Working format: {plan.rate} Hz, {_channels(plan.channels)}")
    L.append("")
    L.append("Settings")
    L.append(f"  Safety margin: {s.margin_seconds:.3f} s, fade: {s.fade_ms:g} ms")
    L.append(f"  Loudness matching: {'on' if s.match_loudness else 'off'}")
    for t in plan.tracks:
        d = t.detection
        L.append("")
        L.append(f"Cut detection [{t.label}]")
        L.append(f"  Silence level: {d.silence_level_db:.1f} dB "
                 f"({'automatic' if d.silence_level_auto else 'manual'}; background noise "
                 f"{d.noise_floor_db:.1f} dB, speech {d.speech_level_db:.1f} dB)")
        L.append(f"  Minimum silence for a cut: {d.min_cut_seconds:.2f} s ({d.cut_method})")
        L.append(f"  Segments found: {len(d.segments)}")
        L.append(f"  Ignored silence at start: {d.leading_silence:.2f} s, at end: {d.trailing_silence:.2f} s")
        L.append("  Cut silences: " + (", ".join(f"{x:.2f}" for x in d.cut_lengths) + " s"
                                       if d.cuts else "none"))
        L.append(f"  Longest speech pause kept inside a segment: {d.longest_speech_pause:.2f} s")
        if s.match_loudness and t.loudness_lufs is not None:
            L.append(f"  Loudness: {t.loudness_lufs:.1f} LUFS, gain applied: {t.gain_db:+.1f} dB")
        L.append("  Segments (sound start - end in the original file):")
        for seg in d.segments:
            a, b = seg.sound_start / d.rate, seg.sound_end / d.rate
            L.append(f"    {seg.number:3d}  {fmt_time(a)} - {fmt_time(b)}  ({b - a:.2f} s)")
    L.append("")
    L.append("Order")
    for t in plan.tracks:
        used = plan.order.used_segments(t.label)
        L.append(f"  {t.label}: {len(used)} of {len(t.detection.segments)} segments used")
    L.append(f"  Segments placed: {len(plan.order.rows)}")
    L.append(f"  Inserted gaps total: {plan.order.total_gap:.2f} s")
    L.append("")
    L.append("Warnings")
    L += [f"  - {w}" for w in plan.warnings] or ["  none"]
    L.append("")
    return "\n".join(L)

