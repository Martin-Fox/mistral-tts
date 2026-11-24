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

## Audit and release evidence

Dated reports record what was checked at a particular revision or release.
They do not replace the current guides or establish the state of a running
installation.

- [1.0.5 image verification and digest](audit/RELEASE_1.0.5_2026-11-24.md).
- [1.0.4 image verification and digest](audit/RELEASE_1.0.4_2026-11-18.md).
- [November 2026 security audit](audit/SECURITY_AUDIT_2026-11-18.md), followed by
  [media/dependency remediation](audit/SECURITY_REMEDIATION_2_3_2026-11-18.md),
  [authentication/XML remediation](audit/SECURITY_REMEDIATION_5_2026-11-18.md)
  and [SDK/native updates](audit/SECURITY_DEPENDENCY_UPDATES_2026-11-18.md).
- [Earlier repository audit](audit/AUDIT_REPORT.md) and its
  [remediation plan](audit/REFACTORING_PLAN.md).

Design and implementation notes under `plans/` are historical proposals;
implemented behavior and acceptance status belong in the current guides.

## Maintaining these docs

- Write repository documentation, PR titles and PR descriptions in English.
- Keep the root README focused on the overview, one quick start and navigation.
- Update the relevant guide with a behavior change. Keep configuration tables
  and technical contracts in their reference page; link to them from other guides.
- Put version-specific migration notes in release notes and dated test/CVE
  evidence in audit reports. Distinguish implemented behavior from pending
  platform or deployment acceptance.
- When moving a section, update relative links and heading anchors throughout
  the repository. Check links, fenced examples and `git diff --check` before
  publishing documentation changes.
