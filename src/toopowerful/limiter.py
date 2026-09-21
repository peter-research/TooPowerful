from __future__ import annotations

import asyncio
import threading
import time


class RateLimiter:
    """Garde-fou debit: min_interval entre 2 requetes + burst.

    - rate_per_second: ex 5.0 -> au moins 0.2s entre appels
    - burst: appels immediats autorises avant d'appliquer le delai
    Thread-safe (sync). Version async via `async_acquire()`.
    """

    def __init__(self, rate_per_second: float = 5.0, burst: int = 1) -> None:
        if rate_per_second <= 0:
            raise ValueError("rate_per_second must be > 0")
        self.min_interval = 1.0 / float(rate_per_second)
        self.burst = max(1, int(burst))
        self._lock = threading.Lock()
        self._window_start = 0.0
        self._used_in_window = 0

    def acquire(self) -> float:
        """Bloque si besoin. Retourne les secondes attendues."""
        with self._lock:
            now = time.monotonic()
            if now - self._window_start >= self.min_interval:
                self._window_start = now
                self._used_in_window = 1
                return 0.0
            if self._used_in_window < self.burst:
                self._used_in_window += 1
                return 0.0
            wait = self.min_interval - (now - self._window_start)
        if wait > 0:
            time.sleep(wait)
        with self._lock:
            self._window_start = time.monotonic()
            self._used_in_window = 1
        return max(0.0, wait)

    async def async_acquire(self) -> float:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.acquire)

    def __call__(self) -> float:
        return self.acquire()
