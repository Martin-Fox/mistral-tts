# Mistral-TTS

Turn long texts and ebooks into audiobooks with Mistral Voxtral or OpenAI TTS.
Use the browser interface, terminal UI or CLI, with optional Mistral translation
before speech generation.

The primary repository is [Gitea](https://gitea.marcin-lis.pl/fox/mistral-tts).
The [GitHub mirror](https://github.com/Martin-Fox/mistral-tts) also accepts issues,
feedback and pull requests.

## Features

- **WebUI, TUI and CLI** for generation, progress and audio playback/download.
- **Mistral reference voices and presets**, plus six OpenAI preset voices.
- **TXT, SRT and EPUB input**, with optional translation before synthesis.
  MOBI is supported only for trusted local CLI/TUI files.
- **Ordered audio compilation** with loudness normalization, trailing padding
  and decoded-duration checks to detect truncation.
- **Persistent WebUI jobs and explicit resume**, plus shared audio caching
  across interfaces. Resume may still repeat provider work and incur charges.
- **Docker distribution** with Python, FFmpeg and ffprobe included.

Windows packaging is implemented; native executable acceptance remains pending.
See [Windows setup and acceptance](docs/WINDOWS.md).

## Quick start with Docker

The versioned release is `marcinlis82/mistral-tts:1.0.5` for **linux/amd64**.
Create a private `.env` file in the directory from which you run Docker:

```dotenv
APP_USERNAME=admin
APP_PASSWORD=replace-with-a-unique-long-password
MISTRAL_API_KEY=your-mistral-api-key
# Set this instead of, or alongside, Mistral for OpenAI TTS:
# OPENAI_API_KEY=your-openai-api-key
```

Use a unique password of **12–1024 characters**, with at least 12 after trimming.
Only configure the provider keys you need; translation always requires Mistral.
Protect the file from other users and do not commit it.

```bash
docker pull marcinlis82/mistral-tts:1.0.5
mkdir -p storage
docker run -d \
  -p 127.0.0.1:8000:8000 \
  -v "$PWD/storage:/app/storage" \
  --env-file "$PWD/.env" \
  --name mistral-tts \
  marcinlis82/mistral-tts:1.0.5
```

Open **http://localhost:8000** and sign in. Storage survives container replacement.
Keep one WebUI worker/replica. For access from another machine, configure binding,
TLS and trusted proxies using the [deployment guide](docs/SECURITY_DEPLOYMENT.md).

Prefer a source installation? Start with [Installation and usage](docs/USAGE.md)
for Python setup, WebUI/TUI/CLI commands, voices, translation and CLI options.
Container commands and persistent configuration are in [DOCKER.md](DOCKER.md).

## Documentation

| What you want to do | Read |
| --- | --- |
| Install from source or use WebUI/TUI/CLI | [Installation and usage](docs/USAGE.md) |
| Run or configure the container | [Docker guide](DOCKER.md) |
| Deploy, back up, upgrade or recover jobs | [Operations](docs/OPERATIONS.md) |
| Configure login, HTTP clients or browser security | [WebUI security](docs/WEB_SECURITY.md) |
| Set upload, decoding or API retry limits | [Processing reference](docs/PROCESSING.md) |
| Understand cache, resume and retention | [Storage reference](docs/STORAGE.md) |
| Run tests or update dependencies | [Tests and CI](docs/TESTING.md) · [Dependencies](docs/DEPENDENCIES.md) |

The [documentation index](docs/README.md) also covers architecture, native
libraries, Windows acceptance, release history, audits and planned work.

## Upgrading and release status

Stop the old instance and back up **all of `storage/`** before upgrading.
Review [1.0.5 changes](docs/RELEASE_NOTES.md#security-audit-remediation--105)
for the audit-remediation changes, then follow the
[upgrade procedure](docs/OPERATIONS.md#upgrade-and-rollback).

The [1.0.5 release notes](docs/RELEASE_NOTES.md#security-audit-remediation--105)
record the verified image digest and tests. Offline tests do not establish
provider access or output quality; native Windows acceptance and some security
work remain open.

## License

MIT — see [LICENSE](LICENSE). Bundled native tools have their own licenses;
see [Native dependencies](docs/NATIVE_DEPENDENCIES.md).
