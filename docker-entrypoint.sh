#!/bin/sh
set -e

storage_error() {
    echo "Storage initialization failed: /app/storage must be writable by the application user. Check bind-mount ownership, permissions and read-only flags." >&2
    exit 1
}

# Prepare only managed storage. Some bind filesystems do not support chown;
# the subsequent check as the actual runtime user decides whether startup is safe.
mkdir -p /app/storage/cache /app/storage/output /app/storage/translations /app/storage/tasks || storage_error
if [ "$(id -u)" = "0" ]; then
    chown -R appuser:appuser /app/storage 2>/dev/null || true
fi
# Restrict directories without making data files executable or group-writable.
find /app/storage -type d -exec chmod 750 {} + || storage_error
if [ -f /app/storage/auth.json ]; then
    chmod 600 /app/storage/auth.json || storage_error
fi

as_application_user() {
    if [ "$(id -u)" = "0" ]; then
        gosu appuser "$@"
    else
        "$@"
    fi
}

as_application_user python - <<'PY' || storage_error
import os
from pathlib import Path
import sys
import tempfile

path = Path('/app/storage')
try:
    for path in (Path('/app/storage'), *(Path('/app/storage') / name for name in
                                      ('cache', 'output', 'translations', 'tasks'))):
        with tempfile.TemporaryFile(dir=path) as probe:
            probe.write(b'storage-check')
            probe.flush()
            os.fsync(probe.fileno())
    path = Path('/app/storage/state.db')
    if path.exists():
        descriptor = os.open(path, os.O_RDWR)
        os.close(descriptor)
except OSError as error:
    print(f'Storage check failed for {path} (UID {os.getuid()}): {error}', file=sys.stderr)
    sys.exit(1)
PY

# If running as root, drop privileges to appuser
if [ "$(id -u)" = "0" ]; then
    exec gosu appuser "$@"
fi

exec "$@"
