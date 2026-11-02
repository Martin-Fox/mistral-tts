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
silently reuse mismatched segments. Persisting translated results and coordinating
concurrent writers remain separate follow-up work. This shared cache change does
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
