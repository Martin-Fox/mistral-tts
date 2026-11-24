# Mistral-TTS Docker Image Overview

[Documentation](docs/README.md) · [Project overview](README.md)

This repository contains the containerized version of **Mistral-TTS**, a text-to-speech pipeline designed to convert long-form text (articles, books, essays) into seamless audiobooks. It integrates the **Mistral AI Voxtral TTS** API (with zero-shot voice cloning), **OpenAI TTS** as an alternative engine, configurable **Mistral chat models** (default: `ministral-8b-latest`) for pre-translation, and support for EPUB, MOBI, SRT, and TXT ingestion.

The Dockerfile bundles Python 3.11, runtime dependencies, **FFmpeg and ffprobe**.
It builds a hash-pinned audio-only FFmpeg **9.0.2** without libxml2 or network
protocols in a separate stage. The final stage avoids distro FFmpeg's multimedia
dependency graph, pins the Debian trixie base digest, explicitly upgrades zlib
to a corrected minimum, and installs util-linux for decoder resource limits.
Installers are removed after dependency validation; pip is unavailable at runtime.
The versioned image for this security update is
`marcinlis82/mistral-tts:1.0.5` (Linux amd64). See the
[1.0.5 change notes](docs/RELEASE_NOTES.md#security-audit-remediation--105) before upgrading.

```bash
docker pull marcinlis82/mistral-tts:1.0.5
mkdir -p storage
```

See the [1.0.5 image checks and digest](docs/audit/RELEASE_1.0.5_2026-11-24.md)
(and the earlier [1.0.4 CVE scan](docs/audit/RELEASE_1.0.4_2026-11-18.md)).

See [Operations](docs/OPERATIONS.md) for TLS, restart recovery, backup/restore and
upgrade/rollback procedures. All examples below use the versioned image. To build from source, run
`docker build -t marcinlis82/mistral-tts:1.0.5 .` in this checkout.
See [deployment security](docs/SECURITY_DEPLOYMENT.md) for LAN-only publication,
HTTP/HTTPS settings, request limits and image identity checks. Docker and desktop
launches ignore forwarded headers by default; a reverse proxy needs an explicit
command override with its actual trusted source address.

---

## Running the container

The container supports WebUI, TUI and CLI. For provider, voice and translation
options, see [Installation and usage](docs/USAGE.md).

### 1. Run the WebUI (Default)
To start the responsive, glassmorphism WebUI, expose port `8000` and mount a local folder to `/app/storage` to persist generated audiobooks, manifests, and cache state.

```bash
docker run -d \
  -p 127.0.0.1:8000:8000 \
  -v "$PWD/storage:/app/storage" \
  --env-file "$PWD/.env" \
  --name mistral-tts \
  marcinlis82/mistral-tts:1.0.5
```

Once running, access the WebUI at **`http://localhost:8000`**.
*Note: Set a unique `APP_PASSWORD` before first start. Empty credentials and the password `admin` prevent WebUI startup, even on localhost. `APP_USERNAME` defaults to `admin`. If mounted storage contains `auth.json`, its credentials take precedence: follow [credential recovery](docs/OPERATIONS.md#credential-recovery) if it contains rejected credentials.*

### 2. Run the Interactive TUI
To run the terminal configuration and progress tracking interface inside the container, run with interactive terminal flags (`-it`):

```bash
docker run -it --rm \
  -v "$PWD/storage:/app/storage" \
  --env-file "$PWD/.env" \
  marcinlis82/mistral-tts:1.0.5 \
  python -m src.cli --tui
```

### 3. Run via Headless CLI
For automated script integrations, execute the CLI directly:

```bash
docker run --rm \
  -v "$PWD/storage:/app/storage" \
  --env-file "$PWD/.env" \
  marcinlis82/mistral-tts:1.0.5 \
  python -m src.cli \
  --text /app/storage/book.txt \
  --voice /app/storage/sample.mp3 \
  --output /app/storage/audiobook.mp3
```

---

## Environment variables

Create a private host `.env` as described in [Installation and usage](docs/USAGE.md#setup). `--env-file` injects its
values at container creation; changes require container recreation. It does not
mount the file, and writing `/app/.env` in WebUI/TUI does not update the host file.
For model settings that must survive container replacement, set
`BOOKSMITH_ENV_FILE=/app/storage/application.env` and keep that writable file on
the storage mount. Omit `MISTRAL_TRANSLATION_MODEL` from injected process variables
if the saved file should select it after restart: process variables take priority.
This path is private configuration, not a public upload.

The main environment variables are listed below. Full configuration tables are in
[Processing](docs/PROCESSING.md), [WebUI security](docs/WEB_SECURITY.md) and
[Storage](docs/STORAGE.md).

| Variable | Description |
| --- | --- |
| `MISTRAL_API_KEY` | Your Mistral AI API Key (required for Voxtral TTS and Translation). |
| `OPENAI_API_KEY` | Your OpenAI API Key (required if selecting the OpenAI TTS engine). |
| `MISTRAL_TRANSLATION_MODEL` | Mistral chat model for text translation (default: `ministral-8b-latest`). |
| `APP_USERNAME` | Custom username for WebUI cookie authentication (default: `admin`). |
| `APP_PASSWORD` | Required unique password for WebUI cookie authentication; empty values and `admin` are rejected at startup. |

Without an existing auth file, use 12-1024 characters (at least 12 after trimming)
before upgrading. Persisted legacy short passwords allow only a password-change
session until rotated. Non-browser HTTP clients must supply
`X-Requested-With: Booksmith` on writes without Origin; the frontend does this
automatically. See [request/browser security](docs/WEB_SECURITY.md#request-origin-and-browser-security)
for CSP, proxy origin handling and API documentation availability.

## Startup diagnostics and smoke checks

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

## Application reference

Shared behavior is documented once for Docker and source installations:

- [Authentication, sessions, CSRF and API keys](docs/WEB_SECURITY.md).
- [Upload/EPUB limits, reference decoding and API retries](docs/PROCESSING.md).
- [Cache locks, atomic output, restart/resume and retention](docs/STORAGE.md).
- [Backups, upgrades and credential recovery](docs/OPERATIONS.md).
- [Python locks](docs/DEPENDENCIES.md) and [native build profile](docs/NATIVE_DEPENDENCIES.md).
