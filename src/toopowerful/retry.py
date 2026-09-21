from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence


@dataclass
class Retry:
    """Exponential backoff retry policy."""

    attempts: int = 3
    backoff: float = 0.4
    max_backoff: float = 8.0
    statuses: Sequence[int] = field(default_factory=lambda: (408, 429, 500, 502, 503, 504))
    methods: Iterable[str] = field(
        default_factory=lambda: ("GET", "HEAD", "OPTIONS", "PUT", "DELETE", "TRACE")
    )

    def should(self, method: str, status: int | None = None, exc: BaseException | None = None) -> bool:
        if method.upper() not in {m.upper() for m in self.methods}:
            return False
        if exc is not None:
            return True
        return status in self.statuses

    def delay(self, attempt: int) -> float:
        return min(self.max_backoff, self.backoff * (2 ** max(0, attempt)))
