# 1.0.6 image verification — 2026-11-27

Release of the priority findings of the 2026-11-26 security/functional audit
(B-01 partial, B-01/B-02 trusted proxy, B-03, B-04, B-06), merged as PR #35.

- Source revision: `main@5dae03a` (merge of PR #35; change commit `e0f7281`).
- Build: `docker build -t marcinlis82/mistral-tts:1.0.6 --platform linux/amd64 .`
  on linux/amd64. Base `python:3.11-slim-trixie@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535`,
  audio-only FFmpeg 9.0.2 compiled from the hash-pinned upstream tarball, pip
  install with `--require-hashes --only-binary=:all:`.
- Local image ID: `sha256:2ad436eee5f94baf8b16ef95519dc053f74069e8f95489f2d3627aa1e070aefe` (195 MB).
- Published 2026-11-27 to Docker Hub as `marcinlis82/mistral-tts:1.0.6` and
  `:latest`; both tags point at the same manifest, digest
  `sha256:30e6ae038b8311c3eb818d1a88dac3c33fe64283315d60d5b955a0d48dcc0379`
  (confirmed via the Docker Hub tags API on 2026-11-27: `1.0.6` and `latest`
  report the identical digest).
- Checks before publication, on `main@5dae03a`:
  - `python3 -m ruff check src tests scripts` — all checks passed (ruff 0.15.16).
  - `python3 -m pytest -q` — 691 passed, 0 failed (ffmpeg/ffprobe present in PATH).
  - `python3 scripts/docker_smoke.py` — 7 tests, OK (nonroot startup, storage
    permission guards, default-credential lockout, upload/compile/download and
    restart persistence on a bind mount, build canary absent from all layers).
- Out of scope per the audit plan: B-08 (SSE-per-session limit), B-07 (ffprobe
  chunk validation in the OpenAI client), F-01/F-02, the Phase 3 refactor and
  pip-audit in CI.
