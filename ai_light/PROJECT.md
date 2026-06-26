# Project Overview

An automated, open-source text-to-speech pipeline designed to transform long-form text (articles, books, essays) into seamless audiobooks using the Mistral AI Voxtral TTS API with instant, zero-shot voice cloning and preset voice support.

## What this project does
Mistral-TTS-Booksmith bridges the gap between raw text files and polished, long-form audiobooks. Standard text-to-speech APIs suffer from strict character limits and produce disjointed audio files when processed in chunks. This tool completely automates the heavy lifting: it ingests a massive text file, intelligently tokenizes and splits it into context-aware semantic paragraphs, handles asynchronous batch streaming to the Mistral Voxtral API (using either a cloned voice or a preset profile), and cleanly merges the resulting audio segments into a single, high-fidelity MP3 or M4B file with natural pacing.

## Core functionality
- **Interactive WebUI:** A premium, responsive single-page web interface built with FastAPI, vanilla HTML/CSS/JS, glassmorphism card layouts, real-time progress bar animations, drag-and-drop file uploaders, and an in-browser console terminal streaming live logs via Server-Sent Events (SSE).
- **Interactive TUI:** A modern Terminal User Interface built with Textual for easy parameter configuration and real-time progress monitoring.
- **Zero-Shot Voice Cloning:** Instantly clones any voice profile using a 3-to-10-second reference audio sample (.mp3/.wav) via Mistral's native zero-shot endpoints.
- **Preset Voice Selection:** Support for high-quality built-in Mistral voices (e.g., `en_paul_neutral`, `fr_marie_neutral`) for zero-configuration generation.
- **Intelligent Text Segmentation:** Tokenizes long texts dynamically based on punctuation, sentence boundaries, and character constraints to prevent API truncation without breaking semantic flow.
- **Asynchronous Batching:** Dispatches parallel chunk requests to the Mistral API (`voxtral-mini-tts-2603`) with exponential backoff retry mechanisms.
- **Audio Compiling & Mastering:** Merges independent audio buffers seamlessly using FFmpeg, injecting natural-sounding pause intervals between segments.
- **Progress Persistence:** Maintains a local manifest and cache to resume interrupted generation tasks without repeating successful work.
- **Integrated Translation:** Translates `.txt` and `.srt` source files from a source language to a target language using the **Mistral Large** model (`v1/chat/completions`) prior to TTS, preserving subtitle timecodes and including rate-limit-resilient backoffs.
- **Docker Containerization:** Containerized setup bundling FFmpeg, Python environment, and runtime dependencies for zero-configuration deployments (available on Docker Hub as `marcinlis82/mistral-tts`).

---


## Priorities
- **Audio Continuity:** The final output must sound like a continuous, single-session recording, entirely eliminating abrupt cuts or fluctuating volume baselines.
- **Resource Efficiency:** Leverage stream-to-disk and temporary buffer chunking during compilation to maintain a low RAM footprint.
- **Robust Fault Tolerance:** Network dropouts or single-chunk API errors must not crash the entire book generation process. Failed chunks must automatically retry or cache state for resuming.
- **Developer & User Simplicity:** Maintain a clean codebase and provide intuitive interfaces (CLI/TUI/WebUI) with secure credential management via environment variables (`.env`).

---

## Architecture

### Structure
mistral-tts/
├── ai_light/
│   ├── AGENTS.md              # Project-scoped AI rules
│   └── PROJECT.md             # Project overview and architecture
├── src/
│   ├── api/
│   │   └── mistral_client.py  # Wrapper for Voxtral API (`complete_async`)
│   ├── core/
│   │   ├── audio_compiler.py  # FFmpeg stitching & metadata manipulation
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
│   ├── cache/                 # Temporary storage for single-chunk audio files
│   └── output/                # Destination for compiled audiobooks
├── tests/                     # Automated test suites for core modules & WebUI
│   ├── test_text_splitter.py
│   ├── test_translation.py
│   └── test_web.py
├── .dockerignore              # Files excluded from the Docker build context
├── .env                       # (Local only) Secure storage for MISTRAL_API_KEY
├── .gitignore                 # Files excluded from git tracking
├── Dockerfile                 # Docker configuration for containerized setup
├── LICENSE                    # MIT License file
├── README.md                  # Main project documentation
└── requirements.txt           # Application Python dependencies

### Data flow
[Input Text (.txt/.srt)] ──> [Text Splitter] ──> [Semantic Chunks List]
                                                        │
[Voice Sample / ID]       ──> [Mistral Client]  ──> [Voice Configuration]
                                                        │
[Voice + Chunks]          ──> [Async Dispatch]  ──> [Temporary Chunk Cache (.mp3)]
                                                        │
                                                   [Audio Compiler (FFmpeg)]
                                                        │
                                                        ▼
                                            [Final Audiobook File]
---

## Constraints
- **API Payload Constraints:** Individual text chunks must strictly adhere to Mistral API's payload size limits.
- **Local System Dependencies:** Requires **FFmpeg** installed in the system PATH.
- **SDK Compatibility:** Dependent on `mistralai` SDK version 2.4.9+.

---

## Future Roadmap

- [x] **Integrated Translation:** Direct translation from Language A to Language B using the **Mistral Large** model (`v1/chat/completions`) before the TTS phase.
- [x] **Interactive WebUI:** A responsive web application to configure runs, preview voices, and monitor generation.
- [x] **Docker Containerization:** Containerize the application, bundling FFmpeg and Python dependencies for zero-setup deployments.
- [x] **Basic Authentication Layer:** Secure the WebUI and API endpoints with session cookies for multi-user or network deployments.
- [ ] **OpenID Connect (OIDC) Login:** Integrate authentication based on OpenID Connect (OIDC) provided by a self-hosted Pocket ID instance for single sign-on.
- [ ] **Multi-User Login:** Support multiple user accounts and sessions, paving the way for personalized histories, settings, and task queues.
- [ ] **CLI User Management:** Add command-line interface options to create, update, and manage user accounts securely, keeping user-creation tools out of the WebUI.
- [ ] **Robust Task State Management:** Implement a background cleanup task that runs periodically to evict all tasks older than 24 hours regardless of their state, or transition the global in-memory state tracking to a SQLite database.
- [ ] **EPUB Support:** Ingest and parse EPUB files to extract chapters while preserving document structure.
- [ ] **MOBI Support:** Ingest and parse MOBI files to extract chapters for synthesis.
- [ ] **OpenAI TTS Integration:** Add support for the OpenAI TTS API as an alternative synthesis engine, enabling voice options for languages not natively supported by Mistral (such as Polish).


