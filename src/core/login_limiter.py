"""Bounded, process-local login limits; no credentials are retained."""

import hashlib
import math
import threading
import time


class LoginLimiter:
    def __init__(self, account_limit=5, source_limit=20, window_seconds=300, max_entries=1024):
        self.account_limit = account_limit
        self.source_limit = source_limit
        self.window_seconds = window_seconds
        self.max_entries = max_entries
        self._entries = {}
        self._lock = threading.Lock()

    def consume(self, source: str, username: str) -> int | None:
        """Reserve an attempt atomically, or return seconds until retry is allowed."""
        source = hashlib.sha256(source.encode("utf-8")).digest()
        account = hashlib.sha256(username.encode("utf-8")).digest()
        keys = [("source", source), ("account", source, account)]
        limits = [self.source_limit, self.account_limit]
        with self._lock:
            now = time.monotonic()
            self._entries = {key: value for key, value in self._entries.items() if value[1] > now}
            blocked_until = [
                self._entries[key][1] for key, limit in zip(keys, limits)
                if key in self._entries and self._entries[key][0] >= limit
            ]
            if blocked_until:
                return max(1, math.ceil(max(blocked_until) - now))
            missing = sum(key not in self._entries for key in keys)
            if len(self._entries) + missing > self.max_entries:
                # Do not evict live limits: rotating usernames/IPs must not reset them.
                return max(1, math.ceil(min(value[1] for value in self._entries.values()) - now))
            for key in keys:
                count, expiry = self._entries.get(key, (0, now + self.window_seconds))
                self._entries[key] = (count + 1, expiry)
        return None
