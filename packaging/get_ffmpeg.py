"""Put the small LGPL ffmpeg build (made by packaging/ffmpeg/build_ffmpeg.sh) into vendor/ffmpeg/.

  python packaging/get_ffmpeg.py              download ffmpeg-audio-win64.zip from the latest release
  python packaging/get_ffmpeg.py --zip FILE   use a local ffmpeg-audio-win64.zip (for example a CI artifact)

The zip holds ffmpeg.exe, its licenses/ and BUILDINFO.txt.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

URL = "https://github.com/formful-dev/audio-assembler/releases/latest/download/ffmpeg-audio-win64.zip"
DEST = Path(__file__).resolve().parents[1] / "vendor" / "ffmpeg"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", type=Path, help="use this local zip instead of downloading")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        zpath = args.zip
        if zpath is None:
            zpath = tmp / "ffmpeg-audio-win64.zip"
            print(f"Downloading {URL}")
            urllib.request.urlretrieve(URL, zpath)
        extract = tmp / "x"
        with zipfile.ZipFile(zpath) as z:
            z.extractall(extract)
        exe = extract / "ffmpeg.exe"
        if not exe.is_file() or not (extract / "licenses").is_dir():
            raise SystemExit("This zip is not an ffmpeg-audio-win64.zip (ffmpeg.exe or licenses/ missing).")
        if sys.platform == "win32":
            conf = subprocess.run([str(exe), "-hide_banner", "-buildconf"], capture_output=True, text=True).stdout
            if "--enable-gpl" in conf or "--enable-nonfree" in conf:
                raise SystemExit("This ffmpeg build is not LGPL-only.")
            encoders = subprocess.run([str(exe), "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
            if "libmp3lame" not in encoders:
                raise SystemExit("This ffmpeg build has no MP3 encoder.")
        if DEST.exists():
            shutil.rmtree(DEST)
        shutil.copytree(extract, DEST)
    print(f"ffmpeg ready in {DEST}")


if __name__ == "__main__":
    main()
