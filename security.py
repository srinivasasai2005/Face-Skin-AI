"""Small, dependency-free security helpers (hashing, integrity check, rate limiting).

Kept free of Streamlit imports so every function here is unit-testable.
"""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
from collections import deque
from collections.abc import Callable


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class IntegrityError(RuntimeError):
    """A file does not match the fingerprint we pinned for it."""


def verify_sha256(data: bytes, expected_hex: str, what: str = "file") -> None:
    """Raise :class:`IntegrityError` unless ``data`` hashes to ``expected_hex``.

    The comparison is constant-time. Callers should load *these same bytes* after
    verifying, not re-open the path, otherwise the file could be swapped in between.
    """
    actual = sha256_hex(data)
    if not hmac.compare_digest(actual, expected_hex.strip().lower()):
        raise IntegrityError(f"{what} failed its integrity check")


class RateLimiter:
    """Sliding-window limiter: at most ``limit`` events per ``window`` seconds.

    One instance per Streamlit session slows down accidental loops and casual abuse.
    It cannot stop someone who opens many sessions; per-IP limits belong in the
    reverse proxy (see deploy/ and SECURITY.md).
    """

    def __init__(self, limit: int, window: float, clock: Callable[[], float] = time.monotonic):
        self.limit, self.window, self._clock = limit, window, clock
        self._events: deque[float] = deque()
        self._lock = threading.Lock()

    def allow(self) -> bool:
        """Record an event and return True if it is within the limit."""
        now = self._clock()
        with self._lock:
            while self._events and now - self._events[0] >= self.window:
                self._events.popleft()
            if len(self._events) >= self.limit:
                return False
            self._events.append(now)
            return True

    def retry_after(self) -> float:
        """Seconds until the next event would be allowed (0 if allowed now)."""
        now = self._clock()
        with self._lock:
            if len(self._events) < self.limit:
                return 0.0
            return max(0.0, self.window - (now - self._events[0]))
