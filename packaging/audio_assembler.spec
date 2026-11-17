# PyInstaller recipe: one folder with "Audio Assembler.exe" (window) and "audio-assembler.exe" (command line).
# Build with:  packaging\build_windows.ps1
from pathlib import Path

ROOT = Path(SPECPATH).parent
RES = ROOT / "src" / "audio_assembler" / "gui" / "resources"
FFMPEG = ROOT / "vendor" / "ffmpeg"

if not (FFMPEG / "ffmpeg.exe").is_file():
    raise SystemExit("ffmpeg is missing. Run: python packaging/get_ffmpeg.py")

# ffmpeg is copied as-is (not analysed) into <app>/_internal/ffmpeg/
datas = [(str(p), "ffmpeg") for p in FFMPEG.iterdir() if p.suffix.lower() in (".exe", ".dll")]
datas += [(str(RES / name), "audio_assembler/gui/resources") for name in ("icon.png", "icon.ico", "icon.svg")]

excludes = ["tkinter", "unittest", "pydoc_data", "test", "PIL", "pytest",
            "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtWebEngineCore",
            "PySide6.QtPdf", "PySide6.QtMultimedia", "PySide6.QtOpenGL", "PySide6.Qt3DCore"]

gui = Analysis([str(ROOT / "packaging" / "launcher_gui.py")], pathex=[str(ROOT / "src")],
               datas=datas, excludes=excludes)
cli = Analysis([str(ROOT / "packaging" / "launcher_cli.py")], pathex=[str(ROOT / "src")],
               excludes=excludes + ["PySide6", "shiboken6"])


def slim(toc):
    """Drop files the app never uses: a second copy of the ffmpeg DLLs that PyInstaller finds through
    ffmpeg.exe, Qt modules for QML/Quick/PDF/3D, the software OpenGL fallback, and Qt translations."""
    ffmpeg_names = {p.name.lower() for p in FFMPEG.iterdir()}
    drop_parts = ("opengl32sw", "qt6quick", "qt6qml", "qt6pdf", "qt6virtualkeyboard", "qt6opengl",
                  "qt6network", "qt6svg", "qpdf", "qsvg", "qtvirtualkeyboard", "pyside6/translations",
                  "pyside6\\translations", "libcrypto", "libssl", "_ssl")
    kept = []
    for entry in toc:
        dest = entry[0].replace("\\", "/").lower()
        if "/" not in dest and dest in ffmpeg_names:
            continue
        if any(part.replace("\\", "/") in dest for part in drop_parts):
            continue
        kept.append(entry)
    return kept


gui.binaries, gui.datas = slim(gui.binaries), slim(gui.datas)
cli.binaries, cli.datas = slim(cli.binaries), slim(cli.datas)

gui_exe = EXE(PYZ(gui.pure), gui.scripts, [], exclude_binaries=True, name="Audio Assembler",
              icon=str(RES / "icon.ico"), console=False, upx=False)
cli_exe = EXE(PYZ(cli.pure), cli.scripts, [], exclude_binaries=True, name="audio-assembler",
              icon=str(RES / "icon.ico"), console=True, upx=False)

coll = COLLECT(gui_exe, cli_exe, gui.binaries, gui.datas, cli.binaries, cli.datas,
               name="Audio Assembler", upx=False)
