# Mistral-TTS Docker Image Overview

This repository contains the containerized version of **Mistral-TTS**, a text-to-speech pipeline designed to convert long-form text (articles, books, essays) into seamless audiobooks. It integrates the **Mistral AI Voxtral TTS** API (with zero-shot voice cloning), **OpenAI TTS** as an alternative engine, **Mistral Large** for pre-translation, and support for EPUB, MOBI, SRT, and TXT ingestion.

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
  -e APP_USERNAME=admin \
  -e APP_PASSWORD=admin_secure_password \
  --name mistral-tts \
  marcinlis82/mistral-tts:0.9
```

Once running, access the WebUI at **`http://localhost:8000`**.
*Note: If `APP_USERNAME` and `APP_PASSWORD` are omitted, they default to `admin` / `admin` respectively.*

### 2. Run the Interactive TUI
To run the terminal configuration and progress tracking interface inside the container, run with interactive terminal flags (`-it`):

```bash
docker run -it --rm \
  -v $(pwd)/storage:/app/storage \
  -e MISTRAL_API_KEY=your_mistral_api_key_here \
  -e OPENAI_API_KEY=your_openai_api_key_here \
  marcinlis82/mistral-tts:0.9 \
  python src/cli.py --tui
```

### 3. Run via Headless CLI
For automated script integrations, execute the CLI directly:

```bash
docker run --rm \
  -v $(pwd)/storage:/app/storage \
  -e MISTRAL_API_KEY=your_mistral_api_key_here \
  marcinlis82/mistral-tts:0.9 \
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
| `APP_USERNAME` | Custom username for WebUI cookie authentication (default: `admin`). |
| `APP_PASSWORD` | Custom password for WebUI cookie authentication (default: `admin`). |

---

## 🌟 Key Features

* **Dual Engine Support:** Switch seamlessly between Mistral Voxtral (with instant cloning) and OpenAI TTS (presets: alloy, echo, fable, onyx, nova, shimmer) for global language support.
* **Integrated Translation:** Automatic language-to-language translation using Mistral Large prior to speech synthesis.
* **Format Ingestion:** Parsers for `.txt`, `.srt` (retains timecodes), `.epub`, and unencrypted `.mobi` ebooks.
* **Persistent SQLite States:** Task state, progress, and logs are tracked in a SQLite database (`storage/state.db`) to survive container restarts.
* **Automated Cleanup:** Built-in purger evicts completed and failed task histories older than 24 hours.

---

## 🔗 Project Links

* **Primary Repository & Source of Truth:** [Gitea Instance](https://gitea.marcin-lis.pl/fox/mistral-tts)
* **Public Mirror (Feedback, Comments, Issues & PRs):** [GitHub Mirror](https://github.com/Martin-Fox/mistral-tts)
