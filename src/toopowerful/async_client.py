from __future__ import annotations

import asyncio
from typing import Any, Mapping, Optional, Sequence, Union

from .cache import MemoryCache
from .client import Client
from .limiter import RateLimiter
from .middleware import Middleware
from .models import Response, Timeout
from .retry import Retry


class AsyncClient:
    """Meme API que Client, async (transport via to_thread)."""

    def __init__(
        self,
        base_url: str = "",
        headers: Optional[Mapping[str, str]] = None,
        timeout: Union[None, float, Timeout] = 30,
        retry: Optional[Retry] = None,
        cache: Optional[MemoryCache] = None,
        middleware: Optional[Middleware] = None,
        auth: Optional[object] = None,
        cookies: Optional[Mapping[str, str]] = None,
        verify: Union[bool, str] = True,
        allow_redirects: bool = True,
        max_redirects: int = 10,
        params: Optional[Mapping[str, Any]] = None,
        proxies: Optional[Mapping[str, str]] = None,
        trust_env: bool = True,
        cert: Optional[Union[str, tuple]] = None,
        event_hooks: Optional[dict] = None,
        limiter: Optional[RateLimiter] = None,
        transport: Optional[Any] = None,
        max_concurrency: int = 16,
        follow_redirects: Optional[bool] = None,
        request_id: bool = True,
    ) -> None:
        self._sync = Client(
            base_url=base_url,
            headers=headers,
            timeout=timeout,
            retry=retry,
            cache=cache,
            middleware=middleware,
            auth=auth,
            cookies=cookies,
            verify=verify,
            allow_redirects=allow_redirects,
            max_redirects=max_redirects,
            params=params,
            proxies=proxies,
            trust_env=trust_env,
            cert=cert,
            event_hooks=event_hooks,
            limiter=limiter,
            transport=transport,
            follow_redirects=follow_redirects,
            request_id=request_id,
        )
        self._sem = asyncio.Semaphore(max(1, max_concurrency))

    @property
    def stats(self) -> dict:
        return self._sync.stats

    @property
    def cookies(self) -> dict[str, str]:
        return self._sync.cookies

    def set_cookies(self, cookies: Mapping[str, str]) -> None:
        self._sync.set_cookies(cookies)

    async def __aenter__(self) -> "AsyncClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        self._sync.close()

    async def request(self, method: str, url: str, **kw: Any) -> Response:
        async with self._sem:
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

    async def stream(self, method: str, url: str, **kw: Any) -> Response:
        return await self.request(method, url, stream=True, cache=False, **kw)

    async def download(self, url: str, path: str, **kw: Any) -> int:
        resp = await self.stream("GET", url, **kw)
        return await asyncio.to_thread(resp.download, path)

    async def bulk(self, operations: Sequence[Mapping[str, Any]], **kw: Any) -> list[Response]:
        out: list[Response] = []
        for op in operations:
            op = dict(op)
            method = str(op.pop("method", "GET"))
            url = str(op.pop("url", "/"))
            out.append(await self.request(method, url, **{**kw, **op}))
        return out

    async def gather(self, method: str, urls: Sequence[str], **kw: Any) -> list[Response]:
        return list(await asyncio.gather(*(self.request(method, u, **kw) for u in urls)))

    async def map(self, method: str, urls: Sequence[str], **kw: Any) -> list[Response]:
        return await self.gather(method, urls, **kw)
