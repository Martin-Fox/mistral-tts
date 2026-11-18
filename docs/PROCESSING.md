# Input processing, limits and API retries

[Documentation](README.md) · [Project overview](../README.md)

On this page:

- [Resource limits and generation admission](#resource-limits-and-generation-admission)
- [FFmpeg/ffprobe budgets and voice preprocessing](#ffmpegffprobe-budgets-and-voice-preprocessing)
- [API retries and deadlines](#api-retries-and-deadlines)
- [Input text integrity and translation limits](#input-text-integrity-and-translation-limits)

## Resource limits and generation admission

The WebUI rejects oversized generation requests with HTTP `413` before creating
a task or calling an API. The complete request is bounded before form parsing,
including chunked bodies or understated Content-Length; it is spooled to disk
above 1 MiB. Individual uploads are read in bounded chunks. Uploaded text/ebooks
are parsed in preflight so oversized extracted text/EPUB is rejected before work
is queued. Limits reject content; they never silently truncate an audiobook.

Configure positive integer limits through environment variables (byte budgets
are in bytes, character budgets in Python Unicode characters):

| Variable | Default | Scope |
| --- | --- | --- |
| `MAX_REQUEST_BYTES` | 33554432 (32 MiB) | Complete WebUI generation body, including multipart overhead |
| `MAX_JSON_REQUEST_BYTES` | 65536 (64 KiB) | All other HTTP request bodies, including login, password changes and configuration (also forms) |
| `REQUEST_BODY_TIMEOUT_SECONDS` | 120 | Total time to receive a complete request body |
| `REQUEST_BODY_IDLE_TIMEOUT_SECONDS` | 15 | Maximum wait for the next request-body chunk |
| `MAX_TEXT_UPLOAD_BYTES` | 10485760 (10 MiB) | WebUI text/ebook upload and local input file reads |
| `MAX_VOICE_UPLOAD_BYTES` | 20971520 (20 MiB) | WebUI voice reference upload |
| `MAX_VOICE_SECONDS` | 30 | Maximum accepted duration of a voice reference |
| `MAX_VOICE_PROCESS_MEMORY_BYTES` | 536870912 (512 MiB) | Linux reference-decoder address-space limit, including shared libraries |
| `MAX_TEXT_CHARS` | 2000000 | Input/extracted text and completed translation |
| `MAX_EPUB_BYTES` | 67108864 (64 MiB) | Sum of ZIP uncompressed sizes and cumulative actual EPUB reads |
| `MAX_EPUB_ENTRY_BYTES` | 8388608 (8 MiB) | One EPUB element, including XML metadata |
| `MAX_EPUB_ENTRIES` | 10000 | EPUB ZIP entry count |
| `MAX_EPUB_XML_DEPTH` | 64 | Maximum nesting depth in container/OPF XML metadata |
| `MAX_EPUB_XML_ELEMENTS` | 10000 | Maximum elements in each metadata XML document |
| `MAX_RUNNING_JOBS` | 2 | Running WebUI pipelines, including cache waits and compilation |
| `MAX_QUEUED_JOBS` | 2 | Additional admitted WebUI requests/jobs; zero is allowed |

Restart the WebUI after changing configuration. Invalid limits prevent startup.
The parser also limits multipart uploads to 2 files and forms to 32 fields.
Generation/resume requests require a valid session **before** reading the body,
checking storage or reserving capacity. Anonymous requests receive `401` even
when the queue is full. Sessions are checked again after upload, so expiry or
logout during upload prevents submission. Other request bodies use the smaller
`MAX_JSON_REQUEST_BYTES` budget before JSON/form parsing. Login usernames are
limited to 256 characters, passwords to 1024, and translation model IDs to 100.
The password length bound applies to both login and password changes; existing
usernames/passwords beyond these bounds require operator-assisted replacement.

Slow bodies receive `408` when the total or idle timeout expires. Upload spools
are closed and reserved slots released. These deadlines apply only to body
reception, not queued/running generation or SSE streams. When all running/queued
slots are occupied, new authenticated generation requests receive
HTTP `429` with `Retry-After: 5`, before reading their body. Admission includes
uploads and preflight, so concurrent preflight work is bounded too. Accepted jobs
may remain `Pending` while waiting for a worker. Capacity is released after work,
exceptions, cancellation or client disconnect during upload. This is a bounded
in-process execution queue; restart requires explicit resume from saved inputs.

The concurrency budget applies to this single WebUI process. Independent CLI/TUI
processes do not share that worker budget, but their input parsing uses the same
file/text/EPUB limits. EPUB metadata and actual decompressed reads are checked;
repeated spine reads also consume the decompression budget. WebUI rejects MOBI
uploads and resumes with `415` before extraction or paid work; convert them to
EPUB/TXT. CLI/TUI still accept trusted local MOBI files. That extractor runs in
the application process without hard unpacking quotas and must not be used for
untrusted files. Configure reverse-proxy
request-size and upload-timeout limits as well for network deployments.

EPUB container/OPF XML rejects all DTD declarations before entity processing,
using parser callbacks rather than a byte-pattern scan (including UTF-16).
Metadata trees have the depth/element limits above. Standard HTML/XHTML chapter
doctypes are still handled by HTMLParser without fetching DTDs or expanding
custom XML entities. These application guards do not patch the native Expat
library; keep the runtime's XML libraries updated as part of release maintenance.

See [deployment security](SECURITY_DEPLOYMENT.md) for LAN binding, HTTP/HTTPS
cookie settings, trusted proxies and recording the exact deployed image.

## FFmpeg/ffprobe budgets and voice preprocessing

All application-owned FFmpeg/ffprobe calls now have finite timeouts. Configure
finite positive values through the environment:

| Variable | Default | Meaning |
| --- | --- | --- |
| `AUDIO_PROBE_TIMEOUT_SECONDS` | 30 | Base seconds for metadata/chunk probes and decoded-duration checks |
| `AUDIO_PROCESS_TIMEOUT_SECONDS` | 120 | Base seconds for compilation, silence and denoising |
| `AUDIO_TIMEOUT_FACTOR` | 0.1 | Additional wall-clock seconds per audio second for duration-aware operations |
| `AUDIO_MAX_TIMEOUT_SECONDS` | 7200 | Maximum budget for one process |

Compilation uses the expected segment/pause duration to extend its budget.
Decoded-duration checks use a separately bounded ffprobe metadata hint; if that
hint is unavailable they use the ordinary process budget. Metadata only sizes
the timeout: final completeness is still checked by full FFmpeg decoding with
the existing 4-second tolerance. Invalid timeout settings prevent WebUI startup.

Timeouts stop and reap the direct child. Async cancellation also stops the child;
async/threaded cancellation allows 2 seconds after terminate, then uses kill.
WebUI, CLI and TUI compilation runs outside the event loop. Cancellation keeps
WebUI/CLI/TUI cache locks and compiler workspaces until the compiler thread has stopped. The TUI remains
responsive while compiling; Mistral chunk probing is asynchronous too.

Voice references must have matching `.mp3`/`.wav` contents. The decoder is forced
to MP3 or WAV with an explicit MP3/PCM codec allowlist and `file` protocol only;
playlists, ADX/CAF and compressed WAV codecs are rejected. References normalize
to mono 24 kHz s16 PCM WAV with denoising. Original files are preserved. A decode,
duration or quota failure rejects the reference; no original-file fallback is
sent to the provider. WebUI validates references before creating a task or paid
translation/TTS work, then reprocesses the private original when generation runs.

Reference decoding uses a private temporary working directory and an environment
without application keys/proxy settings. Async process stdout/stderr capture is
limited to 64 KiB each; overflow kills and reaps the process. FFmpeg has a 16 MiB
single-allocation guard, one codec/filter thread, a byte limit and a duration
guard that rejects overlong audio rather than accepting truncation. Linux uses
`prlimit` for a 512 MiB address-space limit, a CPU budget and a hard file-size
limit; install util-linux for local Linux cloning. Absence of `prlimit` fails
closed. Other platforms have the format/allocation/output/time guards, but the
configured total-memory limit is Linux-only. Native Windows acceptance remains
required. These measures do not isolate the filesystem or contain arbitrary
decoder code execution; keep untrusted processing in a restricted service/container.

Reference-preprocessing version **3** and the processed-byte fingerprint identify
the normalized reference. Preset-voice cache identities remain unchanged. Older
cloned-voice cache entries are retained but not reused, and older cloned-voice
resume snapshots are rejected as incompatible; resubmit those jobs deliberately.
This may incur API charges. No existing output is deleted or regenerated on
startup. Cancellation propagates after child and temporary-directory cleanup.

## API retries and deadlines

Mistral TTS, translation (including SRT batches), model/voice listing and OpenAI
TTS share one retry policy. Only network/transport errors, request timeouts and
HTTP `408`, `429`, `5xx` are retried. Other `4xx`, invalid responses, filesystem
errors and local FFmpeg/probe failures do not repeat the paid request. Truncated
text responses are not retried unchanged; SRT may fall back once to individual
cues when its batch response cannot be used. Mistral SDK internal retries are
disabled, avoiding nested attempts.

| Variable | Default | Meaning |
| --- | --- | --- |
| `API_REQUEST_TIMEOUT_SECONDS` | 60 | Maximum duration of one request attempt |
| `API_RETRY_BUDGET_SECONDS` | 180 | Total request/retry/backoff budget for one remote operation |
| `API_RETRY_MAX_DELAY_SECONDS` | 60 | Maximum accepted wait between attempts |

Values must be finite and positive; invalid settings prevent WebUI startup and
client construction. A method's `retry_count` means maximum total attempts:
3 by default for TTS/listing and 5 for translation. The budget is per operation,
not for an entire book. Local processing uses the separate audio budgets.

Backoff doubles from 1 second, or 15 seconds for `429` without usable Retry-After,
with bounded positive jitter. Retry-After accepts seconds or an HTTP date and is
respected as a minimum wait. If it exceeds the configured maximum delay, the
request fails rather than retrying early. If a wait cannot fit the remaining
operation budget, retry stops. Cancellation propagates without another attempt.

Retry logs contain status/type/delay, not response bodies or Authorization values;
provider HTTP errors are surfaced as sanitized status errors. Saved translation
checkpoints still bypass completed remote work. Retrying a network timeout can
repeat work already processed by the provider; exactly-once billing is not
guaranteed. All regression tests use fake clients/responses, without paid calls.

## Input text integrity and translation limits

Plain text and SRT use strict UTF-8 by default. UTF-8, UTF-16 and UTF-32 BOMs
are recognized automatically. For a legacy plain-text file, explicitly set
`INPUT_TEXT_ENCODING=cp1250` (or another Python codec name), or convert it to
UTF-8 before uploading. There is no guessing or silent removal of invalid bytes;
a decode error stops the job. UTF-16 without a BOM needs an explicit byte order,
for example `INPUT_TEXT_ENCODING=utf-16-le`. Uploaded file validation reports an
invalid document before creating a task or calling the provider.

EPUB XML respects its declared encoding; chapter HTML and extracted MOBI HTML
respect BOMs and XML/HTML charset declarations, defaulting to UTF-8. Missing
manifest references, spine IDs or chapter files fail the EPUB import, including
when earlier chapters were readable. A partial book is not accepted as complete.

Resume snapshots freeze the input encoding. Pasted WebUI text and translated
output are always UTF-8, independent of the legacy input encoding setting.
Translations split source text into at most 2500-character fragments, including
long words and subtitle cues. SRT JSON batches also limit the serialized source
payload to 2500 characters and 25 cues while preserving cue indices and timing.
Prompt instructions add overhead; these character limits are conservative source
budgets, not token counts. Empty/non-text results and malformed subtitle lists
are rejected; unusable SRT batches fall back to validated individual cues.

A truncated translation response is discarded. Its source can be split again
(up to four levels, stopping at 64 characters); persistent truncation fails the
job without replacing an existing complete translation. Output is checked against
`MAX_TEXT_CHARS` as fragments arrive and before atomic publication. Splitting and
SRT fallback can incur additional provider requests; they cannot guarantee the
linguistic completeness of a model response that reports normal completion.

Segmentation version 2 separates the corrected text pipeline from old audio
cache identities. Old task snapshots are rejected as incompatible; resubmit them
after upgrading. Existing output files remain available, but regeneration uses
new cache entries and may incur API charges.
