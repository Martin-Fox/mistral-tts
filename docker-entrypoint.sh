#!/bin/sh
set -e

# Ensure storage directories exist and have proper permissions for appuser
mkdir -p /app/storage/cache /app/storage/output /app/storage/translations
chown -R appuser:appuser /app/storage 2>/dev/null || true
# Restrict directories without making data files executable or group-writable.
find /app/storage -type d -exec chmod 750 {} +
if [ -f /app/storage/auth.json ]; then
    chmod 600 /app/storage/auth.json
fi

# If running as root, drop privileges to appuser
if [ "$(id -u)" = "0" ]; then
    exec gosu appuser "$@"
fi

exec "$@"
