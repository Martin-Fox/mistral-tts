# Dependency management

The validated baseline is CPython 3.11 on Linux, matching the Docker Python minor
version. The locks use platform markers and hashes for other distributions, but
universal resolution does not replace native Windows/macOS or other Python-minor
testing. Windows smoke/build verification remains audit P22.

## Files and installation

| File | Role |
| --- | --- |
| `requirements.in` | Direct runtime dependencies with explicit versions |
| `requirements-dev.in` | Runtime inputs plus pytest, pytest-timeout, AnyIO, Ruff and uv |
| `constraints.txt` | Compatibility pins for indirect dependencies |
| `requirements.txt` | Generated runtime lock: complete pins and artifact hashes |
| `requirements-dev.txt` | Generated development lock: runtime plus development tools |

Install the generated `.txt` lock in a fresh virtual environment. Installing the
`.in` files bypasses the locked artifact selection. The dev lock already includes
runtime; there is no need to install both locks.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
# Application users:
python -m pip install --require-hashes --only-binary=:all: -r requirements.txt
# Contributors, instead:
python -m pip install --require-hashes --only-binary=:all: -r requirements-dev.txt
python -m pip check
```

If the system Python lacks `ensurepip`, install its venv support through the
system administrator or use an already available `uv venv --seed --python 3.11`.
Do not install into the system interpreter to work around this restriction.

The runtime declares HTTPX and Starlette explicitly because application modules
import them directly. OpenAI TTS uses HTTPX rather than the OpenAI SDK. The
Mistral SDK is `2.10.1`, with patched OpenTelemetry API `1.45.2` and semantic
conventions `0.66b2`. SDK 3.x/HTTPX2 is not required for this security update.
FFmpeg/ffprobe remain native executables: Docker builds the reviewed 9.0.2
audio-only profile rather than installing the distro multimedia dependency graph.

`asyncio` comes from Python's standard library. Neither `pydub` nor
`ffmpeg-python` is used by the subprocess-based compiler, so those distributions
are excluded. Pytest/Ruff are dev-only. Black had no configured invocation or
formatting contract and is no longer an application/development requirement.
AnyIO is explicitly selected in the dev inputs for its
[bundled pytest plugin](https://anyio.readthedocs.io/en/stable/testing.html);
separate `pytest-anyio` or `pytest-asyncio` packages are unnecessary for this suite.
The pinned uv tool is used only to maintain the locks. Dev-only pytest-timeout
provides the bounded test execution required by P20.

## Updating dependencies

Edit the relevant `.in` file for direct dependencies and `constraints.txt` for
indirect compatibility pins. Do not copy an unrelated workstation's `pip freeze`
into the project. The initial constraints preserve the tested dependency graph;
CA certificates (`certifi`) and IDNA were refreshed to the versions recorded in
the locks. They remain pinned during ordinary installation and recompilation.

Activate the dev environment so the pinned `uv==0.13.4` is used, then compile the
dev graph first. Constrain the runtime graph to those same versions:

```bash
uv pip compile requirements-dev.in --python-version 3.11 --universal \
  --generate-hashes --default-index https://pypi.org/simple \
  --output-file requirements-dev.txt
uv pip compile requirements.in --constraint requirements-dev.txt \
  --python-version 3.11 --universal --generate-hashes \
  --default-index https://pypi.org/simple --output-file requirements.txt
```

Existing output pins are preferred by default. For an intentional update to a
package without an explicit input/constraint pin, pass `--upgrade-package NAME`
to the first command, then regenerate runtime. For a pinned package, change its
input/constraint version first. Review both the version and hash diff before
installing. See the [uv compile documentation](https://docs.astral.sh/uv/pip/compile/).

Validate proposed locks in fresh runtime and dev environments: install with hash
checking, run `pip check`, import CLI/TUI/WebUI and both client factories using
dummy keys, run regression tests with fake API responses, and build the Docker
image. WebUI import creates local storage, so run its import smoke in a throwaway
working directory with `PYTHONPATH` pointing at the repository. Full test runs
use the shared isolation fixtures described in [Tests and CI](TESTING.md).
Never validate dependency updates using paid provider requests.

The P19 check installed each lock in separate clean environments and ran the
selected 450-test regression set in the dev environment. One known dotenv-dependent
test was deselected, and the three existing Textual pilot/UI tests were not part
of that selected set. Logic-level TUI, cross-interface, cancellation, cache and
local FFmpeg tests were included. P20 subsequently enabled the entire suite,
including those configuration and pilot tests, under shared isolation fixtures
and added the Gitea workflow in `.gitea/workflows/ci.yml`.

## Docker and repeatability limits

The Dockerfile installs only `requirements.txt`, enforces hashes and wheel-only
installation, and runs `pip check`. Development tooling is not installed in the
runtime image. After validation, pip, setuptools and wheel (including their
vendored libraries) are removed from the final runtime. They are unnecessary
for application execution; installer/debug commands such as `python -m pip`
are therefore unavailable inside that image. No uv executable is required to
install the already compiled locks.

[Pip hash checking](https://pip.pypa.io/en/stable/topics/secure-installs/)
verifies selected package artifacts against the lock. This does not establish
that a dependency is vulnerability-free. Refresh pins/hashes deliberately and
review security advisories as part of maintenance.

These locks fix Python package versions and accepted artifact hashes. The
Dockerfile also pins the `python:3.11-slim-trixie` manifest digest and explicitly
installs/upgrades zlib with a minimum corrected Debian version. FFmpeg source and
its minimal configure profile are pinned in `scripts/build_ffmpeg.sh`; its
internal libraries are static and the LAME encoder remains a dynamic apt library.
Apt repositories/compiler/LAME remain mutable, so the entire OS image is not
bit-for-bit reproducible. Review/refresh the base digest for security releases;
pinning it does not provide automatic updates. Source builds are disabled for these install
commands; an unavailable compatible wheel fails the install instead of selecting
an unreviewed build toolchain.

## Initial security refresh, 2026-11-18 (historical stage)

The paired locks update AnyIO 4.13.0 to 4.14.2, python-dotenv 0.21.0 to 1.2.2,
and dev-only uv 0.11.7 to 0.13.4. No Python dependency was added. The SDK remains
2.4.9. Fresh runtime/dev hash installations and `pip check` passed; a fresh
runtime also imported CLI/TUI/WebUI and both client factories after uninstalling
pip/setuptools/wheel. Both locks retain two OpenTelemetry API advisories:
`CVE-2026-114603` and `CVE-2026-126360`. Its version cannot be updated independently
of the SDK/semantic-conventions contract; see the
[security audit](audit/SECURITY_AUDIT_2026-11-18.md#konflikt-aktualizacji-opentelemetry).

Per operator instruction, this refresh **does not build or publish a Docker
image**. The zlib version guard, installer cleanup and prlimit installation are
prepared in Dockerfile. A future authorized build, container smoke and image
scan must establish the resulting OS package versions and absence of vendored
installer findings. Tests of equivalent cleanup in a Python virtual environment
do not replace those checks. FFmpeg/libxml2 advisories without a trixie fix are
tracked separately; constrained reference decoding is mitigation, not a claim
that those installed packages are patched.

## SDK and native update, 2026-11-18

The next stage upgrades Mistral `2.4.9` to `2.10.1`, OpenTelemetry API `1.39.1`
to `1.45.2` and semantic conventions `0.60b1` to `0.66b2`. The obsolete
importlib-metadata/zipp transitive dependencies drop out of both generated locks.
Fresh hash-checked installs and dependency checks passed. Offline tests exercise
the actual SDK serializer/parser via HTTPX MockTransport, including preset and
reference audio, translation/JSON batches, model/voice lists and disabled SDK
retries. Both lock scans report zero known findings at the time of checking.
The SDK still warns that its v1 voice-list pagination will eventually retire;
the pinned endpoint's request/response behavior is covered by the wire test.

Dockerfile now builds FFmpeg 9.0.2 from the signed upstream source archive with
a reviewed SHA-256 and only required audio components. No libxml2, networking or
video codecs are enabled. The final stage installs LAME, gosu/util-linux and
zlib, not distro FFmpeg; a build guard rejects an unexpected libxml2 package.
No unstable Debian packages are mixed into stable. See
[native dependency updates](NATIVE_DEPENDENCIES.md) for exact hashes, local
build/testing instructions, Windows differences and known residual native CVEs.

Per operator instruction no Docker image was built, scanned or deployed for
this update. Local native compilation and regression checks do not substitute
for the future image/ABI/OS-package scan or native Windows release acceptance.
