# Mistral-TTS Docker Image Overview

This repository contains the containerized version of **Mistral-TTS**, a text-to-speech pipeline designed to convert long-form text (articles, books, essays) into seamless audiobooks. It integrates the **Mistral AI Voxtral TTS** API (with zero-shot voice cloning), **OpenAI TTS** as an alternative engine, configurable **Mistral chat models** (default: `ministral-8b-latest`) for pre-translation, and support for EPUB, MOBI, SRT, and TXT ingestion.

The Dockerfile bundles Python 3.11, runtime dependencies, **FFmpeg and ffprobe**.
Build the current checkout to include its remediations; historical registry tags
(including `1.0.2`) have not been checked against this branch.

```bash
docker build -t mistral-tts:audit-local .
mkdir -p storage
```

See [Operations](docs/OPERATIONS.md) for TLS, restart recovery, backup/restore and
upgrade/rollback procedures. All examples below use the locally built image.

---

## 🛠️ How to Run the Container

The container supports running the WebUI, the interactive Terminal UI (TUI), or standard CLI commands.

### 1. Run the WebUI (Default)
To start the responsive, glassmorphism WebUI, expose port `8000` and mount a local folder to `/app/storage` to persist generated audiobooks, manifests, and cache state.

```bash
docker run -d \
  -p 127.0.0.1:8000:8000 \
  -v "$PWD/storage:/app/storage" \
  --env-file "$PWD/.env" \
  --name mistral-tts \
  mistral-tts:audit-local
```

Once running, access the WebUI at **`http://localhost:8000`**.
*Note: Set a unique `APP_PASSWORD` before first start. Empty credentials and the password `admin` prevent WebUI startup, even on localhost. `APP_USERNAME` defaults to `admin`. If mounted storage contains `auth.json`, its credentials take precedence: follow [credential recovery](docs/OPERATIONS.md#credential-recovery) if it contains rejected credentials.*

### 2. Run the Interactive TUI
To run the terminal configuration and progress tracking interface inside the container, run with interactive terminal flags (`-it`):

```bash
docker run -it --rm \
  -v "$PWD/storage:/app/storage" \
  --env-file "$PWD/.env" \
  mistral-tts:audit-local \
  python -m src.cli --tui
```

### 3. Run via Headless CLI
For automated script integrations, execute the CLI directly:

```bash
docker run --rm \
  -v "$PWD/storage:/app/storage" \
  --env-file "$PWD/.env" \
  mistral-tts:audit-local \
  python -m src.cli \
  --text /app/storage/book.txt \
  --voice /app/storage/sample.mp3 \
  --output /app/storage/audiobook.mp3
```

---

## ⚙️ Environment Variables

Create a private host `.env` as described in README. `--env-file` injects its
values at container creation; changes require container recreation. It does not
mount the file, and writing `/app/.env` in WebUI/TUI does not update the host file.
For model settings that must survive container replacement, set
`BOOKSMITH_ENV_FILE=/app/storage/application.env` and keep that writable file on
the storage mount. Omit `MISTRAL_TRANSLATION_MODEL` from injected process variables
if the saved file should select it after restart: process variables take priority.
This path is private configuration, not a public upload.

The main environment variables are listed below; the complete limit, retry,
process-timeout and retention tables are in README.

| Variable | Description |
| --- | --- |
| `MISTRAL_API_KEY` | Your Mistral AI API Key (required for Voxtral TTS and Translation). |
| `OPENAI_API_KEY` | Your OpenAI API Key (required if selecting the OpenAI TTS engine). |
| `MISTRAL_TRANSLATION_MODEL` | Mistral chat model for text translation (default: `ministral-8b-latest`). |
| `APP_USERNAME` | Custom username for WebUI cookie authentication (default: `admin`). |
| `APP_PASSWORD` | Required unique password for WebUI cookie authentication; empty values and `admin` are rejected at startup. |

---

## 🌟 Key Features

* **Dual Engine Support:** Mistral Voxtral reference-audio/preset synthesis and OpenAI TTS presets (`alloy`, `echo`, `fable`, `onyx`, `nova`, `shimmer`). Provider access and output quality are not established by offline tests.
* **Integrated Translation:** Automatic language-to-language translation using configurable Mistral chat models (default: `ministral-8b-latest`) prior to speech synthesis.
* **Format Ingestion:** Parsers for `.txt`, `.srt` (translation retains timecodes; speech segmentation removes cue numbers and timing), `.epub`, and unencrypted `.mobi` ebooks.
* **Persistent SQLite States:** Task state, progress, and logs are tracked in a SQLite database (`storage/state.db`) to survive container restarts.
* **Storage Maintenance:** State-aware retention defaults to dry-run; deletion can be enabled for expired completed jobs and recognized orphaned artifacts. Failed/interrupted jobs remain protected.

---

## 🔗 Project Links

* **Primary Repository & Source of Truth:** [Gitea Instance](https://gitea.marcin-lis.pl/fox/mistral-tts)
* **Public Mirror (Feedback, Comments, Issues & PRs):** [GitHub Mirror](https://github.com/Martin-Fox/mistral-tts)

### WebUI password storage and migration

The WebUI stores salted PBKDF2-HMAC-SHA256 password hashes (600,000 iterations),
not plaintext passwords, in `storage/auth.json`. Existing plaintext files are
migrated atomically during startup; migration failure stops startup and preserves
the original file. Environment credentials are hashed in memory and do not create
an auth file until the password is changed through the WebUI. Unicode passwords
and usernames are supported. On POSIX, the credentials file has mode `0600`;
on Windows, restrict access using filesystem ACLs.

Persisted credentials override the environment. If the file is damaged or contains
rejected default credentials, stop the server and move `storage/auth.json` to a
private backup location, configure a unique `APP_PASSWORD`, then restart. Protect
any legacy backup because it may contain a plaintext password. Hash-only files
must not be edited as if `password_hash` were a plaintext password.

### WebUI sessions

Run the WebUI with **one worker** (`uvicorn src.web:app --workers 1`). Sessions
are process-local and are lost on restart. Multiple replicas/workers are not
supported; `WEB_CONCURRENCY` values other than `1` are rejected at startup.
Explicit server CLI worker settings must also remain `1`.

- `SESSION_TTL_SECONDS`: positive integer, default `28800` (8 hours).
  Expiry is absolute from login, not extended by activity. The server checks expiry
  independently of the cookie, including while streaming progress via SSE.
- `SESSION_COOKIE_SECURE`: `true` for HTTPS deployments, including behind a TLS
  reverse proxy; `false` (default) supports local HTTP. Invalid values stop startup.
  Secure cookies are not suitable for ordinary HTTP deployments. Use HTTPS when
  accessing the WebUI over a network; this option does not configure TLS itself.
- A successful password change signs out **all** sessions, including the current
  browser; sign in with the new password. Failed writes leave sessions valid.
  Logout revokes the current token. Expired sessions are removed during login and
  session validation. Running generation jobs continue after logout/session expiry;
  authenticated access to their progress requires a new login.

### Login attempt limits

The WebUI allows **5 attempts per username and client address** and **20 attempts
per client address across all usernames** in a 5-minute fixed window. Successful
attempts count too. Exhausting either limit returns HTTP `429` with `Retry-After`
in seconds, before password hashing. Rejected attempts do not extend the window.
A different address has an independent allowance; this is not a global account
lockout. Use network-level controls for distributed brute-force attacks.

The limiter stores at most 1024 counters per process and does not evict active
limits to admit new identities. If full, attempts requiring new counters receive
`429` until space expires; existing identities still use their remaining allowance.
State is lost on restart. The single-worker requirement also applies here.

The application uses the ASGI client address and does not parse `X-Forwarded-For`
or `Forwarded` itself. For direct Uvicorn access, use `--no-proxy-headers`. Behind
a reverse proxy, use `--proxy-headers --forwarded-allow-ips=<trusted-proxy-IP>` and
prevent clients from bypassing that proxy. Never trust arbitrary forwarded headers
(`--forwarded-allow-ips='*'`) on an exposed listener. Without trusted forwarding,
users behind one proxy/NAT share the source allowance. Configure TLS separately.

### Audio cache v2 (CLI, WebUI and TUI)

CLI, WebUI and TUI share `storage/cache/v2_<sha256>/`. The canonical identity
includes the parsed source text, effective TTS engine/model and voice, SHA-256 of
reference audio bytes (not its path), effective translation languages/model, and
text splitter version/character limit. API keys and output filenames are excluded.
Defaults are resolved before hashing; a manual voice ID and the same preset ID
identify the same effective voice. Changing reference audio at the same path or
changing the configured translation model creates a different cache directory.

**Upgrade:** old unversioned cache directories are preserved but are not reused
or automatically migrated. The first run with v2 may regenerate audio and incur
API charges, even if old chunk files exist. Existing completed audiobook files
are unaffected. Do not rename old cache directories to v2 names: their parameters
cannot be reliably verified. Legacy unversioned data remains outside automatic
retention; remove it manually only when it is no longer needed.

Translation may still run again on resubmission. The manifest checks the actual
resulting segment text before reusing audio, so different translations do not
silently reuse mismatched segments. Explicit WebUI resume retains translated results/checkpoints as described below.
CLI/TUI resubmission uses the same audio manifest but can repeat translation;
it does not create a durable WebUI job or translation checkpoint.

### API keys in the WebUI

Keys entered in the WebUI are sent with the generation request but are no longer
saved in browser storage or restored after reloading the page. Legacy `api_key`
and `openai_key` localStorage entries are removed when the page opens and on
logout. Logout also clears and masks the key fields, even if the logout request
fails. Confirmed unauthenticated status clears them too, including after a
successful password change.

Leave the fields empty to use the server's `MISTRAL_API_KEY` / `OPENAI_API_KEY`.
The key inputs request `autocomplete="off"`; browser/password-manager behavior
is independent of the application. If browser policy blocks storage access, the
UI continues without reading or writing keys; legacy removal can only succeed
when storage access is allowed. No persistent "remember key" option is enabled.

### Verified audio publication

WebUI output names include the task ID, e.g. `<task-id>_audiobook.mp3`. Submitting
two tasks with the same requested filename keeps both results; the progress API
returns the actual published filename used by the player and download link.
Long filename stems are shortened to at most 180 UTF-8 bytes to leave room for
the task ID. Existing audiobook files and their old URLs remain available.

The compiler used by WebUI, CLI and TUI writes into a private `.compile-*`
directory on the destination filesystem. Only after FFmpeg and the existing
duration validation succeed is the staged file atomically moved to its final
path. Failed compilation/validation preserves any previous result. Normal success
and exception paths remove the workspace, including temporary silence and concat
files. Forced termination may leave workspaces for later cleanup.

CLI and TUI retain the explicitly requested output path: a successful run replaces
that file atomically. Two CLI/TUI runs deliberately targeting the same path may
still replace each other's completed result; choose different paths to keep both.
FFmpeg concat lists support spaces, apostrophes and Unicode; paths containing
line breaks are rejected. CLI/WebUI/TUI cache writers are coordinated as described below.

### Concurrent CLI/WebUI/TUI cache access

CLI, WebUI and TUI take an exclusive OS file lock on each v2 cache directory before
reading/updating its manifest, generating segments, or compiling its audio.
Identical jobs wait and then recheck completed segments; different cache keys
have independent locks. The WebUI reports `Waiting for Cache` while waiting.
Lock ownership is released when the process exits/crashes. Do not delete the
persistent `.cache.lock` file while jobs are running: removing it can split locks.

`CACHE_LOCK_TIMEOUT_SECONDS` controls the maximum wait for a lock (default `3600`,
a finite positive number of seconds). A timeout fails the waiting job without
starting chunk generation; it does not cancel the owner. Waiting is asynchronous.
If compilation is cancelled, the lock is retained until its worker thread finishes
reading the segments. FFmpeg/ffprobe deadlines are described below.

Segments are generated into unique `.pending-*` files, validated by the client
and checked for minimum size, then atomically published before the completion
marker is saved. Manifests and translated text use unique temporary files too.
Readers of a published path see the previous complete file or the new complete
file. Exceptions/cancellation clean up unpublished files; forced process death
may leave pending files, which are ignored during resume and covered by the
conservative retention policy below when their containing artifact is eligible.

These locks cover cooperating CLI/WebUI/TUI processes using the same local cache
filesystem. Network filesystems/multi-host shared storage have not been validated.
Use separate BooksmithCLI instances for concurrent invocations. TUI jobs also
use isolated cache sessions and hold their locks through compilation. CLI/TUI
translation files with identical output names still use last-completed-writer-wins publication;
this change prevents temporary-file collisions, not that naming policy.

### Resource limits and generation admission

The WebUI rejects oversized generation requests with HTTP `413` before creating
a task or calling an API. The complete request is bounded before form parsing,
including chunked bodies or understated Content-Length; it is spooled to disk
above 1 MiB. Individual uploads are read in bounded chunks. Uploaded text/ebooks
are parsed in preflight so oversized extracted text/EPUB is rejected before work
is queued. Limits reject content; they never silently truncate an audiobook.

Configure positive integer limits through environment variables (byte budgets
are in bytes, character budgets in Python Unicode characters):

| Variable | Default | Scope |
| --- | --- | --- |
| `MAX_REQUEST_BYTES` | 33554432 (32 MiB) | Complete WebUI generation body, including multipart overhead |
| `MAX_TEXT_UPLOAD_BYTES` | 10485760 (10 MiB) | WebUI text/ebook upload and local input file reads |
| `MAX_VOICE_UPLOAD_BYTES` | 20971520 (20 MiB) | WebUI voice reference upload |
| `MAX_TEXT_CHARS` | 2000000 | Input/extracted text and completed translation |
| `MAX_EPUB_BYTES` | 67108864 (64 MiB) | Sum of ZIP uncompressed sizes and cumulative actual EPUB reads |
| `MAX_EPUB_ENTRY_BYTES` | 8388608 (8 MiB) | One EPUB element, including XML metadata |
| `MAX_EPUB_ENTRIES` | 10000 | EPUB ZIP entry count |
| `MAX_RUNNING_JOBS` | 2 | Running WebUI pipelines, including cache waits and compilation |
| `MAX_QUEUED_JOBS` | 2 | Additional admitted WebUI requests/jobs; zero is allowed |

Restart the WebUI after changing configuration. Invalid limits prevent startup.
The parser also limits multipart uploads to 2 files and forms to 32 fields.
When all running/queued slots are occupied, new generation requests receive
HTTP `429` with `Retry-After: 5`, before reading their body. Admission includes
uploads and preflight, so concurrent preflight work is bounded too. Accepted jobs
may remain `Pending` while waiting for a worker. Capacity is released after work,
exceptions, cancellation or client disconnect during upload. This is a bounded
in-process execution queue; restart requires explicit resume from saved inputs.

The concurrency budget applies to this single WebUI process. Independent CLI/TUI
processes do not share that worker budget, but their input parsing uses the same
file/text/EPUB limits. EPUB metadata and actual decompressed reads are checked;
repeated spine reads also consume the decompression budget. MOBI output size/text
are checked after extraction; the external MOBI library's extraction phase is
not sandboxed or given an unpacking quota by this change. Configure reverse-proxy
request-size and upload-timeout limits as well for network deployments.

### Restart recovery and explicit resume (WebUI)

On startup, unfinished database tasks become `Interrupted`; successful/failed
terminal states are preserved. Progress streams report the interruption and end.
The `finished_at` column is migrated automatically. Retention is a dry-run by default. When deletion is enabled, only completed
tasks expire (24 hours after finish time by default); active, failed and
interrupted tasks and their recovery files are preserved regardless of age. Legacy terminal records without a
known finish time receive the migration time, preserving a full retention window.

New WebUI jobs save private input files and an explicit parameter snapshot in
`storage/tasks/<hash-of-task-id>/` before being queued. The snapshot contains the
original text/ebook, reference audio, effective translation model, TTS model and
segmentation version, **never client API keys**. Original inputs are hash-checked
before resume. Changing global configuration does not change a saved job. Changes
to the supported TTS model/segmentation version make old snapshots incompatible
rather than silently changing their output. Back up the entire storage volume,
not just `state.db`, and protect it because it contains source documents/audio.

After login, the WebUI lists interrupted/failed resumable tasks. Enter API keys
again in the existing key fields (or configure server-side keys), then click
**Resume**. The authenticated endpoints are `GET /api/tasks` and
`POST /api/resume/{task_id}` (form fields `api_key`, `openai_key`). Resume uses the
same job ID and immutable parameters, the normal admission/worker limits and
cache lock. Concurrent resume requests cannot both claim the same job; active or
completed jobs return `409`. Missing/modified/incompatible inputs also return
`409`; missing required keys return `400` without claiming the job.

Completed translation responses/batches are checkpointed per job; the assembled
translation is retained too. Resume reuses those checkpoints and audio segments
marked completed in the matching manifest, and recompiles the output if needed.
There is no automatic execution on restart. Old pre-snapshot jobs can be marked
Interrupted but cannot be resumed without their original inputs; resubmit them.
Completed history and recognized orphaned artifacts follow the state-aware
retention policy described below; failed/interrupted snapshots are retained. API execution is not exactly-once: if the process dies after a
provider responds but before the local checkpoint is committed, that request may
need to be repeated. CLI/TUI keep their existing resubmission behavior.

### FFmpeg/ffprobe budgets and voice preprocessing

All application-owned FFmpeg/ffprobe calls now have finite timeouts. Configure
finite positive values through the environment:

| Variable | Default | Meaning |
| --- | --- | --- |
| `AUDIO_PROBE_TIMEOUT_SECONDS` | 30 | Base seconds for metadata/chunk probes and decoded-duration checks |
| `AUDIO_PROCESS_TIMEOUT_SECONDS` | 120 | Base seconds for compilation, silence and denoising |
| `AUDIO_TIMEOUT_FACTOR` | 0.1 | Additional wall-clock seconds per audio second for duration-aware operations |
| `AUDIO_MAX_TIMEOUT_SECONDS` | 7200 | Maximum budget for one process |

Compilation uses the expected segment/pause duration to extend its budget.
Decoded-duration checks use a separately bounded ffprobe metadata hint; if that
hint is unavailable they use the ordinary process budget. Metadata only sizes
the timeout: final completeness is still checked by full FFmpeg decoding with
the existing 4-second tolerance. Invalid timeout settings prevent WebUI startup.

Timeouts stop and reap the direct child. Async cancellation also stops the child;
async/threaded cancellation allows 2 seconds after terminate, then uses kill.
WebUI, CLI and TUI compilation runs outside the event loop. Cancellation keeps
WebUI/CLI/TUI cache locks and compiler workspaces until the compiler thread has stopped. The TUI remains
responsive while compiling; Mistral chunk probing is asynchronous too.

Voice denoising uses a private temporary file with a valid audio extension and
never overwrites the user's original reference. Its processed bytes are reused
for TTS requests; failure is logged with bounded FFmpeg stderr and falls back to
the original reference. Cancellation propagates after child cleanup. The voice
size limit also applies to local references and processed buffers.

Reference-preprocessing version 2 and the processed-byte fingerprint distinguish
filtered audio from fallback audio in the cache. Preset-voice cache identities
remain unchanged. Previous cloned-voice cache entries are not reused and old
cloned-voice resume snapshots are rejected as incompatible; resubmit those jobs
to generate a consistent audiobook with the corrected preprocessing. This can
incur new API charges. The [portable source smoke](docs/WINDOWS.md) covers
process handling, but native Windows acceptance remains pending; recorded local
results are Linux-only.

### API retries and deadlines

Mistral TTS, translation (including SRT batches), model/voice listing and OpenAI
TTS share one retry policy. Only network/transport errors, request timeouts and
HTTP `408`, `429`, `5xx` are retried. Other `4xx`, invalid responses, filesystem
errors and local FFmpeg/probe failures do not repeat the paid request. Truncated
text responses are not retried unchanged; SRT may fall back once to individual
cues when its batch response cannot be used. Mistral SDK internal retries are
disabled, avoiding nested attempts.

| Variable | Default | Meaning |
| --- | --- | --- |
| `API_REQUEST_TIMEOUT_SECONDS` | 60 | Maximum duration of one request attempt |
| `API_RETRY_BUDGET_SECONDS` | 180 | Total request/retry/backoff budget for one remote operation |
| `API_RETRY_MAX_DELAY_SECONDS` | 60 | Maximum accepted wait between attempts |

Values must be finite and positive; invalid settings prevent WebUI startup and
client construction. A method's `retry_count` means maximum total attempts:
3 by default for TTS/listing and 5 for translation. The budget is per operation,
not for an entire book. Local processing uses the separate audio budgets.

Backoff doubles from 1 second, or 15 seconds for `429` without usable Retry-After,
with bounded positive jitter. Retry-After accepts seconds or an HTTP date and is
respected as a minimum wait. If it exceeds the configured maximum delay, the
request fails rather than retrying early. If a wait cannot fit the remaining
operation budget, retry stops. Cancellation propagates without another attempt.

Retry logs contain status/type/delay, not response bodies or Authorization values;
provider HTTP errors are surfaced as sanitized status errors. Saved translation
checkpoints still bypass completed remote work. Retrying a network timeout can
repeat work already processed by the provider; exactly-once billing is not
guaranteed. All regression tests use fake clients/responses, without paid calls.

### Strict text decoding

Inputs default to UTF-8, with automatic UTF-8/16/32 BOM recognition. For legacy
plain text or SRT, set `INPUT_TEXT_ENCODING=cp1250` explicitly in the container
environment, or convert files to UTF-8. Invalid bytes fail validation instead of
being discarded. EPUB/MOBI HTML uses its BOM or declared charset; broken EPUB
spine/chapter references fail the import. Pasted text and translated results
always use UTF-8. Saved jobs retain their input encoding when resumed.

The corrected pipeline uses segmentation version 2: older resume snapshots are
incompatible and must be resubmitted; old audio cache entries are not reused.
Existing outputs are preserved, but regeneration may incur API charges. See the
README section on input integrity for translation batching and truncation limits.

### Storage retention and disk budgets

Retention runs every 30 minutes and defaults to **dry-run**. It keeps active,
queued, failed and interrupted jobs and their recovery data. To inspect the plan
inside a running container (replace the container name if needed):

```bash
docker exec --user 1000 mistral-tts python3 -m src.core.storage_retention --storage storage
```

Explicit command-line `--apply` recalculates and applies the plan. Alternatively,
set `STORAGE_CLEANUP_ENABLED=true` for periodic deletion. Back up the volume and
archive desired completed audiobooks outside managed storage before enabling
expiry. Completed artifacts/history become eligible after
`STORAGE_RETENTION_SECONDS=86400`; recognized orphans and unpinned caches after
`STORAGE_ORPHAN_GRACE_SECONDS=604800`. Failed/interrupted recovery data is retained
indefinitely. Unknown files and symlinks are skipped; unresolved cache references
conservatively keep all audio caches. Busy cache/compiler leases are skipped too.

`STORAGE_MAX_BYTES=0` disables the optional logical-byte threshold.
`STORAGE_MIN_FREE_BYTES=268435456` reserves 256 MiB by default on the storage
filesystem. Full storage rejects generate/resume with HTTP `507` and is rechecked
before expensive pipeline steps; it never forces deletion of recovery data.
These checks permit in-flight/concurrent overshoot. Configure a volume/filesystem
quota for a strict bound, and keep space for compilation and Docker's own logs.

The maintenance command is read-only unless `--apply` is supplied, even when
periodic deletion is enabled. It requires the existing migrated database inside
the selected root. See README for managed filenames, lock preservation, shared
CLI/TUI limitations, legacy artifacts and the full policy.

### Shared TUI/CLI/WebUI audio cache

All three interfaces now use `storage/cache/v2_<sha256>/` with one shared manifest,
chunk-file validator and OS lock held through compilation. TUI resubmission reuses
matching completed segments, and concurrent books/voices use separate cache keys.
Compatible CLI/WebUI v2 cache entries remain usable without a format migration.

Old flat TUI `chunk_*.mp3` files are retained but not trusted or reused, so the
first migrated TUI run may require paid regeneration. TUI still requires manual
resubmission with the same input/settings and may repeat translation; durable job
and translation checkpoints remain a WebUI feature. See README for the contract.

### Shared pipeline service

CLI, WebUI and TUI now delegate text preparation, voice configuration, cached
segment generation and compilation to `src/core/pipeline.py`. Interface adapters
retain progress presentation, upload handling, task persistence and translation
checkpoints. No new container settings, dependencies, cache-key version or task
snapshot migration are required by this extraction. Existing retry, disk budgets,
OS locks and cancellation cleanup remain in effect; see README for the service
and TTS-client contracts.

### Locked Python dependencies

The image installs the runtime-only `requirements.txt` with exact versions,
artifact hash verification and wheel-only installation, followed by `pip check`.
Pytest, Ruff and the uv lock compiler belong to the separate development lock.
HTTPX is a direct runtime requirement; FFmpeg remains an OS executable rather
than a Python wrapper dependency. The Mistral SDK stays at `2.4.9`.

See [Dependency management](docs/DEPENDENCIES.md) for installation and the paired
runtime/dev lock update procedure. The Python package locks do not pin the base
image digest or apt packages. Native Windows acceptance is still pending; the Linux Docker smoke suite
below is implemented. Dependency validation does not publish an image or expose
a server port.

### Runtime smoke checks and startup diagnostics

Run `python scripts/docker_smoke.py` from a checkout with Python and a Linux Docker
daemon. The same suite is included in Gitea CI. It builds a temporary runtime image
and checks nonroot startup, bind-mounted storage, real HTTP sessions/uploads,
FFmpeg output and persistence after restart. TTS responses are replaced with local
synthetic audio; application containers have no external network or published ports.
The test image is not pushed. See [Tests and CI](docs/TESTING.md) for fixture handling.

The entrypoint prepares only `/app/storage`, keeps ordinary file modes intact,
restricts `auth.json` to `0600` and then tests actual writes as the application
user. Existing `state.db` must also be writable. Inaccessible or read-only storage
stops startup with `Storage initialization failed` and an ownership/permissions/
read-only-mount hint. Root startup still drops to UID 1000; explicit nonroot startup
requires storage that the selected user can prepare and write.

Root and nested `.env`/`.env.*` files are excluded from the build context. Smoke
tests check synthetic canaries across every saved image layer, not only the final
filesystem. The production image contains application source without test helpers.
