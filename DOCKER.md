# Mistral-TTS Docker Image Overview

This repository contains the containerized version of **Mistral-TTS**, a text-to-speech pipeline designed to convert long-form text (articles, books, essays) into seamless audiobooks. It integrates the **Mistral AI Voxtral TTS** API (with zero-shot voice cloning), **OpenAI TTS** as an alternative engine, configurable **Mistral chat models** (default: `ministral-8b-latest`) for pre-translation, and support for EPUB, MOBI, SRT, and TXT ingestion.

The Docker image bundles Python 3.11, all application dependencies, and **FFmpeg** for high-quality audio compounding.

---

## 🛠️ How to Run the Container

The container supports running the WebUI, the interactive Terminal UI (TUI), or standard CLI commands.

### 1. Run the WebUI (Default)
To start the responsive, glassmorphism WebUI, expose port `8000` and mount a local folder to `/app/storage` to persist generated audiobooks, manifests, and cache state.

```bash
docker run -d \
  -p 8000:8000 \
  -v $(pwd)/storage:/app/storage \
  -e MISTRAL_API_KEY=your_mistral_api_key_here \
  -e OPENAI_API_KEY=your_openai_api_key_here \
  -e MISTRAL_TRANSLATION_MODEL=ministral-8b-latest \
  -e APP_USERNAME=admin \
  -e APP_PASSWORD=admin_secure_password \
  --name mistral-tts \
  marcinlis82/mistral-tts:1.0.2
```

Once running, access the WebUI at **`http://localhost:8000`**.
*Note: Set a unique `APP_PASSWORD` before first start. Empty credentials and the password `admin` prevent WebUI startup, even on localhost. `APP_USERNAME` defaults to `admin`. If mounted storage contains `auth.json`, its credentials take precedence: update that file locally if it contains rejected credentials, then restart.*

### 2. Run the Interactive TUI
To run the terminal configuration and progress tracking interface inside the container, run with interactive terminal flags (`-it`):

```bash
docker run -it --rm \
  -v $(pwd)/storage:/app/storage \
  -e MISTRAL_API_KEY=your_mistral_api_key_here \
  -e OPENAI_API_KEY=your_openai_api_key_here \
  marcinlis82/mistral-tts:1.0.2 \
  python src/cli.py --tui
```

### 3. Run via Headless CLI
For automated script integrations, execute the CLI directly:

```bash
docker run --rm \
  -v $(pwd)/storage:/app/storage \
  -e MISTRAL_API_KEY=your_mistral_api_key_here \
  marcinlis82/mistral-tts:1.0.2 \
  python src/cli.py \
  --text /app/storage/book.txt \
  --voice /app/storage/sample.mp3 \
  --output /app/storage/audiobook.mp3
```

---

## ⚙️ Environment Variables

The container configuration is managed using the following environment variables:

| Variable | Description |
| --- | --- |
| `MISTRAL_API_KEY` | Your Mistral AI API Key (required for Voxtral TTS and Translation). |
| `OPENAI_API_KEY` | Your OpenAI API Key (required if selecting the OpenAI TTS engine). |
| `MISTRAL_TRANSLATION_MODEL` | Mistral chat model for text translation (default: `ministral-8b-latest`). |
| `APP_USERNAME` | Custom username for WebUI cookie authentication (default: `admin`). |
| `APP_PASSWORD` | Required unique password for WebUI cookie authentication; empty values and `admin` are rejected at startup. |

---

## 🌟 Key Features

* **Dual Engine Support:** Switch seamlessly between Mistral Voxtral (with instant cloning) and OpenAI TTS (presets: alloy, echo, fable, onyx, nova, shimmer) for global language support.
* **Integrated Translation:** Automatic language-to-language translation using configurable Mistral chat models (default: `ministral-8b-latest`) prior to speech synthesis.
* **Format Ingestion:** Parsers for `.txt`, `.srt` (retains timecodes), `.epub`, and unencrypted `.mobi` ebooks.
* **Persistent SQLite States:** Task state, progress, and logs are tracked in a SQLite database (`storage/state.db`) to survive container restarts.
* **Automated Cleanup:** Built-in purger evicts completed and failed task histories older than 24 hours.

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

### Audio cache v2 (CLI and WebUI)

CLI and WebUI now share `storage/cache/v2_<sha256>/`. The canonical identity
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
cannot be reliably verified. Remove obsolete data manually only when it is no
longer needed; this update does not perform cleanup.

Translation may still run again on resubmission. The manifest checks the actual
resulting segment text before reusing audio, so different translations do not
silently reuse mismatched segments. Persisting translated results remains separate follow-up work. This shared cache change does
not add manifest resume to the TUI.

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
line breaks are rejected. CLI/WebUI cache writers are coordinated as described below.

### Concurrent CLI/WebUI cache access

CLI and WebUI take an exclusive OS file lock on each v2 cache directory before
reading/updating its manifest, generating segments, or compiling its audio.
Identical jobs wait and then recheck completed segments; different cache keys
have independent locks. The WebUI reports `Waiting for Cache` while waiting.
Lock ownership is released when the process exits/crashes. Do not delete the
persistent `.cache.lock` file while jobs are running: removing it can split locks.

`CACHE_LOCK_TIMEOUT_SECONDS` controls the maximum wait for a lock (default `3600`,
a finite positive number of seconds). A timeout fails the waiting job without
starting chunk generation; it does not cancel the owner. Waiting is asynchronous.
If compilation is cancelled, the lock is retained until its worker thread finishes
reading the segments. Process/FFmpeg execution deadlines are separate work.

Segments are generated into unique `.pending-*` files, validated by the client
and checked for minimum size, then atomically published before the completion
marker is saved. Manifests and translated text use unique temporary files too.
Readers of a published path see the previous complete file or the new complete
file. Exceptions/cancellation clean up unpublished files; forced process death
may leave pending files, which are ignored during resume (retention is separate).

These locks cover cooperating CLI/WebUI processes using the same local cache
filesystem. Network filesystems/multi-host shared storage have not been validated.
Use separate BooksmithCLI instances for concurrent invocations. The TUI still
uses its older cache layout; its migration is planned separately. Translation
files with identical output names still use last-completed-writer-wins publication;
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
in-process queue, not durable restart/resume storage.

The concurrency budget applies to this single WebUI process. Independent CLI/TUI
processes do not share that worker budget, but their input parsing uses the same
file/text/EPUB limits. EPUB metadata and actual decompressed reads are checked;
repeated spine reads also consume the decompression budget. MOBI output size/text
are checked after extraction; the external MOBI library's extraction phase is
not sandboxed or given an unpacking quota by this change. Configure reverse-proxy
request-size and upload-timeout limits as well for network deployments.
