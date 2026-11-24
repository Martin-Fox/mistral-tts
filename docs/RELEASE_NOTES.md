# Release notes

[Documentation](README.md) · [Project overview](../README.md)

## Security update — 1.0.4

This release includes the November 2026 security audit remediations:

- Requests are authenticated before upload processing and queue admission;
  bounded request sizes, upload deadlines and disabled proxy-header trust by
  default reduce unauthenticated resource consumption and address spoofing.
- State-changing requests require a matching Origin or, for originless clients,
  `X-Requested-With: Booksmith`. Browser responses include CSP, frame protection
  and no-store headers. Interactive Swagger/ReDoc pages are disabled.
- New passwords require 12–1024 characters. Existing short passwords allow only
  password rotation; changing the password revokes all sessions.
- Voice references accept MP3/PCM WAV only, with duration, allocation, process
  and output limits. Normalization failures stop the job without sending the
  original file to the provider. Linux adds `prlimit` resource limits.
- EPUB XML metadata rejects DTD/entities and excessive nesting. WebUI MOBI
  upload/resume is disabled; trusted local CLI/TUI MOBI remains available.
- Both hashed Python locks include Mistral SDK 2.10.1, OpenTelemetry API 1.45.2,
  AnyIO 4.14.2 and python-dotenv 1.2.2. Both locks had zero known findings in
  the 2026-11-18 pip-audit scan.
- Docker builds a hash-pinned audio-only FFmpeg 9.0.2 without libxml2, networking
  or video codecs; runtime installers are removed and zlib has a corrected
  minimum version. Windows packaging separately pins its FFmpeg archive/hash.

Before upgrading, stop the old instance and back up all of `storage/`. Existing
sessions reset on restart. Reference preprocessing version 3 invalidates older
cloned-voice cache/resume identities; resubmission may incur provider charges.
Update custom HTTP clients for the request header above, and configure trusted
proxy forwarding explicitly when terminating HTTPS at a reverse proxy.

Verification before image publication: **651 tests passed** with the new SDK
and locally compiled FFmpeg, plus **223 portable smoke tests** (a subset).
These are offline checks, not native Windows acceptance or a zero-CVE claim for
the image. FFmpeg retains known native risks, including MOV parsing used for
generated M4B verification; decoder limits are not a complete OS sandbox.
See the [audit and remediation record](audit/SECURITY_AUDIT_2026-11-18.md),
[dependency update report](audit/SECURITY_DEPENDENCY_UPDATES_2026-11-18.md),
[native dependency limits](NATIVE_DEPENDENCIES.md) and
[deployment guidance](SECURITY_DEPLOYMENT.md).

The published **linux/amd64** image passed **7 Docker smoke checks**. Its package
scan found **0 Critical** and **0 Python findings**, with **96 remaining OS CVEs**
(including 11 High); compiled FFmpeg also retains separately documented risks.
See the [1.0.4 image verification and digest](audit/RELEASE_1.0.4_2026-11-18.md).
