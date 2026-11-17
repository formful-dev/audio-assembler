"""File-name helpers: track labels from suffixes, and the shared base name of two files."""

from __future__ import annotations

import re
from pathlib import Path

_SEPARATORS = "_- ."
_TOKEN = re.compile(r"[_\-\s.]+")


def label_from_filename(path: str) -> str | None:
    """'Lesson3_LV.wav' -> 'LV'. Returns None when the name has no separate last part."""
    parts = [p for p in _TOKEN.split(Path(path).stem) if p]
    if len(parts) < 2:
        return None
    last = parts[-1]
    return last if 1 <= len(last) <= 12 else None


def suggest_labels(path_a: str, path_b: str) -> tuple[str, str]:
    a = label_from_filename(path_a) if path_a else None
    b = label_from_filename(path_b) if path_b else None
    if not a or not b or a.casefold() == b.casefold():
        return a or "A", b or "B"
    return a, b


def shared_base_name(path_a: str, path_b: str) -> str:
    """'TEST_LV', 'TEST_EN' -> 'TEST'. Falls back to the first file's name."""
    a, b = Path(path_a).stem, Path(path_b).stem
    n = 0
    while n < min(len(a), len(b)) and a[n].casefold() == b[n].casefold():
        n += 1
    prefix = a[:n]
    if n < len(a) and n < len(b) and prefix and prefix[-1] not in _SEPARATORS:
        cut = max(prefix.rfind(c) for c in _SEPARATORS)
        prefix = prefix[:cut] if cut > 0 else ""
    prefix = prefix.rstrip(_SEPARATORS)
    return prefix or a
