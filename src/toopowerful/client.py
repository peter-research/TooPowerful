from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Mapping, Optional, Sequence, Union

from .cache import MemoryCache
from .middleware import Middleware
from .models import PreparedRequest, Response, Timeout, join_url
from .retry import Retry
from . import transport


class Client:
    """Session persistante — retry, cache, middleware."""

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
        self.base_url = base_url
        self.headers = dict(headers or {})
        self.timeout = Timeout.coerce(timeout)
        self.retry = retry or Retry()
        self.cache = cache
        self.middleware = middleware or Middleware()
        self.verify = verify

    def close(self) -> None:
        if self.cache:
            self.cache.clear()

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        data: Optional[Mapping[str, object]] = None,
        json: Any = None,
        content: Optional[bytes] = None,
        timeout: Union[None, float, Timeout] = None,
        cache: Optional[bool] = None,
    ) -> Response:
        merged_headers = {**self.headers, **(headers or {})}
        body, merged_headers = transport.encode_body(data=data, json_body=json, content=content, headers=merged_headers)
        req = PreparedRequest(
            method=method.upper(),
            url=join_url(self.base_url, url),
            headers=merged_headers,
            body=body,
            json=None,
            params=params or {},
        )
        req = self.middleware.apply_before(req)
        use_cache = cache if cache is not None else bool(self.cache) and req.method == "GET"
        full_url = req.with_params()
        if use_cache and self.cache:
            hit = self.cache.get(req.method, full_url)
            if hit is not None:
                return self.middleware.apply_after(hit)

        last_exc: Optional[BaseException] = None
        response: Optional[Response] = None
        attempts = max(1, self.retry.attempts)
        for attempt in range(attempts):
            try:
                response = transport.send(req, Timeout.coerce(timeout or self.timeout), verify=self.verify)
                last_exc = None
                if attempt + 1 < attempts and self.retry.should(req.method, status=response.status_code):
                    time.sleep(self.retry.delay(attempt))
                    continue
                break
            except BaseException as exc:
                last_exc = exc
                if attempt + 1 < attempts and self.retry.should(req.method, exc=exc):
                    time.sleep(self.retry.delay(attempt))
                    continue
                raise
        if response is None:
            raise last_exc  # type: ignore[misc]
        response = self.middleware.apply_after(response)
        if use_cache and self.cache and response.ok:
            self.cache.set(req.method, full_url, response)
        return response

    def get(self, url: str, **kw: Any) -> Response:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw: Any) -> Response:
        return self.request("POST", url, **kw)

    def put(self, url: str, **kw: Any) -> Response:
        return self.request("PUT", url, **kw)

    def patch(self, url: str, **kw: Any) -> Response:
        return self.request("PATCH", url, **kw)

    def delete(self, url: str, **kw: Any) -> Response:
        return self.request("DELETE", url, **kw)

    def head(self, url: str, **kw: Any) -> Response:
        return self.request("HEAD", url, **kw)

    def options(self, url: str, **kw: Any) -> Response:
        return self.request("OPTIONS", url, **kw)

    def map(self, method: str, urls: Sequence[str], *, max_workers: int = 8, **kw: Any) -> list[Response]:
        results: list[Optional[Response]] = [None] * len(urls)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(self.request, method, url, **kw): i for i, url in enumerate(urls)}
            for fut in as_completed(futures):
                results[futures[fut]] = fut.result()
        return [r for r in results if r is not None]


_default = Client()


def request(method: str, url: str, **kw: Any) -> Response:
    return _default.request(method, url, **kw)


def get(url: str, **kw: Any) -> Response:
    return _default.get(url, **kw)


def post(url: str, **kw: Any) -> Response:
    return _default.post(url, **kw)


def put(url: str, **kw: Any) -> Response:
    return _default.put(url, **kw)


def patch(url: str, **kw: Any) -> Response:
    return _default.patch(url, **kw)


def delete(url: str, **kw: Any) -> Response:
    return _default.delete(url, **kw)


def head(url: str, **kw: Any) -> Response:
    return _default.head(url, **kw)


def options(url: str, **kw: Any) -> Response:
    return _default.options(url, **kw)
