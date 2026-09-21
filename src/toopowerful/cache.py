from __future__ import annotations

import base64
import fnmatch
import hashlib
import json
import os
import tempfile
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional, Sequence

from .models import Response


@dataclass
class _Entry:
    response: Response
    expires_at: float


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    sets: int = 0
    evictions: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


CACHEABLE_STATUSES: tuple[int, ...] = (200, 203, 204, 206, 300, 301, 308)


def _snapshot(resp: Response, *, from_cache: bool) -> Response:
    return Response(
        status_code=resp.status_code,
        headers=dict(resp.headers),
        content=resp.content,
        url=resp.url,
        request=resp.request,
        elapsed=0.0 if from_cache else resp.elapsed,
        from_cache=from_cache,
        history=[],
        cookies=dict(resp.cookies),
    )


class MemoryCache:
    """In-memory TTL cache LRU keyed by METHOD + URL."""

    def __init__(
        self,
        ttl: float = 30.0,
        max_items: int = 512,
        cacheable_statuses: Sequence[int] = CACHEABLE_STATUSES,
    ) -> None:
        self.ttl = ttl
        self.max_items = max_items
        self.cacheable_statuses = tuple(cacheable_statuses)
        self._store: "OrderedDict[str, _Entry]" = OrderedDict()
        self.stats = CacheStats()

    def key(self, method: str, url: str, extra: str = "") -> str:
        return f"{method.upper()} {url} {extra}".strip()

    def get(self, method: str, url: str, extra: str = "") -> Optional[Response]:
        k = self.key(method, url, extra)
        entry = self._store.get(k)
        if not entry:
            self.stats.misses += 1
            return None
        if entry.expires_at < time.monotonic():
            self._store.pop(k, None)
            self.stats.misses += 1
            return None
        self._store.move_to_end(k)
        self.stats.hits += 1
        return _snapshot(entry.response, from_cache=True)

    def set(self, method: str, url: str, response: Response, extra: str = "") -> None:
        if response.status_code not in self.cacheable_statuses:
            return
        k = self.key(method, url, extra)
        if k in self._store:
            self._store.move_to_end(k)
        elif len(self._store) >= self.max_items:
            self._store.popitem(last=False)
            self.stats.evictions += 1
        self._store[k] = _Entry(_snapshot(response, from_cache=False), time.monotonic() + self.ttl)
        self.stats.sets += 1

    def invalidate(self, pattern: str) -> int:
        """Supprime les cles dont l'URL matche un glob (ex: '*/users/*')."""
        doomed = [k for k in self._store if fnmatch.fnmatch(k, pattern) or fnmatch.fnmatch(k.split(" ", 1)[-1], pattern)]
        for k in doomed:
            self._store.pop(k, None)
        return len(doomed)

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)


class FileCache:
    """Cache disque persistant (un fichier JSON par entree, body en base64).

    Reutilise la meme API que MemoryCache: get/set/clear/invalidate/key/stats.
    """

    def __init__(
        self,
        directory: str,
        ttl: float = 300.0,
        max_items: int = 2048,
        cacheable_statuses: Sequence[int] = CACHEABLE_STATUSES,
    ) -> None:
        self.directory = os.path.abspath(directory)
        os.makedirs(self.directory, exist_ok=True)
        self.ttl = ttl
        self.max_items = max_items
        self.cacheable_statuses = tuple(cacheable_statuses)
        self.stats = CacheStats()

    def key(self, method: str, url: str, extra: str = "") -> str:
        raw = f"{method.upper()} {url} {extra}".strip()
        return hashlib.sha256(raw.encode("utf-8")).hexdigest() + ".json"

    def _path(self, method: str, url: str, extra: str = "") -> str:
        return os.path.join(self.directory, self.key(method, url, extra))

    def get(self, method: str, url: str, extra: str = "") -> Optional[Response]:
        from .models import PreparedRequest

        path = self._path(method, url, extra)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, ValueError):
            self.stats.misses += 1
            return None
        if payload.get("expires_at", 0) < time.time():
            try:
                os.remove(path)
            except OSError:
                pass
            self.stats.misses += 1
            return None
        self.stats.hits += 1
        req = PreparedRequest(method.upper(), payload.get("url", url))
        return Response(
            status_code=int(payload["status"]),
            headers=dict(payload.get("headers", {})),
            content=base64.b64decode(payload.get("body_b64", "")),
            url=payload.get("url", url),
            request=req,
            elapsed=0.0,
            from_cache=True,
            history=[],
            cookies=dict(payload.get("cookies", {})),
        )

    def set(self, method: str, url: str, response: Response, extra: str = "") -> None:
        if response.status_code not in self.cacheable_statuses:
            return
        try:
            entries = [f for f in os.listdir(self.directory) if f.endswith(".json")]
            if len(entries) >= self.max_items:
                oldest = min(
                    (os.path.join(self.directory, f) for f in entries),
                    key=lambda p: os.path.getmtime(p),
                )
                os.remove(oldest)
                self.stats.evictions += 1
        except OSError:
            pass
        payload = {
            "status": response.status_code,
            "headers": dict(response.headers),
            "body_b64": base64.b64encode(response.content).decode("ascii"),
            "url": response.url,
            "cookies": dict(response.cookies),
            "expires_at": time.time() + self.ttl,
        }
        path = self._path(method, url, extra)
        try:
            fd, tmp = tempfile.mkstemp(dir=self.directory, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
            os.replace(tmp, path)
            self.stats.sets += 1
        except OSError:
            pass

    def invalidate(self, pattern: str) -> int:
        removed = 0
        try:
            for fname in os.listdir(self.directory):
                if fnmatch.fnmatch(fname, pattern):
                    try:
                        os.remove(os.path.join(self.directory, fname))
                        removed += 1
                    except OSError:
                        pass
        except OSError:
            pass
        return removed

    def clear(self) -> None:
        try:
            for fname in os.listdir(self.directory):
                if fname.endswith((".json", ".tmp")):
                    try:
                        os.remove(os.path.join(self.directory, fname))
                    except OSError:
                        pass
        except OSError:
            pass

    def __len__(self) -> int:
        try:
            return sum(1 for f in os.listdir(self.directory) if f.endswith(".json"))
        except OSError:
            return 0
