"""Put the pinned LGPL ffmpeg build into vendor/ffmpeg/ (Windows x64).

  python packaging/get_ffmpeg.py              download the pinned build and check its SHA-256
  python packaging/get_ffmpeg.py --zip FILE   use an already downloaded zip of the same version

Only ffmpeg.exe and the DLLs it needs are kept. The build is LGPL (no GPL or non-free parts).
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

RELEASE = "autobuild-2026-11-17-12-40"
ASSET = "ffmpeg-n9.0.2-57-gd838f9f9ae-win64-lgpl-shared-9.0.zip"
URL = f"https://github.com/BtbN/FFmpeg-Builds/releases/download/{RELEASE}/{ASSET}"
SHA256 = "8388f846a8b56a9316ad8f24d9eedf186097a59555816b7b222de392611b0279"
VERSION = "n9.0.2-57-gd838f9f9ae"

DEST = Path(__file__).resolve().parents[1] / "vendor" / "ffmpeg"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", type=Path, help="use this local zip instead of downloading")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        if args.zip:
            zpath = args.zip
        else:
            zpath = tmp / ASSET
            print(f"Downloading {URL}")
            urllib.request.urlretrieve(URL, zpath)
            if sha256(zpath) != SHA256:
                raise SystemExit("Checksum mismatch: the downloaded file is not the expected build.")

        extract = tmp / "x"
        with zipfile.ZipFile(zpath) as z:
            members = [m for m in z.namelist()
                       if "/bin/" in m and (m.endswith("ffmpeg.exe") or m.lower().endswith(".dll"))]
            z.extractall(extract, members)
        files = [p for p in extract.rglob("*") if p.is_file()]
        exe = next(p for p in files if p.name == "ffmpeg.exe")
        out = subprocess.run([str(exe), "-hide_banner", "-version"], capture_output=True, text=True).stdout
        if VERSION not in out:
            raise SystemExit(f"Unexpected ffmpeg version (expected {VERSION}):\n{out.splitlines()[0]}")
        conf = subprocess.run([str(exe), "-hide_banner", "-buildconf"], capture_output=True, text=True).stdout
        if "--enable-gpl" in conf or "--enable-nonfree" in conf:
            raise SystemExit("This ffmpeg build is not LGPL-only.")

        if DEST.exists():
            shutil.rmtree(DEST)
        DEST.mkdir(parents=True)
        for p in files:
            shutil.copy2(p, DEST / p.name)
    print(f"ffmpeg {VERSION} ready in {DEST}")


if __name__ == "__main__":
    main()
