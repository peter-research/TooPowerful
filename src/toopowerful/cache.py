from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from .models import Response


@dataclass
class _Entry:
    response: Response
    expires_at: float


class MemoryCache:
    """In-memory TTL cache keyed by METHOD + URL."""

    def __init__(self, ttl: float = 30.0, max_items: int = 512) -> None:
        self.ttl = ttl
        self.max_items = max_items
        self._store: dict[str, _Entry] = {}

    def key(self, method: str, url: str, extra: str = "") -> str:
        return f"{method.upper()} {url} {extra}".strip()

    def get(self, method: str, url: str, extra: str = "") -> Optional[Response]:
        entry = self._store.get(self.key(method, url, extra))
        if not entry:
            return None
        if entry.expires_at < time.monotonic():
            self._store.pop(self.key(method, url, extra), None)
            return None
        cached = entry.response
        return Response(
            status_code=cached.status_code,
            headers=dict(cached.headers),
            content=cached.content,
            url=cached.url,
            request=cached.request,
            elapsed=0.0,
            from_cache=True,
            history=[],
            cookies=dict(cached.cookies),
        )

    def set(self, method: str, url: str, response: Response, extra: str = "") -> None:
        if len(self._store) >= self.max_items:
            oldest = next(iter(self._store))
            self._store.pop(oldest, None)
        self._store[self.key(method, url, extra)] = _Entry(response, time.monotonic() + self.ttl)

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)
