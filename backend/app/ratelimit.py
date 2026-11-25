"""Remembers recent failed sign-in attempts so guessing a password is slow.

In memory and per process, which is enough for one backend instance. Supabase Auth also has its own limits; this
protects our endpoint and gives a friendly message before Supabase has to say no.
"""
import threading
import time
from collections import defaultdict, deque


class FailureLimiter:
    def __init__(self, max_failures: int, window_seconds: float, clock=time.monotonic) -> None:
        self.max_failures = max_failures
        self.window = window_seconds
        self._clock = clock
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _trim(self, key: str, now: float) -> deque:
        q = self._failures[key]
        while q and now - q[0] >= self.window:
            q.popleft()
        if not q:
            self._failures.pop(key, None)
            return deque()
        return q

    def seconds_until_allowed(self, key: str) -> int:
        """0 if the key may try now, otherwise whole seconds to wait."""
        with self._lock:
            now = self._clock()
            q = self._trim(key, now)
            if len(q) < self.max_failures:
                return 0
            return max(1, int(self.window - (now - q[0]) + 0.999))

    def record_failure(self, key: str) -> None:
        with self._lock:
            now = self._clock()
            self._trim(key, now)
            self._failures[key].append(now)
            if len(self._failures) > 10_000:            # never let an attacker grow this without bound
                oldest = min(self._failures, key=lambda k: self._failures[k][-1])
                self._failures.pop(oldest, None)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._failures.clear()


# 5 wrong passwords for one email, or 25 from one address, in 5 minutes
by_email = FailureLimiter(max_failures=5, window_seconds=300)
by_address = FailureLimiter(max_failures=25, window_seconds=300)
