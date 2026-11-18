# Windows source distribution and acceptance

[Documentation](README.md) · [Project overview](../README.md)

The current P22 target is **CPython 3.11 x64 + FFmpeg/ffprobe**, running from
source with `PYTHONUTF8=1`. PR #28 added `desktop.py`, `src/desktop.py`, `mistral-tts.spec` and a separate
`build-windows.yml` workflow. These provide the packaging implementation, not
evidence of a tested standalone `.exe`. A source smoke suite alone does not
validate an executable release.

## Source setup (PowerShell)

Install CPython 3.11 and a Windows FFmpeg build providing both `ffmpeg.exe` and
`ffprobe.exe` in PATH. Keep their versions in the verification log. From the
checkout, create an environment and install the existing locked runtime:

```powershell
$env:PYTHONUTF8 = '1'
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes --only-binary=:all: -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
ffmpeg -version
ffprobe -version
```

Configure credentials as described in [Installation and usage](USAGE.md#setup)
before starting WebUI; the default
password is intentionally refused. Use filesystem ACLs to restrict `.env` and
`storage` to the service account. Do not put provider keys in test logs.

Reference audio now requires MP3 or PCM WAV, is normalized without fallback and
has duration/output/allocation/time guards. The hard address-space/CPU/file
resource wrapper uses Linux prlimit; it is not provided by Windows. Native
Windows resource containment (e.g. Job Objects) remains an acceptance item.
WebUI MOBI upload/resume is disabled on every platform; CLI/TUI MOBI is for
trusted local inputs only. Version-3 reference preprocessing invalidates older
cloned-voice cache identities/resume specs, while retaining existing outputs.

```powershell
.\.venv\Scripts\python.exe -m uvicorn src.web:app --host 127.0.0.1 --port 8000 --workers 1
```

Always choose a writable, stable launch directory. `storage/` (database, auth,
tasks, cache, translations and outputs) belongs to that **working directory**.
Static HTML/CSS/JS belong to the source tree beside `src/web.py` and are read
from there even when the launch directory differs. Starting in a different
directory selects different storage; existing data is not automatically moved.
To launch outside the checkout, use an absolute `PYTHONPATH` pointing to it and
`BOOKSMITH_ENV_FILE` pointing to the intended configuration file. Paths with
spaces need PowerShell quoting. No global path/storage migration is introduced.

## Local verification (no provider calls)

Packaging now pins Gyan's FFmpeg **9.0.2** essentials archive and SHA-256, with no
fallback to a moving `latest` build. The archive hash was downloaded and checked
locally; its EXEs have not been executed here. The Windows package is a general
GPLv3 multimedia build, not the Linux audio-only profile; embedded library
versions (including libxml2), native process/resource handling and the final
application still need native acceptance. See [Native dependencies](NATIVE_DEPENDENCIES.md).

Use a development environment for the tests:

```powershell
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe -m pip install --require-hashes --only-binary=:all: -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe -m pytest -q --durations=10 --junitxml=test-results.xml
.\.venv\Scripts\python.exe scripts/platform_smoke.py
```

The smoke runner creates a private copied checkout named with spaces, an
apostrophe and Polish Unicode. It runs real audio compilation and publication,
cache reuse/locking across processes (including recovery from a terminated lock
owner), cancellation/deadlines, storage retention, auth persistence and static
assets from another working directory. Both FFmpeg and ffprobe must execute.
Only local synthetic audio and fake provider clients are used. The normal
harness isolates dotenv/storage and blocks external Python connections; literal
loopback IPC remains available for Windows asyncio/socketpair. This use of
[socketpair on Windows](https://docs.python.org/3.11/library/socket.html#socket.socketpair)
is supported by Python. Tests are trusted code, not security-sandboxed programs.

Symlink regressions require the runner account to have permission to create
symlinks (for example an appropriately configured Windows Developer Mode host).
They are not silently skipped if permissions are absent. POSIX-only signal and
mode-bit assertions are explicitly skipped on Windows; Windows ACL protection
requires a separate deployment check.

## Gitea runner requirements

`.gitea/workflows/ci.yml` contains Linux and Windows matrix entries. Windows
steps use PowerShell (`pwsh`) and require a **native Windows x64 host runner**
with a `windows-latest:host` label, Git, PowerShell 7, Node 20 for the pinned
actions, access to CPython 3.11 through setup-python, preinstalled FFmpeg/ffprobe
and symlink creation privileges. This label is configured on your Gitea runner;
it does not provision a GitHub-hosted VM. See the
[Gitea runner label documentation](https://docs.gitea.com/usage/actions/act-runner/).
The FFmpeg preflight fails if binaries are missing. CI does not install random
Windows packages or silently substitute Linux/Wine. Docker checks run only on
the Linux entry. Each entry has a 15-minute deadline and runs independently
(`fail-fast: false`). With no matching Windows runner, that entry remains queued.

## Acceptance status

Local Linux checks after integrating PR #28: **505 pytest tests passed**,
**112 portable smoke tests passed** from the disposable Unicode checkout, Ruff and `pip check`
passed. A dry-run wheel-only resolution of the existing dev lock for Windows
x64/CPython 3.11 succeeded (48 packages); no Windows packages were installed.
This checks dependency selection, not native imports or execution.

Linux verification is recorded separately from native Windows acceptance. The
P22 preparation provides tests, portable fixes and CI wiring; **native Windows
acceptance is still pending**. Before declaring source distribution verified,
record the Windows/CPython/FFmpeg versions and successful dependency installation,
full pytest output (including explicit platform skips), smoke output and a local
WebUI startup/static-page check. Confirm that temporary compiler files disappear,
cache locks are released after a child is stopped and user state is untouched.

The combined source supports bundled binary resolution for every compiler,
metadata-probe and reference-preprocessing call while retaining process budgets,
atomic output publication and cleanup. Frozen WebUI assets are read from
`sys._MEIPASS/src/web/static`; they are not created or modified at startup.
The desktop launcher selects a writable executable directory when frozen (the
checkout during source execution), and only does so when actually launching.
Importing its helper functions does not change the caller's working directory.
Before starting the desktop application, configure unique WebUI credentials in a
private `.env` beside the executable; default credentials still stop startup.

Native artifact acceptance must cover the built executable without system
Python/FFmpeg, included static assets/binaries, login, storage writes and a local
synthetic audiobook after restart, from paths with spaces/apostrophe/Unicode.
The existing packaging workflow alone does not establish these results; no
native build or new dependency installation was performed while resolving this
merge. Network filesystems and multi-host writers remain outside acceptance.
