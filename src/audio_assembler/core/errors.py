"""Errors that carry a plain-language message: what is wrong and what to do."""

from __future__ import annotations


class AssemblerError(Exception):
    """Base error. `problem` says what is wrong, `fix` says what to do, `details` lists specifics."""

    def __init__(self, problem: str, fix: str = "", details: list[str] | None = None):
        self.problem = problem
        self.fix = fix
        self.details = list(details or [])
        super().__init__(self.text())

    def text(self) -> str:
        lines = [self.problem]
        lines += [f"  - {d}" for d in self.details]
        if self.fix:
            lines.append(f"What to do: {self.fix}")
        return "\n".join(lines)


class AudioError(AssemblerError):
    """An audio file could not be read or written."""


class OrderListError(AssemblerError):
    """The order list is malformed or does not match the audio."""


class DetectionError(AssemblerError):
    """Cut silences could not be detected reliably."""

    def __init__(self, problem: str, fix: str = "", details: list[str] | None = None,
                 pause_lengths: list[float] | None = None):
        super().__init__(problem, fix, details)
        self.pause_lengths = list(pause_lengths or [])


class SettingsError(AssemblerError):
    """A setting has an invalid value."""
