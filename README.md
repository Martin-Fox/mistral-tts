# Mistral-TTS

> [!NOTE]
> **Repository Setup & Contributions:** The primary development repository and source of truth for this project is hosted on my [Gitea Instance](https://gitea.marcin-lis.pl/fox/mistral-tts). A public mirror is available on [GitHub](https://github.com/Martin-Fox/mistral-tts), which you are warmly invited to use for submitting issues, creating pull requests, or leaving comments and feedback.

An automated, open-source text-to-speech pipeline designed to transform long-form text (articles, books, essays) into seamless audiobooks using the Mistral AI Voxtral TTS API with instant, zero-shot voice cloning.

## 🚀 Features

- **Interactive WebUI:** A premium, responsive single-page web application featuring glassmorphism card layouts, real-time progress bar animations, drag-and-drop file uploaders, an in-browser console terminal streaming live server logs via Server-Sent Events (SSE), and a custom audio player for instant playback.
- **Interactive TUI:** A modern terminal interface for easy configuration and progress monitoring.
- **Integrated Translation:** Translate source files from a source language to a target language using configurable Mistral chat models (default: `ministral-8b-latest`, with support for `ministral-3b-latest`, `mistral-small-latest`, `mistral-medium-latest`, and `mistral-large-latest`) before the TTS phase. Supports rate-limit-aware retries and preserves subtitle timecodes.
- **Multi-Format Ingestion:** Direct support for plain text (`.txt`), subtitles (`.srt`), and electronic books (`.epub` and unencrypted `.mobi`), automatically extracting content in the correct reading order.
- **Audio Truncation Safeguard & Duration Verification:** Appends format-matched trailing silence padding (1.0s default) to prevent FFmpeg `loudnorm` filter buffer cutoff at stream end. Accurately verifies decoded presentation duration using FFmpeg null decoding (`-f null -`) to eliminate VBR header estimation drift, and enforces strict end-to-end duration verification (4.0s tolerance) to guarantee no audio is lost.


- **Zero-Shot Voice Cloning:** Instantly clones any voice profile using a 3-to-10-second reference audio sample.
- **Preset Voice Selection:** Choose from high-quality default Mistral voices (e.g., Paul, Sarah) without needing a sample.
- **Intelligent Text Segmentation:** Tokenizes long texts based on punctuation and character constraints to preserve semantic flow.
- **Asynchronous Batching:** Dispatches parallel requests with exponential backoff for maximum throughput.
- **Progress Persistence:** Tracks generation state via a local manifest, allowing you to resume if interrupted.
- **Environment Support:** Securely store your API key in a `.env` file.

## 🛠️ Installation


### Prerequisites

- **Python 3.11+**
- **FFmpeg:** Must be installed and available in your system PATH.

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

3. (Optional) Configure environment variables:
   Create a `.env` file in the root directory to set your API Keys and optional WebUI credentials:
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

### Running the WebUI

To launch the WebUI:

```bash
python3 -m uvicorn src.web:app --reload
```

Once running, open `http://localhost:8000` in your web browser.

* **Required credentials:** Before starting the WebUI, set `APP_PASSWORD` to a unique password in your environment or `.env`; `APP_USERNAME` defaults to `admin`. Empty credentials and the password `admin` are rejected at startup, including on localhost. Existing `storage/auth.json` credentials take precedence: if startup rejects them, update that file locally before restarting. The error never prints the configured password.


### Interactive TUI (Recommended)

The easiest way to use the tool is via the built-in Terminal UI:

```bash
export PYTHONPATH=$PYTHONPATH:.
python3 src/cli.py --tui
```

### Standard CLI

For automated workflows, you can use the traditional CLI:

```bash
python3 src/cli.py --text <path_to_text_file> \
                   --voice <path_to_voice_sample> \
                   --output <output_path.mp3> \
                   --api-key <your_mistral_api_key>
```

*Note: If `MISTRAL_API_KEY` is set in your `.env` file, the `--api-key` flag is optional.*

CLI exit codes: `0` after a successful run (or `--help`), `1` for an execution
error such as a missing input file, failed generation or failed compilation,
and `2` for invalid or missing arguments. Automation should check the exit code
before treating the output as a completed audiobook.

### OpenAI TTS Integration

To use the OpenAI TTS synthesis engine (e.g., for languages like Polish where Mistral Voxtral is not natively supported):

1. **API Configuration:** Configure `OPENAI_API_KEY` in your `.env` file, or supply it as a parameter in the interfaces.
2. **Preset Voices:** OpenAI TTS only supports its 6 preset voices: `alloy`, `echo`, `fable`, `onyx`, `nova`, and `shimmer`. Dynamic voice cloning is not supported.
3. **WebUI Usage:** Select **OpenAI TTS** as the *TTS Engine*. The WebUI dynamically hides the voice cloning section and switches preset options to the OpenAI voices.
4. **TUI Usage:** Set the *TTS Engine* dropdown to **OpenAI**. The dropdown for *Default Voice* will populate with OpenAI voices, and inputs for cloning and manual voice IDs will be disabled.
5. **CLI Usage:** Include the `--engine openai` parameter and specify one of the 6 preset voices in the `--voice` argument:
   ```bash
   python3 src/cli.py --text book.txt \
                      --engine openai \
                      --voice alloy \
                      --output audiobook.mp3 \
                      --openai-key your_openai_key
   ```
   *Note: Passing a file path to `--voice` when running with `--engine openai` will trigger a validation error.*

### Translation Model Configuration

When `--target-lang` is specified, the pipeline translates the input text via the Mistral Chat API prior to audio synthesis. By default, `ministral-8b-latest` is used instead of `mistral-large-latest` to ensure compatibility across all account tiers (including free/starter tiers) and avoid HTTP 403 `tier_not_allowed` errors.

*(For a comprehensive comparison of Free vs. Paid tiers, rate limits, and audio capabilities, see the [Models & Account Tiers](#models--account-tiers) section below.)*

#### Supported Models

| Model ID | Display Name | Recommended Account Tier | Notes |
| --- | --- | --- | --- |
| `ministral-8b-latest` | Ministral 8B | Free, Starter, Enterprise | **Default.** Low latency, cost-effective, works on all tiers. |
| `ministral-3b-latest` | Ministral 3B | Free, Starter, Enterprise | Ultra-lightweight edge model. |
| `mistral-small-latest` | Mistral Small | Starter, Enterprise | Balanced speed and quality. |
| `mistral-medium-latest` | Mistral Medium | Enterprise | High quality for literary and nuanced texts. |
| `mistral-large-latest` | Mistral Large | Enterprise (Tier 2+) | Flagship reasoning model; requires elevated Mistral account tier. |

#### Changing the Model

- **WebUI:** Expand **Translation Settings** and select the desired model from the **Translation Model** dropdown. The selection is automatically sent to `POST /api/config` and saved directly to your `.env` file without requiring a backend restart.
- **TUI:** Choose your preferred model in the **Trans Model** dropdown selector. Selection is immediately saved to `.env` and takes effect for subsequent generation runs.
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

Install the development lock before running tests in a disposable checkout with
throwaway storage and configuration. Shared storage/environment isolation is
tracked in audit P20; the current suite must not use a live application's data.

```bash
python -m pip install --require-hashes --only-binary=:all: -r requirements-dev.txt
python -m pytest
```

## 🎙️ Models & Account Tiers

This project integrates both **Mistral AI** and **OpenAI** APIs to provide speech synthesis and automated translation. Capabilities, pricing, and rate limits vary depending on your account tier (**Free Tier** vs. **Paid / PAYG**).

---

### 1. Text-to-Speech (TTS) Engines

#### Mistral AI Voxtral TTS
- **Dedicated TTS Model:** `voxtral-mini-tts-latest` (snapshot: `voxtral-mini-tts-2603`).
  > [!NOTE]
  > Only `voxtral-mini-tts-latest` (and its dated snapshots) is designed for Text-to-Speech synthesis. Other models in the Voxtral family (such as `voxtral-small`) are Speech-to-Text (STT), transcription, and audio-understanding models, and cannot be used for speech generation.
- **Key Capabilities:**
  - **Zero-Shot Voice Cloning:** Clones any voice profile using a short 3–10 second reference audio sample (`.wav` or `.mp3`). The pipeline automatically applies FFmpeg spectral noise reduction (`afftdn`) to optimize cloning quality.
  - **Emotionally Expressive Presets:** Built-in speaker presets offering rich emotional modulation (e.g., *Paul* with cheerful, sad, or confident tones; *Jane* with sarcastic delivery; *Oliver*, etc.).
- **Supported Languages & Accents:** Optimized for **English** (US / UK), **French**, and **Spanish**. Unsupported languages (such as **Polish**) do not have native phonetic synthesis; translate the text into English, French, or Spanish before synthesis using the built-in translation pipeline, or switch to the OpenAI TTS engine.
- **Tier Availability:**
  - **Free Tier:** Fully accessible within Mistral's standard free community rate limits (RPM / TPM).
  - **Paid / PAYG Tier:** Supported with elevated rate limits and concurrency for large book synthesis.

#### OpenAI TTS
- **Available Models:**
  - `tts-1`: Standard low-latency model optimized for real-time applications and rapid batch processing.
  - `tts-1-hd`: High-definition studio model offering superior bandwidth, dynamic range, and acoustic fidelity.
- **Key Capabilities:**
  - **Native Multilingual Synthesis:** Exceptional out-of-the-box support for dozens of languages—including **Polish** with authentic accents and natural pronunciation—without requiring prior translation.
  - **Curated Voice Presets:** 6 fixed studio presets: `alloy`, `echo`, `fable`, `onyx`, `nova`, and `shimmer`.
  - **No Voice Cloning:** OpenAI TTS does not support custom voice cloning from audio files.
- **Tier Availability & Pricing:**
  - Requires a funded OpenAI API account (Pay-As-You-Go).
  - Standard pricing:
    - `tts-1`: ~$0.015 per 1,000 input characters.
    - `tts-1-hd`: ~$0.030 per 1,000 input characters.

#### TTS Engine Comparison

| Feature / Metric | Mistral AI (`voxtral-mini-tts-latest`) | OpenAI TTS (`tts-1` / `tts-1-hd`) |
| :--- | :--- | :--- |
| **Primary Specialty** | Zero-shot cloning & expressive emotional presets | Multilingual accuracy & polished studio presets |
| **Voice Cloning** | ✅ Yes (3–10s audio sample) | ❌ No (preset voices only) |
| **Preset Voices** | ✅ Expressive presets (Paul, Jane, Oliver, etc.) with emotion modulation | ✅ 6 curated voices (`alloy`, `echo`, `fable`, `onyx`, `nova`, `shimmer`) |
| **Native Language Support** | English (US/UK), French, Spanish | 50+ languages natively (including Polish) |
| **Unsupported Language Strategy** | Pre-translate via `--target-lang` before synthesis | Synthesize source text directly without translation |
| **Account Tiers** | **Free Tier** & **Paid / PAYG** | **Paid / PAYG Only** |
| **Pricing** | Free tier quotas / Mistral PAYG rates | `tts-1`: ~$0.015 / 1k chars<br>`tts-1-hd`: ~$0.030 / 1k chars |

---

### 2. Translation Models (Mistral Chat API)

When `--target-lang` is specified, source text is translated using the Mistral Chat API prior to audio generation. Model selection directly impacts tier compatibility and rate limiting.

#### Free Tier
- **`ministral-8b-latest` (Default):**
  - **Recommended default.** High-quality, fast, and cost-effective translation.
  - **Zero 403 errors:** Fully accessible on free/starter tiers without permission errors.
- **`ministral-3b-latest`:**
  - Ultra-lightweight edge model with minimal token footprint; best for quick runs and simple phrasing.
- **`mistral-small-latest`:**
  - Higher literary capacity, but subject to strict Free tier RPM/TPM limits. Large books may encounter HTTP 429 (`rate_limited`) pauses.
- **`mistral-large-latest`:**
  - ❌ **Unavailable on Free Tier.** Calling this model without a paid account triggers HTTP 403 `tier_not_allowed`.

#### Paid Tier (PAYG)
- **`mistral-large-latest` (Flagship):**
  - Unlocked on PAYG accounts. Delivers top-tier literary and nuanced translations, accurately rendering complex prose, idioms, and stylistic subtleties.
- **High Concurrency & Throughput:**
  - Significantly higher RPM and TPM quotas across all models (`ministral-8b`, `mistral-small`, `mistral-large`), reducing or eliminating rate-limit delays during long book translations.

#### Translation Model & Tier Matrix

| Model ID | Display Name | Free Tier | Paid / PAYG Tier | Translation Profile & Best Use Case |
| :--- | :--- | :---: | :---: | :--- |
| `ministral-8b-latest` | **Ministral 8B** | ✅ Supported (**Default**) | ✅ Supported | **Recommended Default.** Excellent translation quality and zero tier restrictions. |
| `ministral-3b-latest` | **Ministral 3B** | ✅ Supported | ✅ Supported | Ultra-fast edge model; low latency and minimal resource consumption. |
| `mistral-small-latest` | **Mistral Small** | ⚠️ Partial (strict 429 limits) | ✅ Supported | Strong translation quality; may hit rate limits on long-form Free tier tasks. |
| `mistral-medium-latest`| **Mistral Medium**| ⚠️ Legacy / Restricted | ✅ Supported | High literary capability; generally superseded by Ministral 8B / Mistral Large. |
| `mistral-large-latest` | **Mistral Large** | ❌ Blocked (HTTP 403 `tier_not_allowed`) | ✅ Supported | **Flagship literary model.** Best for novels, nuanced prose, and complex metaphors. |

## 🏗️ Architecture

- **`src/tui.py`**: The interactive Terminal UI built with Textual.
- **`src/web.py`**: FastAPI web server hosting API endpoints and background synthesis tasks.
- **`src/web/static/`**: Contains HTML, CSS, and JS assets for the Single-Page Web application.
- **`src/core/config.py`**: Environment management and persistent `.env` synchronization for runtime configuration.
- **`src/core/text_splitter.py`**: Handles semantic chunking logic.
- **`src/api/mistral_client.py`**: Wrapper for Voxtral API interaction, voice cloning, and text translation.
- **`src/core/audio_compiler.py`**: FFmpeg-based stitching, pause/trailing silence injection, loudness normalization (`loudnorm`), and duration verification.
- **`src/cli.py`**: Primary command-line interface entry point.


## ⚙️ State Persistence

Mistral-TTS-Booksmith automatically caches generated audio chunks in `storage/cache/` and maintains a `manifest.json`. If a run fails or is stopped, simply run the same command again; the tool will skip completed chunks and resume from where it left off.

## 🐳 Docker Setup

You can run the application using Docker to avoid installing system-level dependencies like FFmpeg. A pre-built image is available on Docker Hub as **`marcinlis82/mistral-tts`**.

### 1. Pull the pre-built image (Recommended)
```bash
docker pull marcinlis82/mistral-tts
```

Alternatively, you can build the image locally from source:
```bash
docker build -t mistral-tts .
```

*Note: In the commands below, replace `marcinlis82/mistral-tts` with `mistral-tts` if you built the image locally.*

### 2. Run the WebUI (Default)
To run the WebUI inside Docker (passing custom credentials):
```bash
docker run -d --rm \
  -p 8000:8000 \
  -v $(pwd)/storage:/app/storage \
  -e MISTRAL_API_KEY=your_key_here \
  -e OPENAI_API_KEY=your_openai_key_here \
  -e MISTRAL_TRANSLATION_MODEL=ministral-8b-latest \
  -e APP_USERNAME=myuser \
  -e APP_PASSWORD=mypassword \
  --name mistral-tts \
  marcinlis82/mistral-tts
```
*Note: Set a unique `APP_PASSWORD` before starting the WebUI; empty credentials and the password `admin` prevent startup. `APP_USERNAME` defaults to `admin`. Existing `storage/auth.json` credentials take precedence over environment variables. The `MISTRAL_API_KEY` and `OPENAI_API_KEY` environment variables configure the backend clients for the respective engines.*


### 3. Run the interactive TUI
To run the interactive Textual Terminal UI inside Docker, you need to enable interactive mode (`-it`):
```bash
docker run -it --rm \
  -v $(pwd)/storage:/app/storage \
  -e MISTRAL_API_KEY=your_key_here \
  marcinlis82/mistral-tts \
  python src/cli.py --tui
```

### 4. Run the standard CLI
For headless or automated audiobook generation:
```bash
docker run --rm \
  -v $(pwd)/storage:/app/storage \
  -v $(pwd)/your_text_dir:/app/data \
  -e MISTRAL_API_KEY=your_key_here \
  marcinlis82/mistral-tts \
  python src/cli.py \
  --text /app/data/book.txt \
  --voice /app/data/sample.mp3 \
  --output /app/storage/output/audiobook.mp3
```


## 🗺️ Future Roadmap

- [x] **Integrated Translation:** Direct translation from Language A to Language B using configurable Mistral chat models (default: `ministral-8b-latest`, with support for Small, Medium, Large) before the TTS phase.
- [x] **Interactive WebUI:** A responsive web application to configure runs, preview voices, and monitor generation.
- [x] **Docker Containerization:** Containerize the application, bundling FFmpeg and Python dependencies for zero-setup deployments.
- [x] **Basic Authentication Layer:** Secure the WebUI and API endpoints with session cookies for multi-user or network deployments.
- [ ] **OpenID Connect (OIDC) Login:** Integrate authentication based on OpenID Connect (OIDC) provided by a self-hosted Pocket ID instance for single sign-on.
- [ ] **Multi-User Login:** Support multiple user accounts and sessions, paving the way for personalized histories, settings, and task queues.
- [ ] **CLI User Management:** Add command-line interface options to create, update, and manage user accounts securely, keeping user-creation tools out of the WebUI.
- [ ] **WebUI About Modal & Current Version Display:** Add a menu item / modal for "About" that displays application metadata, current version (e.g. 1.0.2), license, and project links.
- [ ] **WebUI Help / Quick Guide:** Interactive help or documentation drawer/modal explaining parameters (chunking, temperature, voices, engines, loudnorm) and troubleshooting tips.
- [x] **Robust Task State Management:** SQLite task state, explicit restart recovery and conservative storage retention protect active/resumable jobs.
- [x] **EPUB Support:** Ingest and parse EPUB files to extract chapters while preserving document structure.
- [x] **MOBI Support:** Ingest and parse MOBI files to extract chapters for synthesis.
- [x] **OpenAI TTS Integration:** Add support for the OpenAI TTS API as an alternative synthesis engine, enabling voice options for languages not natively supported by Mistral (such as Polish).
- [x] **Audio Truncation Safeguard & Duration Verification:** Enforce end-to-end duration verification and trailing silence padding.



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
incur new API charges. Native Windows process handling still needs its own smoke
test; the process cleanup tests here were run on Linux.

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
Native Windows cleanup still needs a platform smoke test; network filesystems
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
