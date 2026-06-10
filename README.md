# Mistral-TTS-Booksmith

An automated, open-source text-to-speech pipeline designed to transform long-form text (articles, books, essays) into seamless audiobooks using the Mistral AI Voxtral TTS API with instant, zero-shot voice cloning.

## 🚀 Features

- **Interactive TUI:** A modern terminal interface for easy configuration and progress monitoring.
- **Zero-Shot Voice Cloning:** Instantly clones any voice profile using a 3-to-10-second reference audio sample.
- **Preset Voice Selection:** Choose from high-quality default Mistral voices (e.g., Paul, Sarah) without needing a sample.
- **Intelligent Text Segmentation:** Tokenizes long texts based on punctuation and character constraints to preserve semantic flow.
- **Asynchronous Batching:** Dispatches parallel requests with exponential backoff for maximum throughput.
- **Progress Persistence:** Tracks generation state via a local manifest, allowing you to resume if interrupted.
- **Environment Support:** Securely store your API key in a `.env` file.

## 🚀 Current focus

We are working towards making Mistral-TTS-Booksmith a truly global audiobook creator. Our next major milestone is:
- **Direct Translation:** Integrate translation from Language A to Language B using the **Mistral Large** model (`v1/chat/completions`). This will allow you to ingest a book in one language and generate the audiobook in another, all within a single pipeline.

## 🛠️ Installation

### Prerequisites

- **Python 3.11+**
- **FFmpeg:** Must be installed and available in your system PATH.

### Setup

1. Clone the repository:
   ```bash
   git clone https://gitea.marcin-lis.pl/fox/mistral-tts-booksmith.git
   cd mistral-tts-booksmith
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. (Optional) Configure your API Key:
   Create a `.env` file in the root directory:
   ```bash
   MISTRAL_API_KEY=your_mistral_api_key_here
   ```

## 📖 Usage

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

### Parameters

| Flag | Description |
| --- | --- |
| `--tui` | Launches the interactive Terminal User Interface. |
| `--text` | Path to the source `.txt` or `.srt` file. |
| `--voice` | Path to a short `.mp3` or `.wav` sample for cloning. |
| `--output` | The destination path for the final `.mp3` file. |
| `--api-key` | Your Mistral AI API key (overrides `.env`). |

## 🏗️ Architecture

- **`src/tui.py`**: The interactive Terminal UI built with Textual.
- **`src/core/text_splitter.py`**: Handles semantic chunking logic.
- **`src/api/mistral_client.py`**: Wrapper for Voxtral API interaction and cloning.
- **`src/core/audio_compiler.py`**: FFmpeg-based stitching and metadata manipulation.
- **`src/cli.py`**: Primary command-line interface entry point.

## ⚙️ State Persistence

Mistral-TTS-Booksmith automatically caches generated audio chunks in `storage/cache/` and maintains a `manifest.json`. If a run fails or is stopped, simply run the same command again; the tool will skip completed chunks and resume from where it left off.

## ⚖️ License

MIT License - see [LICENSE](LICENSE) for details.
