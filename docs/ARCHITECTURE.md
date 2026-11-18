# Architecture and extension contracts

[Documentation](README.md) · [Project overview](../README.md)

## Modules

- **`src/tui.py`**: The interactive Terminal UI built with Textual.
- **`src/web.py`**: FastAPI web server hosting API endpoints and background synthesis tasks.
- **`src/web/static/`**: Contains HTML, CSS, and JS assets for the Single-Page Web application.
- **`src/core/config.py`**: Environment management and persistent `.env` synchronization for runtime configuration.
- **`src/core/pipeline.py`**: Shared ordered text preparation, cache-backed generation and verified compilation.
- **`src/core/audio_cache.py` / `cache_io.py`**: Matching segment manifests, cross-process locks and atomic publication.
- **`src/core/task_db.py` / `task_store.py`**: WebUI state, private resume inputs and translation checkpoints.
- **`src/core/storage_retention.py`**: State-aware maintenance and soft disk-budget checks.
- **`src/core/text_splitter.py`**: Handles semantic chunking logic.
- **`src/api/mistral_client.py`**: Wrapper for Voxtral API interaction, voice cloning, and text translation.
- **`src/core/audio_compiler.py`**: FFmpeg-based stitching, pause/trailing silence injection, loudness normalization (`loudnorm`), and duration verification.
- **`src/cli.py`**: Primary command-line interface entry point.

## Pipeline service and interface adapters

`src/core/pipeline.py` provides shared text preparation and audiobook generation.
`prepare_text` reads input with the selected encoding, invokes an optional async
translation adapter, reads translated UTF-8 text and splits it in source order.
It freezes the effective translation model for the prepared job. `run_pipeline`
configures a preset/reference voice, builds the existing cache identity, generates
or reuses ordered segments and runs verified compilation under the cache lock.

The service accepts synchronous progress callbacks, a cache-ready callback,
an injected TTS client and a compiler factory. Callbacks run on the caller's event
loop; callback errors propagate and stop the operation. Compilation stays in its
cancellation-aware worker thread, retaining the cache lock until that worker has
stopped. Results include the output path, cache directory, segment count and
compiler verification metadata. The service imports neither FastAPI/Textual nor
the provider SDKs; provider clients are supplied by the adapters.

CLI owns Rich output and exit codes. TUI owns widgets, progress and voice/model
error assistance. WebUI owns uploads, task state, UUID output names, durable
input/translation checkpoints and temporary-input cleanup. Translation adapters
keep those persistence differences explicit: CLI/TUI resubmission can still repeat
translation, while WebUI resume reuses its saved results. Cache keys, manifests,
API retry/deadline policy and output publication rules are unchanged by this
extraction; there is no cache or task-snapshot migration for P18.

Custom TTS clients must implement `BaseTTSClient.set_voice_id` alongside audio
generation, voice listing and cloning. Preset selection clears a previous
reference on reference-capable clients. Mistral supports reference input; OpenAI
rejects cloning and uses preset voices. API credentials remain in runtime clients
and adapter closures, outside prepared text, progress events and pipeline results.
