#!/usr/bin/env bash
# Builds a small LGPL ffmpeg.exe for Windows x64 that contains only what Audio Assembler needs:
# reading common audio formats, resampling, loudness measurement, and writing WAV and MP3 (LAME).
#
# Runs on Ubuntu with the mingw-w64 cross compiler (see .github/workflows/build.yml):
#   sudo apt-get install -y mingw-w64 nasm make pkg-config curl xz-utils
#   bash packaging/ffmpeg/build_ffmpeg.sh OUTPUT_DIR
#
# Output: OUTPUT_DIR/ffmpeg-audio-win64.zip  (ffmpeg.exe, licenses/, BUILDINFO.txt)
#         OUTPUT_DIR/sources/                (exact source archives, for the LGPL source offer)
set -euo pipefail

FFMPEG_VERSION=9.0.2
FFMPEG_SHA256=""   # filled in after the first verified download; empty = print only
LAME_VERSION=3.100
LAME_SHA256=ddfe36cab873794038ae2c1210557ad34857a4b6bdc515785d1da9e175b1da1e
HOST=x86_64-w64-mingw32

OUT=$(realpath -m "${1:-ffmpeg-out}")
WORK=$(mktemp -d)
PREFIX=$WORK/prefix
mkdir -p "$OUT/sources" "$PREFIX"
cd "$WORK"

fetch() {  # url file sha256
  curl -fsSL --retry 3 -o "$2" "$1"
  local got; got=$(sha256sum "$2" | cut -d' ' -f1)
  echo "$2 sha256 $got"
  if [ -n "$3" ] && [ "$got" != "$3" ]; then echo "Checksum mismatch for $2" >&2; exit 1; fi
}
fetch "https://downloads.sourceforge.net/project/lame/lame/$LAME_VERSION/lame-$LAME_VERSION.tar.gz" \
      "lame-$LAME_VERSION.tar.gz" "$LAME_SHA256"
fetch "https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VERSION.tar.xz" "ffmpeg-$FFMPEG_VERSION.tar.xz" "$FFMPEG_SHA256"
cp "lame-$LAME_VERSION.tar.gz" "ffmpeg-$FFMPEG_VERSION.tar.xz" "$OUT/sources/"

# --- LAME (MP3 encoder), static library only
tar xzf "lame-$LAME_VERSION.tar.gz"
(
  cd "lame-$LAME_VERSION"
  ./configure --host=$HOST --prefix="$PREFIX" --enable-static --disable-shared \
              --disable-frontend --disable-decoder --disable-gtktest --enable-nasm
  make -j"$(nproc)" install
)

# --- FFmpeg: everything off, then only the audio parts we use
tar xJf "ffmpeg-$FFMPEG_VERSION.tar.xz"
PCM=pcm_s8,pcm_u8,pcm_s16le,pcm_s16be,pcm_s24le,pcm_s24be,pcm_s32le,pcm_s32be,pcm_f32le,pcm_f32be,pcm_f64le,pcm_f64be,pcm_alaw,pcm_mulaw
CONFIGURE=(
  --target-os=mingw32 --arch=x86_64 --cross-prefix=$HOST- --prefix="$PREFIX"
  --enable-static --disable-shared --disable-debug --disable-doc --disable-autodetect
  --disable-everything --disable-network --disable-avdevice --disable-swscale
  --disable-ffprobe --disable-ffplay --enable-ffmpeg --enable-w32threads
  --enable-libmp3lame --enable-swresample
  --extra-cflags="-I$PREFIX/include" --extra-ldflags="-L$PREFIX/lib -static"
  --enable-protocol=file,pipe
  --enable-demuxer=wav,w64,mp3,flac,ogg,mov,aac,aiff,asf,pcm_f32le
  --enable-decoder=$PCM,mp3,mp3float,mp2,mp2float,flac,vorbis,opus,aac,aac_fixed,alac,wmav1,wmav2,wmapro,adpcm_ms,adpcm_ima_wav
  --enable-parser=mpegaudio,flac,aac,vorbis,opus
  --enable-muxer=wav,mp3,null
  --enable-encoder=pcm_s16le,pcm_f32le,libmp3lame
  --enable-filter=aresample,aformat,anull,ebur128,abuffer,abuffersink
)
(
  cd "ffmpeg-$FFMPEG_VERSION"
  ./configure "${CONFIGURE[@]}"
  make -j"$(nproc)"
  $HOST-strip ffmpeg.exe
)

# --- Package
PKG=$WORK/pkg
mkdir -p "$PKG/licenses"
cp "ffmpeg-$FFMPEG_VERSION/ffmpeg.exe" "$PKG/"
cp "ffmpeg-$FFMPEG_VERSION/LICENSE.md" "$PKG/licenses/FFmpeg-LICENSE.md"
cp "ffmpeg-$FFMPEG_VERSION/COPYING.LGPLv2.1" "$PKG/licenses/LGPL-2.1.txt"
cp "lame-$LAME_VERSION/COPYING" "$PKG/licenses/LAME-COPYING.txt"
{
  echo "FFmpeg $FFMPEG_VERSION with LAME $LAME_VERSION, Windows x64, static, LGPL (no GPL or non-free parts)."
  echo "Built by packaging/ffmpeg/build_ffmpeg.sh of Audio Assembler."
  echo "Sources: https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VERSION.tar.xz"
  echo "         https://downloads.sourceforge.net/project/lame/lame/$LAME_VERSION/lame-$LAME_VERSION.tar.gz"
  echo "Copies of both source archives are attached to each Audio Assembler release."
  echo
  echo "configure ${CONFIGURE[*]}"
} > "$PKG/BUILDINFO.txt"

if grep -qE -- "--enable-(gpl|nonfree)" "ffmpeg-$FFMPEG_VERSION/ffbuild/config.mak"; then
  echo "Refusing: build is not LGPL-only" >&2; exit 1
fi
(cd "$PKG" && zip -qr "$OUT/ffmpeg-audio-win64.zip" .)
ls -la "$OUT" "$PKG"
