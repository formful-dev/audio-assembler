"""The single main window. All audio work is done by audio_assembler.core in a background thread."""

from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton, QRadioButton, QScrollArea,
    QSizePolicy, QStackedWidget, QTextBrowser, QToolButton, QVBoxLayout, QWidget,
)

from .. import APP_NAME, __version__
from ..core import AssemblerError, DetectionError, Job, Settings, export, prepare, run_batch
from ..core.assemble import output_paths
from ..core.audio_io import AUDIO_EXTENSIONS
from ..core.batch import DONE, ERROR, SKIPPED, WARNING
from ..core.naming import suggest_labels
from ..core.report import fmt_time
from .config import AppState, config_dir, load_state, save_state
from .widgets import PathField, Task, dropped_paths

AUDIO_FILTER = "Audio files (" + " ".join(f"*{e}" for e in AUDIO_EXTENSIONS) + ");;All files (*)"
CSV_FILTER = "Order list (*.csv);;All files (*)"

RED, GREEN, AMBER = "#d64545", "#2e9d5b", "#c98a00"


def _esc(text: str) -> str:
    return html.escape(text).replace("\n", "<br>")


def _file_link(path: Path, text: str) -> str:
    return f'<a href="{QUrl.fromLocalFile(str(path)).toString()}">{_esc(text)}</a>'


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.state: AppState = load_state()
        self.task: Task | None = None
        self._auto_labels = ("", "")
        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        self.resize(680, 760)
        self.setMinimumWidth(560)

        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(14)

        title = QLabel(APP_NAME)
        title.setObjectName("AppTitle")
        subtitle = QLabel("Cuts two audio files at their long pauses and joins the pieces "
                          "in the order of your list.")
        subtitle.setObjectName("Subtitle")
        subtitle.setWordWrap(True)
        outer.addWidget(title)
        outer.addWidget(subtitle)

        outer.addLayout(self._build_mode_switch())
        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_single_page())
        self.pages.addWidget(self._build_folder_page())
        self.pages.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        outer.addWidget(self.pages)
        outer.addLayout(self._build_output_row())
        outer.addWidget(self._build_advanced())

        self.assemble_btn = QPushButton("Assemble")
        self.assemble_btn.setObjectName("Primary")
        self.assemble_btn.setCursor(Qt.PointingHandCursor)
        self.assemble_btn.clicked.connect(self.on_assemble)
        outer.addWidget(self.assemble_btn)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.status = QLabel("Ready.")
        self.status.setObjectName("Status")
        outer.addWidget(self.progress)
        outer.addWidget(self.status)

        self.result = QTextBrowser()
        self.result.setObjectName("Result")
        self.result.setOpenLinks(False)
        self.result.document().setDefaultStyleSheet("a { color: #5B8DEF; }")
        self.result.anchorClicked.connect(QDesktopServices.openUrl)
        self.result.setMinimumHeight(140)
        outer.addWidget(self.result, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(root)
        self.setCentralWidget(scroll)

        self._apply_state()
        self._show_welcome()

    # ---------- building ----------

    def _build_mode_switch(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(0)
        self.mode_group = QButtonGroup(self)
        self.single_btn = QPushButton("Single lesson")
        self.folder_btn = QPushButton("Folder")
        for i, b in enumerate((self.single_btn, self.folder_btn)):
            b.setCheckable(True)
            b.setObjectName("SegLeft" if i == 0 else "SegRight")
            b.setCursor(Qt.PointingHandCursor)
            self.mode_group.addButton(b, i)
            row.addWidget(b)
        row.addStretch(1)
        self.mode_group.idClicked.connect(self._set_mode)
        return row

    def _build_single_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        start = lambda: self.state.last_dir  # noqa: E731
        self.field_a = PathField("Audio file A", "file", AUDIO_FILTER, "Drop an audio file here, or click Browse",
                                 with_label=True, start_dir=start)
        self.field_b = PathField("Audio file B", "file", AUDIO_FILTER, "Drop an audio file here, or click Browse",
                                 with_label=True, start_dir=start)
        self.field_order = PathField("Order list", "file", CSV_FILTER, "Drop the order list (CSV) here, or click Browse",
                                     start_dir=start)
        self.field_a.changed.connect(lambda _: self._audio_changed("a"))
        self.field_b.changed.connect(lambda _: self._audio_changed("b"))
        for f in (self.field_a, self.field_b, self.field_order):
            lay.addWidget(f)
        return page

    def _build_folder_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.field_folder = PathField("Lesson folder", "dir", "", "Drop a folder here, or click Browse",
                                      start_dir=lambda: self.state.last_dir)
        self.folder_hint = QLabel()
        self.folder_hint.setObjectName("Hint")
        self.folder_hint.setWordWrap(True)
        lay.addWidget(self.field_folder)
        lay.addWidget(self.folder_hint)
        return page

    def _build_output_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        fmt_box = QVBoxLayout()
        fmt_box.setSpacing(4)
        lbl = QLabel("Format")
        lbl.setObjectName("FieldTitle")
        self.format_combo = QComboBox()
        self.format_combo.addItem("MP3", "mp3")
        self.format_combo.addItem("WAV", "wav")
        self.format_combo.setFixedWidth(96)
        fmt_box.addWidget(lbl)
        fmt_box.addWidget(self.format_combo)
        self.field_out = PathField("Save to", "dir", "", "Next to the input files",
                                   start_dir=lambda: self.state.last_dir)
        row.addLayout(fmt_box)
        row.addWidget(self.field_out, 1)
        return row

    def _build_advanced(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.adv_toggle = QToolButton()
        self.adv_toggle.setText("Advanced")
        self.adv_toggle.setCheckable(True)
        self.adv_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.adv_toggle.setObjectName("AdvancedToggle")
        self.adv_toggle.toggled.connect(self._toggle_advanced)
        lay.addWidget(self.adv_toggle)

        self.adv_panel = QFrame()
        self.adv_panel.setObjectName("AdvancedPanel")
        form = QFormLayout(self.adv_panel)
        form.setContentsMargins(14, 12, 14, 12)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(8)

        def auto_manual(spin: QDoubleSpinBox) -> tuple[QWidget, QRadioButton, QRadioButton]:
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            auto, manual = QRadioButton("Automatic"), QRadioButton("Manual:")
            grp = QButtonGroup(w)
            grp.addButton(auto)
            grp.addButton(manual)
            manual.toggled.connect(spin.setEnabled)
            h.addWidget(auto)
            h.addWidget(manual)
            h.addWidget(spin)
            h.addStretch(1)
            return w, auto, manual

        self.cut_spin = QDoubleSpinBox(decimals=2, minimum=0.05, maximum=600, singleStep=0.5, suffix=" s")
        self.cut_spin.setToolTip("Silences at least this long are treated as cut points. "
                                 "Shorter silences are normal speech pauses and are never cut.")
        w, self.cut_auto, self.cut_manual = auto_manual(self.cut_spin)
        form.addRow("Minimum silence for a cut", w)

        self.level_spin = QDoubleSpinBox(decimals=1, minimum=-120, maximum=-1, singleStep=1, suffix=" dB")
        self.level_spin.setToolTip("Sound quieter than this counts as silence. "
                                   "Automatic sets it from each file's background noise.")
        w, self.level_auto, self.level_manual = auto_manual(self.level_spin)
        form.addRow("Silence level", w)

        self.margin_spin = QDoubleSpinBox(decimals=3, minimum=0, maximum=2, singleStep=0.05, suffix=" s")
        self.margin_spin.setToolTip("Silence kept before and after each piece so no speech is clipped.")
        form.addRow("Safety margin", self.margin_spin)
        self.fade_spin = QDoubleSpinBox(decimals=1, minimum=0, maximum=200, singleStep=1, suffix=" ms")
        self.fade_spin.setToolTip("A very short fade at every cut prevents clicks.")
        form.addRow("Fade length", self.fade_spin)
        self.loudness_check = QCheckBox("Match loudness between the two tracks")
        self.loudness_check.setToolTip("Turns the louder track down to the loudness of the quieter one.")
        form.addRow("", self.loudness_check)

        sfx = QWidget()
        h = QHBoxLayout(sfx)
        h.setContentsMargins(0, 0, 0, 0)
        self.suffix_a, self.suffix_b, self.suffix_order = QLineEdit(), QLineEdit(), QLineEdit()
        for edit, tip in ((self.suffix_a, "Ending of audio file A"), (self.suffix_b, "Ending of audio file B"),
                          (self.suffix_order, "Ending of the order list")):
            edit.setToolTip(tip)
            edit.setFixedWidth(90)
            edit.textChanged.connect(self._update_folder_hint)
            h.addWidget(edit)
        h.addStretch(1)
        form.addRow("Folder mode file endings", sfx)
        self.batch_warn_check = QCheckBox("In folder mode, save lessons that have warnings")
        form.addRow("", self.batch_warn_check)

        for spin in (self.cut_spin, self.level_spin, self.margin_spin, self.fade_spin):
            spin.setFixedWidth(110)

        reset = QPushButton("Reset to defaults")
        reset.clicked.connect(lambda: self._apply_settings(Settings()))
        reset.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        form.addRow("", reset)
        lay.addWidget(self.adv_panel)
        return box

    # ---------- state ----------

    def _apply_state(self) -> None:
        s = self.state
        self._apply_settings(s.settings)
        self.field_out.set_path(s.output_dir)
        self.adv_toggle.setChecked(s.advanced_open)
        self._toggle_advanced(s.advanced_open)
        self._set_mode(1 if s.mode == "folder" else 0)

    def _apply_settings(self, s: Settings) -> None:
        self.cut_manual.setChecked(s.min_cut_seconds is not None)
        self.cut_auto.setChecked(s.min_cut_seconds is None)
        self.cut_spin.setValue(s.min_cut_seconds if s.min_cut_seconds is not None else 2.0)
        self.cut_spin.setEnabled(s.min_cut_seconds is not None)
        self.level_manual.setChecked(s.silence_level_db is not None)
        self.level_auto.setChecked(s.silence_level_db is None)
        self.level_spin.setValue(s.silence_level_db if s.silence_level_db is not None else -50.0)
        self.level_spin.setEnabled(s.silence_level_db is not None)
        self.margin_spin.setValue(s.margin_seconds)
        self.fade_spin.setValue(s.fade_ms)
        self.loudness_check.setChecked(s.match_loudness)
        self.format_combo.setCurrentIndex(max(0, self.format_combo.findData(s.output_format)))
        self.suffix_a.setText(s.suffix_a)
        self.suffix_b.setText(s.suffix_b)
        self.suffix_order.setText(s.suffix_order)
        self.batch_warn_check.setChecked(s.batch_export_with_warnings)
        self._update_folder_hint()

    def _settings_from_ui(self) -> Settings:
        return Settings(
            min_cut_seconds=self.cut_spin.value() if self.cut_manual.isChecked() else None,
            silence_level_db=self.level_spin.value() if self.level_manual.isChecked() else None,
            margin_seconds=self.margin_spin.value(),
            fade_ms=self.fade_spin.value(),
            match_loudness=self.loudness_check.isChecked(),
            output_format=self.format_combo.currentData(),
            suffix_a=self.suffix_a.text().strip(),
            suffix_b=self.suffix_b.text().strip(),
            suffix_order=self.suffix_order.text().strip(),
            batch_export_with_warnings=self.batch_warn_check.isChecked(),
        )

    def _save_state(self) -> None:
        try:
            self.state.settings = self._settings_from_ui()
        except Exception:
            pass
        self.state.mode = "folder" if self.pages.currentIndex() == 1 else "single"
        self.state.output_dir = self.field_out.path()
        self.state.advanced_open = self.adv_toggle.isChecked()
        save_state(self.state)

    def _remember_dir(self, path: str) -> None:
        if path:
            p = Path(path)
            self.state.last_dir = str(p if p.is_dir() else p.parent)

    # ---------- small behaviours ----------

    def _set_mode(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        (self.folder_btn if index else self.single_btn).setChecked(True)

    def _toggle_advanced(self, on: bool) -> None:
        self.adv_panel.setVisible(on)
        self.adv_toggle.setArrowType(Qt.DownArrow if on else Qt.RightArrow)

    def _update_folder_hint(self) -> None:
        a, b, o = (e.text().strip() or "?" for e in (self.suffix_a, self.suffix_b, self.suffix_order))
        la, lb = a.lstrip("_- ."), b.lstrip("_- .")
        self.folder_hint.setText(
            f"Every lesson in the folder needs three files whose names start the same, for example "
            f"Lesson1{a}.mp3, Lesson1{b}.mp3 and Lesson1{o}.csv. The labels {la} and {lb} come from "
            "these endings. You can change the endings in Advanced.")

    def _audio_changed(self, which: str) -> None:
        a, b = self.field_a.path(), self.field_b.path()
        # Fill labels from file names, unless the user typed their own.
        la, lb = suggest_labels(a, b)
        for edit, new, old in ((self.field_a.label_edit, la, self._auto_labels[0]),
                               (self.field_b.label_edit, lb, self._auto_labels[1])):
            if edit.text() in ("", old):
                edit.setText(new)
        self._auto_labels = (la, lb)
        self._find_partners(a if which == "a" else b)

    def _find_partners(self, path: str) -> None:
        """When one file of a lesson set is chosen, fill in the others if they are next to it."""
        p = Path(path)
        if not p.is_file():
            return
        self._remember_dir(path)
        s = self._settings_from_ui()
        stem = p.stem
        base = next((stem[:-len(x)] for x in (s.suffix_a, s.suffix_b)
                     if x and stem.casefold().endswith(x.casefold()) and len(stem) > len(x)), None)
        if base is None:
            return
        folder = p.parent

        def find(suffix: str, exts) -> Path | None:
            for ext in exts:
                cand = folder / f"{base}{suffix}{ext}"
                if cand.is_file():
                    return cand
            return None

        if not self.field_a.path() and (c := find(s.suffix_a, AUDIO_EXTENSIONS)):
            self.field_a.set_path(str(c))
        if not self.field_b.path() and (c := find(s.suffix_b, AUDIO_EXTENSIONS)):
            self.field_b.set_path(str(c))
        if not self.field_order.path() and (c := find(s.suffix_order, (".csv",))):
            self.field_order.set_path(str(c))

    def dragEnterEvent(self, event) -> None:
        if dropped_paths(event):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        """Dropping files anywhere on the window puts each one in the right box."""
        paths = dropped_paths(event)
        if len(paths) == 1 and paths[0].is_dir():
            self._set_mode(1)
            self.field_folder.set_path(str(paths[0]))
            return
        self._set_mode(0)
        s = self._settings_from_ui()
        audio = [p for p in paths if p.suffix.lower() in AUDIO_EXTENSIONS]
        for p in paths:
            if p.suffix.lower() == ".csv":
                self.field_order.set_path(str(p))
        rest = []
        for p in audio:
            if p.stem.casefold().endswith(s.suffix_b.casefold()):
                self.field_b.set_path(str(p))
            elif p.stem.casefold().endswith(s.suffix_a.casefold()):
                self.field_a.set_path(str(p))
            else:
                rest.append(p)
        for p in rest:
            target = self.field_a if not self.field_a.path() else self.field_b
            target.set_path(str(p))
        event.acceptProposedAction()

    # ---------- messages ----------

    def _show_welcome(self) -> None:
        self.result.setHtml(
            "<p>Choose two audio files and an order list, then click <b>Assemble</b>.</p>"
            "<p style='color:gray'>Tip: drop all three files onto this window at once.</p>")

    def _say(self, html_text: str, append: bool = False) -> None:
        if append:
            self.result.append(html_text)
        else:
            self.result.setHtml(html_text)

    def _error_html(self, e: Exception) -> str:
        if isinstance(e, AssemblerError):
            parts = [f"<p style='color:{RED}'><b>{_esc(e.problem)}</b></p>"]
            if e.details:
                parts.append("<ul>" + "".join(f"<li>{_esc(d)}</li>" for d in e.details) + "</ul>")
            if e.fix:
                parts.append(f"<p><b>What to do:</b> {_esc(e.fix)}</p>")
            return "".join(parts)
        return (f"<p style='color:{RED}'><b>Something unexpected went wrong.</b></p>"
                f"<p>{_esc(str(e))}</p><p><b>What to do:</b> Try again. If it happens again, send the file "
                f"{_file_link(config_dir() / 'error_log.txt', 'error_log.txt')} to the developer.</p>")

    def _log_unexpected(self, tb: str) -> None:
        try:
            config_dir().mkdir(parents=True, exist_ok=True)
            with open(config_dir() / "error_log.txt", "a", encoding="utf-8") as f:
                f.write(f"--- {APP_NAME} {__version__}\n{tb}\n")
        except OSError:
            pass

    # ---------- running ----------

    def _busy(self, on: bool) -> None:
        for w in (self.assemble_btn, self.pages, self.single_btn, self.folder_btn, self.field_out,
                  self.format_combo, self.adv_panel):
            w.setEnabled(not on)
        self.assemble_btn.setText("Working…" if on else "Assemble")
        if not on:
            self.task = None

    def _run(self, fn, on_success, on_item=None, lo: float = 0.0, hi: float = 1.0) -> None:
        # Signals are connected to methods of this window (never to lambdas), so Qt delivers them
        # on the window's thread. Lambdas would run on the worker thread and could freeze the window.
        self._task_success, self._task_item, self._task_range = on_success, on_item, (lo, hi)
        self.task = Task(fn, self)
        self.task.progressed.connect(self._on_task_progress)
        self.task.item.connect(self._on_task_item)
        self.task.succeeded.connect(self._on_task_success)
        self.task.failed.connect(self._on_failed)
        self._busy(True)
        self.task.start()

    def _on_task_progress(self, fraction: float, message: str) -> None:
        lo, hi = self._task_range
        self.progress.setValue(int(max(0.0, min(1.0, lo + (hi - lo) * fraction)) * 1000))
        self.status.setText(message)

    def _on_task_item(self, item) -> None:
        if self._task_item:
            self._task_item(item)

    def _on_task_success(self, result) -> None:
        if self.task is not None:
            self.task.wait()
        self._task_success(result)

    def _on_failed(self, e: Exception, tb: str) -> None:
        if self.task is not None:
            self.task.wait()
        self._busy(False)
        self.progress.setValue(0)
        if not isinstance(e, AssemblerError):
            self._log_unexpected(tb)
        self.status.setText("Stopped. Nothing was saved.")
        self._say(self._error_html(e))
        if isinstance(e, DetectionError) and e.pause_lengths:
            self.adv_toggle.setChecked(True)
            self.cut_manual.setChecked(True)
            self.cut_spin.setFocus()
            self.cut_spin.selectAll()
            self._say("<p>I opened <b>Advanced</b> and switched the cut setting to <b>Manual</b>. "
                      "Enter a value and click Assemble again.</p>", append=True)

    def on_assemble(self) -> None:
        if self.task is not None:
            return
        try:
            settings = self._settings_from_ui()
            settings.validate()
        except AssemblerError as e:
            self._say(self._error_html(e))
            return
        self._save_state()
        if self.pages.currentIndex() == 1:
            self._start_folder(settings)
        else:
            self._start_single(settings)

    # single lesson

    def _start_single(self, settings: Settings) -> None:
        job = Job(self.field_a.path(), self.field_b.path(), self.field_order.path(),
                  self.field_a.label_edit.text(), self.field_b.label_edit.text(), settings,
                  output_dir=self.field_out.path() or None)
        if job.audio_a:
            out, _ = output_paths(job)
            if out.exists() and not self.confirm_replace(out.name):
                self.status.setText("Not saved.")
                return
        self._say("<p>Checking the files…</p>")
        self._run(lambda progress, _item: prepare(job, progress), self._on_prepared, hi=0.5)

    def confirm_warnings(self, warnings: list[str]) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(APP_NAME)
        box.setText("Please check these warnings before saving:")
        box.setInformativeText("\n\n".join(f"• {w}" for w in warnings))
        save = box.addButton("Save anyway", QMessageBox.AcceptRole)
        box.addButton("Don't save", QMessageBox.RejectRole)
        box.exec()
        return box.clickedButton() is save

    def confirm_replace(self, name: str) -> bool:
        answer = QMessageBox.question(self, APP_NAME, f"'{name}' already exists.\n\nReplace it?",
                                      QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return answer == QMessageBox.Yes

    def _on_prepared(self, plan) -> None:
        self._busy(False)
        if plan.warnings:
            if not self.confirm_warnings(plan.warnings):
                self.progress.setValue(0)
                self.status.setText("Not saved.")
                self._say("<p>Not saved. Warnings:</p><ul>"
                          + "".join(f"<li>{_esc(w)}</li>" for w in plan.warnings) + "</ul>")
                return
        self._run(lambda progress, _item: export(plan, progress), lambda res: self._on_exported(plan, res), lo=0.5)

    def _on_exported(self, plan, res) -> None:
        self._busy(False)
        self.progress.setValue(1000)
        self.status.setText("Done.")
        a, b = plan.tracks
        lines = [
            f"<p style='color:{GREEN}'><b>Done.</b> Saved {_file_link(res.output_path, res.output_path.name)} "
            f"({fmt_time(res.duration)}).</p>",
            "<ul>",
            f"<li>{_esc(a.label)}: {len(a.detection.segments)} pieces found ({_esc(a.detection.cut_method)})</li>",
            f"<li>{_esc(b.label)}: {len(b.detection.segments)} pieces found ({_esc(b.detection.cut_method)})</li>",
            f"<li>{len(plan.order.rows)} pieces placed, {plan.order.total_gap:.2f} s of pauses added</li>",
            "</ul>",
        ]
        if res.warnings:
            lines.append(f"<p style='color:{AMBER}'><b>Saved with warnings:</b></p><ul>"
                         + "".join(f"<li>{_esc(w)}</li>" for w in res.warnings) + "</ul>")
        lines.append(f"<p>{_file_link(res.report_path, 'Open the report')} · "
                     f"{_file_link(res.output_path.parent, 'Open the folder')}</p>")
        self._say("".join(lines))

    # folder

    def _start_folder(self, settings: Settings) -> None:
        folder = self.field_folder.path()
        if not folder:
            self._say(f"<p style='color:{RED}'><b>No folder is selected.</b></p>"
                      "<p><b>What to do:</b> Choose the folder that contains your lesson files.</p>")
            return
        self._remember_dir(folder)
        out = self.field_out.path() or None
        self._batch_counts = {DONE: 0, WARNING: 0, ERROR: 0, SKIPPED: 0}
        self._say(f"<p>Processing the folder {_esc(folder)}…</p>")
        self._run(lambda progress, item: run_batch(folder, settings, out, progress, item),
                  lambda results: self._on_batch_done(folder, out, results), on_item=self._on_batch_item)

    def _on_batch_item(self, r) -> None:
        self._batch_counts[r.status] += 1
        color, word = {DONE: (GREEN, "Done"), WARNING: (AMBER, "Warning"),
                       ERROR: (RED, "Error"), SKIPPED: (AMBER, "Not saved")}[r.status]
        text = f"<p><b style='color:{color}'>{word}</b> · <b>{_esc(r.base)}</b>: {_esc(r.message)}"
        if r.warnings:
            text += "<ul>" + "".join(f"<li>{_esc(w)}</li>" for w in r.warnings) + "</ul>"
        self._say(text + "</p>", append=True)

    def _on_batch_done(self, folder: str, out: str | None, results) -> None:
        self._busy(False)
        self.progress.setValue(1000)
        c = self._batch_counts
        saved = c[DONE] + c[WARNING]
        self.status.setText(f"Folder finished: {saved} of {len(results)} lessons saved.")
        summary = Path(out or folder) / "_batch_summary.txt"
        self._say(f"<p><b>Finished:</b> {saved} of {len(results)} lessons saved"
                  f" ({c[WARNING]} with warnings, {c[ERROR] + c[SKIPPED]} not saved). "
                  f"{_file_link(summary, 'Open the summary')} · {_file_link(Path(out or folder), 'Open the folder')}</p>",
                  append=True)

    def closeEvent(self, event) -> None:
        if self.task is not None and self.task.isRunning():
            answer = QMessageBox.question(self, APP_NAME, "Work is still in progress. Quit anyway?",
                                          QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.task.wait(3000)
        self._save_state()
        event.accept()
