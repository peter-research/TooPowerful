from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.cookiejar import CookieJar
from typing import Any, Callable, Mapping, Optional, Sequence, Union

from .auth import Auth, resolve_auth
from .cache import MemoryCache
from .limiter import RateLimiter
from .middleware import Middleware, build_middleware, request_id as request_id_hook
from .models import PreparedRequest, Response, Timeout, join_url
from .retry import Retry
from . import transport as _transport_mod

TransportFn = Callable[..., Response]


class Client:
    """Session persistante — cookies, auth, retry, cache, middleware, redirects."""

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
        transport: Optional[TransportFn] = None,
        follow_redirects: Optional[bool] = None,
        request_id: bool = True,
    ) -> None:
        self.base_url = base_url
        self.headers = dict(headers or {})
        self.params = dict(params or {})
        self.timeout = Timeout.coerce(timeout)
        self.retry = retry or Retry()
        self.cache = cache
        self.middleware = build_middleware(middleware, event_hooks)
        if request_id:
            rid = request_id_hook()
            self.middleware.before.insert(0, rid)
        self.auth: Optional[Auth] = resolve_auth(auth)
        self.verify = verify
        self.allow_redirects = follow_redirects if follow_redirects is not None else allow_redirects
        self.max_redirects = max_redirects
        self.proxies = dict(proxies) if proxies else None
        self.trust_env = trust_env
        self.cert = cert
        self.limiter = limiter
        self._transport: TransportFn = transport or _transport_mod.send
        self.cookiejar = CookieJar()
        self._extra_cookies: dict[str, str] = {}
        if cookies:
            self.set_cookies(cookies)
        self.stats = {"requests": 0, "retries": 0, "cache_hits": 0, "errors": 0}

    def set_cookies(self, cookies: Mapping[str, str]) -> None:
        self._extra_cookies.update({str(k): str(v) for k, v in cookies.items()})

    def get_cookies(self) -> dict[str, str]:
        out = dict(self._extra_cookies)
        for c in self.cookiejar:
            out[c.name] = c.value
        return out

    def clear_cookies(self) -> None:
        self._extra_cookies.clear()
        try:
            self.cookiejar.clear()
        except Exception:
            pass

    @property
    def cookies(self) -> dict[str, str]:
        return self.get_cookies()

    def close(self) -> None:
        pass

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _merged_params(self, params: Optional[Mapping[str, Any]]) -> dict[str, Any]:
        merged = dict(self.params)
        if params:
            merged.update(params)
        return merged

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        path_params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
        data: Optional[Mapping[str, object]] = None,
        json: Any = None,
        content: Optional[bytes] = None,
        files: Optional[Mapping[str, Any]] = None,
        auth: Optional[object] = None,
        timeout: Union[None, float, Timeout] = None,
        cache: Optional[bool] = None,
        allow_redirects: Optional[bool] = None,
        follow_redirects: Optional[bool] = None,
        stream: bool = False,
    ) -> Response:
        if self.limiter is not None:
            self.limiter.acquire()
        merged_headers = {**self.headers, **(headers or {})}
        if self._extra_cookies:
            cookie_hdr = "; ".join(f"{k}={v}" for k, v in self._extra_cookies.items())
            if "Cookie" in merged_headers:
                merged_headers["Cookie"] = merged_headers["Cookie"] + "; " + cookie_hdr
            else:
                merged_headers["Cookie"] = cookie_hdr

        body, merged_headers = _transport_mod.encode_body(
            data=data,
            json_body=json,
            content=content,
            files=files,
            headers=merged_headers,
        )
        req_auth = resolve_auth(auth) if auth is not None else self.auth
        if req_auth is not None:
            req_auth.apply(merged_headers)

        target = join_url(self.base_url, url)
        if req_auth is not None and hasattr(req_auth, "inject_url"):
            try:
                target = req_auth.inject_url(target)  # type: ignore[attr-defined]
            except Exception:
                pass
        if req_auth is not None and req_auth.__class__.__name__ == "ApiKeyAuth":
            cookie_name = getattr(req_auth, "cookie_name", None)
            if cookie_name:
                api_key = getattr(req_auth, "api_key", "")
                if "Cookie" in merged_headers:
                    merged_headers["Cookie"] += f"; {cookie_name}={api_key}"
                else:
                    merged_headers["Cookie"] = f"{cookie_name}={api_key}"

        req = PreparedRequest(
            method=method.upper(),
            url=target,
            headers=merged_headers,
            body=body,
            json=None,
            params=self._merged_params(params),
            path_params=dict(path_params or {}),
        )
        req = self.middleware.apply_before(req)
        use_cache = cache if cache is not None else (self.cache is not None and req.method == "GET" and not stream)
        full_url = req.with_params()
        if use_cache and self.cache is not None:
            hit = self.cache.get(req.method, full_url)
            if hit is not None:
                self.stats["cache_hits"] += 1
                return self.middleware.apply_after(hit)

        follow = self.allow_redirects
        if allow_redirects is not None:
            follow = allow_redirects
        if follow_redirects is not None:
            follow = follow_redirects
        last_exc: Optional[BaseException] = None
        response: Optional[Response] = None
        attempts = max(1, self.retry.attempts)
        for attempt in range(attempts):
            try:
                self.stats["requests"] += 1
                response = self._transport(
                    req,
                    Timeout.coerce(timeout or self.timeout),
                    verify=self.verify,
                    cookiejar=self.cookiejar,
                    allow_redirects=follow,
                    max_redirects=self.max_redirects,
                    proxies=self.proxies,
                    trust_env=self.trust_env,
                    cert=self.cert,
                    stream=stream,
                    auth=req_auth,
                )
                last_exc = None
                if attempt + 1 < attempts and self.retry.should(req.method, status=response.status_code):
                    secs = self.retry.sleep_secs(attempt, headers=response.headers)
                    self.stats["retries"] += 1
                    self.retry.notify(attempt, req.method, response.status_code, secs)
                    time.sleep(secs)
                    continue
                break
            except BaseException as exc:
                last_exc = exc
                if attempt + 1 < attempts and self.retry.should(req.method, exc=exc):
                    secs = self.retry.sleep_secs(attempt)
                    self.stats["retries"] += 1
                    self.retry.notify(attempt, req.method, None, secs)
                    time.sleep(secs)
                    continue
                self.stats["errors"] += 1
                raise
        if response is None:
            self.stats["errors"] += 1
            raise last_exc  # type: ignore[misc]
        response = self.middleware.apply_after(response)
        if use_cache and self.cache is not None and response.ok:
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

    def stream(self, method: str, url: str, **kw: Any) -> Response:
        """Requete en streaming (body lu a la volee via iter_content)."""
        kw["stream"] = True
        kw["cache"] = False
        return self.request(method, url, **kw)

    def download(self, url: str, path: str, **kw: Any) -> int:
        """GET streaming -> fichier. Retourne les octets ecrits."""
        resp = self.stream("GET", url, **kw)
        return resp.download(path)

    def bulk(self, operations: Sequence[Mapping[str, Any]], **kw: Any) -> list[Response]:
        """ operations: [{'method': 'GET', 'url': '/x', ...}] — sequentiel. """
        out: list[Response] = []
        for op in operations:
            op = dict(op)
            method = str(op.pop("method", "GET"))
            url = str(op.pop("url", "/"))
            merged = {**kw, **op}
            out.append(self.request(method, url, **merged))
        return out

    def map(
        self,
        method: str,
        urls: Sequence[str],
        *,
        max_workers: int = 8,
        return_exceptions: bool = False,
        **kw: Any,
    ) -> list[Response]:
        results: list[Optional[Response]] = [None] * len(urls)
        errors: list[Optional[BaseException]] = [None] * len(urls)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(self.request, method, url, **kw): i for i, url in enumerate(urls)}
            for fut in as_completed(futures):
                i = futures[fut]
                try:
                    results[i] = fut.result()
                except BaseException as exc:
                    if not return_exceptions:
                        raise
                    errors[i] = exc
        if return_exceptions:
            out: list[Response] = []
            for r, e in zip(results, errors):
                if e is not None:
                    raise e
                out.append(r)  # type: ignore[arg-type]
            return out
        return [r for r in results if r is not None]


_default = Client(request_id=False)


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
