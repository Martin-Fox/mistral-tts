# Installation and usage

[Documentation](README.md) · [Project overview](../README.md)

On this page:

- [Installation](#installation)
- [Interfaces](#interfaces)
- [Configured provider models](#configured-provider-models)

## Installation

### Prerequisites

- **CPython 3.11:** the version exercised by CI and the current dependency locks. Other Python versions require separate verification.
- **FFmpeg and ffprobe:** Both executables must be available in PATH. Linux
  reference-audio cloning also requires util-linux `prlimit`; see
  [reference decoding and platform limits](PROCESSING.md#ffmpegffprobe-budgets-and-voice-preprocessing).

### Setup

1. Clone the repository:
   ```bash
   git clone https://gitea.marcin-lis.pl/fox/mistral-tts.git
   cd mistral-tts
   ```

2. Install dependencies:
   ```bash
   python -m pip install --require-hashes --only-binary=:all: -r requirements.txt
   ```

   Use an isolated Python environment. This installs runtime dependencies only;
   development tools and the lock update procedure are described in
   [Dependency management](DEPENDENCIES.md).

3. Configure the selected provider and WebUI credentials:
   Create a private `.env` file in the root directory (or supply process environment variables). WebUI requires a unique password before startup; CLI/TUI require the keys for the selected operations:
   ```bash
   MISTRAL_API_KEY=your_mistral_api_key_here
   OPENAI_API_KEY=your_openai_api_key_here

   # Translation model (defaults to ministral-8b-latest if omitted)
   MISTRAL_TRANSLATION_MODEL=ministral-8b-latest

   # WebUI login credentials (required before first start)
   APP_USERNAME=admin
   APP_PASSWORD=replace-with-a-unique-password
   ```

## Interfaces

### Windows desktop packaging

The launcher, `mistral-tts.spec` and `.gitea/workflows/build-windows.yml` are
implemented. The intended artifact is `mistral-tts-windows-x64.zip`; a successful
native build and clean-Windows artifact smoke are still required before treating
it as a verified portable release. See [Windows acceptance](WINDOWS.md).

For a built artifact, extract into a writable directory and configure a private
`.env` beside the executable with a unique `APP_PASSWORD` before launching
`mistral-tts.exe` or `run.bat`. The default password is refused before WebUI
startup. Configure provider keys in that file or, after login, in WebUI. The
launcher selects a local port and opens the browser. Storage is kept beside the
executable; assets/binaries are read from their bundled locations.

### Running the WebUI (Python)

To launch the WebUI:

```bash
python3 -m uvicorn src.web:app --host 127.0.0.1 --port 8000 --workers 1 --no-proxy-headers
```

Run from the checkout, then open `http://localhost:8000`. Keep one worker;
`--reload` is a development option and interrupts jobs on code changes.
For remote access, configure HTTPS and trusted proxy forwarding as described in
[Operations](OPERATIONS.md#network-access-and-tls).

* **Required credentials:** Before starting the WebUI, set `APP_PASSWORD` to a unique phrase of 12-1024 characters in your environment or `.env`; `APP_USERNAME` defaults to `admin`. Without an existing auth file, shorter credentials prevent startup, including on localhost. Persisted credentials take precedence; legacy short passwords permit a change-only login. Empty/default `admin` credentials remain rejected. See [credential recovery](OPERATIONS.md#credential-recovery). Errors never print the configured password.

### Interactive TUI (Recommended)

The easiest way to use the tool is via the built-in Terminal UI:

```bash
python3 -m src.cli --tui
```

### Standard CLI

For automated workflows, you can use the traditional CLI:

```bash
python3 -m src.cli --text "book.txt" \
                   --voice "sample.mp3" \
                   --output "audiobook.mp3"
```

*Configure `MISTRAL_API_KEY` in your environment or private dotenv file.
Command-line key flags are supported but can appear in shell history and process listings.*

CLI exit codes: `0` after a successful run (or `--help`), `1` for an execution
error such as a missing input file, failed generation or failed compilation,
and `2` for invalid or missing arguments. Automation should check the exit code
before treating the output as a completed audiobook.

### OpenAI TTS integration

To use the OpenAI TTS integration:

1. **API Configuration:** Configure `OPENAI_API_KEY` in your `.env` file, or supply it as a parameter in the interfaces.
2. **Preset Voices:** This integration exposes six OpenAI preset voices: `alloy`, `echo`, `fable`, `onyx`, `nova`, and `shimmer`. Reference-audio cloning is not implemented for this engine.
3. **WebUI Usage:** Select **OpenAI TTS** as the *TTS Engine*. The WebUI dynamically hides the voice cloning section and switches preset options to the OpenAI voices.
4. **TUI Usage:** Set the *TTS Engine* dropdown to **OpenAI**. The dropdown for *Default Voice* will populate with OpenAI voices, and inputs for cloning and manual voice IDs will be disabled.
5. **CLI Usage:** Include the `--engine openai` parameter and specify one of the 6 preset voices in the `--voice` argument:
   ```bash
   python3 -m src.cli --text book.txt \
                      --engine openai \
                      --voice alloy \
                      --output audiobook.mp3
   ```
   *Note: Passing a file path to `--voice` when running with `--engine openai` will trigger a validation error.*

### Translation model configuration

When `--target-lang` is specified, the pipeline translates the input text via the Mistral Chat API prior to audio synthesis. The configured default is `ministral-8b-latest`; model availability, pricing and account permissions must be checked with the provider. This default does not guarantee access or prevent HTTP 403 errors.

See [Configured provider models](#configured-provider-models) for the models this code selects.

#### Configured translation models

| Configured model ID | Display name |
| --- | --- |
| `ministral-8b-latest` | Ministral 8B (default) |
| `ministral-3b-latest` | Ministral 3B |
| `mistral-small-latest` | Mistral Small |
| `mistral-medium-latest` | Mistral Medium |
| `mistral-large-latest` | Mistral Large |

These are interface choices, not an account-access or translation-quality guarantee.

`mistral-large-latest` is a reasoning model: it spends time in a thinking phase
before answering, so a translation request can take noticeably longer than with
the other models — often more than the default 60-second per-request timeout
(`API_REQUEST_TIMEOUT_SECONDS`). If translation with this model fails with
`TimeoutError` / `API retry budget exhausted`, raise the retry settings in the
environment, for example in `docker-compose.yml`:

```yaml
environment:
  - MISTRAL_API_KEY=...
  - API_REQUEST_TIMEOUT_SECONDS=300
  - API_RETRY_BUDGET_SECONDS=900
```

See [API retries and deadlines](PROCESSING.md#api-retries-and-deadlines) for the
full description of these variables. Responses from reasoning models arrive as
chunked content (thinking + text); the client extracts the text chunks
automatically.

#### Changing the model

- **WebUI:** Expand **Translation Settings** and select the desired model from the **Translation Model** dropdown. The selection is automatically sent to `POST /api/config` and saved to the selected dotenv file without requiring a backend restart. See [configuration precedence](OPERATIONS.md#supported-operating-model-and-configuration).
- **TUI:** Choose your preferred model in the **Trans Model** dropdown selector. Selection is saved to the selected dotenv file and takes effect for subsequent generation runs in that process.
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

### Testing

See [Tests and CI](TESTING.md) for the locked development setup, isolated
offline tests, Docker smoke and portable checks.

## Configured provider models

| Operation | Model selected by the application | Credentials |
| --- | --- | --- |
| Mistral TTS | `voxtral-mini-tts-2603` | `MISTRAL_API_KEY` |
| OpenAI TTS | `tts-1` | `OPENAI_API_KEY` |
| Translation with either TTS engine | `MISTRAL_TRANSLATION_MODEL`, default `ministral-8b-latest` | `MISTRAL_API_KEY` |

CLI/WebUI/TUI do not expose a TTS-model selector. The OpenAI adapter provides
preset voices and rejects reference audio; the Mistral adapter supports presets
and reference preprocessing. Translation remains a Mistral operation even when
OpenAI produces the audio. Provider model access, quotas, languages, pricing and
output quality are not established by offline tests. Check them for your account
before submitting a book. Authentication/permission failures are not retried;
see [API retries and deadlines](PROCESSING.md#api-retries-and-deadlines).
