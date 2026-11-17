"""Starts the window."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .. import APP_NAME

RESOURCES = Path(__file__).resolve().parent / "resources"
ACCENT = "#3D6FE6"

STYLE = f"""
QLabel#AppTitle {{ font-size: 20pt; font-weight: 600; }}
QLabel#Subtitle, QLabel#Hint, QLabel#Status {{ color: palette(placeholder-text); }}
QLabel#FieldTitle {{ font-weight: 600; }}
QLineEdit, QComboBox, QDoubleSpinBox {{ padding: 5px 8px; border-radius: 6px;
    border: 1px solid palette(mid); background: palette(base); }}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus {{ border: 1px solid {ACCENT}; }}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 14px; border: none; }}
QFrame#PathField[dropping="true"] QLineEdit {{ border: 2px dashed {ACCENT}; }}
QPushButton {{ padding: 6px 14px; border-radius: 6px; border: 1px solid palette(mid); background: palette(button); }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton#SegLeft, QPushButton#SegRight {{ padding: 6px 18px; }}
QPushButton#SegLeft {{ border-top-right-radius: 0; border-bottom-right-radius: 0; }}
QPushButton#SegRight {{ border-top-left-radius: 0; border-bottom-left-radius: 0; border-left: none; }}
QPushButton#SegLeft:checked, QPushButton#SegRight:checked {{ background: {ACCENT}; color: white; border-color: {ACCENT}; }}
QPushButton#Primary {{ background: {ACCENT}; color: white; border: none; font-size: 12pt;
    font-weight: 600; padding: 10px; }}
QPushButton#Primary:hover {{ background: #2F5DCC; }}
QPushButton#Primary:disabled {{ background: palette(mid); }}
QToolButton#AdvancedToggle {{ border: none; font-weight: 600; padding: 2px 0; }}
QFrame#AdvancedPanel {{ border: 1px solid palette(mid); border-radius: 8px; }}
QProgressBar {{ border: none; border-radius: 3px; background: palette(midlight); }}
QProgressBar::chunk {{ border-radius: 3px; background: {ACCENT}; }}
QTextBrowser#Result {{ border: 1px solid palette(mid); border-radius: 8px; padding: 6px; background: palette(base); }}
"""


def run(argv: list[str] | None = None) -> int:
    if sys.platform == "win32":
        try:  # own taskbar icon instead of the Python one
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AudioAssembler.App")
        except Exception:
            pass
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    app.setWindowIcon(QIcon(str(RESOURCES / "icon.svg")))

    from .main_window import MainWindow
    window = MainWindow()
    window.show()
    return app.exec()
