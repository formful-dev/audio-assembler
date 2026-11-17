"""User-adjustable settings shared by the command line and the window."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, fields

from .errors import SettingsError

OUTPUT_FORMATS = ("mp3", "wav")


@dataclass
class Settings:
    # Cut detection. None means automatic.
    min_cut_seconds: float | None = None
    silence_level_db: float | None = None
    # Processing
    margin_seconds: float = 0.1
    fade_ms: float = 5.0
    match_loudness: bool = False
    # Output
    output_format: str = "mp3"
    # Folder mode
    suffix_a: str = "_LV"
    suffix_b: str = "_EN"
    suffix_order: str = "_ORDER"
    batch_export_with_warnings: bool = True

    def validate(self) -> None:
        def bad(what: str, fix: str) -> SettingsError:
            return SettingsError(what, fix)

        if self.min_cut_seconds is not None:
            if not _finite(self.min_cut_seconds) or self.min_cut_seconds <= 0:
                raise bad("The minimum silence length for a cut must be a number above 0.",
                          "Enter a value in seconds, for example 2 or 0.5, or choose Automatic.")
        if self.silence_level_db is not None:
            if not _finite(self.silence_level_db) or not -120 <= self.silence_level_db < 0:
                raise bad("The silence level must be between -120 and 0 dB.",
                          "Enter a value such as -50, or choose Automatic.")
        if not _finite(self.margin_seconds) or not 0 <= self.margin_seconds <= 2:
            raise bad("The safety margin must be between 0 and 2 seconds.", "Enter a value such as 0.1.")
        if not _finite(self.fade_ms) or not 0 <= self.fade_ms <= 200:
            raise bad("The fade length must be between 0 and 200 milliseconds.", "Enter a value such as 5.")
        if self.output_format not in OUTPUT_FORMATS:
            raise bad(f"Unknown output format '{self.output_format}'.", "Choose MP3 or WAV.")
        suffixes = [self.suffix_a.strip(), self.suffix_b.strip(), self.suffix_order.strip()]
        if any(not s for s in suffixes):
            raise bad("The file name endings for folder mode cannot be empty.",
                      "Enter endings such as _LV, _EN and _ORDER.")
        if len({s.casefold() for s in suffixes}) < 3:
            raise bad("The file name endings for folder mode must all be different.",
                      "Enter three different endings, such as _LV, _EN and _ORDER.")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        """Build settings from a saved dict, ignoring unknown or broken values."""
        s = cls()
        for f in fields(cls):
            if f.name in data:
                setattr(s, f.name, data[f.name])
        try:
            s.validate()
        except SettingsError:
            return cls()
        return s


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
