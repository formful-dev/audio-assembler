"""The window, driven automatically without showing it on screen."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from audiogen import make_track, write_order, write_wav  # noqa: E402

RATE = 16000


@pytest.fixture
def window(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIO_ASSEMBLER_CONFIG_DIR", str(tmp_path / "settings"))
    from audio_assembler.gui import app as gui_app
    from audio_assembler.gui.main_window import MainWindow
    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    qapp.setStyleSheet(gui_app.STYLE)
    w = MainWindow()
    w.show()
    yield w
    w.close()


def make_lesson(folder, base="L1", en_seg=2):
    lv = make_track([2, 3, 2], 4.0, 0.3, rate=RATE, seed=51)
    en = make_track([3, 2], 4.0, 0.3, rate=RATE, seed=52)
    write_wav(folder / f"{base}_LV.wav", lv.samples, RATE)
    write_wav(folder / f"{base}_EN.wav", en.samples, RATE)
    write_order(folder / f"{base}_ORDER.csv",
                [(1, "LV", 1, 1), (2, "EN", 1, 1), (3, "LV", 2, 0.5), (4, "EN", en_seg, 1), (5, "LV", 3, 0)])


def wait(window, timeout_ms=60000):
    while window.task is not None:
        window.task.wait(50)
        QtWidgets.QApplication.processEvents()
        timeout_ms -= 50
        assert timeout_ms > 0, "timed out"
    QtWidgets.QApplication.processEvents()


def test_single_lesson_fills_partners_and_labels(window, tmp_path):
    make_lesson(tmp_path)
    window.field_a.set_path(str(tmp_path / "L1_LV.wav"))
    # Choosing one file finds the other two and fills the labels.
    assert window.field_b.path().endswith("L1_EN.wav")
    assert window.field_order.path().endswith("L1_ORDER.csv")
    assert (window.field_a.label_edit.text(), window.field_b.label_edit.text()) == ("LV", "EN")
    window.format_combo.setCurrentIndex(window.format_combo.findData("wav"))
    window.assemble_btn.click()
    wait(window)
    wait(window)
    assert (tmp_path / "L1_FINAL.wav").is_file()
    assert (tmp_path / "L1_FINAL_report.txt").is_file()
    assert "Done." in window.result.toPlainText()
    window.grab().save(str(tmp_path / "window.png"))


def test_errors_are_plain_and_nothing_saved(window, tmp_path):
    make_lesson(tmp_path, en_seg=8)
    window.field_a.set_path(str(tmp_path / "L1_LV.wav"))
    window.assemble_btn.click()
    wait(window)
    text = window.result.toPlainText()
    assert "EN segment 8 does not exist" in text and "What to do" in text
    assert not (tmp_path / "L1_FINAL.mp3").exists()


def test_warnings_can_be_declined(window, tmp_path, monkeypatch):
    make_lesson(tmp_path)
    write_order(tmp_path / "L1_ORDER.csv", [(1, "LV", 1, 1), (2, "EN", 1, 0)])  # unused segments
    asked = []
    monkeypatch.setattr(window, "confirm_warnings", lambda w: asked.append(w) or False)
    window.field_a.set_path(str(tmp_path / "L1_LV.wav"))
    window.assemble_btn.click()
    wait(window)
    assert asked and "never used" in " ".join(asked[0])
    assert "Not saved" in window.result.toPlainText()
    assert not list(tmp_path.glob("*_FINAL*"))


def test_missing_input_message(window):
    window.assemble_btn.click()
    wait(window)
    assert "No audio file A is selected" in window.result.toPlainText()


def test_ambiguous_detection_opens_manual_setting(window, tmp_path, monkeypatch):
    monkeypatch.setattr(window, "confirm_warnings", lambda w: True)
    lv = make_track([4, 4, 4], lambda r: r.uniform(0.85, 1.0), lambda r: r.uniform(0.7, 0.9), rate=RATE, seed=4)
    write_wav(tmp_path / "X_LV.wav", lv.samples, RATE)
    write_wav(tmp_path / "X_EN.wav", lv.samples, RATE)
    write_order(tmp_path / "X_ORDER.csv", [(1, "LV", 1, 0)])
    window.field_a.set_path(str(tmp_path / "X_LV.wav"))
    window.assemble_btn.click()
    wait(window)
    assert "Longest pauses found" in window.result.toPlainText()
    assert window.adv_toggle.isChecked() and window.cut_manual.isChecked()
    window.cut_spin.setValue(0.8)  # a manual value now works
    window.assemble_btn.click()
    wait(window)
    wait(window)
    assert window.task is None


def test_folder_mode(window, tmp_path):
    make_lesson(tmp_path, "A1")
    make_lesson(tmp_path, "A2", en_seg=9)
    window._set_mode(1)
    window.field_folder.set_path(str(tmp_path))
    window.assemble_btn.click()
    wait(window)
    text = window.result.toPlainText()
    assert "Done · A1" in text and "Error · A2" in text
    assert "1 of 2 lessons saved" in text
    assert (tmp_path / "A1_FINAL.mp3").is_file()


def test_settings_are_remembered(window, tmp_path):
    from audio_assembler.gui.config import load_state
    window.cut_manual.setChecked(True)
    window.cut_spin.setValue(3.5)
    window.loudness_check.setChecked(True)
    window._set_mode(1)
    window.close()
    st = load_state()
    assert st.settings.min_cut_seconds == 3.5 and st.settings.match_loudness and st.mode == "folder"
