# Release notes

[Documentation](README.md) · [Project overview](../README.md)

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
The published **linux/amd64** image (`marcinlis82/mistral-tts:1.0.5`, with
`latest` pointing at the same manifest) has manifest digest
`sha256:373b47b928b5b9e6a0b484526f378d9d3295093f692593d9f6c7c8e8e78b3162`
(config digest `sha256:a75c2dd83ed758cfd6248c2de39aab9642401d9eecdf62851ff10f57b2e1c589`),
verified on 2026-11-24 via `docker manifest inspect` and the Docker Hub API.

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
See [native dependency limits](NATIVE_DEPENDENCIES.md) and
[deployment guidance](SECURITY_DEPLOYMENT.md). Dated audit reports and raw
scanner evidence are no longer kept in this repository (decision of 2026-11-24);
see [plans/2026-11-24-audit-comparison.md](plans/2026-11-24-audit-comparison.md).

The published **linux/amd64** image passed **7 Docker smoke checks**. Its package
scan found **0 Critical** and **0 Python findings**, with **96 remaining OS CVEs**
(including 11 High); compiled FFmpeg also retains separately documented risks.
The 1.0.4 image manifest digest was
`sha256:6a33ab36dcbe5a1b0d18878a1dc19646fda1eddaf2c30d66e416d1a47c4410a5`
(superseded by 1.0.5).
