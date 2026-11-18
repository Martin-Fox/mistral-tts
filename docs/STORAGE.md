# Storage, cache and recovery contracts

[Documentation](README.md) · [Project overview](../README.md)

On this page:

- [Recovery by interface](#recovery-by-interface)
- [Audio cache v2 (CLI, WebUI and TUI)](#audio-cache-v2-cli-webui-and-tui)
- [Verified audio publication](#verified-audio-publication)
- [Concurrent CLI/WebUI/TUI cache access](#concurrent-cliwebuitui-cache-access)
- [Restart recovery and explicit resume (WebUI)](#restart-recovery-and-explicit-resume-webui)
- [Storage retention and disk budgets](#storage-retention-and-disk-budgets)
- [Shared cache contract and TUI migration](#shared-cache-contract-and-tui-migration)

## Recovery by interface

| Interface | Recovery after interruption | Translation and output behavior |
| --- | --- | --- |
| WebUI | Restart, sign in again, then explicitly Resume a compatible failed/interrupted saved job | Reuses translation checkpoints and validated matching audio; keeps the same task ID and task-prefixed output name |
| CLI | Rerun with the same source, voice and settings | Matching audio cache is reused; translation may repeat; successful compilation atomically replaces the requested output path |
| TUI | Reselect the same input/settings and start again | Same cache rules as CLI; no durable WebUI job snapshot or translation checkpoints |

Restart never automatically submits provider work. Missing or incompatible saved
inputs require resubmission, potentially with new API charges. See
[Restart recovery](#restart-recovery-and-explicit-resume-webui) and the
[operational recovery steps](OPERATIONS.md#restart-and-resume).

## Audio cache v2 (CLI, WebUI and TUI)

CLI, WebUI and TUI share `storage/cache/v2_<sha256>/`. The canonical identity
includes the parsed source text, effective TTS engine/model and voice, SHA-256 of
reference audio bytes (not its path), effective translation languages/model, and
text splitter version/character limit. API keys and output filenames are excluded.
Defaults are resolved before hashing; a manual voice ID and the same preset ID
identify the same effective voice. Changing reference audio at the same path or
changing the configured translation model creates a different cache directory.

**Upgrade:** old unversioned cache directories are preserved but are not reused
or automatically migrated. The first run with v2 may regenerate audio and incur
API charges, even if old chunk files exist. Existing completed audiobook files
are unaffected. Do not rename old cache directories to v2 names: their parameters
cannot be reliably verified. Legacy unversioned data remains outside automatic
retention; remove it manually only when it is no longer needed.

Translation may still run again on resubmission. The manifest checks the actual
resulting segment text before reusing audio, so different translations do not
silently reuse mismatched segments. Explicit WebUI resume retains translated results/checkpoints as described below.
CLI/TUI resubmission uses the same audio manifest but can repeat translation;
it does not create a durable WebUI job or translation checkpoint.

## Verified audio publication

WebUI output names include the task ID, e.g. `<task-id>_audiobook.mp3`. Submitting
two tasks with the same requested filename keeps both results; the progress API
returns the actual published filename used by the player and download link.
Long filename stems are shortened to at most 180 UTF-8 bytes to leave room for
the task ID. Existing audiobook files and their old URLs remain available.

The compiler used by WebUI, CLI and TUI writes into a private `.compile-*`
directory on the destination filesystem. Only after FFmpeg and the existing
duration validation succeed is the staged file atomically moved to its final
path. Failed compilation/validation preserves any previous result. Normal success
and exception paths remove the workspace, including temporary silence and concat
files. Forced termination may leave workspaces for later cleanup.

CLI and TUI retain the explicitly requested output path: a successful run replaces
that file atomically. Two CLI/TUI runs deliberately targeting the same path may
still replace each other's completed result; choose different paths to keep both.
FFmpeg concat lists support spaces, apostrophes and Unicode; paths containing
line breaks are rejected. CLI/WebUI/TUI cache writers follow the locking contract in the next section.

## Concurrent CLI/WebUI/TUI cache access

CLI, WebUI and TUI take an exclusive OS file lock on each v2 cache directory before
reading/updating its manifest, generating segments, or compiling its audio.
Identical jobs wait and then recheck completed segments; different cache keys
have independent locks. The WebUI reports `Waiting for Cache` while waiting.
Lock ownership is released when the process exits/crashes. Do not delete the
persistent `.cache.lock` file while jobs are running: removing it can split locks.

`CACHE_LOCK_TIMEOUT_SECONDS` controls the maximum wait for a lock (default `3600`,
a finite positive number of seconds). A timeout fails the waiting job without
starting chunk generation; it does not cancel the owner. Waiting is asynchronous.
If compilation is cancelled, the lock is retained until its worker thread finishes
reading the segments. See [FFmpeg/ffprobe deadlines](PROCESSING.md#ffmpegffprobe-budgets-and-voice-preprocessing).

Segments are generated into unique `.pending-*` files, validated by the client
and checked for minimum size, then atomically published before the completion
marker is saved. Manifests and translated text use unique temporary files too.
Readers of a published path see the previous complete file or the new complete
file. Exceptions/cancellation clean up unpublished files; forced process death
may leave pending files, which are ignored during resume and covered by the
conservative retention policy below when their containing artifact is eligible.

These locks cover cooperating CLI/WebUI/TUI processes using the same local cache
filesystem. Network filesystems/multi-host shared storage have not been validated.
Use separate BooksmithCLI instances for concurrent invocations. TUI jobs also
use isolated cache sessions and hold their locks through compilation. CLI/TUI
translation files with identical output names still use last-completed-writer-wins publication;
this change prevents temporary-file collisions, not that naming policy.

## Restart recovery and explicit resume (WebUI)

On startup, unfinished database tasks become `Interrupted`; successful/failed
terminal states are preserved. Progress streams report the interruption and end.
The `finished_at` column is migrated automatically. Retention is a dry-run by default. When deletion is enabled, only completed
tasks expire (24 hours after finish time by default); active, failed and
interrupted tasks and their recovery files are preserved regardless of age. Legacy terminal records without a
known finish time receive the migration time, preserving a full retention window.

New WebUI jobs save private input files and an explicit parameter snapshot in
`storage/tasks/<hash-of-task-id>/` before being queued. The snapshot contains the
original text/ebook, reference audio, effective translation model, TTS model and
segmentation version, **never client API keys**. Original inputs are hash-checked
before resume. Changing global configuration does not change a saved job. Changes
to the supported TTS model/segmentation version make old snapshots incompatible
rather than silently changing their output. Back up the entire storage volume,
not just `state.db`, and protect it because it contains source documents/audio.

After login, the WebUI lists interrupted/failed resumable tasks. Enter API keys
again in the existing key fields (or configure server-side keys), then click
**Resume**. The authenticated endpoints are `GET /api/tasks` and
`POST /api/resume/{task_id}` (form fields `api_key`, `openai_key`). Resume uses the
same job ID and immutable parameters, the normal admission/worker limits and
cache lock. Concurrent resume requests cannot both claim the same job; active or
completed jobs return `409`. Missing/modified/incompatible inputs also return
`409`; missing required keys return `400` without claiming the job.

Completed translation responses/batches are checkpointed per job; the assembled
translation is retained too. Resume reuses those checkpoints and audio segments
marked completed in the matching manifest, and recompiles the output if needed.
There is no automatic execution on restart. Old pre-snapshot jobs can be marked
Interrupted but cannot be resumed without their original inputs; resubmit them.
Completed history and recognized orphaned artifacts follow the state-aware
retention policy described below; failed/interrupted snapshots are retained. API execution is not exactly-once: if the process dies after a
provider responds but before the local checkpoint is committed, that request may
need to be repeated. CLI/TUI keep their existing resubmission behavior.

## Storage retention and disk budgets

The WebUI plans maintenance every 30 minutes. **Deletion is off by default**:
logs report dry-run counts, and completed history remains until deletion is
enabled. Failed/interrupted jobs are kept indefinitely, including their input,
translation checkpoints and pinned audio cache. Active and queued jobs are also
protected. Upgrading no longer expires resumable history after 24 hours.

| Variable | Default | Meaning |
| --- | --- | --- |
| `STORAGE_CLEANUP_ENABLED` | `false` | Enable periodic deletion (`true`/`false` or `1`/`0`) |
| `STORAGE_RETENTION_SECONDS` | `86400` | Minimum age after completion and minimum artifact age for completed-job expiry |
| `STORAGE_ORPHAN_GRACE_SECONDS` | `604800` | Minimum age of recognized orphaned artifacts and unpinned cache (7 days) |
| `STORAGE_MAX_BYTES` | `0` | Optional logical-byte threshold under `storage`; 0 disables this threshold |
| `STORAGE_MIN_FREE_BYTES` | `268435456` | Free-space reserve on the storage filesystem (256 MiB); 0 disables it |

Before enabling automatic deletion, inspect the plan from the repository root:

```bash
python3 -m src.core.storage_retention --storage storage
# Explicitly apply a freshly calculated plan after reviewing the policy:
python3 -m src.core.storage_retention --storage storage --apply
```

The command defaults to read-only dry-run even if `STORAGE_CLEANUP_ENABLED=true`.
It requires an existing, migrated `state.db` inside the selected storage root;
it never creates or migrates a database. Dry-run reports relative artifact paths,
logical bytes and completed task IDs, without file contents. Apply rechecks the
current state and locks; it does not execute a previously saved report.

Recognized artifacts are hashed WebUI job directories, UUID task scratch/output/
translation names, v2 audio caches and `.compile-*` workspaces under storage.
Completed job inputs, named outputs and translations can expire after the
configured retention time. Their history/logs are removed only after those
artifacts are gone. Back up or move audiobooks outside managed storage before
enabling expiry if you want to keep them permanently. Orphaned artifacts and
unpinned audio must pass the longer grace period. Fresh files in an otherwise
old directory postpone cleanup. Cache pending files are removed with eligible
cache contents; abandoned task workspaces and compiler workspaces are reclaimed.

The sweeper skips symbolic links and unknown artifacts, including legacy flat TUI
chunk layouts, arbitrary CLI output names and loose shared translation staging
files whose owner cannot be proven. It never scans outside the selected root.
A non-expired job without a valid cache-reference marker conservatively protects
**all** v2 caches, including older snapshots until they are resumed. Failed jobs
are not evicted to meet a disk threshold; archive unwanted jobs manually while
the application is stopped. This deliberately favors recoverability over reclaiming
the maximum possible space.

A sweep takes an OS maintenance lock and acquires each cache/compiler lease
without waiting. Busy resources are skipped. Cache `.cache.lock` files and their
parent directories remain in place, preserving the lock inode for CLI/WebUI/TUI
waiters. Compiler leases also protect CLI/TUI compilation inside storage. Deleting
cache after its grace period can require paid regeneration on later resubmission.
Native Windows cleanup still needs a successful native run of the
[platform smoke suite](WINDOWS.md); network filesystems
and multi-host writers are not supported by these local-lock guarantees.

When a disk threshold is reached, WebUI generate/resume requests return `507`
before body parsing. Known uploaded-input copies are checked again before saving
a new job or claiming resume. CLI/TUI check before generation; chunk generation,
uncached translation requests and compilation recheck the budget as work proceeds.
A failed check preserves existing snapshots/cache and makes no subsequent API
call for that step. Full quota measurement counts logical file sizes, includes
unknown files and refuses symbolic-link trees; it can add filesystem scanning
cost when `STORAGE_MAX_BYTES` is enabled.

These are admission/checkpoint thresholds, **not a hard filesystem quota**.
Concurrent writers, in-flight responses and one compilation can exceed the byte
threshold between checks, and outputs outside storage may use a different disk.
Use a filesystem/container volume quota for a strict upper bound. Maintenance
never discards protected recovery data to force usage below the threshold.

## Shared cache contract and TUI migration

`src/core/audio_cache.py` owns manifest loading, comparison of previous segment
text, completed markers, file checks and atomic generation. CLI, WebUI and TUI
use one locked session through final compilation. Only a segment with matching
previous text, a completion marker and a regular non-symlink file larger than
100 bytes can be reused. Malformed manifests or missing/invalid files trigger
regeneration. File-size checks do not replace provider/probe and final decoded
audio verification. The compiler receives all current segments in source order.

TUI now uses the same `storage/cache/v2_<sha256>/` identity as CLI/WebUI, including
source text before translation, the resolved translation model, reference bytes
and processed-reference fingerprint. It resumes completed audio on resubmission
and isolates different books/voices; simultaneous identical jobs wait for the
same OS lock. CLI/WebUI cache identities and manifest format are unchanged by
this consolidation.

Old flat TUI `storage/cache/chunk_*.mp3` files remain untouched and are not reused:
their source/voice cannot be verified. The first TUI run may therefore incur new
API charges. Existing compatible v2 entries from CLI/WebUI can be reused. TUI
has no durable job snapshot or translation checkpoints; rerun with the same input
and settings after interruption. Changed translation text invalidates affected
segments. Choose distinct output paths for independent audiobooks.
