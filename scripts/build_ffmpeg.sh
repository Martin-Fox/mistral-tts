#!/bin/sh
# Audio-only FFmpeg from the upstream 9.0.2 release. Its archive signature was
# checked against FCF986EA15E6E293A5644F10B4322F04D67658D8 before pinning this hash.
# Usage: sh scripts/build_ffmpeg.sh /absolute/archive.tar.xz /absolute/prefix
set -eu

if [ "$#" -ne 2 ]; then
    echo "Usage: build_ffmpeg.sh ARCHIVE PREFIX" >&2
    exit 2
fi
ffmpeg_archive=$1
ffmpeg_prefix=$2
case "$ffmpeg_archive:$ffmpeg_prefix" in
    /*:/*) ;;
    *) echo "Archive and prefix must be absolute paths" >&2; exit 2 ;;
esac
ffmpeg_sha256=8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e
printf '%s  %s\n' "$ffmpeg_sha256" "$ffmpeg_archive" | sha256sum --check -
ffmpeg_work=$(mktemp -d)
trap 'rm -rf "$ffmpeg_work"' EXIT HUP INT TERM
tar -xJf "$ffmpeg_archive" -C "$ffmpeg_work" --no-same-owner
cd "$ffmpeg_work/ffmpeg-9.0.2"

# Disable optional dependency autodetection, networking, XML, video, devices
# and unrelated codecs. Lavfi/sine also support the offline runtime smoke.
# CFLAGS/LDFLAGS may select an isolated local development sysroot for testing.
./configure --prefix="$ffmpeg_prefix" \
    --disable-autodetect --disable-everything --disable-network \
    --disable-shared --enable-static --disable-debug --disable-doc \
    --disable-ffplay --disable-swscale --disable-iconv --disable-zlib \
    --disable-bzlib --disable-lzma --disable-libxml2 \
    --enable-ffmpeg --enable-ffprobe --enable-libmp3lame \
    --enable-protocol=file,pipe \
    --enable-demuxer=concat,mp3,wav,mov \
    --enable-muxer=mp3,wav,mp4,ipod,null \
    --enable-parser=mpegaudio,aac \
    --enable-decoder=mp3,mp3float,aac,pcm_u8,pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,pcm_f64le \
    --enable-encoder=libmp3lame,aac,pcm_u8,pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,pcm_f64le \
    --enable-filter=abuffer,abuffersink,anull,anullsrc,aformat,aresample,afftdn,loudnorm,sine \
    --enable-indev=lavfi
make -j "${FFMPEG_BUILD_JOBS:-2}"
make install
ffmpeg_notice="$ffmpeg_prefix/share/doc/booksmith-ffmpeg"
mkdir -p "$ffmpeg_notice"
cp COPYING.LGPLv2.1 "$ffmpeg_notice/"
printf '%s\n' 'https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz' "$ffmpeg_sha256" > "$ffmpeg_notice/source.txt"
"$ffmpeg_prefix/bin/ffmpeg" -version > "$ffmpeg_notice/configuration.txt"
