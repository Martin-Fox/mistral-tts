# Mistral-TTS-Booksmith

An automated, open-source text-to-speech pipeline designed to transform long-form text (articles, books, essays) into seamless audiobooks using the Mistral AI Voxtral TTS API with instant, zero-shot voice cloning.

## 🚀 Features

- **Zero-Shot Voice Cloning:** Instantly clones any voice profile using a 3-to-10-second reference audio sample.
- **Intelligent Text Segmentation:** Tokenizes long texts based on punctuation and character constraints to preserve semantic flow.
- **Asynchronous Batching:** Dispatches parallel requests with exponential backoff for maximum throughput.
- **Progress Persistence:** Tracks generation state via a local manifest, allowing you to resume if interrupted.
- **Polished CLI:** Beautiful terminal UI with progress bars and status indicators.

## 🛠️ Installation

### Prerequisites

- **Python 3.11+**
- **FFmpeg:** Must be installed and available in your system PATH.

### Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/your-repo/mistral-tts-booksmith.git
   cd mistral-tts-booksmith
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## 📖 Usage

The primary function of Mistral-TTS-Booksmith is to convert a text file (.txt or .srt) into a high-fidelity MP3 audiobook.

### Basic Command

```bash
python3 src/cli.py --text <path_to_text_file> \
                   --voice <path_to_voice_sample> \
                   --output <output_path.mp3> \
                   --api-key <your_mistral_api_key>
```

### Parameters

| Flag | Description |
| --- | --- |
| `--text` | Path to the source `.txt` or `.srt` file. |
| `--voice` | Path to a short `.mp3` or `.wav` sample of the voice you want to clone. |
| `--output` | The destination path for the final `.mp3` file. |
| `--api-key` | Your Mistral AI API key (Voxtral access required). |

### Example

```bash
python3 src/cli.py --text examples/essay.txt \
                   --voice voices/reference.mp3 \
                   --output output/audiobook.mp3 \
                   --api-key your_api_key_here
```

## 🏗️ Architecture

- **`src/core/text_splitter.py`**: Handles semantic chunking logic.
- **`src/api/mistral_client.py`**: Wrapper for Voxtral API interaction and cloning.
- **`src/core/audio_compiler.py`**: FFmpeg-based stitching and metadata manipulation.
- **`src/cli.py`**: Primary command-line interface entry point.

## ⚙️ State Persistence

Mistral-TTS-Booksmith automatically caches generated audio chunks in `storage/cache/` and maintains a `manifest.json`. If a run fails or is stopped, simply run the same command again; the tool will skip completed chunks and resume from where it left off.

## ⚖️ License

MIT License - see [LICENSE](LICENSE) for details.
