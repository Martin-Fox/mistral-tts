# Mistral-TTS

> [!NOTE]
> **Repository Setup & Contributions:** The primary development repository and source of truth for this project is hosted on my [Gitea Instance](https://gitea.marcin-lis.pl/fox/mistral-tts). A public mirror is available on [GitHub](https://github.com/Martin-Fox/mistral-tts), which you are warmly invited to use for submitting issues, creating pull requests, or leaving comments and feedback.

An automated, open-source text-to-speech pipeline designed to transform long-form text (articles, books, essays) into seamless audiobooks using the Mistral AI Voxtral TTS API with reference-audio voice cloning and OpenAI TTS preset voices.

For deployment, restart recovery, backups and upgrades, see
[Operations](docs/OPERATIONS.md). Verification instructions are in
[Tests and CI](docs/TESTING.md), [Windows acceptance](docs/WINDOWS.md) and
[Dependency management](docs/DEPENDENCIES.md).

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
See the [audit and remediation record](docs/audit/SECURITY_AUDIT_2026-11-18.md),
[dependency update report](docs/audit/SECURITY_DEPENDENCY_UPDATES_2026-11-18.md),
[native dependency limits](docs/NATIVE_DEPENDENCIES.md) and
[deployment guidance](docs/SECURITY_DEPLOYMENT.md).

## 🚀 Features

- **Interactive WebUI:** A premium, responsive single-page web application featuring glassmorphism card layouts, real-time progress bar animations, drag-and-drop file uploaders, an in-browser console terminal streaming live server logs via Server-Sent Events (SSE), and a custom audio player for instant playback.
- **Interactive TUI:** A modern terminal interface for easy configuration and progress monitoring.
- **Windows Desktop Packaging:** PyInstaller specification and CI workflow for a portable executable with web assets and FFmpeg/ffprobe; native source/artifact acceptance remains pending.
- **Integrated Translation:** Translate source files from a source language to a target language using configurable Mistral chat models (default: `ministral-8b-latest`, with support for `ministral-3b-latest`, `mistral-small-latest`, `mistral-medium-latest`, and `mistral-large-latest`) before the TTS phase. Supports rate-limit-aware retries and preserves subtitle timecodes.
- **Multi-Format Ingestion:** Direct support for plain text (`.txt`), subtitles (`.srt`) and EPUB. Unencrypted MOBI remains available for trusted local CLI/TUI files; WebUI uploads and resume of MOBI jobs are disabled until extraction is isolated.
- **Audio Truncation Safeguard & Duration Verification:** Adds trailing silence (1.0s default), verifies full decoded duration with FFmpeg and rejects output more than 4.0s shorter than the expected total. This detects duration loss; it does not prove linguistic completeness or detect every short omission.


- **Reference-Audio Voice Cloning:** Sends a preprocessed reference sample to Mistral TTS; quality and accepted input depend on the provider.
- **Preset Voice Selection:** Choose from high-quality default Mistral voices (e.g., Paul, Sarah) without needing a sample.
- **Intelligent Text Segmentation:** Tokenizes long texts based on punctuation and character constraints to preserve semantic flow.
- **Asynchronous Generation:** Generates chunks sequentially within each job, with bounded retries. WebUI admits a configured number of independent jobs concurrently.
- **Progress Persistence:** WebUI saves task inputs and checkpoints for explicit resume after restart. CLI/TUI resubmission reuses matching audio cache; translation may run again.
- **Environment Support:** Load keys from process environment or a private plaintext dotenv file; restrict file access.

## 🛠️ Installation


### Prerequisites

- **CPython 3.11:** the version exercised by CI and the current dependency locks. Other Python versions require separate verification.
- **FFmpeg and ffprobe:** Both executables must be available in PATH.

### Setup

1. Clone the repository:
   ```bash
   git clone https://gitea.marcin-lis.pl/fox/mistral-tts.git
   cd mistral-tts
   ```

2. Install dependencies:
   ```bash
   python -m pip install --require-hashes --only-binary=:all: -r requirements.txt
   ```

   Use an isolated Python environment. This installs runtime dependencies only;
   development tools and the lock update procedure are described in
   [Dependency management](docs/DEPENDENCIES.md).

3. Configure the selected provider and WebUI credentials:
   Create a private `.env` file in the root directory (or supply process environment variables). WebUI requires a unique password before startup; CLI/TUI require the keys for the selected operations:
   ```bash
   MISTRAL_API_KEY=your_mistral_api_key_here
   OPENAI_API_KEY=your_openai_api_key_here

   # Translation model (defaults to ministral-8b-latest if omitted)
   MISTRAL_TRANSLATION_MODEL=ministral-8b-latest

   # WebUI login credentials (required before first start)
   APP_USERNAME=admin
   APP_PASSWORD=replace-with-a-unique-password
   ```

## 📖 Usage

### Windows desktop packaging

The launcher, `mistral-tts.spec` and `.gitea/workflows/build-windows.yml` are
implemented. The intended artifact is `mistral-tts-windows-x64.zip`; a successful
native build and clean-Windows artifact smoke are still required before treating
it as a verified portable release. See [Windows acceptance](docs/WINDOWS.md).

For a built artifact, extract into a writable directory and configure a private
`.env` beside the executable with a unique `APP_PASSWORD` before launching
`mistral-tts.exe` or `run.bat`. The default password is refused before WebUI
startup. Configure provider keys in that file or, after login, in WebUI. The
launcher selects a local port and opens the browser. Storage is kept beside the
executable; assets/binaries are read from their bundled locations.

### Running the WebUI (Python)

To launch the WebUI:

```bash
python3 -m uvicorn src.web:app --host 127.0.0.1 --port 8000 --workers 1 --no-proxy-headers
```

Run from the checkout, then open `http://localhost:8000`. Keep one worker;
`--reload` is a development option and interrupts jobs on code changes.
For remote access, configure HTTPS and trusted proxy forwarding as described in
[Operations](docs/OPERATIONS.md#network-access-and-tls).

* **Required credentials:** Before starting the WebUI, set `APP_PASSWORD` to a unique phrase of 12-1024 characters in your environment or `.env`; `APP_USERNAME` defaults to `admin`. Without an existing auth file, shorter credentials prevent startup, including on localhost. Persisted credentials take precedence; legacy short passwords permit a change-only login. Empty/default `admin` credentials remain rejected. See [credential recovery](docs/OPERATIONS.md#credential-recovery). Errors never print the configured password.


### Interactive TUI (Recommended)

The easiest way to use the tool is via the built-in Terminal UI:

```bash
python3 -m src.cli --tui
```

### Standard CLI

For automated workflows, you can use the traditional CLI:

```bash
python3 -m src.cli --text "book.txt" \
                   --voice "sample.mp3" \
                   --output "audiobook.mp3"
```

*Configure `MISTRAL_API_KEY` in your environment or private dotenv file.
Command-line key flags are supported but can appear in shell history and process listings.*

CLI exit codes: `0` after a successful run (or `--help`), `1` for an execution
error such as a missing input file, failed generation or failed compilation,
and `2` for invalid or missing arguments. Automation should check the exit code
before treating the output as a completed audiobook.

### OpenAI TTS Integration

To use the OpenAI TTS integration:

1. **API Configuration:** Configure `OPENAI_API_KEY` in your `.env` file, or supply it as a parameter in the interfaces.
2. **Preset Voices:** This integration exposes six OpenAI preset voices: `alloy`, `echo`, `fable`, `onyx`, `nova`, and `shimmer`. Reference-audio cloning is not implemented for this engine.
3. **WebUI Usage:** Select **OpenAI TTS** as the *TTS Engine*. The WebUI dynamically hides the voice cloning section and switches preset options to the OpenAI voices.
4. **TUI Usage:** Set the *TTS Engine* dropdown to **OpenAI**. The dropdown for *Default Voice* will populate with OpenAI voices, and inputs for cloning and manual voice IDs will be disabled.
5. **CLI Usage:** Include the `--engine openai` parameter and specify one of the 6 preset voices in the `--voice` argument:
   ```bash
   python3 -m src.cli --text book.txt \
                      --engine openai \
                      --voice alloy \
                      --output audiobook.mp3
   ```
   *Note: Passing a file path to `--voice` when running with `--engine openai` will trigger a validation error.*

### Translation Model Configuration

When `--target-lang` is specified, the pipeline translates the input text via the Mistral Chat API prior to audio synthesis. The configured default is `ministral-8b-latest`; model availability, pricing and account permissions must be checked with the provider. This default does not guarantee access or prevent HTTP 403 errors.

See [Configured provider models](#configured-provider-models) for the models this code selects.

#### Supported Models

| Configured model ID | Display name |
| --- | --- |
| `ministral-8b-latest` | Ministral 8B (default) |
| `ministral-3b-latest` | Ministral 3B |
| `mistral-small-latest` | Mistral Small |
| `mistral-medium-latest` | Mistral Medium |
| `mistral-large-latest` | Mistral Large |

These are interface choices, not an account-access or translation-quality guarantee.

#### Changing the Model

- **WebUI:** Expand **Translation Settings** and select the desired model from the **Translation Model** dropdown. The selection is automatically sent to `POST /api/config` and saved to the selected dotenv file without requiring a backend restart. See [configuration precedence](docs/OPERATIONS.md#supported-operating-model-and-configuration).
- **TUI:** Choose your preferred model in the **Trans Model** dropdown selector. Selection is saved to the selected dotenv file and takes effect for subsequent generation runs in that process.
- **CLI / Headless:** Set the `MISTRAL_TRANSLATION_MODEL` environment variable in your `.env` file or export it in your shell:
  ```bash
  export MISTRAL_TRANSLATION_MODEL=mistral-small-latest
  ```

### Parameters

| Flag | Description |
| --- | --- |
| `--tui` | Launches the interactive Terminal User Interface. |
| `--text` | Path to the source file (`.txt`, `.srt`, `.epub`, or `.mobi`). |
| `--source-lang` | (Optional) Source language of the input file (e.g., `Polish`). Defaults to `English`. |
| `--target-lang` | (Optional) Target language to translate the text into before generating speech (e.g., `English`). |
| `--voice` | Path to a short `.mp3` or `.wav` sample for cloning (for Mistral) or a preset voice ID (e.g. `alloy` for OpenAI). |
| `--output` | The destination path for the final `.mp3` file. |
| `--api-key` | Your Mistral AI API key (overrides `.env`). |
| `--engine` | TTS engine to use: `mistral` (default) or `openai`. |
| `--openai-key` | Your OpenAI API key (overrides `OPENAI_API_KEY` in `.env`). |

*Note: The translation model can be specified via the `MISTRAL_TRANSLATION_MODEL` variable in `.env` or in the environment (defaults to `ministral-8b-latest`).*

### Running Tests

Install the development lock and make FFmpeg/ffprobe available, then run from
the repository root. The test harness isolates collection and individual tests
from user storage/configuration, clears provider keys and blocks external Python connections and DNS
lookups. Literal loopback and Unix sockets remain available for local IPC. API calls use fakes; no real keys are required.

```bash
python -m pip install --require-hashes --only-binary=:all: -r requirements-dev.txt
python -m pip check
python -m ruff check src tests scripts
python -m pytest -q --durations=10 --junitxml=test-results.xml
```

Tests have a 30-second per-test limit. The complete suite is also defined in
`.gitea/workflows/ci.yml`; see [Tests and CI](docs/TESTING.md) for fixtures,
subprocess protection, diagnostics and runner requirements.

With a Linux Docker daemon available, run `python scripts/docker_smoke.py` for
the seven runtime-container checks: nonroot startup, bind mounts, HTTP/auth/upload,
real local audio compilation, persistence, permission failures and image-layer
configuration exclusion. These tests use disposable fixtures and never push an image.

## Configured provider models

| Operation | Model selected by the application | Credentials |
| --- | --- | --- |
| Mistral TTS | `voxtral-mini-tts-2603` | `MISTRAL_API_KEY` |
| OpenAI TTS | `tts-1` | `OPENAI_API_KEY` |
| Translation with either TTS engine | `MISTRAL_TRANSLATION_MODEL`, default `ministral-8b-latest` | `MISTRAL_API_KEY` |

CLI/WebUI/TUI do not expose a TTS-model selector. The OpenAI adapter provides
preset voices and rejects reference audio; the Mistral adapter supports presets
and reference preprocessing. Translation remains a Mistral operation even when
OpenAI produces the audio. Provider model access, quotas, languages, pricing and
output quality are not established by offline tests. Check them for your account
before submitting a book. Authentication/permission failures are not retried;
see the API retry policy below.

## 🏗️ Architecture

- **`src/tui.py`**: The interactive Terminal UI built with Textual.
- **`src/web.py`**: FastAPI web server hosting API endpoints and background synthesis tasks.
- **`src/web/static/`**: Contains HTML, CSS, and JS assets for the Single-Page Web application.
- **`src/core/config.py`**: Environment management and persistent `.env` synchronization for runtime configuration.
- **`src/core/pipeline.py`**: Shared ordered text preparation, cache-backed generation and verified compilation.
- **`src/core/audio_cache.py` / `cache_io.py`**: Matching segment manifests, cross-process locks and atomic publication.
- **`src/core/task_db.py` / `task_store.py`**: WebUI state, private resume inputs and translation checkpoints.
- **`src/core/storage_retention.py`**: State-aware maintenance and soft disk-budget checks.
- **`src/core/text_splitter.py`**: Handles semantic chunking logic.
- **`src/api/mistral_client.py`**: Wrapper for Voxtral API interaction, voice cloning, and text translation.
- **`src/core/audio_compiler.py`**: FFmpeg-based stitching, pause/trailing silence injection, loudness normalization (`loudnorm`), and duration verification.
- **`src/cli.py`**: Primary command-line interface entry point.


## ⚙️ State Persistence

| Interface | Recovery after interruption | Translation and output behavior |
| --- | --- | --- |
| WebUI | Restart, sign in again, then explicitly Resume a compatible failed/interrupted saved job | Reuses translation checkpoints and validated matching audio; keeps the same task ID and task-prefixed output name |
| CLI | Rerun with the same source, voice and settings | Matching audio cache is reused; translation may repeat; successful compilation atomically replaces the requested output path |
| TUI | Reselect the same input/settings and start again | Same cache rules as CLI; no durable WebUI job snapshot or translation checkpoints |

Restart never automatically submits provider work. Missing or incompatible saved
inputs require resubmission, potentially with new API charges. See
[Restart recovery](#restart-recovery-and-explicit-resume-webui) and the
[operational recovery steps](docs/OPERATIONS.md#restart-and-resume).

## 🐳 Docker Setup

Use the versioned image for this security update:

```bash
docker pull marcinlis82/mistral-tts:1.0.4
mkdir -p storage
docker run -d \
  -p 127.0.0.1:8000:8000 \
  -v "$PWD/storage:/app/storage" \
  --env-file "$PWD/.env" \
  --name mistral-tts \
  marcinlis82/mistral-tts:1.0.4
```

The private `.env` must configure a unique WebUI password. Docker `--env-file`
passes values into the container; it does not mount that file. Bind-mounted
storage survives container replacement. For TUI/CLI commands, nonroot ownership,
TLS, persistent model configuration and maintenance, see [DOCKER.md](DOCKER.md).
Use [Operations](docs/OPERATIONS.md) before replacing an existing installation.

## 🗺️ Future Roadmap

- [x] **Integrated Translation:** Direct translation from Language A to Language B using configurable Mistral chat models (default: `ministral-8b-latest`, with support for Small, Medium, Large) before the TTS phase.
- [x] **Interactive WebUI:** A responsive web application to configure runs, preview voices, and monitor generation.
- [x] **Docker Containerization:** Containerize the application, bundling FFmpeg and Python dependencies for zero-setup deployments.
- [x] **Session Authentication:** One shared account with expiring session cookies. Multiple user accounts are not implemented; remote deployment requires HTTPS.
- [ ] **OpenID Connect (OIDC) Login:** Integrate authentication based on OpenID Connect (OIDC) provided by a self-hosted Pocket ID instance for single sign-on.
- [ ] **Multi-User Login:** Support multiple user accounts and sessions, paving the way for personalized histories, settings, and task queues.
- [ ] **CLI User Management:** Add command-line interface options to create, update, and manage user accounts securely, keeping user-creation tools out of the WebUI.
- [ ] **WebUI About Modal & Current Version Display:** Add a menu item / modal for "About" that displays application metadata, current version (e.g. 1.0.2), license, and project links.
- [ ] **WebUI Help / Quick Guide:** Interactive help or documentation drawer/modal explaining parameters (chunking, temperature, voices, engines, loudnorm) and troubleshooting tips.
- [x] **Robust Task State Management:** SQLite task state, explicit restart recovery and conservative storage retention protect active/resumable jobs.
- [x] **EPUB Support:** Ingest and parse EPUB files to extract chapters while preserving document structure.
- [x] **MOBI Support:** Ingest and parse MOBI files to extract chapters for synthesis.
- [x] **OpenAI TTS Integration:** Support the OpenAI TTS API as an alternative synthesis engine using preset voices.
- [x] **Audio Truncation Safeguard & Duration Verification:** Enforce end-to-end duration verification and trailing silence padding.
- [x] **Standalone Windows Packaging:** PyInstaller specification and build workflow exist; native artifact acceptance remains pending.



## ⚖️ License

MIT License - see [LICENSE](LICENSE) for details.


### WebUI password storage and migration

The WebUI stores salted PBKDF2-HMAC-SHA256 password hashes (600,000 iterations),
not plaintext passwords, in `storage/auth.json`. Existing plaintext files are
migrated atomically during startup; migration failure stops startup and preserves
the original file. Environment credentials are hashed in memory and do not create
an auth file until the password is changed through the WebUI. Unicode passwords
and usernames are supported. On POSIX, the credentials file has mode `0600`;
on Windows, restrict access using filesystem ACLs.

New environment credentials (when no auth file exists) and password changes
require 12-1024 characters, with at least 12 after trimming surrounding whitespace.
The actual password is preserved, including Unicode and whitespace; there is no
mandatory mix of character types. Choose a unique phrase. Existing persisted
short passwords are not rejected solely for their length at startup: after a
correct login, the server returns `requires_password_change: true` and permits
only auth status, password change and logout. The UI opens the change form;
generation, data/config reads and resume return `403`, including before upload.
Changing the password signs out all clients, then the new login has full access.
Failed persistence leaves the restricted session available for retry. Lost
passwords and credentials beyond input length bounds need operator recovery.

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

### Request origin and browser security

Every state-changing HTTP request, including login/logout, must have an `Origin`
matching the request scheme, host and port. Default ports normalize and subdomains
are not implicitly trusted. `null`, foreign or duplicated origins are rejected
with `403` **before** reading the body or reserving generation capacity. The
application does not trust raw forwarded headers; HTTPS proxies must configure
Uvicorn's trusted proxy handling as described in Operations.

Clients that omit Origin must send `X-Requested-With: Booksmith`. The WebUI adds
it automatically. For example, a non-browser client can log in with that header
and retain its session cookie. CLI/TUI do not use these HTTP routes. A bad Origin
cannot be overridden by the custom header, and originless requests marked
`Sec-Fetch-Site: cross-site` or `same-site` are rejected. Do not enable broad CORS
without reviewing this contract. Custom clients using old headerless POSTs need
to be updated; no CSRF-disable switch is provided.

Responses have `nosniff`, frame protection, no-referrer policy and a CSP allowing
scripts/connects only from the same origin. Styles retain inline CSS and the
existing Google Fonts sources for UI compatibility. Root/API responses use
`Cache-Control: no-store`. TLS/HSTS remain a reverse-proxy responsibility.
Interactive `/docs` and `/redoc` are disabled because their default CDN/inline
scripts conflict with the CSP; `/openapi.json` remains available.

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
| `MAX_JSON_REQUEST_BYTES` | 65536 (64 KiB) | All other HTTP request bodies, including login, password changes and configuration (also forms) |
| `REQUEST_BODY_TIMEOUT_SECONDS` | 120 | Total time to receive a complete request body |
| `REQUEST_BODY_IDLE_TIMEOUT_SECONDS` | 15 | Maximum wait for the next request-body chunk |
| `MAX_TEXT_UPLOAD_BYTES` | 10485760 (10 MiB) | WebUI text/ebook upload and local input file reads |
| `MAX_VOICE_UPLOAD_BYTES` | 20971520 (20 MiB) | WebUI voice reference upload |
| `MAX_VOICE_SECONDS` | 30 | Maximum accepted duration of a voice reference |
| `MAX_VOICE_PROCESS_MEMORY_BYTES` | 536870912 (512 MiB) | Linux reference-decoder address-space limit, including shared libraries |
| `MAX_TEXT_CHARS` | 2000000 | Input/extracted text and completed translation |
| `MAX_EPUB_BYTES` | 67108864 (64 MiB) | Sum of ZIP uncompressed sizes and cumulative actual EPUB reads |
| `MAX_EPUB_ENTRY_BYTES` | 8388608 (8 MiB) | One EPUB element, including XML metadata |
| `MAX_EPUB_ENTRIES` | 10000 | EPUB ZIP entry count |
| `MAX_EPUB_XML_DEPTH` | 64 | Maximum nesting depth in container/OPF XML metadata |
| `MAX_EPUB_XML_ELEMENTS` | 10000 | Maximum elements in each metadata XML document |
| `MAX_RUNNING_JOBS` | 2 | Running WebUI pipelines, including cache waits and compilation |
| `MAX_QUEUED_JOBS` | 2 | Additional admitted WebUI requests/jobs; zero is allowed |

Restart the WebUI after changing configuration. Invalid limits prevent startup.
The parser also limits multipart uploads to 2 files and forms to 32 fields.
Generation/resume requests require a valid session **before** reading the body,
checking storage or reserving capacity. Anonymous requests receive `401` even
when the queue is full. Sessions are checked again after upload, so expiry or
logout during upload prevents submission. Other request bodies use the smaller
`MAX_JSON_REQUEST_BYTES` budget before JSON/form parsing. Login usernames are
limited to 256 characters, passwords to 1024, and translation model IDs to 100.
The password length bound applies to both login and password changes; existing
usernames/passwords beyond these bounds require operator-assisted replacement.

Slow bodies receive `408` when the total or idle timeout expires. Upload spools
are closed and reserved slots released. These deadlines apply only to body
reception, not queued/running generation or SSE streams. When all running/queued
slots are occupied, new authenticated generation requests receive
HTTP `429` with `Retry-After: 5`, before reading their body. Admission includes
uploads and preflight, so concurrent preflight work is bounded too. Accepted jobs
may remain `Pending` while waiting for a worker. Capacity is released after work,
exceptions, cancellation or client disconnect during upload. This is a bounded
in-process execution queue; restart requires explicit resume from saved inputs.

The concurrency budget applies to this single WebUI process. Independent CLI/TUI
processes do not share that worker budget, but their input parsing uses the same
file/text/EPUB limits. EPUB metadata and actual decompressed reads are checked;
repeated spine reads also consume the decompression budget. WebUI rejects MOBI
uploads and resumes with `415` before extraction or paid work; convert them to
EPUB/TXT. CLI/TUI still accept trusted local MOBI files. That extractor runs in
the application process without hard unpacking quotas and must not be used for
untrusted files. Configure reverse-proxy
request-size and upload-timeout limits as well for network deployments.

EPUB container/OPF XML rejects all DTD declarations before entity processing,
using parser callbacks rather than a byte-pattern scan (including UTF-16).
Metadata trees have the depth/element limits above. Standard HTML/XHTML chapter
doctypes are still handled by HTMLParser without fetching DTDs or expanding
custom XML entities. These application guards do not patch the native Expat
library; keep the runtime's XML libraries updated as part of release maintenance.

See [deployment security](docs/SECURITY_DEPLOYMENT.md) for LAN binding, HTTP/HTTPS
cookie settings, trusted proxies and recording the exact deployed image.

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

Voice references must have matching `.mp3`/`.wav` contents. The decoder is forced
to MP3 or WAV with an explicit MP3/PCM codec allowlist and `file` protocol only;
playlists, ADX/CAF and compressed WAV codecs are rejected. References normalize
to mono 24 kHz s16 PCM WAV with denoising. Original files are preserved. A decode,
duration or quota failure rejects the reference; no original-file fallback is
sent to the provider. WebUI validates references before creating a task or paid
translation/TTS work, then reprocesses the private original when generation runs.

Reference decoding uses a private temporary working directory and an environment
without application keys/proxy settings. Async process stdout/stderr capture is
limited to 64 KiB each; overflow kills and reaps the process. FFmpeg has a 16 MiB
single-allocation guard, one codec/filter thread, a byte limit and a duration
guard that rejects overlong audio rather than accepting truncation. Linux uses
`prlimit` for a 512 MiB address-space limit, a CPU budget and a hard file-size
limit; install util-linux for local Linux cloning. Absence of `prlimit` fails
closed. Other platforms have the format/allocation/output/time guards, but the
configured total-memory limit is Linux-only. Native Windows acceptance remains
required. These measures do not isolate the filesystem or contain arbitrary
decoder code execution; keep untrusted processing in a restricted service/container.

Reference-preprocessing version **3** and the processed-byte fingerprint identify
the normalized reference. Preset-voice cache identities remain unchanged. Older
cloned-voice cache entries are retained but not reused, and older cloned-voice
resume snapshots are rejected as incompatible; resubmit those jobs deliberately.
This may incur API charges. No existing output is deleted or regenerated on
startup. Cancellation propagates after child and temporary-directory cleanup.

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

### Input text integrity and translation limits

Plain text and SRT use strict UTF-8 by default. UTF-8, UTF-16 and UTF-32 BOMs
are recognized automatically. For a legacy plain-text file, explicitly set
`INPUT_TEXT_ENCODING=cp1250` (or another Python codec name), or convert it to
UTF-8 before uploading. There is no guessing or silent removal of invalid bytes;
a decode error stops the job. UTF-16 without a BOM needs an explicit byte order,
for example `INPUT_TEXT_ENCODING=utf-16-le`. Uploaded file validation reports an
invalid document before creating a task or calling the provider.

EPUB XML respects its declared encoding; chapter HTML and extracted MOBI HTML
respect BOMs and XML/HTML charset declarations, defaulting to UTF-8. Missing
manifest references, spine IDs or chapter files fail the EPUB import, including
when earlier chapters were readable. A partial book is not accepted as complete.

Resume snapshots freeze the input encoding. Pasted WebUI text and translated
output are always UTF-8, independent of the legacy input encoding setting.
Translations split source text into at most 2500-character fragments, including
long words and subtitle cues. SRT JSON batches also limit the serialized source
payload to 2500 characters and 25 cues while preserving cue indices and timing.
Prompt instructions add overhead; these character limits are conservative source
budgets, not token counts. Empty/non-text results and malformed subtitle lists
are rejected; unusable SRT batches fall back to validated individual cues.

A truncated translation response is discarded. Its source can be split again
(up to four levels, stopping at 64 characters); persistent truncation fails the
job without replacing an existing complete translation. Output is checked against
`MAX_TEXT_CHARS` as fragments arrive and before atomic publication. Splitting and
SRT fallback can incur additional provider requests; they cannot guarantee the
linguistic completeness of a model response that reports normal completion.

Segmentation version 2 separates the corrected text pipeline from old audio
cache identities. Old task snapshots are rejected as incompatible; resubmit them
after upgrading. Existing output files remain available, but regeneration uses
new cache entries and may incur API charges.

### Storage retention and disk budgets

The WebUI plans maintenance every 30 minutes. **Deletion is off by default**:
logs report dry-run counts, and completed history remains until deletion is
enabled. Failed/interrupted jobs are kept indefinitely, including their input,
translation checkpoints and pinned audio cache. Active and queued jobs are also
protected. Upgrading no longer expires resumable history after 24 hours.

| Variable | Default | Meaning |
| --- | --- | --- |
| `STORAGE_CLEANUP_ENABLED` | `false` | Enable periodic deletion (`true`/`false` or `1`/`0`) |
| `STORAGE_RETENTION_SECONDS` | `86400` | Minimum age after completion and minimum artifact age for completed-job expiry |
| `STORAGE_ORPHAN_GRACE_SECONDS` | `604800` | Minimum age of recognized orphaned artifacts and unpinned cache (7 days) |
| `STORAGE_MAX_BYTES` | `0` | Optional logical-byte threshold under `storage`; 0 disables this threshold |
| `STORAGE_MIN_FREE_BYTES` | `268435456` | Free-space reserve on the storage filesystem (256 MiB); 0 disables it |

Before enabling automatic deletion, inspect the plan from the repository root:

```bash
python3 -m src.core.storage_retention --storage storage
# Explicitly apply a freshly calculated plan after reviewing the policy:
python3 -m src.core.storage_retention --storage storage --apply
```

The command defaults to read-only dry-run even if `STORAGE_CLEANUP_ENABLED=true`.
It requires an existing, migrated `state.db` inside the selected storage root;
it never creates or migrates a database. Dry-run reports relative artifact paths,
logical bytes and completed task IDs, without file contents. Apply rechecks the
current state and locks; it does not execute a previously saved report.

Recognized artifacts are hashed WebUI job directories, UUID task scratch/output/
translation names, v2 audio caches and `.compile-*` workspaces under storage.
Completed job inputs, named outputs and translations can expire after the
configured retention time. Their history/logs are removed only after those
artifacts are gone. Back up or move audiobooks outside managed storage before
enabling expiry if you want to keep them permanently. Orphaned artifacts and
unpinned audio must pass the longer grace period. Fresh files in an otherwise
old directory postpone cleanup. Cache pending files are removed with eligible
cache contents; abandoned task workspaces and compiler workspaces are reclaimed.

The sweeper skips symbolic links and unknown artifacts, including legacy flat TUI
chunk layouts, arbitrary CLI output names and loose shared translation staging
files whose owner cannot be proven. It never scans outside the selected root.
A non-expired job without a valid cache-reference marker conservatively protects
**all** v2 caches, including older snapshots until they are resumed. Failed jobs
are not evicted to meet a disk threshold; archive unwanted jobs manually while
the application is stopped. This deliberately favors recoverability over reclaiming
the maximum possible space.

A sweep takes an OS maintenance lock and acquires each cache/compiler lease
without waiting. Busy resources are skipped. Cache `.cache.lock` files and their
parent directories remain in place, preserving the lock inode for CLI/WebUI/TUI
waiters. Compiler leases also protect CLI/TUI compilation inside storage. Deleting
cache after its grace period can require paid regeneration on later resubmission.
Native Windows cleanup still needs a successful native run of the
[platform smoke suite](docs/WINDOWS.md); network filesystems
and multi-host writers are not supported by these local-lock guarantees.

When a disk threshold is reached, WebUI generate/resume requests return `507`
before body parsing. Known uploaded-input copies are checked again before saving
a new job or claiming resume. CLI/TUI check before generation; chunk generation,
uncached translation requests and compilation recheck the budget as work proceeds.
A failed check preserves existing snapshots/cache and makes no subsequent API
call for that step. Full quota measurement counts logical file sizes, includes
unknown files and refuses symbolic-link trees; it can add filesystem scanning
cost when `STORAGE_MAX_BYTES` is enabled.

These are admission/checkpoint thresholds, **not a hard filesystem quota**.
Concurrent writers, in-flight responses and one compilation can exceed the byte
threshold between checks, and outputs outside storage may use a different disk.
Use a filesystem/container volume quota for a strict upper bound. Maintenance
never discards protected recovery data to force usage below the threshold.

### Shared cache contract and TUI migration

`src/core/audio_cache.py` owns manifest loading, comparison of previous segment
text, completed markers, file checks and atomic generation. CLI, WebUI and TUI
use one locked session through final compilation. Only a segment with matching
previous text, a completion marker and a regular non-symlink file larger than
100 bytes can be reused. Malformed manifests or missing/invalid files trigger
regeneration. File-size checks do not replace provider/probe and final decoded
audio verification. The compiler receives all current segments in source order.

TUI now uses the same `storage/cache/v2_<sha256>/` identity as CLI/WebUI, including
source text before translation, the resolved translation model, reference bytes
and processed-reference fingerprint. It resumes completed audio on resubmission
and isolates different books/voices; simultaneous identical jobs wait for the
same OS lock. CLI/WebUI cache identities and manifest format are unchanged by
this consolidation.

Old flat TUI `storage/cache/chunk_*.mp3` files remain untouched and are not reused:
their source/voice cannot be verified. The first TUI run may therefore incur new
API charges. Existing compatible v2 entries from CLI/WebUI can be reused. TUI
has no durable job snapshot or translation checkpoints; rerun with the same input
and settings after interruption. Changed translation text invalidates affected
segments. Choose distinct output paths for independent audiobooks.

### Pipeline service and interface adapters

`src/core/pipeline.py` provides shared text preparation and audiobook generation.
`prepare_text` reads input with the selected encoding, invokes an optional async
translation adapter, reads translated UTF-8 text and splits it in source order.
It freezes the effective translation model for the prepared job. `run_pipeline`
configures a preset/reference voice, builds the existing cache identity, generates
or reuses ordered segments and runs verified compilation under the cache lock.

The service accepts synchronous progress callbacks, a cache-ready callback,
an injected TTS client and a compiler factory. Callbacks run on the caller's event
loop; callback errors propagate and stop the operation. Compilation stays in its
cancellation-aware worker thread, retaining the cache lock until that worker has
stopped. Results include the output path, cache directory, segment count and
compiler verification metadata. The service imports neither FastAPI/Textual nor
the provider SDKs; provider clients are supplied by the adapters.

CLI owns Rich output and exit codes. TUI owns widgets, progress and voice/model
error assistance. WebUI owns uploads, task state, UUID output names, durable
input/translation checkpoints and temporary-input cleanup. Translation adapters
keep those persistence differences explicit: CLI/TUI resubmission can still repeat
translation, while WebUI resume reuses its saved results. Cache keys, manifests,
API retry/deadline policy and output publication rules are unchanged by this
extraction; there is no cache or task-snapshot migration for P18.

Custom TTS clients must implement `BaseTTSClient.set_voice_id` alongside audio
generation, voice listing and cloning. Preset selection clears a previous
reference on reference-capable clients. Mistral supports reference input; OpenAI
rejects cloning and uses preset voices. API credentials remain in runtime clients
and adapter closures, outside prepared text, progress events and pipeline results.

### Windows verification

The current verification target is CPython 3.11 + FFmpeg/ffprobe, launched from
source with UTF-8 mode. See [Windows setup and acceptance](docs/WINDOWS.md) for
PowerShell commands, native CI prerequisites and the isolated smoke suite.
Native Windows acceptance is pending; no tested standalone `.exe` is provided.
