"""Render the SVG icon to icon.png (window icon) and icon.ico (Windows app, shortcut, installer).

Run after changing icon.svg:  python packaging/make_icon.py
Needs PySide6 and Pillow.
"""

from pathlib import Path

from PIL import Image
from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

RES = Path(__file__).resolve().parents[1] / "src" / "audio_assembler" / "gui" / "resources"
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def render(svg: bytes, size: int) -> Image.Image:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(QByteArray(svg)).render(p)
    p.end()
    tmp = RES / f".tmp_{size}.png"
    img.save(str(tmp))
    out = Image.open(tmp).convert("RGBA")
    out.load()
    tmp.unlink()
    return out


def main() -> None:
    _app = QGuiApplication([])
    svg = (RES / "icon.svg").read_bytes()
    images = [render(svg, s) for s in SIZES]   # each size rendered sharp, not scaled down
    images[-1].save(RES / "icon.png")
    images[-1].save(RES / "icon.ico", sizes=[(s, s) for s in SIZES], append_images=images[:-1])
    print("wrote", RES / "icon.png", "and", RES / "icon.ico")


if __name__ == "__main__":
    main()
