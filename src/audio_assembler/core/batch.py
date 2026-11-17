"""Folder mode: find lesson sets by shared base name and process each one independently."""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from .assemble import Job, export, prepare
from .audio_io import AUDIO_EXTENSIONS, Progress
from .errors import AssemblerError
from .settings import Settings

DONE, WARNING, ERROR, SKIPPED = "done", "warning", "error", "skipped"


@dataclass
class LessonSet:
    base: str
    audio_a: Path | None = None
    audio_b: Path | None = None
    order_list: Path | None = None
    problem: str | None = None


@dataclass
class BatchResult:
    base: str
    status: str                 # done | warning | error | skipped
    message: str
    output_path: Path | None = None
    warnings: list[str] = field(default_factory=list)


def label_from_suffix(suffix: str) -> str:
    return suffix.strip().lstrip("_- .") or suffix.strip()


def find_lesson_sets(folder: str, settings: Settings) -> list[LessonSet]:
    root = Path(folder)
    if not root.is_dir():
        raise AssemblerError(f"The folder '{folder}' was not found.", "Choose an existing folder.")
    sa, sb, so = (x.strip().casefold() for x in (settings.suffix_a, settings.suffix_b, settings.suffix_order))
    sets: dict[str, LessonSet] = {}

    def entry(base: str) -> LessonSet:
        return sets.setdefault(base.casefold(), LessonSet(base))

    for f in sorted(root.iterdir()):
        if not f.is_file() or f.name.startswith(".~"):
            continue
        stem, ext = f.stem, f.suffix.lower()
        low = stem.casefold()
        if ext in AUDIO_EXTENSIONS:
            for suffix, attr in ((sa, "audio_a"), (sb, "audio_b")):
                if low.endswith(suffix) and len(low) > len(suffix):
                    ls = entry(stem[:-len(suffix)])
                    if getattr(ls, attr) is not None:
                        ls.problem = (f"There are two audio files for '{ls.base}{suffix}' "
                                      f"({getattr(ls, attr).name} and {f.name}). Keep only one.")
                    else:
                        setattr(ls, attr, f)
        elif ext == ".csv" and low.endswith(so) and len(low) > len(so):
            entry(stem[:-len(so)]).order_list = f

    result = sorted(sets.values(), key=lambda s: s.base.casefold())
    for ls in result:
        if ls.problem:
            continue
        missing = [name for name, val in ((f"audio file ending in {settings.suffix_a}", ls.audio_a),
                                          (f"audio file ending in {settings.suffix_b}", ls.audio_b),
                                          (f"order list ending in {settings.suffix_order}.csv", ls.order_list))
                   if val is None]
        if missing:
            ls.problem = "Missing " + " and ".join(missing) + "."
    return result


def run_batch(folder: str, settings: Settings, output_dir: str | None = None,
              progress: Progress | None = None,
              on_result: Callable[[BatchResult], None] | None = None) -> list[BatchResult]:
    """Process every lesson set in `folder`. One failed set never stops the others."""
    settings.validate()
    progress = progress or (lambda f, m: None)
    if output_dir and not Path(output_dir).is_dir():
        raise AssemblerError(f"The output folder '{output_dir}' does not exist.", "Choose an existing folder.")
    sets = find_lesson_sets(folder, settings)
    if not sets:
        raise AssemblerError(
            "No lesson sets were found in this folder.",
            f"Each set needs three files with the same start, for example Lesson1{settings.suffix_a}.mp3, "
            f"Lesson1{settings.suffix_b}.mp3 and Lesson1{settings.suffix_order}.csv. "
            "Check the file name endings in Advanced.",
        )
    label_a, label_b = label_from_suffix(settings.suffix_a), label_from_suffix(settings.suffix_b)
    results: list[BatchResult] = []
    n = len(sets)
    for i, ls in enumerate(sets):
        def sub(f: float, m: str, i=i, base=ls.base) -> None:
            progress((i + f) / n, f"{base}: {m}")

        sub(0.0, "starting")
        if ls.problem:
            res = BatchResult(ls.base, ERROR, ls.problem)
        else:
            job = Job(str(ls.audio_a), str(ls.audio_b), str(ls.order_list), label_a, label_b,
                      settings, output_dir=output_dir or str(ls.audio_a.parent),
                      output_name=f"{ls.base}_FINAL")
            try:
                plan = prepare(job, lambda f, m: sub(0.5 * f, m))
                if plan.warnings and not settings.batch_export_with_warnings:
                    res = BatchResult(ls.base, SKIPPED, "Not saved because of warnings.", None, plan.warnings)
                else:
                    out = export(plan, lambda f, m: sub(0.5 + 0.5 * f, m))
                    status = WARNING if plan.warnings else DONE
                    msg = f"Saved {out.output_path.name}"
                    if plan.warnings:
                        msg += f" with {len(plan.warnings)} warning(s)"
                    res = BatchResult(ls.base, status, msg + ".", out.output_path, plan.warnings)
            except AssemblerError as e:
                res = BatchResult(ls.base, ERROR, e.text())
            except Exception as e:  # never let one set stop the batch
                res = BatchResult(ls.base, ERROR, f"Unexpected problem: {e}\n{traceback.format_exc(limit=3)}")
        results.append(res)
        if on_result:
            on_result(res)
    progress(1.0, "Folder finished")
    _write_summary(Path(output_dir or folder), results)
    return results


def _write_summary(folder: Path, results: list[BatchResult]) -> None:
    lines = [f"Audio Assembler folder summary, {datetime.now():%Y-%m-%d %H:%M}", ""]
    for r in results:
        lines.append(f"[{r.status.upper()}] {r.base}: {r.message}")
        lines += [f"    - {w}" for w in r.warnings]
    try:
        (folder / "_batch_summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass
