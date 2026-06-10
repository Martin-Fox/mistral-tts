# Project Overview

An automated, open-source text-to-speech pipeline designed to transform long-form text (articles, books, essays) into seamless audiobooks using the Mistral AI Voxtral TTS API with instant, zero-shot voice cloning and preset voice support.

## What this project does
Mistral-TTS-Booksmith bridges the gap between raw text files and polished, long-form audiobooks. Standard text-to-speech APIs suffer from strict character limits and produce disjointed audio files when processed in chunks. This tool completely automates the heavy lifting: it ingests a massive text file, intelligently tokenizes and splits it into context-aware semantic paragraphs, handles asynchronous batch streaming to the Mistral Voxtral API (using either a cloned voice or a preset profile), and cleanly merges the resulting audio segments into a single, high-fidelity MP3 or M4B file with natural pacing.

## Core functionality
- **Interactive TUI:** A modern Terminal User Interface built with Textual for easy parameter configuration and real-time progress monitoring.
- **Zero-Shot Voice Cloning:** Instantly clones any voice profile using a 3-to-10-second reference audio sample (.mp3/.wav) via Mistral's native zero-shot endpoints.
- **Preset Voice Selection:** Support for high-quality built-in Mistral voices (e.g., `en_paul_neutral`, `en_sarah_expressive`) for zero-configuration generation.
- **Intelligent Text Segmentation:** Tokenizes long texts dynamically based on punctuation, sentence boundaries, and character constraints to prevent API truncation without breaking semantic flow.
- **Asynchronous Batching:** Dispatches parallel chunk requests to the Mistral API (`voxtral-mini-tts-2603`) with exponential backoff retry mechanisms.
- **Audio Compiling & Mastering:** Merges independent audio buffers seamlessly using FFmpeg, injecting natural-sounding pause intervals between segments.
- **Progress Persistence:** Maintains a local manifest and cache to resume interrupted generation tasks without repeating successful work.

## 🚀 Future Roadmap
- **Integrated Translation:** Direct translation from Language A to Language B using the **Mistral Large** model (`v1/chat/completions`) before the TTS phase.

---

## Priorities
- **Audio Continuity:** The final output must sound like a continuous, single-session recording, entirely eliminating abrupt cuts or fluctuating volume baselines.
- **Resource Efficiency:** Leverage stream-to-disk and temporary buffer chunking during compilation to maintain a low RAM footprint.
- **Robust Fault Tolerance:** Network dropouts or single-chunk API errors must not crash the entire book generation process. Failed chunks must automatically retry or cache state for resuming.
- **Developer & User Simplicity:** Maintain a clean codebase and provide intuitive interfaces (CLI/TUI) with secure credential management via environment variables (`.env`).

---

## Architecture

### Structure
mistral-tts-booksmith/
├── src/
│   ├── core/
│   │   ├── text_splitter.py   # Semantic chunking logic
│   │   └── audio_compiler.py  # FFmpeg stitching & metadata manipulation
│   ├── api/
│   │   └── mistral_client.py  # Wrapper for Voxtral API (`complete_async`)
│   ├── tui.py                 # Interactive Terminal UI (Textual)
│   └── cli.py                 # Primary entry point & Standard CLI
├── storage/
│   ├── cache/                 # Temporary storage for single-chunk audio files
│   └── output/                # Destination for compiled audiobooks
├── .env                       # (Local only) Secure storage for MISTRAL_API_KEY
├── README.md                  # Project documentation
└── requirements.txt

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
