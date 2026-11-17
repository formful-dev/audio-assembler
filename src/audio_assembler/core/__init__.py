"""Core logic. No user-interface code lives here."""

from .assemble import ExportResult, Job, Plan, assemble, export, prepare
from .batch import BatchResult, LessonSet, find_lesson_sets, run_batch
from .errors import AssemblerError, AudioError, DetectionError, OrderListError, SettingsError
from .settings import Settings

__all__ = [
    "AssemblerError", "AudioError", "DetectionError", "OrderListError", "SettingsError",
    "Settings", "Job", "Plan", "ExportResult", "prepare", "export", "assemble",
    "LessonSet", "BatchResult", "find_lesson_sets", "run_batch",
]
