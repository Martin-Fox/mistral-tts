# Operations: deployment, recovery and upgrades

This describes the current source tree, not a guarantee about an existing
registry image. Build from the intended checkout and record its exact revision
and local changes, or record the immutable image ID/digest used for deployment.
The original [audit](audit/AUDIT_REPORT.md) and [plan](audit/REFACTORING_PLAN.md)
are historical inputs, not a live list of unremediated findings.

## Supported operating model and configuration

Use one WebUI process/worker and one replica. Sessions, login counters and the
execution queue live in that process; multiple workers/replicas are unsupported.
Cooperating CLI/TUI processes may share a local v2 audio cache through OS locks,
but do not share the WebUI worker/admission budget. Network filesystems and
multi-host shared cache writers are outside the verified lock contract.

`storage/` is relative to the **launch working directory**. Preserve the whole
root: `state.db`, `auth.json` if present, `tasks/`, `cache/`, `translations/` and
`output/`. CLI/TUI inputs and explicitly chosen outputs outside that root must
be backed up separately. Web assets are read beside `src/web.py`, independently
of the working directory. Docker uses `/app` and mounts storage at `/app/storage`.

Process environment values take precedence over dotenv. Use an absolute
`BOOKSMITH_ENV_FILE` to select a specific private configuration file; an explicit
missing path does not fall back to another dotenv file. Without this setting,
normal dotenv discovery applies; do not depend on discovering the same file from
an arbitrary launch directory. WebUI/TUI model changes save to the selected
file and update their own process environment; they do not change another
already-running process. Most operational settings require restart; Docker
injected environment changes require container recreation. See
[Docker configuration](../DOCKER.md).

Client keys are not saved in durable job snapshots or browser storage. Reenter
them after reload/resume, or configure server-side provider keys. Snapshot files
still contain private documents and reference audio. Protect storage, config and
backups with service-account permissions (POSIX modes or Windows ACLs). Avoid
putting keys in command arguments, screenshots, shared logs or bug reports.

## Network access and TLS

For local use, bind Uvicorn to loopback with one worker and disable forwarded
header trust:

```bash
python3 -m uvicorn src.web:app --host 127.0.0.1 --port 8000 --workers 1 --no-proxy-headers
```

Docker's listener is `0.0.0.0:8000` **inside the container**. Publish it only on
host loopback (`-p 127.0.0.1:8000:8000`) for local use or a host reverse proxy.
Container-network proxies need their own private routing and access rules.

For remote use, terminate HTTPS at a configured reverse proxy and set
`SESSION_COOKIE_SECURE=true`. That variable only marks cookies Secure; it does
not configure certificates, TLS or HTTP-to-HTTPS redirects. The proxy must keep
plain backend HTTP inaccessible to untrusted clients. Enable forwarding only
from its actual address. For a proxy on the same host, a backend example is:

```bash
python3 -m uvicorn src.web:app --host 127.0.0.1 --port 8000 --workers 1 \
  --proxy-headers --forwarded-allow-ips=127.0.0.1
```

This example assumes `SESSION_COOKIE_SECURE=true` is already configured. Use the
actual container-network proxy address for container deployments; never accept
arbitrary forwarding sources on an exposed backend. The proxy should overwrite
client-supplied forwarding headers with the observed address/scheme. Otherwise
login limits can count the proxy as one client or trust forged source addresses.

Set proxy body-size/upload-timeout limits deliberately and disable response
buffering for `/api/progress` SSE. The application emits progress every 0.5s;
proxy timeouts must allow this connection. Verify HTTPS login, HttpOnly/Secure
cookies, logout, SSE progress, authenticated audio download and blocked backend
bypass in the actual deployment. Offline ASGI tests do not validate certificates
or external proxy configuration. Use a local synthetic workload for this check;
a real provider generation is a separately authorized paid operation.

Docker's default command and the desktop launcher disable forwarded-header trust.
When deploying Docker behind a proxy, explicitly override its command with
`uvicorn src.web:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers
--forwarded-allow-ips=ACTUAL_PROXY_SOURCE_IP`. The trusted IP must be the source
seen inside the container, which may be the Docker bridge gateway for a host
proxy; do not assume that it is loopback. See [deployment security](SECURITY_DEPLOYMENT.md)
for LAN-only use, body deadlines, image identity and acceptance checks.

## Restart and resume

1. Keep the same complete storage root and start the chosen application version.
   Unfinished WebUI rows become `Interrupted`; successful/failed rows remain.
   No remote generation starts automatically. Sessions are lost, so sign in again.
2. Open **Interrupted / failed tasks** (use Refresh if needed). The list considers
   the 50 most recent failed/interrupted rows and shows ones with saved specs;
   presence in the list does not guarantee compatible or intact inputs.
3. Supply keys again or use server keys. Translation needs Mistral credentials
   even when OpenAI is selected for TTS. Click **Resume** on the original task.
   `POST /api/resume/{task_id}` accepts only key fields (`api_key`, `openai_key`),
   not replacement job parameters.
4. A compatible job retains its ID/settings, validates saved input hashes and
   reuses committed translation checkpoints and matching completed audio chunks.
   Missing/unmarked/invalid chunks regenerate; final compilation runs again.
   Wait for `Completed` and use the published filename returned by progress.

CLI/TUI recovery is **resubmission** with the same source/settings; they do not
write a durable WebUI job or translation checkpoints. Translation can repeat and
change the segments, invalidating affected audio. Their successful output
publication replaces the explicitly selected path. WebUI outputs include the task
ID; use the returned name rather than guessing from the requested filename.

A request can have been billed before a local checkpoint is committed. Resume
and retry cannot guarantee exactly-once billing. Do not delete a manifest to
"repair" a job; it can cause regeneration. Old jobs with no snapshot, altered
inputs or incompatible model/segmentation/preprocessing versions require a new
submission from original inputs. Preserve the old storage for inspection.

| Response | Operator action |
| --- | --- |
| `400` | Check input/key requirements; resume requires the original engine's keys |
| `401` | Sign in again; jobs keep running after session expiry/logout |
| `404` | Check the task ID and selected storage root; history may have expired |
| `409` on resume | Task is active/completed, concurrently claimed, or saved inputs are missing/changed/incompatible; inspect before resubmitting |
| `413` | Reduce/split input deliberately or review the specific configured size limit; content is never silently truncated |
| `429` | Respect `Retry-After`; login limits and generation admission are separate |
| `507` | Inspect free space/quota and retention dry-run; recovery data is not automatically sacrificed |

## Resource limits and retention

The [README limit tables](../README.md#resource-limits-and-generation-admission)
list defaults and scopes. Input budgets, the WebUI queue, per-operation API retry
budgets and per-process FFmpeg deadlines are separate controls. The two running
plus two queued WebUI defaults do not limit independent CLI/TUI processes.
Upload size limits do not sandbox the MOBI library's extraction phase.

`STORAGE_CLEANUP_ENABLED=false` is the default. Startup maintenance and subsequent
30-minute sweeps only report a dry-run unless deletion is enabled. Completed jobs
and their recognized artifacts can expire after 24h; recognized orphans/unpinned
cache have a 7-day grace period. These ages are minimums, not deletion deadlines:
fresh files, leases or unresolved cache pins postpone cleanup. Active, queued,
failed and interrupted tasks remain protected. Unknown/legacy artifacts and
symlinks are skipped; do not expect maintenance to reclaim every byte.

Inspect before enabling deletion (the database must already exist and have the
current schema):

```bash
python3 -m src.core.storage_retention --storage storage
# Recalculate and apply the current policy only after reviewing the dry-run:
python3 -m src.core.storage_retention --storage storage --apply
```

For a running Docker WebUI, execute inspection as its application user:

```bash
docker exec --user 1000 mistral-tts python3 -m src.core.storage_retention --storage storage
```

Use the actual UID if deploying with another explicit nonroot user. Maintenance
defaults to dry-run even when automatic deletion is enabled. Apply recalculates;
it does not execute a previously saved report. Do not manually remove lock files
while any writer/maintenance process is alive. Archive completed audiobooks
outside managed storage **before** enabling expiry.

`STORAGE_MAX_BYTES=0` disables the optional logical-byte threshold;
`STORAGE_MIN_FREE_BYTES=268435456` reserves 256 MiB by default. Concurrent or
in-flight writes can overshoot; these checks are not a hard filesystem quota.
Budget for compilation, outputs on other disks, backups and Docker logs too.

## Backup and restore

Use an **offline whole-storage backup** for a simple consistent recovery point.
A live copy of `state.db` alone cannot capture matching inputs, translation
checkpoints, manifests and audio. A SQLite-only online backup does not make the
other files transactionally consistent.

1. Stop admission and all WebUI/CLI/TUI writers and scheduled maintenance sharing
   that storage. Wait for them to exit; stop the container with `docker stop
   mistral-tts` if applicable. After forced shutdown, expect interrupted tasks.
2. Make a private backup **outside managed storage**. Keep the exact application
   revision/image identity, lockfiles and operational configuration separately.
   Provider keys/config need a private backup or a reproducible secret source;
   environment-only passwords have no `auth.json` until changed in WebUI.
3. For a POSIX bind-mounted checkout, run the following **after stopping writers**:

```bash
umask 077
backup_dir="../booksmith-backups/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup_dir"
tar -cf "$backup_dir/storage.tar" storage
```

This copies the full tree, including any SQLite journal/WAL/SHM files; do not
selectively discard them from a backup. Copy the actual private config file and
any external CLI/TUI input/output paths separately without printing their
contents. Named volumes require the equivalent stopped-volume backup, preserving
ownership and the full tree. Protect archives because legacy auth may be plaintext.
Restart the original deployment only when the copy is complete.

4. Test recovery into a **new empty staging directory**, never over running data.
   The following POSIX example assumes `backup_dir` still selects your own trusted
   archive:

```bash
restore_dir="$(mktemp -d "${TMPDIR:-/tmp}/booksmith-restore.XXXXXX")"
tar -xf "$backup_dir/storage.tar" -C "$restore_dir"
python3 - "$restore_dir/storage/state.db" <<'PY'
from contextlib import closing
from pathlib import Path
import sqlite3
import sys

path = Path(sys.argv[1]).resolve()
with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
    assert db.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
    assert db.execute('PRAGMA foreign_key_check').fetchall() == []
print('SQLite integrity and foreign keys: OK')
PY
```

This validates SQLite read-only without application startup/migration; it does
not validate all snapshot assets or prove a task is resumable. On a private
staging copy, compare the original/snapshot/checkpoint/cache/output files with the
backup and test migration/startup using the intended version, deletion disabled
and no provider keys. Start from the staging working directory with an explicit
staging `BOOKSMITH_ENV_FILE`; do not accidentally discover production dotenv.
WebUI can start without provider keys when its login credentials are valid.
Check login and static assets; **do not click Generate/Resume** in a restore drill.

5. For actual recovery, keep writers stopped, select the restored storage as the
   deployment's root/mount, restore service-account ownership/ACLs and the intended
   private configuration, and start one WebUI worker. Keep the previous tree as a
   rollback copy. Sign in again and inspect interrupted tasks before explicitly
   resuming. Verify known completed outputs against backup checksums. The Docker
   entrypoint prepares storage as UID 1000; a custom nonroot user must already
   have write access. Do not use `chmod 777` as a recovery step.

## Upgrade and rollback

Back up before the first startup of new code: database initialization occurs
on WebUI import, and credential migration happens on startup. Test the target
version against a copy first. `finished_at` is added automatically to legacy
schemas; terminal rows with unknown finish time receive migration time rather
than immediately expiring. Legacy plaintext credentials migrate atomically to
PBKDF2 hashes; damaged credentials stop startup without an environment fallback.

There is no automatic migration from old unversioned/flat TUI audio cache to v2.
Segmentation version 2 and corrected reference preprocessing invalidate older
identities/snapshots as documented in README. Do not rename cache directories or
edit snapshot version/hash fields to bypass checks. Completed outputs remain
files, but retention may remove them if enabled. Resubmission can incur API costs.

Rollback means the previous exact code/image **and its pre-upgrade storage/config
backup**, not old code against a database already changed by new code. There is
no down-migration command or general backward-compatibility guarantee. Reverting
a backup discards progress made since that backup; retain the newer tree for
reconciliation and account for possible repeated provider requests.

## Credential recovery

Persisted `storage/auth.json` takes precedence over `APP_USERNAME`/`APP_PASSWORD`.
For a lost password, damaged file or rejected default password, stop WebUI, move
that file to a private location outside managed storage, configure a unique
12-1024-character `APP_PASSWORD` (at least 12 after trimming) and non-empty username,
then restart. Never replace
`password_hash` with plaintext or print the old file. Legacy backups may contain
plaintext credentials. Environment credentials are hashed in memory; changing
the password through WebUI creates a new persisted auth file. A successful change
revokes all sessions; failed writes leave existing sessions intact.

An existing persisted short password allows a restricted login for changing it,
even after legacy plaintext migration. It does not permit generation, resume or
data/config reads. The UI opens Security Settings automatically; sign in again
after a successful change. If there is no auth file and credentials come from
the environment, set a sufficiently long `APP_PASSWORD` **before** upgrading or
startup will be refused. Updating only the environment does not override a
persisted auth file.

## Origin checks and browser headers

The frontend supplies `X-Requested-With: Booksmith` automatically. Non-browser
HTTP integrations must include it on writes when omitting Origin. Matching
same-origin browser requests are accepted; foreign/opaque origins return `403`
before body reception. Do not copy an Origin from another host or use wildcard
CORS as a workaround. Behind HTTPS, preserve Host and configure trusted proxy
scheme handling; raw `X-Forwarded-*` headers do not establish a trusted origin.

CSP restricts scripts and API connections to the same origin, while preserving
the UI's existing inline styles and Google Fonts. Frame protection, nosniff,
no-referrer and no-store on root/API responses are included. HSTS belongs on
the HTTPS terminator. Interactive Swagger/ReDoc are disabled; the OpenAPI schema
is available at `/openapi.json` for clients honoring the write-header contract.

## Verification and remaining release gates

See [Tests and CI](TESTING.md) for isolated fake-provider tests, dependency checks,
Linux Docker smoke and portable source smoke. Native Windows acceptance remains
[pending](WINDOWS.md#acceptance-status); no tested standalone `.exe` exists.
External TLS/proxy configuration and restore drills on the actual deployment
remain operator checks. Offline tests do not measure real-provider quality,
account access, billing or end-to-end production throughput.
