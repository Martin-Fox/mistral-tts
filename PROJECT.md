# Project Overview

An automated, open-source text-to-speech pipeline designed to transform long-form text (articles, books, essays, subtitles) into seamless audiobooks using the Mistral AI Voxtral TTS API (and OpenAI TTS) with reference-audio voice cloning, preset voices, and integrated multi-model translation.

## What this project does
Mistral-TTS-Booksmith bridges the gap between raw text / ebook files and polished, long-form audiobooks. Standard text-to-speech APIs suffer from strict character limits and produce disjointed audio files when processed in chunks. This tool completely automates the heavy lifting: it ingests long texts, subtitles (.srt), or ebooks (.epub, .mobi), intelligently tokenizes and splits them into context-aware semantic chunks, generates ordered chunks asynchronously through Mistral Voxtral or OpenAI TTS, and cleanly merges the resulting audio segments into a single, high-fidelity MP3 file with natural pacing, loudness normalization, and audio verification.

## Core functionality
- **Interactive WebUI:** A responsive single-page web interface built with FastAPI, vanilla HTML/CSS/JS, glassmorphism card layouts, real-time progress bar animations, drag-and-drop file uploaders, session authentication, and an in-browser console terminal streaming live logs via Server-Sent Events (SSE).
- **Interactive TUI:** A modern Terminal User Interface built with Textual for easy parameter configuration, model selection, and real-time progress monitoring.
- **Zero-Shot Voice Cloning:** Clones voice profiles using a reference audio sample (.mp3/.wav) via Mistral's native zero-shot endpoints, with automatic afftdn audio denoising.
- **Preset Voice Selection:** Built-in high-quality Mistral voices (`en_paul_neutral`, `fr_marie_neutral`, etc.) and OpenAI voices (`alloy`, `echo`, `fable`, `onyx`, `nova`, `shimmer`).
- **Dual TTS Engine Architecture:** Switch seamlessly between Mistral Voxtral (`voxtral-mini-tts-2603`) and OpenAI TTS (`tts-1`).
- **Multi-Format Ingestion:** Ingests plain text (.txt), subtitles (.srt with timecode stripping), and ebooks (.epub, .mobi).
- **Intelligent Text Segmentation:** Tokenizes long texts dynamically based on punctuation, sentence boundaries, and character constraints to prevent API truncation while preserving semantic flow and avoiding dropped trailing text.
- **Configurable Translation Subsystem:** Translates text and subtitle files using Mistral Chat Completion models (`ministral-8b-latest` default, `ministral-3b-latest`, `mistral-small-latest`, `mistral-medium-latest`, `mistral-large-latest`) with rate-limit handling and JSON batch modes.
- **Audio Compiling & Mastering:** Merges independent audio buffers seamlessly using FFmpeg concat demuxer, injecting natural-sounding pause intervals between segments, appending format-matched trailing silence to prevent `loudnorm` filter cutoff, and performing strict decoded presentation duration verification (`ffmpeg -f null -`) against expected chunk totals.
- **Progress & State Persistence:** SQLite tracks WebUI task state; private snapshots and translation checkpoints support explicit resume of compatible failed/interrupted jobs after login. Restart marks unfinished work Interrupted and never automatically submits provider work. CLI/TUI resubmission can reuse matching audio cache but may repeat translation.
- **Docker Containerization:** Containerized setup bundling FFmpeg, Python runtime, and entrypoint permission handling for zero-setup deployments (Docker Hub: `marcinlis82/mistral-tts`).

---

## Priorities
- **Audio Continuity & Completeness:** The final output must sound continuous and never drop or truncate content—especially ensuring trailing text and final audio segments are fully preserved.
- **Resource Efficiency:** Stream-to-disk and temporary buffer chunking during compilation maintain low RAM footprint.
- **Robust Fault Tolerance:** Retry eligible transport/timeouts and HTTP 408/429/5xx within finite per-operation budgets. Local parsing, filesystem and FFmpeg errors fail without repeating a paid request. Reuse compatible committed chunks/checkpoints; do not promise exactly-once billing.
- **Developer & User Simplicity:** Clean codebase, intuitive CLI/TUI/WebUI interfaces, and secure credential management via `.env`.

---

## Architecture

### Structure
mistral-tts/
├── AGENTS.md                  # Project-scoped AI rules & workflow
├── PROJECT.md                 # Root project overview & architecture
├── src/
│   ├── api/
│   │   ├── base_client.py     # Base abstract TTS client interface
│   │   ├── factory.py         # TTS client factory (Mistral / OpenAI)
│   │   ├── mistral_client.py  # Mistral Voxtral TTS and translation client
│   │   └── openai_client.py   # OpenAI TTS client implementation
│   ├── core/
│   │   ├── audio_compiler.py  # FFmpeg stitching, pause injection, loudnorm, validation
│   │   ├── audio_cache.py     # Shared CLI/WebUI/TUI manifest, chunk validation and resume
│   │   ├── cache_identity.py  # Canonical identity of text, voices, models and segmentation
│   │   ├── cache_io.py        # Cross-process locks and atomic file publication
│   │   ├── pipeline.py        # Shared preparation/generation service with progress callbacks
│   │   ├── config.py          # Translation model configuration and .env persistence
│   │   ├── epub_parser.py     # Parser for EPUB, MOBI, and plain text
│   │   ├── task_store.py      # Durable private resume inputs and translation checkpoints
│   │   ├── storage_retention.py # State-aware maintenance and soft disk budgets
│   │   ├── task_db.py         # SQLite persistent state management
│   │   └── text_splitter.py   # Semantic chunking logic
│   ├── web/
│   │   └── static/            # Static assets for the WebUI SPA
│   │       ├── app.js         # JavaScript application logic (SSE, state management)
│   │       ├── index.html     # HTML structure with modern layouts
│   │       └── styles.css     # CSS style rules with dark theme and glassmorphism
│   ├── cli.py                 # Primary command-line interface entry point
│   ├── tui.py                 # Interactive Terminal UI built with Textual
│   └── web.py                 # FastAPI backend server with background runner and SSE
├── storage/
│   ├── cache/                 # Temporary chunk audio cache and manifests
│   ├── output/                # Destination for compiled audiobooks
│   ├── tasks/                 # Hashed WebUI task directories and resume checkpoints
│   ├── auth.json              # Optional persisted password hash (legacy files migrate)
│   ├── state.db               # SQLite database for persistent task tracking
│   └── translations/          # Destination for translated source documents
├── tests/                     # Automated test suites for core modules & WebUI
│   ├── test_audio_compiler.py
│   ├── test_config.py
│   ├── test_epub.py
│   ├── test_text_splitter.py
│   ├── test_translation.py
│   ├── test_tui.py
│   ├── test_web.py
│   ├── conftest.py             # Collection/per-test storage, config and auth isolation
│   └── network_guard.py        # Test-only external IP/DNS guard; local IPC permitted
├── .dockerignore
├── .env                       # (Local only) Secure API keys & config
├── Dockerfile                 # Multi-stage container configuration
├── LICENSE                    # MIT License
├── README.md                  # Main project documentation
├── requirements.in            # Direct runtime dependencies
├── requirements-dev.in        # Development tools and test dependencies
├── constraints.txt            # Indirect-dependency compatibility baseline
├── requirements.txt           # Compiled runtime pins and artifact hashes
└── requirements-dev.txt       # Compiled development pins and artifact hashes

### Data flow
[Input Text (.txt/.srt/.epub/.mobi)]
         │
         ▼
[Optional Mistral Translation] ──> [storage/translations/]
         │
         ▼
[Text Splitter] ──> [Semantic Chunks List]
         │
         ▼
[TTS Engine (Mistral / OpenAI)] ──> [storage/cache/<hash>/chunk_*.mp3]
         │
         ▼
[Audio Compiler (FFmpeg concat + loudnorm + verification)]
         │
         ▼
[Final Audiobook: storage/output/<filename>]

---

## Constraints
- **API Payload Constraints:** Individual text chunks must strictly adhere to Mistral and OpenAI API character/token limits.
- **Local System Dependencies:** Requires **FFmpeg** and **ffprobe** installed in the system PATH. Windows verification targets CPython 3.11 with UTF-8 mode; native acceptance is tracked in `docs/WINDOWS.md`.
- **Filesystem Locations:** WebUI static assets are resolved relative to `src/web.py`; mutable `storage/` stays relative to the launch working directory. No storage migration is implied by launching from another directory.
- **Audio Verification:** Compilation probes decoded chunk/output duration, pads trailing silence (1.0s default) to protect `loudnorm` buffers, and rejects output more than 4.0s shorter than the expected chunk/pause/padding total. Only verified output is published atomically. Duration checks do not prove linguistic completeness of provider output.
- **Deployment and Recovery:** One shared WebUI account, worker and replica; process-local sessions expire and reset on restart. Remote access needs configured HTTPS; Secure cookies do not provide TLS. Retention defaults to dry-run, protects failed/interrupted jobs and uses soft disk thresholds rather than hard quotas. Use stopped whole-storage backups before migration; see `docs/OPERATIONS.md`.
- **SDK Compatibility:** The dependency locks retain `mistralai==2.4.9`; OpenAI TTS uses HTTPX directly and does not require the OpenAI SDK. Regenerate and verify both dependency locks when updating versions.

---

## Roadmap

- [x] **Integrated Translation:** Direct translation from Language A to Language B using Mistral models before TTS.
- [x] **Interactive WebUI:** Responsive web application to configure runs, preview voices, and monitor generation.
- [x] **Docker Containerization:** Bundling FFmpeg and Python dependencies for zero-setup deployments.
- [x] **Session Authentication:** One shared account with expiring session cookies; multiple accounts remain planned.
- [x] **EPUB & MOBI Support:** Direct ingestion of EPUB and unencrypted MOBI ebooks.
- [x] **OpenAI TTS Integration:** Support for OpenAI TTS voices alongside Mistral Voxtral.
- [x] **Persistent Task State Management:** SQLite-backed task state storage.
- [x] **Configurable Translation Models:** Dynamic switching and persistence of translation models.
- [ ] **OpenID Connect (OIDC) Login:** Integrate authentication based on OpenID Connect (OIDC).
- [ ] **Multi-User Login:** Support multiple user accounts and personalized histories.
- [x] **Audio Truncation Safeguard & Duration Verification:** Enforce end-to-end duration verification and trailing silence padding.
- [ ] **WebUI About Modal & Current Version Display:** Add a menu item / modal for "About" that displays application metadata, current version (e.g. 1.0.2), license, and project links.
- [ ] **WebUI Help / Quick Guide:** Interactive help or documentation drawer/modal explaining parameters (chunking, temperature, voices, engines, loudnorm) and troubleshooting tips.
