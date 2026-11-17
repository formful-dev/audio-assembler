**Download:** `AudioAssembler-0.1.1-Setup.exe` (Windows 10 and 11, 64-bit). Nothing else needs to be installed. Installing over 0.1.0 updates it and keeps your settings.

Windows may show "Windows protected your PC" because the app is not signed. Click **More info**, then **Run anyway**.

### Fixed in 0.1.1
- Command line: no longer stops when file or folder names contain letters such as ā, č, ž and the output is saved to a file or read by another program. In folder mode this also stopped the remaining lessons.
- Long lessons use about half the memory (two 54-minute files: 0.9 GB instead of 1.8 GB).

### Other files in this release
- `ffmpeg-audio-win64.zip`: the small LGPL ffmpeg build used inside the app.
- `ffmpeg-9.0.2.tar.xz`, `lame-3.100.tar.gz`: the exact source code of that build (LGPL source offer).
