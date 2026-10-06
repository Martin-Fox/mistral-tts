#!/bin/sh
set -e

# Ensure storage directories exist and have proper permissions for appuser
mkdir -p /app/storage/cache /app/storage/output /app/storage/translations
chown -R appuser:appuser /app/storage 2>/dev/null || true
chmod -R 775 /app/storage 2>/dev/null || true

# If running as root, drop privileges to appuser
if [ "$(id -u)" = "0" ]; then
    exec gosu appuser "$@"
fi

exec "$@"
