"""Remembering settings and folders between runs (a small JSON file in the user's settings folder)."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..core.settings import Settings


def config_dir() -> Path:
    if os.environ.get("AUDIO_ASSEMBLER_CONFIG_DIR"):  # used by the tests
        return Path(os.environ["AUDIO_ASSEMBLER_CONFIG_DIR"])
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / "Audio Assembler"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Audio Assembler"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "audio-assembler"


@dataclass
class AppState:
    settings: Settings = field(default_factory=Settings)
    mode: str = "single"        # single | folder
    last_dir: str = ""          # where the file dialogs open
    output_dir: str = ""        # "" = next to the input files
    advanced_open: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["settings"] = self.settings.to_dict()
        return d


def _path() -> Path:
    return config_dir() / "settings.json"


def load_state() -> AppState:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return AppState()
    state = AppState()
    if isinstance(data.get("settings"), dict):
        state.settings = Settings.from_dict(data["settings"])
    if data.get("mode") in ("single", "folder"):
        state.mode = data["mode"]
    for key in ("last_dir", "output_dir"):
        if isinstance(data.get(key), str):
            setattr(state, key, data[key])
    state.advanced_open = bool(data.get("advanced_open", False))
    return state


def save_state(state: AppState) -> None:
    try:
        _path().parent.mkdir(parents=True, exist_ok=True)
        _path().write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")
    except OSError:
        pass  # remembering settings is a convenience; never fail because of it
