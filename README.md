# Mistral-TTS

> [!NOTE]
> **Repository Setup & Contributions:** The primary development repository and source of truth for this project is hosted on my [Gitea Instance](https://gitea.marcin-lis.pl/fox/mistral-tts). A public mirror is available on [GitHub](https://github.com/Martin-Fox/mistral-tts), which you are warmly invited to use for submitting issues, creating pull requests, or leaving comments and feedback.

An automated, open-source text-to-speech pipeline designed to transform long-form text (articles, books, essays) into seamless audiobooks using the Mistral AI Voxtral TTS API with instant, zero-shot voice cloning.

## 🚀 Features

- **Interactive WebUI:** A premium, responsive single-page web application featuring glassmorphism card layouts, real-time progress bar animations, drag-and-drop file uploaders, an in-browser console terminal streaming live server logs via Server-Sent Events (SSE), and a custom audio player for instant playback.
- **Interactive TUI:** A modern terminal interface for easy configuration and progress monitoring.
- **Standalone Windows Executable:** Zero-setup portable Windows desktop distribution (`mistral-tts-windows-x64.zip`) bundling the executable, web assets, and embedded FFmpeg/FFprobe binaries—no Python, Docker, or manual PATH setup required.
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
   pip install -r requirements.txt
   ```

3. (Optional) Configure environment variables:
   Create a `.env` file in the root directory to set your API Keys and optional WebUI credentials:
   ```bash
   MISTRAL_API_KEY=your_mistral_api_key_here
   OPENAI_API_KEY=your_openai_api_key_here

   # Translation model (defaults to ministral-8b-latest if omitted)
   MISTRAL_TRANSLATION_MODEL=ministral-8b-latest

   # WebUI login credentials (defaults to admin/admin if not set)
   APP_USERNAME=admin
   APP_PASSWORD=admin
   ```

## 📖 Usage

### 🖥️ Standalone Windows Executable (Zero Setup)

For Windows users who prefer a zero-dependency setup without installing Python, Git, or FFmpeg:

1. **Download:** Get the latest portable release archive `mistral-tts-windows-x64.zip` from [Releases](https://gitea.marcin-lis.pl/fox/mistral-tts/releases) or CI build artifacts.
2. **Extract:** Unpack the zip archive into any directory of your choice.
3. **Launch:** Run `mistral-tts.exe` or `run.bat`.
   - The launcher will detect an open port (starting at `8000`), boot the backend server with bundled static assets and embedded FFmpeg/FFprobe binaries, and automatically open the WebUI in your default browser.
   - Configure your API keys directly in the WebUI or via a `.env` file placed next to `mistral-tts.exe`.

### Running the WebUI (Python)

To launch the WebUI:

```bash
python3 -m uvicorn src.web:app --reload
```

Once running, open `http://localhost:8000` in your web browser.

* **Default Credentials:** If you do not specify `APP_USERNAME` and `APP_PASSWORD` in your `.env` file, the WebUI defaults to the username `admin` and password `admin`. It is recommended to change these credentials in your `.env` file before exposing the interface to a network.


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

To run the automated test suite and verify the integrity of core modules, the translation pipeline, and the WebUI backend:

```bash
PYTHONPATH=. pytest
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
*Note: If `APP_USERNAME` and `APP_PASSWORD` are not specified, they will default to `admin` and `admin` respectively. The `MISTRAL_API_KEY` and `OPENAI_API_KEY` environment variables configure the backend clients for the respective engines.*


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
- [x] **Robust Task State Management:** Implement a background cleanup task that runs periodically to evict all tasks older than 24 hours regardless of their state, or transition the global in-memory state tracking to a SQLite database.
- [x] **EPUB Support:** Ingest and parse EPUB files to extract chapters while preserving document structure.
- [x] **MOBI Support:** Ingest and parse MOBI files to extract chapters for synthesis.
- [x] **OpenAI TTS Integration:** Add support for the OpenAI TTS API as an alternative synthesis engine, enabling voice options for languages not natively supported by Mistral (such as Polish).
- [x] **Audio Truncation Safeguard & Duration Verification:** Enforce end-to-end duration verification and trailing silence padding.
- [x] **Standalone Windows Portable Executable (PyInstaller + FFmpeg bundle):** Bundled Windows executable and Gitea Actions CI pipeline creating zero-setup desktop zip packages.



## ⚖️ License

MIT License - see [LICENSE](LICENSE) for details.

