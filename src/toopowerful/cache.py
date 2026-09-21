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
    """Simple in-memory TTL cache keyed by METHOD + URL."""

    def __init__(self, ttl: float = 30.0, max_items: int = 256) -> None:
        self.ttl = ttl
        self.max_items = max_items
        self._store: dict[str, _Entry] = {}

    def key(self, method: str, url: str) -> str:
        return f"{method.upper()} {url}"

    def get(self, method: str, url: str) -> Optional[Response]:
        entry = self._store.get(self.key(method, url))
        if not entry:
            return None
        if entry.expires_at < time.monotonic():
            self._store.pop(self.key(method, url), None)
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
        )

    def set(self, method: str, url: str, response: Response) -> None:
        if len(self._store) >= self.max_items:
            oldest = next(iter(self._store))
            self._store.pop(oldest, None)
        self._store[self.key(method, url)] = _Entry(response, time.monotonic() + self.ttl)

    def clear(self) -> None:
        self._store.clear()
