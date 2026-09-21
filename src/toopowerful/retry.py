from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Callable, Iterable, Mapping, Optional, Sequence


def parse_retry_after(value: str) -> Optional[float]:
    """Parse un header Retry-After: secondes ou date HTTP. None si invalide."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(value)
        if dt is None:
            return None
        ts = dt.timestamp()
        return max(0.0, ts - time.time())
    except (ValueError, TypeError, OverflowError):
        return None


OnRetry = Callable[[int, str, Optional[int], float], None]


@dataclass
class Retry:
    """Exponential backoff retry policy.

    - attempts: nombre total de tentatives (>=1)
    - backoff: delai de base en secondes (delai(attempt) = backoff * 2**attempt)
    - backoff_factor: alias accepte a la construction (prioritaire si fourni)
    - max_backoff: plafond
    - jitter: amplitude aleatoire ajoutee (0 = deterministe, defaut pour tests)
    - statuses: statuts HTTP qui declenchent un retry
    - methods: methodes idempotentes retentees (POST exclu par defaut)
    - respect_retry_after: honore le header Retry-After (min(backoff, retry-after)? non: max)
    - on_retry: callback(attempt, method, status, sleep_secs)
    """

    attempts: int = 3
    backoff: float = 0.4
    max_backoff: float = 8.0
    jitter: float = 0.0
    statuses: Sequence[int] = field(default_factory=lambda: (408, 425, 429, 500, 502, 503, 504))
    methods: Iterable[str] = field(
        default_factory=lambda: ("GET", "HEAD", "OPTIONS", "PUT", "DELETE", "TRACE")
    )
    respect_retry_after: bool = True
    on_retry: Optional[OnRetry] = None
    backoff_factor: Optional[float] = None

    def __post_init__(self) -> None:
        if self.backoff_factor is not None:
            self.backoff = float(self.backoff_factor)
        self.attempts = max(1, int(self.attempts))

    def should(self, method: str, status: int | None = None, exc: BaseException | None = None) -> bool:
        if method.upper() not in {m.upper() for m in self.methods}:
            return False
        if exc is not None:
            return True
        return status in self.statuses

    def delay(self, attempt: int) -> float:
        base = min(self.max_backoff, self.backoff * (2 ** max(0, attempt)))
        if self.jitter and self.jitter > 0:
            base = base + random.uniform(0, self.jitter)
            base = min(self.max_backoff + self.jitter, base)
        return base

    def sleep_secs(
        self,
        attempt: int,
        *,
        headers: Optional[Mapping[str, str]] = None,
    ) -> float:
        secs = self.delay(attempt)
        if self.respect_retry_after and headers:
            raw = ""
            for k, v in headers.items():
                if k.lower() == "retry-after":
                    raw = v
                    break
            parsed = parse_retry_after(raw) if raw else None
            if parsed is not None:
                secs = max(secs, min(parsed, self.max_backoff * 4))
        return secs

    def notify(self, attempt: int, method: str, status: Optional[int], sleep_secs: float) -> None:
        if self.on_retry is not None:
            try:
                self.on_retry(attempt, method, status, sleep_secs)
            except Exception:
                pass
