# Release notes

[Documentation](README.md) · [Project overview](../README.md)

## Security audit 2026-11-26 — 1.0.6

This release applies the priority findings of the security/functional audit of
2026-11-26 (audited base `main@c65d470`; merged as PR #35 from
`fix/security-audit-2026-11-26`):

- B-01 (partial): the login limiter now also keeps a global per-account counter,
  so rotating source addresses (including spoofed `X-Forwarded-For`) cannot
  multiply the 5-attempts-per-account allowance.
- B-01/B-02: a new `TrustedProxyHeaders` middleware resolves the client address
  from `X-Forwarded-For` only when the direct peer is inside
  `TRUSTED_PROXY_CIDRS`; unset/empty (default) trusts nobody, malformed or
  duplicated headers fail closed, and an invalid value stops startup. The Docker
  default (`--no-proxy-headers`) is unchanged.
- B-03: `/api/audio/{filename}` serves a per-extension `Content-Type`
  (`.mp3` audio/mpeg, `.wav` audio/wav, `.m4b` audio/mp4) instead of always
  audio/mpeg.
- B-04: login success/failure/lockout, logout and password changes are logged on
  the `booksmith.auth` logger with source address and username only — never
  passwords, session tokens or API keys.
- B-06: voice-reference decoding applies `RLIMIT_AS`/`RLIMIT_FSIZE`/`RLIMIT_CPU`/
  `RLIMIT_CORE` via `preexec_fn` on every POSIX platform; Linux keeps the
  mandatory `prlimit` wrapper.

Verification: `ruff check src tests scripts` clean; full offline suite
**691 passed, 0 failed** on `main@c65d470` (with ffmpeg/ffprobe in PATH);
Docker smoke suite **7/7 OK** on the published image. Image
`marcinlis82/mistral-tts:1.0.6` (linux/amd64), manifest digest
`sha256:30e6ae038b8311c3eb818d1a88dac3c33fe64283315d60d5b955a0d48dcc0379`;
`latest` points at the same manifest. Source revision `main@5dae03a`.
See the [1.0.6 image verification and digest](audit/RELEASE_1.0.6_2026-11-27.md).

## Security audit remediation — 1.0.5

This release applies the findings of the read-only repository audit of
2026-11-24 (findings F-01..F-11):

- F-01: the Windows release workflow pins its actions by commit SHA and
  installs a hash-locked toolchain (`requirements-dev.txt` with
  `--require-hashes --only-binary=:all:` plus `pip check`);
  `pyinstaller==6.22.3` is now a pinned dev dependency.
- F-02: `.env` (provider keys, `APP_PASSWORD`) is tightened to mode `0600` on
  POSIX at startup and on every write.
- F-03: `storage/` and per-task upload directories are created `0700`;
  uploaded text/voice files are published atomically with mode `0600`.
- F-04: the login limiter no longer locks out brand-new clients when its entry
  table is full; only redundant entries of already locked-out sources are
  evicted, so per-source limits still hold.
- F-05: the desktop launcher warns when binding a non-loopback address without
  `SESSION_COOKIE_SECURE=true` (cleartext cookies/credentials).
- F-08: the CLI warns when API keys are passed as command-line arguments
  (visible in the process list and shell history).
- F-06: a corrupt translation checkpoint is treated as a cache miss and
  re-translated instead of failing the whole job.
- F-07: dead `shutil.which(...)` expression removed from FFmpeg binary
  resolution.
- F-09: Google Fonts removed from the WebUI; the CSP now has no external
  origins (system font stack).
- F-10: compiled-audiobook duration verification is now two-sided; output
  longer than expected + 4.0 s tolerance is rejected as well.
- F-11: the deprecated FastAPI `@app.on_event("startup")` hook is replaced by
  a lifespan handler.

Verification: full offline test suite **665 passed** (the 2 failures in
`test_test_isolation.py` are sandbox-only — the `pytest-timeout` plugin is not
installed locally and both fail identically on the base commit), `ruff check`
clean, and every finding has a new regression test. Splitter and voice
preprocessing versions are unchanged, so existing audio caches and saved
resumable jobs remain compatible.
See the [1.0.5 image verification and digest](audit/RELEASE_1.0.5_2026-11-24.md).

## Security update — 1.0.4

This release includes the November 2026 security audit remediations:

- Requests are authenticated before upload processing and queue admission;
  bounded request sizes, upload deadlines and disabled proxy-header trust by
  default reduce unauthenticated resource consumption and address spoofing.
- State-changing requests require a matching Origin or, for originless clients,
  `X-Requested-With: Booksmith`. Browser responses include CSP, frame protection
  and no-store headers. Interactive Swagger/ReDoc pages are disabled.
- New passwords require 12–1024 characters. Existing short passwords allow only
  password rotation; changing the password revokes all sessions.
- Voice references accept MP3/PCM WAV only, with duration, allocation, process
  and output limits. Normalization failures stop the job without sending the
  original file to the provider. Linux adds `prlimit` resource limits.
- EPUB XML metadata rejects DTD/entities and excessive nesting. WebUI MOBI
  upload/resume is disabled; trusted local CLI/TUI MOBI remains available.
- Both hashed Python locks include Mistral SDK 2.10.1, OpenTelemetry API 1.45.2,
  AnyIO 4.14.2 and python-dotenv 1.2.2. Both locks had zero known findings in
  the 2026-11-18 pip-audit scan.
- Docker builds a hash-pinned audio-only FFmpeg 9.0.2 without libxml2, networking
  or video codecs; runtime installers are removed and zlib has a corrected
  minimum version. Windows packaging separately pins its FFmpeg archive/hash.

Before upgrading, stop the old instance and back up all of `storage/`. Existing
sessions reset on restart. Reference preprocessing version 3 invalidates older
cloned-voice cache/resume identities; resubmission may incur provider charges.
Update custom HTTP clients for the request header above, and configure trusted
proxy forwarding explicitly when terminating HTTPS at a reverse proxy.

Verification before image publication: **651 tests passed** with the new SDK
and locally compiled FFmpeg, plus **223 portable smoke tests** (a subset).
These are offline checks, not native Windows acceptance or a zero-CVE claim for
the image. FFmpeg retains known native risks, including MOV parsing used for
generated M4B verification; decoder limits are not a complete OS sandbox.
See the [audit and remediation record](audit/SECURITY_AUDIT_2026-11-18.md),
[dependency update report](audit/SECURITY_DEPENDENCY_UPDATES_2026-11-18.md),
[native dependency limits](NATIVE_DEPENDENCIES.md) and
[deployment guidance](SECURITY_DEPLOYMENT.md).

The published **linux/amd64** image passed **7 Docker smoke checks**. Its package
scan found **0 Critical** and **0 Python findings**, with **96 remaining OS CVEs**
(including 11 High); compiled FFmpeg also retains separately documented risks.
See the [1.0.4 image verification and digest](audit/RELEASE_1.0.4_2026-11-18.md).
