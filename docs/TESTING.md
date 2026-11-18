# Tests and CI

[Documentation](README.md) · [Project overview](../README.md)

Use CPython 3.11 and the locked development environment. FFmpeg and ffprobe must
be on `PATH`; real local audio publication/probing tests use both executables.
Provider calls use fake clients or transports. No API credentials are required.

```bash
python -m pip install --require-hashes --only-binary=:all: -r requirements-dev.txt
python -m pip check
python -m ruff check src tests scripts
python -m pytest -q --durations=10 --junitxml=test-results.xml
```

Run from the repository root. The complete suite includes configuration tests,
Textual pilot/UI tests, both TTS client contracts, restart/resume, cross-process
cache locks and local FFmpeg checks. There are no routine deselections for local
dotenv or TUI behavior. The Gitea workflow uses the same commands.

## Storage, credentials and configuration isolation

`tests/conftest.py` creates a private session directory **before collection**,
because some tests import the WebUI's database at module scope. The working
directory changes before application imports. WebUI assets are
resolved from the source module location; sandbox asset copies support older
tests that explicitly exercise repository-relative paths.
Each test then receives a separate application directory, SQLite database,
credential path, task snapshots, cache/output directories and configuration file.
The application's directory is separate from the test's own `tmp_path`, keeping
filesystem tests free to assert that their target directory is initially empty.

The fixture keeps the shared database object's identity so imports such as
`from src.web import db` still refer to the isolated database. Sessions, rate
limiting, admission limits and dependency overrides are reset between tests.
Authentication is bypassed only by the opt-in `authenticated_web` fixture for
endpoint logic tests. Authentication/session tests use the real implementation.

Application configuration variables and provider keys are removed from the test
environment. `BOOKSMITH_ENV_FILE` selects a private `.env` path, including in
spawned workers and command-line tests. An explicitly selected missing file does
not fall back to another `.env`. Without this override, ordinary application
dotenv discovery is preserved. Tests that exercise dotenv parsing create and
read their own synthetic files. The harness restores the caller's environment
and working directory when the pytest session ends.

The subprocess regression builds a synthetic checkout with protected `.env`,
database and auth sentinels, verifies isolation during collection and between
tests, and checks that their bytes and timestamps remain unchanged. It also
checks that relative JUnit reports survive outside the application sandbox.

## Network and time limits

`tests/network_guard.py` rejects external IP connections and all DNS lookups
before test collection. Unix sockets and literal loopback addresses remain
available for local IPC, including Windows socketpair/asyncio internals.
`socket.create_connection` remains blocked; this is an external-network guard,
not a sandbox for untrusted tests. A private
`sitecustomize.py` carries the guard into Python subprocesses through
`PYTHONPATH`; subprocess fixtures retain this path. Use an in-process ASGI
transport, fake provider client or mocked HTTP transport in tests. The guard is
test infrastructure and is not part of the application runtime.

The dev-only [pytest-timeout plugin](https://pypi.org/project/pytest-timeout/2.4.0/)
enforces a 30-second limit per test, including setup/teardown. The thread method
prints thread stacks and terminates a stuck pytest process with a failure;
faulthandler prints an earlier diagnostic at 20 seconds. Hard termination can
prevent JUnit output and fixture cleanup, so the process log is the primary
diagnostic in that case. Temporary directories can remain after such an abort.
An automated regression intentionally stalls a child test and checks that it
exits nonzero with the test name and timeout diagnostics.

For a slower local machine, set an explicit bounded override, for example
`python -m pytest --timeout=60`. Do not disable timeouts to hide a hanging test.

## Gitea Actions

`.gitea/workflows/ci.yml` runs on pushes, pull requests and manual dispatch.
Its Linux/native-Windows matrix uses SHA-pinned checkout/setup-python actions,
CPython 3.11, FFmpeg, hash-locked dev installation, `pip check`, Ruff, the entire
pytest suite and a portable smoke suite. Docker smoke tests run on Linux only. The job has a
15-minute outer limit per matrix job; pytest also reports its slowest tests and writes JUnit.
No provider secrets, registry credentials, image publication or deployment steps
are used. Dependency installation and image builds need repository/index access;
pytest then rejects Python network access. Docker smoke cases allow container
loopback for HTTP and disable external networking.

The Gitea repository needs Actions enabled and an available `ubuntu-latest`
runner capable of using the pinned Node 20 actions, installing apt packages and
accessing a Linux Docker daemon through the Docker CLI.
See [Gitea's runner/Actions quick start](https://docs.gitea.com/usage/actions/quickstart/).
The YAML and local commands can be checked before pushing; a successful remote
workflow run must be confirmed separately after a commit is pushed to a server
with a runner. This change does not provision or modify that server.

## Runtime Docker smoke tests

Run the separate container suite from the checkout:

```bash
python scripts/docker_smoke.py
```

The host-side runner uses only Python's standard library and Docker CLI. Docker
must be able to build the runtime image and create containers, volumes and bind
mounts. Image building needs package-index/OS-repository access; test containers
then run with `--network none` and communicate only over container loopback.
No host ports are published. The suite never pushes images.

The runner copies source/build inputs into a temporary build context, excluding
real dotenv files and user storage. It inserts synthetic configuration canaries,
builds the actual Dockerfile and scans every image layer for the canary. Root and
nested dotenv paths are checked, including files that a later layer could hide.
The runtime image also must not contain the test suite.

Fixtures live in a uniquely named disposable Docker volume. Bind-mount sources
come from that volume's daemon-side mountpoint, allowing the checks to work even
when the CLI runs inside a CI container. No developer storage directory is
mounted. Helper scripts are copied into the fixture container and mounted
read-only by the application containers. Known test-owned containers, volume,
image tag and local temporary files are removed at the end, including when a
negative test unexpectedly starts a server. Normal Docker build cache may remain.

Seven cases check:

- The default command and explicit UID 1000 both run the server without root;
  bind storage remains writable, ordinary file modes are preserved and an
  unrelated mounted file's ownership/mode remains untouched.
- Real HTTP login, cookies, logout, multipart upload, task progress, audio
  download and restart persistence on the same bind mount. Only TTS is replaced
  by `tests/docker/smoke_server.py`; it creates local sine-wave audio. Parsing,
  SQLite, credential migration, cache and FFmpeg compilation are real.
- Read-only storage, a nonroot-inaccessible directory and a read-only database
  fail with a storage-specific diagnostic before the server starts.
- Default unsafe credentials fail during WebUI startup.
- Synthetic build configuration is absent from every saved image layer.

The production entrypoint probes storage as the actual application user after
ownership/permission preparation. This catches failures root could otherwise
mask. Its diagnostic identifies `/app/storage` and advises checking ownership,
permissions and read-only mount flags. The checks cover Linux containers;
native Windows results remain a separate acceptance gate described in
[WINDOWS.md](WINDOWS.md).

## Portable Windows/Linux smoke

```bash
python scripts/platform_smoke.py
```

This copies only source/tests and pytest configuration into a temporary checkout
whose path includes spaces, an apostrophe and Unicode. It installs nothing, uses
the current interpreter, preserves the original checkout and returns pytest's
exit code. A 180-second subprocess deadline complements per-test timeouts.
Real FFmpeg/ffprobe checks, audio publication/cleanup, cross-process cache locks,
timeouts/cancellation, credential persistence, retention and source-relative web
assets are exercised. The portable smoke also includes bundled-binary lookup,
frozen static routes and desktop-import isolation regressions. API clients remain fake and user state is isolated by the
shared harness. The temporary checkout is removed on completion/failure.

See [WINDOWS.md](WINDOWS.md) for native runner prerequisites and the remaining
Windows acceptance gate. A Linux success does not establish Windows support.

## Operational documentation checks

[Operations](OPERATIONS.md) documents restart/resume, retention, backup/restore
and migration. Relevant automated contracts are in `test_task_recovery.py`,
`test_auth.py`, `test_sessions.py`, `test_resource_limits.py`,
`test_storage_retention.py`, `test_config.py` and `test_platform_smoke.py`.
The Docker suite covers real restart persistence; it does not validate an
external TLS proxy or a deployment's backup storage. Exercise the documented
backup/restore drill on a private staging copy before relying on that backup.
