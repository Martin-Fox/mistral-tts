# Documentation

Start with the [project overview and Docker quick start](../README.md).
Choose a guide below for the task you need to complete.

## Use the application

| Guide | Covers |
| --- | --- |
| [Installation and usage](USAGE.md) | Source setup, WebUI/TUI/CLI commands, voices, translation models and CLI options |
| [Docker](../DOCKER.md) | Container startup, persistent configuration, storage permissions and startup diagnostics |
| [Windows](WINDOWS.md) | PowerShell setup, packaging, native runner requirements and outstanding acceptance checks |
| [Release notes](RELEASE_NOTES.md) | User-visible changes and compatibility steps for upgrades |
| [Roadmap](ROADMAP.md) | Implemented capabilities and planned work |

## Run and maintain an installation

Use [Operations](OPERATIONS.md) for deployment, TLS/proxies, explicit resume,
retention inspection, backups, upgrades, rollback and credential recovery.
[Deployment security](SECURITY_DEPLOYMENT.md) adds LAN binding, cookie/proxy
configuration and checks of the deployed image identity.

The detailed references explain the contracts behind those procedures:

| Reference | Covers |
| --- | --- |
| [WebUI security](WEB_SECURITY.md) | Password hashes and migration, sessions, request origins, browser headers, login limits and API-key handling |
| [Processing](PROCESSING.md) | Upload/EPUB limits, queue admission, reference decoding, FFmpeg deadlines, API retries and text integrity |
| [Storage](STORAGE.md) | Cache identity and locks, verified output publication, resume checkpoints, retention and disk thresholds |

## Develop and verify changes

| Guide | Covers |
| --- | --- |
| [Architecture](ARCHITECTURE.md) | Module responsibilities, the shared pipeline and custom TTS-client contracts |
| [Project contract](../PROJECT.md) | Product scope, priorities, structure and implementation constraints |
| [Tests and CI](TESTING.md) | Locked test setup, isolated fixtures, Docker/portable smoke and runner requirements |
| [Python dependencies](DEPENDENCIES.md) | Hash-locked installation, paired lock updates and dependency audits |
| [Native dependencies](NATIVE_DEPENDENCIES.md) | FFmpeg source/hash, enabled components, licensing and remaining native risks |

## Audit evidence and release notes

Image digests and release verification summaries live in
[Release notes](RELEASE_NOTES.md). Per the 2026-11-24 decision, dated audit
reports and raw scanner evidence are no longer kept in this repository; the
comparison of the 2026-11-24 re-audit with the previous audits is recorded in
[plans/2026-11-24-audit-comparison.md](plans/2026-11-24-audit-comparison.md).

Design and implementation notes under `plans/` are historical proposals;
implemented behavior and acceptance status belong in the current guides.

## Maintaining these docs

- Write repository documentation, PR titles and PR descriptions in English.
- Keep the root README focused on the overview, one quick start and navigation.
- Update the relevant guide with a behavior change. Keep configuration tables
  and technical contracts in their reference page; link to them from other guides.
- Put version-specific migration notes in release notes. Keep dated audit and
  scanner evidence outside the public repository (private archive); link only
  conclusions and plans from `plans/`. Distinguish implemented behavior from
  pending platform or deployment acceptance.
- When moving a section, update relative links and heading anchors throughout
  the repository. Check links, fenced examples and `git diff --check` before
  publishing documentation changes.
