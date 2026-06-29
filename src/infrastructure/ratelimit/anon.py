"""In-process sliding-window rate limiter for anonymous public-widget traffic.

Why in-process (not Redis): the platform is built to run on free tiers with no
always-on cache. A per-process limiter is the matching-cost guard against a
single abusive visitor hammering one bot. It is intentionally *best-effort*:

  * Multi-instance deployments get one window per instance (the effective limit
    multiplies by the instance count). That is acceptable here because the hard
    backstop against runaway cost is the per-tenant daily token quota, which is
    shared in Postgres and therefore global. This limiter only smooths bursts.

Keys are (public_key, client_ip). A monotonic clock avoids wall-clock jumps.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock


class SlidingWindowRateLimiter:
    def __init__(self, max_events: int, window_seconds: float) -> None:
        self._max = max_events
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str, *, now: float | None = None) -> bool:
        """Record an event for `key`; return False if it exceeds the window cap.

        Rejected events are NOT recorded, so a blocked caller does not extend its
        own penalty window — once older hits age out, traffic resumes.
        """
        ts = time.monotonic() if now is None else now
        cutoff = ts - self._window
        with self._lock:
            bucket = self._hits[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self._max:
                return False
            bucket.append(ts)
            return True

    def remaining(self, key: str, *, now: float | None = None) -> int:
        ts = time.monotonic() if now is None else now
        cutoff = ts - self._window
        with self._lock:
            bucket = self._hits[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            return max(0, self._max - len(bucket))
