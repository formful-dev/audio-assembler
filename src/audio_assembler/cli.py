"""Command line interface.

  audio-assembler lesson A.mp3 B.mp3 ORDER.csv [options]
  audio-assembler folder FOLDER [options]
  audio-assembler analyze FILE [options]

Exit codes: 0 done, 1 error, 2 stopped because of warnings, 3 some lessons in a folder failed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .core import Job, Settings, assemble, run_batch
from .core.audio_io import Audio, decode
from .core.detect import DetectionSettings, detect_segments
from .core.errors import AssemblerError
from .core.naming import suggest_labels
from .core.report import fmt_time


def _auto_float(text: str) -> float | None:
    if text.strip().lower() in ("auto", "automatic"):
        return None
    return float(text.replace(",", "."))


def _add_settings(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("cut detection and processing")
    g.add_argument("--cut", type=_auto_float, default=None, metavar="SECONDS|auto",
                   help="minimum silence length for a cut (default: auto)")
    g.add_argument("--level", type=_auto_float, default=None, metavar="DB|auto",
                   help="silence level in dB, e.g. -50 (default: auto)")
    g.add_argument("--margin", type=float, default=0.1, help="safety margin in seconds (default: 0.1)")
    g.add_argument("--fade-ms", type=float, default=5.0, help="fade length in ms (default: 5)")
    g.add_argument("--match-loudness", action="store_true", help="match loudness between the two tracks")


def _settings(args) -> Settings:
    return Settings(min_cut_seconds=args.cut, silence_level_db=args.level, margin_seconds=args.margin,
                    fade_ms=args.fade_ms, match_loudness=args.match_loudness,
                    output_format=getattr(args, "format", "mp3"),
                    suffix_a=getattr(args, "suffix_a", "_LV"), suffix_b=getattr(args, "suffix_b", "_EN"),
                    suffix_order=getattr(args, "suffix_order", "_ORDER"),
                    batch_export_with_warnings=not getattr(args, "skip_warnings", False))


def _progress(quiet: bool):
    last = [""]

    def report(_f: float, msg: str) -> None:
        if not quiet and msg != last[0]:
            print(f"  {msg}", file=sys.stderr)
            last[0] = msg
    return report


def cmd_lesson(args) -> int:
    la, lb = suggest_labels(args.audio_a, args.audio_b)
    job = Job(args.audio_a, args.audio_b, args.order_list,
              args.labels[0] if args.labels else la, args.labels[1] if args.labels else lb,
              _settings(args), output_dir=args.out, output_name=args.name)

    def confirm(warnings: list[str]) -> bool:
        print("Warnings:")
        for w in warnings:
            print(f"  - {w}")
        if args.yes:
            return True
        if not sys.stdin.isatty():
            print("Not saved. Run again with --yes to save anyway.")
            return False
        return input("Save the finished file anyway? [y/N] ").strip().lower() in ("y", "yes")

    result = assemble(job, confirm, _progress(args.quiet))
    if result is None:
        return 2
    print(f"Done: {result.output_path}")
    print(f"Report: {result.report_path}")
    print(f"Format: {result.format_description}, duration {fmt_time(result.duration)}")
    return 0


def cmd_folder(args) -> int:
    def show(r) -> None:
        print(f"[{r.status.upper()}] {r.base}: {r.message}")
        for w in r.warnings:
            print(f"    - {w}")

    results = run_batch(args.folder, _settings(args), args.out, _progress(args.quiet), show)
    failed = sum(r.status in ("error", "skipped") for r in results)
    print(f"{len(results) - failed} of {len(results)} lesson sets saved.")
    return 3 if failed else 0


def cmd_analyze(args) -> int:
    samples, rate, ch = decode(args.file)
    audio = Audio(samples, rate, rate, ch)
    det = detect_segments(audio.mono(), rate, DetectionSettings(args.cut, args.level, args.margin),
                          name=Path(args.file).name)
    print(f"File: {args.file} ({rate} Hz, {ch} ch, {fmt_time(audio.duration)})")
    print(f"Silence level: {det.silence_level_db:.1f} dB ({'automatic' if det.silence_level_auto else 'manual'})")
    print(f"Minimum silence for a cut: {det.min_cut_seconds:.2f} s ({det.cut_method})")
    print(f"Segments: {len(det.segments)}")
    print(f"Ignored silence at start {det.leading_silence:.2f} s, at end {det.trailing_silence:.2f} s")
    print("Cut silences: " + (", ".join(f"{x:.2f}" for x in det.cut_lengths) or "none"))
    print(f"Longest speech pause inside segments: {det.longest_speech_pause:.2f} s")
    for seg in det.segments:
        a, b = seg.sound_start / rate, seg.sound_end / rate
        print(f"  {seg.number:3d}  {fmt_time(a)} - {fmt_time(b)}  ({b - a:.2f} s)")
    for w in det.warnings:
        print(f"Warning: {w}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="audio-assembler",
                                description="Cut two audio files at long silences and join the pieces "
                                            "in the order given by a CSV order list.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    pl = sub.add_parser("lesson", help="assemble one lesson from two audio files and an order list")
    pl.add_argument("audio_a")
    pl.add_argument("audio_b")
    pl.add_argument("order_list")
    pl.add_argument("--labels", nargs=2, metavar=("LABEL_A", "LABEL_B"),
                    help="track labels (default: from file name endings, e.g. _LV -> LV)")
    pl.add_argument("--out", help="output folder (default: folder of audio A)")
    pl.add_argument("--name", help="output file name without extension (default: <base>_FINAL)")
    pl.add_argument("--format", choices=("mp3", "wav"), default="mp3")
    pl.add_argument("--yes", "-y", action="store_true", help="save even if there are warnings")
    pl.add_argument("--quiet", "-q", action="store_true")
    _add_settings(pl)
    pl.set_defaults(func=cmd_lesson)

    pf = sub.add_parser("folder", help="assemble every lesson set in a folder")
    pf.add_argument("folder")
    pf.add_argument("--out", help="output folder (default: the same folder)")
    pf.add_argument("--format", choices=("mp3", "wav"), default="mp3")
    pf.add_argument("--suffix-a", default="_LV")
    pf.add_argument("--suffix-b", default="_EN")
    pf.add_argument("--suffix-order", default="_ORDER")
    pf.add_argument("--skip-warnings", action="store_true", help="do not save lessons that have warnings")
    pf.add_argument("--quiet", "-q", action="store_true")
    _add_settings(pf)
    pf.set_defaults(func=cmd_folder)

    pa = sub.add_parser("analyze", help="show detected segments and pauses of one audio file")
    pa.add_argument("file")
    _add_settings(pa)
    pa.set_defaults(func=cmd_analyze)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except AssemblerError as e:
        print(f"Error: {e.text()}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 1


if __name__ == "__main__":
    sys.exit(main())
