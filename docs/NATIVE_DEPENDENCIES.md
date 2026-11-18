# Native dependency baseline (2026-11-18)

The current Docker recipe targets FFmpeg/ffprobe **9.0.2**, built from reviewed
source with an audio-only component profile. It no longer installs Debian's
general FFmpeg package and its XML/video/network dependency graph. The Mistral
SDK/Python lock policy is documented in [Dependencies](DEPENDENCIES.md).

The later authorized Docker release is **1.0.4**; see its
[image verification, scan and digest](audit/RELEASE_1.0.4_2026-11-18.md).
The local validation below preceded that release. Publishing the image did not
update the installed LAN container.

## Source and provenance

| Item | Pin |
| --- | --- |
| Upstream source | `https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz` |
| Source SHA-256 | `8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e` |
| Release signing key fingerprint | `FCF986EA15E6E293A5644F10B4322F04D67658D8` |
| Windows archive | `https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-essentials_build.zip` |
| Windows archive SHA-256 | `60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba` |

The source archive's detached OpenPGP signature was verified against the key
fingerprint published on the [official download page](https://ffmpeg.org/download.html).
The build script verifies its pinned SHA-256 **before extraction or compilation**.
Changing the downloaded bytes fails the build; there is no moving-source fallback.
The Windows ZIP was downloaded and its computed digest matched the release asset
digest. Pinning a binary hash establishes its identity, not absence of all CVEs
or its embedded dependency versions.

## Linux/Docker component profile

[build_ffmpeg.sh](../scripts/build_ffmpeg.sh) is shared by Docker's build stage
and the local validation procedure. Its internal FFmpeg libraries are static;
LAME, libc and libm are dynamic. Local `ldd` confirmed that dependency set and
no libxml2. The runtime stage installs `libmp3lame0`, not the compiler
toolchain. An explicit Dockerfile guard rejects an installed libxml2 package.

- Input demuxers: MP3, WAV, concat and MOV/MP4 (for verifying generated M4B).
- Output muxers: MP3, WAV, MP4/iPod and null decoded-duration verification.
- Decoders: MP3, MP3 float, AAC and the supported little-endian PCM formats.
- Encoders: LAME MP3, AAC and PCM; no video/subtitle encoders/decoders.
- Filters: afftdn, loudnorm, aresample/aformat/anull and required buffers;
  anullsrc for pauses and sine/lavfi for offline synthetic smoke tests.
- Protocols: `file` and `pipe` only. Networking, libxml2, iconv, zlib, bzlib,
  lzma and automatic detection of optional build libraries are disabled.

The normal MP3/WAV/M4B output contract, pauses, trailing padding and full decoded
duration validation are preserved. This is not a general-purpose FFmpeg image:
other media formats/network streams are intentionally unavailable. Application
reference decoding still forces MP3/PCM WAV with its own codec and resource
limits, even when a user selects a general system FFmpeg outside Docker.

The profile is LGPL-2.1-or-later; the build includes its license, source URL/hash
and configure output under `/usr/local/share/doc/booksmith-ffmpeg`. Apt retains
the LAME package's notices. Source pins do not pin compiler/apt/LAME bytes, so
this is not a claim of bit-for-bit reproducible images.

## Build and check without Docker

The helper requires a POSIX shell, compiler/make, xz/tar, sha256sum, nasm and
LAME development headers/library. Docker obtains them only in its build stage.
For an existing prepared development host:

```bash
curl --fail --location --proto '=https' --tlsv1.2 \
  https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz -o /tmp/ffmpeg-9.0.2.tar.xz
FFMPEG_BUILD_JOBS=2 sh scripts/build_ffmpeg.sh \
  /tmp/ffmpeg-9.0.2.tar.xz /tmp/booksmith-ffmpeg
PATH="/tmp/booksmith-ffmpeg/bin:$PATH" python -m pytest -q
PATH="/tmp/booksmith-ffmpeg/bin:$PATH" python scripts/platform_smoke.py
ldd /tmp/booksmith-ffmpeg/bin/ffmpeg
```

Use the hash-installed development environment for the Python commands. Local
validation used CPython 3.11.2/GCC 12 on Debian 12, with compiler support packages
extracted to a temporary sysroot; the host package database was not changed.
Both ffmpeg and ffprobe reported 9.0.2. Full regression: **651 passed**, including
MP3/WAV/M4B compilation, normalized references, cleanup/cancellation, HTTP and SDK
wire contracts. Portable Unicode-checkout smoke: **223 passed**, an overlapping
subset. These checks made no paid provider requests.

## CVE interpretation and outstanding gates

Debian trixie still supplies FFmpeg `7:7.1.5-0+deb13u1` and the older libxml2
package; see [FFmpeg tracker](https://security-tracker.debian.org/tracker/source-package/ffmpeg)
and [libxml2 tracker](https://security-tracker.debian.org/tracker/source-package/libxml2).
The new source profile avoids mixing unstable Debian libraries into stable.

FFmpeg 9.0.2 contains the upstream fixes for the previously identified
[ADX/AAX issue](https://security-tracker.debian.org/tracker/CVE-2026-64835) and
[CAF/MACE6 issue](https://security-tracker.debian.org/tracker/CVE-2026-66039).
Those decoders/demuxers are additionally disabled in this profile. XML-dependent
FFmpeg features are absent, so the runtime recipe does not need libxml2. EPUB
continues to use ElementTree/Expat with the separate DTD/tree guards.

**9.0.2 is not vulnerability-free.** Remaining tracker issues need component
review, not a blanket allowlist based on the version. For example:

- [CVE-2026-125072](https://security-tracker.debian.org/tracker/CVE-2026-125072)
  concerns the mp3adu decoder/API; mp3adu is not compiled into this profile.
- [CVE-2026-107678](https://security-tracker.debian.org/tracker/CVE-2026-107678)
  concerns MOV/MP4 pssh processing. MOV remains enabled to verify generated M4B;
  references cannot select it, because the application accepts only forced
  MP3/PCM WAV. It is still present in the native binary and must remain tracked.

The latter is not claimed fixed. Keep input/CPU/memory/time guards, review new
upstream releases/backports and complete the separate process-containment work.
The Python audit's zero findings says nothing about residual native/OS CVEs.

Windows pins a general Gyan GPLv3 build, not this Linux profile. Its README lists
libxml2; the embedded XML library version was not established by the ZIP hash
and is not claimed fixed. Its native binaries/final app need Windows acceptance
and dependency attestation. Other source installations retain the administrator's
selected FFmpeg until they install/select an updated binary.

For each subsequent Docker release: verify runtime versions,
dynamic linkage, absence of libxml2, entrypoint/nonroot startup, all container
smokes, a fresh OS/native SBOM/CVE scan and the exact deployable digest. No local
source test substitutes for those release checks.
