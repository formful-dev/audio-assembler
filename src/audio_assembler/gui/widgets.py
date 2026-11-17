"""Small reusable widgets: a file/folder field with drag and drop, and a background task runner."""

from __future__ import annotations

import os
import traceback
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout


def dropped_paths(event) -> list[Path]:
    md = event.mimeData()
    if not md.hasUrls():
        return []
    return [Path(u.toLocalFile()) for u in md.urls() if u.isLocalFile()]


class PathField(QFrame):
    """Title, a path box that accepts dropped files, a Browse button and an optional label box."""

    changed = Signal(str)

    def __init__(self, title: str, kind: str = "file", file_filter: str = "", placeholder: str = "",
                 with_label: bool = False, start_dir: Callable[[], str] = lambda: "", parent=None):
        super().__init__(parent)
        self.setObjectName("PathField")
        self.kind, self.file_filter, self.start_dir = kind, file_filter, start_dir
        self.setAcceptDrops(True)

        self.title = QLabel(title)
        self.title.setObjectName("FieldTitle")
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.setAcceptDrops(False)  # let the frame handle drops
        self.edit.setClearButtonEnabled(True)
        self.edit.textChanged.connect(self.changed.emit)
        self.browse = QPushButton("Browse…")
        self.browse.clicked.connect(self._browse)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.edit, 1)
        row.addWidget(self.browse)
        self.label_edit: QLineEdit | None = None
        if with_label:
            self.label_edit = QLineEdit()
            self.label_edit.setPlaceholderText("Label")
            self.label_edit.setToolTip("Track label. It must match the label used in the order list, for example LV.")
            self.label_edit.setFixedWidth(84)
            row.addWidget(self.label_edit)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(self.title)
        lay.addLayout(row)

    def path(self) -> str:
        return self.edit.text().strip().strip('"')

    def set_path(self, p: str) -> None:
        self.edit.setText(os.path.normpath(p) if str(p).strip() else "")

    def _browse(self) -> None:
        start = self.path() or self.start_dir()
        if self.kind == "dir":
            chosen = QFileDialog.getExistingDirectory(self, self.title.text(), start)
        else:
            chosen, _ = QFileDialog.getOpenFileName(self, self.title.text(), start, self.file_filter)
        if chosen:
            self.set_path(str(Path(chosen)))

    def accepts(self, p: Path) -> bool:
        return p.is_dir() if self.kind == "dir" else p.is_file()

    def _set_drop_highlight(self, on: bool) -> None:
        self.setProperty("dropping", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event) -> None:
        paths = dropped_paths(event)
        if len(paths) == 1 and self.accepts(paths[0]):
            event.acceptProposedAction()
            self._set_drop_highlight(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._set_drop_highlight(False)

    def dropEvent(self, event) -> None:
        self._set_drop_highlight(False)
        paths = dropped_paths(event)
        if paths:
            self.set_path(str(paths[0]))
            event.acceptProposedAction()


class Task(QThread):
    """Runs fn(progress, item) in the background and reports back on the window's thread."""

    progressed = Signal(float, str)
    item = Signal(object)
    succeeded = Signal(object)
    failed = Signal(object, str)

    def __init__(self, fn: Callable, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self) -> None:
        try:
            result = self.fn(self.progressed.emit, self.item.emit)
        except Exception as e:  # reported to the window, never lost
            self.failed.emit(e, traceback.format_exc())
        else:
            self.succeeded.emit(result)
