from __future__ import annotations

import asyncio
from typing import Any, Mapping, Optional, Sequence, Union

from .cache import MemoryCache
from .client import Client
from .middleware import Middleware
from .models import Response, Timeout
from .retry import Retry


class AsyncClient:
    """Meme API que Client, 100% async (transport dans un thread)."""

    def __init__(
        self,
        base_url: str = "",
        headers: Optional[Mapping[str, str]] = None,
        timeout: Union[None, float, Timeout] = 30,
        retry: Optional[Retry] = None,
        cache: Optional[MemoryCache] = None,
        middleware: Optional[Middleware] = None,
        verify: bool = True,
    ) -> None:
        self._sync = Client(
            base_url=base_url,
            headers=headers,
            timeout=timeout,
            retry=retry,
            cache=cache,
            middleware=middleware,
            verify=verify,
        )

    async def __aenter__(self) -> "AsyncClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        self._sync.close()

    async def request(self, method: str, url: str, **kw: Any) -> Response:
        return await asyncio.to_thread(self._sync.request, method, url, **kw)

    async def get(self, url: str, **kw: Any) -> Response:
        return await self.request("GET", url, **kw)

    async def post(self, url: str, **kw: Any) -> Response:
        return await self.request("POST", url, **kw)

    async def put(self, url: str, **kw: Any) -> Response:
        return await self.request("PUT", url, **kw)

    async def patch(self, url: str, **kw: Any) -> Response:
        return await self.request("PATCH", url, **kw)

    async def delete(self, url: str, **kw: Any) -> Response:
        return await self.request("DELETE", url, **kw)

    async def head(self, url: str, **kw: Any) -> Response:
        return await self.request("HEAD", url, **kw)

    async def options(self, url: str, **kw: Any) -> Response:
        return await self.request("OPTIONS", url, **kw)

    async def gather(self, method: str, urls: Sequence[str], **kw: Any) -> list[Response]:
        return list(await asyncio.gather(*(self.request(method, u, **kw) for u in urls)))
