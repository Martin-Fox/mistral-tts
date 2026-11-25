# Audit comparison and forward plan — 2026-11-24

**Goal:** re-audit the repository on current `main` (`01a8738`, includes PR #32
and #33), compare the result with the previous audit conclusions, and record the
remaining work as a forward plan.

**Method:** read-only audit of all security-relevant source (`src/api`, `src/core`,
`src/web.py`, `src/web_limits.py`, `src/web_security.py`, `src/web/static`, CLI/TUI/
desktop, Dockerfile, entrypoint, CI workflows, locks, tests), spot-verified with
greps against `main`; full offline test suite and `ruff check` run locally.
Initial and final commit of the audited tree: `01a8738`.

---

## 1. Previous 2026-11-18 security audit (S01–S07) — status on main

| ID | Previous finding | Status on `main` | Evidence |
| --- | --- | --- | --- |
| S01 | Anonymous clients can occupy all generation-admission slots before auth | **Fixed** (PR #30) | `src/web_limits.py` authenticates before admission/body spooling; body deadline + idle timeout; regression tests in `tests/test_request_security.py` |
| S02 | Voice-reference decoding via wide FFmpeg surface | **Fixed** (PR #30) | `src/core/voice_reference.py`: magic-byte format gate, protocol/format/codec whitelists, `-max_alloc`, scrubbed env, `prlimit` AS/CPU/core/fsize on Linux, output byte budget, fail-closed |
| S03 | Body limits did not cover login/config JSON | **Fixed** (PR #30) | `MAX_JSON_REQUEST_BYTES` enforced pre-parse in middleware for non-generation requests |
| S04 | MOBI extraction without isolated budget | **Mitigated by policy** | WebUI upload/resume rejects MOBI with 415 (`check_web_document`); CLI/TUI remain trusted-local only. Isolated worker still open — see forward plan |
| S05 | Very weak passwords accepted | **Fixed** (PR #30) | 12–1024 char policy (`src/core/auth.py`); legacy short persisted passwords get a change-only session |
| S06 | Windows build fetched mutable artifacts | **Fixed** (this re-audit, F-01, PR #32) | actions pinned by commit SHA, `persist-credentials: false`, hash-locked `requirements-dev.txt` incl. `pyinstaller==6.22.3`, FFmpeg archive SHA-256 verified |
| S07 | No Origin/CSRF protection or security headers | **Fixed** (PR #30) | `src/web_security.py`: `permitted_write` origin/`X-Requested-With` contract, CSP, `X-Frame-Options`, `nosniff`, `Referrer-Policy`, `no-store` on `/` and `/api/` |

Dependency decisions from that audit (AnyIO 4.14.2, python-dotenv 1.2.2,
uv 0.13.4, zlib floor, installer removal, OTel/SDK conflict) are reflected in the
current locks and `PROJECT.md` SDK contract (`mistralai==2.10.1`,
`opentelemetry-api==1.45.2`).

## 2. Earlier remediation plan (P01–P23) — status

Implemented in PR #29 (commit `b11b4d5`) and spot-verified on `main`:
credential file 0600 + PBKDF2, session TTL/revocation, login limiter, v2 cache
identity + manifest validation, atomic chunk publication with per-cache OS locks,
state-aware retention (dry-run default), durable resume inputs without API keys,
bounded process runner, bounded retry policy, isolated offline test suite with a
network guard, Docker smoke script. **Status: implemented.**

## 3. New findings of the 2026-11-24 re-audit (F-01–F-11) — status

All fixed in PR #32 and verified present on `main` (grep + tests):

| ID | Finding | Status |
| --- | --- | --- |
| F-01 | Unpinned Windows release workflow | Fixed — SHA-pinned actions, hash-locked toolchain |
| F-02 | `.env` world-readable by default | Fixed — `0600` on POSIX at load and on save (`src/core/config.py`) |
| F-03 | Upload temp dirs/files world-readable | Fixed — `storage/` + `task_<id>` dirs `0700`, uploads via `staged_file` `0600` (`src/web.py`) |
| F-04 | Login-limiter table-full global lockout | Fixed — only redundant entries of locked-out sources are evicted (`src/core/login_limiter.py`) |
| F-05 | Cleartext non-loopback binding silent | Fixed — startup warning (`src/desktop.py`) |
| F-06 | Corrupt translation checkpoint fails job | Fixed — treated as cache miss, re-translated (`src/api/mistral_client.py`) |
| F-07 | Dead `shutil.which` code in FFmpeg resolution | Fixed (`src/core/ffmpeg_utils.py`) |
| F-08 | API keys via CLI argv visible in process list | Fixed — warning (`src/cli.py`) |
| F-09 | Google Fonts external origins in WebUI/CSP | Fixed — removed; CSP has no external origins |
| F-10 | One-sided compiled-duration check | Fixed — two-sided with 4.0 s tolerance (`src/core/audio_compiler.py`) |
| F-11 | Deprecated `@app.on_event("startup")` | Fixed — lifespan handler (`src/web.py`) |

Verification: full suite **665 passed** (2 failures in `test_test_isolation.py`
are sandbox-only: missing `pytest-timeout` plugin locally; identical on the base
commit), `ruff check src tests scripts` clean, one regression test per finding.

## 4. Forward plan (remaining work)

- **P0 — deployment verification (operator):** confirm the running LAN container
  matches the published 1.0.5 manifest digest
  `sha256:373b47b928b5b9e6a0b484526f378d9d3295093f692593d9f6c7c8e8e78b3162`;
  enforce HTTPS + `SESSION_COOKIE_SECURE=true` behind the TLS proxy; never expose
  Uvicorn directly; keep host publication loopback-only.
- **P1 — scanning in CI and a fresh 1.0.5 scan:** add `pip-audit` on both locks,
  Trivy image scan and SBOM generation to `.gitea/workflows/ci.yml` (planned in the
  2026-11-18 audit, not yet in CI). Run a one-off scan of
  `marcinlis82/mistral-tts:1.0.5` and triage the remaining OS CVEs (96 incl.
  11 High at the 1.0.4 scan) with owner + expiry date per exception. Also verify
  the current (future-dated) pins against CVE databases online at every lock
  refresh — they could not be checked offline during this audit.
- **P1 — dependency watch:** when bumping `mistralai`, re-verify the
  OpenTelemetry contract and the offline SDK wire tests as required by
  `PROJECT.md#constraints`.
- **P2 — native code risk tracking:** track Expat (used by EPUB parsing) and the
  self-built audio-only FFmpeg advisories (e.g. the MOV issue noted for 1.0.4);
  rebuild FFmpeg from upstream releases and update the pinned archive hash in
  `scripts/build_ffmpeg.sh` / `build-windows.yml`.
- **P2 — MOBI decision:** either implement an isolated extraction worker with
  resource limits, or keep MOBI permanently trusted-local-only (CLI/TUI) and say
  so in README/USAGE.
- **P2 — native Windows acceptance:** run the PyInstaller artifact on a clean
  Windows host per `docs/WINDOWS.md` before declaring the standalone EXE accepted.
- **P3 — test gaps:** desktop `find_available_port` TOCTOU; load/concurrency tests
  (many SSE clients, admission races on `/api/generate`); deeper TUI coverage.
- **P3 — docs hygiene:** note HSTS at the TLS terminator in `SECURITY_DEPLOYMENT.md`;
  keep exception reviews dated.

## 5. Process decision recorded on 2026-11-24

Per operator decision, the `docs/audit/` catalog (dated audit reports and raw
scanner evidence) is removed from the repository and from git history of the
working tree. Image digests and release verification summaries are preserved in
`docs/RELEASE_NOTES.md`; this comparison is kept under `docs/plans/`. Future audits
should keep raw evidence (scanner CSV/JSON, reproduction scripts) outside the
public repo (private archive) and commit only conclusions, digests and plans.
