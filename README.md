# Mistral-TTS

> [!NOTE]
> **Repository Setup & Contributions:** The primary development repository and source of truth for this project is hosted on our [Gitea Instance](https://gitea.marcin-lis.pl/fox/mistral-tts). A public mirror is available on [GitHub](https://github.com/Martin-Fox/mistral-tts), which you are warmly invited to use for submitting issues, creating pull requests, or leaving comments and feedback.

An automated, open-source text-to-speech pipeline designed to transform long-form text (articles, books, essays) into seamless audiobooks using the Mistral AI Voxtral TTS API with instant, zero-shot voice cloning.

## 🚀 Features

- **Interactive WebUI:** A premium, responsive single-page web application featuring glassmorphism card layouts, real-time progress bar animations, drag-and-drop file uploaders, an in-browser console terminal streaming live server logs via Server-Sent Events (SSE), and a custom audio player for instant playback.
- **Interactive TUI:** A modern terminal interface for easy configuration and progress monitoring.
- **Integrated Translation:** Translate source files from a source language to a target language using the **Mistral Large** model (`v1/chat/completions`) before the TTS phase. Supports rate-limit-aware retries and preserves subtitle timecodes.
- **Multi-Format Ingestion:** Direct support for plain text (`.txt`), subtitles (`.srt`), and electronic books (`.epub` and unencrypted `.mobi`), automatically extracting content in the correct reading order.


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

   # WebUI login credentials (defaults to admin/admin if not set)
   APP_USERNAME=admin
   APP_PASSWORD=admin
   ```

## 📖 Usage

### Running the WebUI

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

### Running Tests

To run the automated test suite and verify the integrity of core modules, the translation pipeline, and the WebUI backend:

```bash
PYTHONPATH=. pytest
```

## 🏗️ Architecture

- **`src/tui.py`**: The interactive Terminal UI built with Textual.
- **`src/web.py`**: FastAPI web server hosting API endpoints and background synthesis tasks.
- **`src/web/static/`**: Contains HTML, CSS, and JS assets for the Single-Page Web application.
- **`src/core/text_splitter.py`**: Handles semantic chunking logic.
- **`src/api/mistral_client.py`**: Wrapper for Voxtral API interaction and cloning.
- **`src/core/audio_compiler.py`**: FFmpeg-based stitching and metadata manipulation.
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

- [x] **Integrated Translation:** Direct translation from Language A to Language B using the **Mistral Large** model (`v1/chat/completions`) before the TTS phase.
- [x] **Interactive WebUI:** A responsive web application to configure runs, preview voices, and monitor generation.
- [x] **Docker Containerization:** Containerize the application, bundling FFmpeg and Python dependencies for zero-setup deployments.
- [x] **Basic Authentication Layer:** Secure the WebUI and API endpoints with session cookies for multi-user or network deployments.
- [ ] **OpenID Connect (OIDC) Login:** Integrate authentication based on OpenID Connect (OIDC) provided by a self-hosted Pocket ID instance for single sign-on.
- [ ] **Multi-User Login:** Support multiple user accounts and sessions, paving the way for personalized histories, settings, and task queues.
- [ ] **CLI User Management:** Add command-line interface options to create, update, and manage user accounts securely, keeping user-creation tools out of the WebUI.
- [x] **Robust Task State Management:** Implement a background cleanup task that runs periodically to evict all tasks older than 24 hours regardless of their state, or transition the global in-memory state tracking to a SQLite database.
- [x] **EPUB Support:** Ingest and parse EPUB files to extract chapters while preserving document structure.
- [x] **MOBI Support:** Ingest and parse MOBI files to extract chapters for synthesis.
- [x] **OpenAI TTS Integration:** Add support for the OpenAI TTS API as an alternative synthesis engine, enabling voice options for languages not natively supported by Mistral (such as Polish).



## ⚖️ License

MIT License - see [LICENSE](LICENSE) for details.

