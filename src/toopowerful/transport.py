from __future__ import annotations

import json
import mimetypes
import os
import socket
import ssl
import time
import uuid
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from typing import Any, BinaryIO, Iterator, Mapping, Optional, Tuple, Union
from urllib.parse import urlencode, urljoin, urlsplit

from .models import (
    ConnectionError as TPConnectionError,
)
from .models import (
    PreparedRequest,
    ProxyError,
    Response,
    SSLError,
    Timeout,
    TimeoutError,
    TooManyRedirects,
    TooPowerfulError,
    header_get,
)

FileValue = Union[bytes, Tuple[str, bytes], Tuple[str, bytes, str], Tuple[str, BinaryIO], Tuple[str, BinaryIO, str]]


def _user_agent() -> str:
    try:
        from . import __version__

        return f"TooPowerful/{__version__}"
    except Exception:
        return "TooPowerful/0.1.0"


def _read_file_part(item: Any) -> tuple[str, bytes, Optional[str]]:
    """Normalise une valeur files -> (filename, bytes, content_type|None)."""
    if isinstance(item, bytes):
        return "file", item, None
    if hasattr(item, "read") and not isinstance(item, tuple):
        data = item.read()
        if isinstance(data, str):
            data = data.encode("utf-8")
        name = getattr(item, "name", "file")
        filename = os.path.basename(str(name)) if isinstance(name, str) else "file"
        return filename, data, None
    if isinstance(item, tuple):
        if len(item) == 2:
            filename, content = item
            if hasattr(content, "read"):
                data = content.read()
                if isinstance(data, str):
                    data = data.encode("utf-8")
                content = data
            assert isinstance(content, (bytes, bytearray)), "files content must be bytes or file-like"
            return str(filename), bytes(content), None
        elif len(item) == 3:
            filename, content, ctype = item
            if hasattr(content, "read"):
                data = content.read()
                if isinstance(data, str):
                    data = data.encode("utf-8")
                content = data
            return str(filename), bytes(content), str(ctype)
    raise TypeError("files values must be bytes, file-like, (filename, bytes) or (filename, bytes, ctype)")


def encode_multipart(
    data: Optional[Mapping[str, Any]] = None,
    files: Optional[Mapping[str, FileValue]] = None,
) -> tuple[bytes, str]:
    boundary = f"----TooPowerful{uuid.uuid4().hex}"
    lines: list[bytes] = []

    def part(name: str, value: bytes, filename: Optional[str] = None, content_type: Optional[str] = None) -> None:
        lines.append(f"--{boundary}".encode())
        if filename:
            disp = f'Content-Disposition: form-data; name="{name}"; filename="{filename}"'
            lines.append(disp.encode())
            ctype = content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
            lines.append(f"Content-Type: {ctype}".encode())
        else:
            lines.append(f'Content-Disposition: form-data; name="{name}"'.encode())
        lines.append(b"")
        lines.append(value)

    for key, val in (data or {}).items():
        if hasattr(val, "read"):
            raw = val.read()  # type: ignore[union-attr]
            part(str(key), raw if isinstance(raw, bytes) else str(raw).encode("utf-8"))
        else:
            part(str(key), str(val).encode("utf-8"))

    for key, item in (files or {}).items():
        filename, content, ctype = _read_file_part(item)
        part(str(key), content, filename=filename, content_type=ctype)

    lines.append(f"--{boundary}--".encode())
    lines.append(b"")
    body = b"\r\n".join(lines)
    return body, f"multipart/form-data; boundary={boundary}"


def encode_body(
    data: Optional[Mapping[str, object]] = None,
    json_body: object = None,
    content: Optional[bytes] = None,
    files: Optional[Mapping[str, FileValue]] = None,
    headers: Optional[dict[str, str]] = None,
) -> tuple[Optional[bytes], dict[str, str]]:
    headers = dict(headers or {})
    if content is not None:
        if hasattr(content, "read"):
            raw = content.read()  # type: ignore[union-attr]
            content = raw if isinstance(raw, bytes) else str(raw).encode("utf-8")
        return content, headers
    if files:
        body, ctype = encode_multipart(data=data, files=files)
        headers["Content-Type"] = ctype
        return body, headers
    if json_body is not None:
        payload = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        headers.setdefault("Content-Type", "application/json; charset=utf-8")
        return payload, headers
    if data is not None:
        if hasattr(data, "read"):
            raw = data.read()  # type: ignore[union-attr]
            return (raw if isinstance(raw, bytes) else str(raw).encode("utf-8")), headers
        normalized: dict[str, Any] = {}
        for k, v in data.items():
            if hasattr(v, "read"):
                chunk = v.read()  # type: ignore[union-attr]
                normalized[str(k)] = chunk.decode("utf-8", "replace") if isinstance(chunk, bytes) else str(chunk)
            else:
                normalized[str(k)] = v
        payload = urlencode(normalized, doseq=True).encode("utf-8")
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        return payload, headers
    return None, headers


def _extract_cookies(headers: Mapping[str, str]) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() != "set-cookie":
            continue
        first = value.split(";", 1)[0]
        if "=" in first:
            name, val = first.split("=", 1)
            cookies[name.strip()] = val.strip()
    return cookies


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        return None


def get_env_proxies() -> dict[str, str]:
    """Proxies depuis l'environnement (http_proxy/https_proxy/all_proxy, no_proxy)."""
    proxies: dict[str, str] = {}
    for scheme in ("http", "https", "all"):
        for var in (f"{scheme}_proxy", f"{scheme.upper()}_PROXY"):
            val = os.environ.get(var)
            if val:
                proxies[scheme] = val
                break
    return proxies


def should_bypass_proxy(url: str, no_proxy: Optional[str] = None) -> bool:
    raw = no_proxy if no_proxy is not None else os.environ.get("no_proxy") or os.environ.get("NO_PROXY") or ""
    if not raw.strip():
        return False
    host = (urlsplit(url).hostname or "").lower()
    if not host:
        return False
    for token in raw.split(","):
        token = token.strip().lower().lstrip(".")
        if not token:
            continue
        if token == "*" or host == token or host.endswith("." + token):
            return True
    return False


def resolve_proxy(url: str, proxies: Optional[Mapping[str, str]], trust_env: bool = True) -> Optional[str]:
    scheme = (urlsplit(url).scheme or "http").lower()
    if proxies:
        for key in (scheme, "all"):
            if key in proxies and proxies[key]:
                if should_bypass_proxy(url):
                    return None
                return str(proxies[key])
        return None
    if not trust_env:
        return None
    if should_bypass_proxy(url):
        return None
    env = get_env_proxies()
    return env.get(scheme) or env.get("all")


def _request_uri(url: str) -> str:
    parts = urlsplit(url)
    uri = parts.path or "/"
    if parts.query:
        uri += "?" + parts.query
    return uri


def _same_host(a: str, b: str) -> bool:
    pa, pb = urlsplit(a), urlsplit(b)
    return (pa.scheme.lower(), pa.hostname, pa.port) == (pb.scheme.lower(), pb.hostname, pb.port)


def _build_ssl_context(verify: Union[bool, str], cert: Optional[Union[str, Tuple[str, str]]] = None) -> ssl.SSLContext:
    if isinstance(verify, str):
        ctx = ssl.create_default_context(cafile=verify)
    elif verify:
        ctx = ssl.create_default_context()
    else:
        ctx = ssl._create_unverified_context()
    if cert:
        if isinstance(cert, (tuple, list)):
            ctx.load_cert_chain(certfile=str(cert[0]), keyfile=str(cert[1]) if len(cert) > 1 else None)
        else:
            ctx.load_cert_chain(certfile=str(cert))
    return ctx


def _map_open_error(exc: Exception, req: PreparedRequest) -> TooPowerfulError:
    from .models import RequestError

    if isinstance(exc, (socket.timeout, TimeoutError)):
        return TimeoutError(f"timeout for {req.method} {req.url}: {exc}")
    name = type(exc).__name__
    msg = str(exc).lower()
    if "timed out" in msg or name in ("TimeoutError", "ReadTimeoutError", "ConnectTimeoutError"):
        return TimeoutError(f"timeout for {req.method} {req.url}: {exc}")
    if isinstance(exc, ssl.SSLError) or "ssl" in name.lower() or "certificate" in msg:
        return SSLError(f"SSL error for {req.url}: {exc}")
    if "proxy" in msg or isinstance(exc, urllib.error.URLError) and "proxy" in str(getattr(exc, "reason", "")).lower():
        from .models import ProxyError as _PE

        return _PE(f"proxy error for {req.url}: {exc}")
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, ssl.SSLError):
            return SSLError(f"SSL error for {req.url}: {reason}")
        return TPConnectionError(f"connection failed for {req.url}: {reason}")
    if isinstance(exc, (ConnectionError, OSError)):
        return TPConnectionError(f"connection failed for {req.url}: {exc}")
    return RequestError(f"request failed for {req.url}: {exc}", request=req)


def send(
    req: PreparedRequest,
    timeout: Timeout,
    *,
    verify: Union[bool, str] = True,
    cookiejar: Optional[CookieJar] = None,
    allow_redirects: bool = True,
    max_redirects: int = 10,
    proxies: Optional[Mapping[str, str]] = None,
    trust_env: bool = True,
    cert: Optional[Union[str, Tuple[str, str]]] = None,
    stream: bool = False,
    auth: Optional[object] = None,
) -> Response:
    history: list[Response] = []
    current = req
    redirects = 0
    jar = cookiejar if cookiejar is not None else CookieJar()
    context = _build_ssl_context(verify, cert)
    proxy_url = resolve_proxy(current.with_params(), proxies, trust_env)
    handlers: list[Any] = [_NoRedirect(), urllib.request.HTTPCookieProcessor(jar)]
    if proxy_url:
        handlers.append(urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))
    handlers.append(urllib.request.HTTPSHandler(context=context))
    opener = urllib.request.build_opener(*handlers)
    original_host: Optional[str] = None

    digest = None
    if auth is not None and auth.__class__.__name__ == "DigestAuth":
        digest = auth

    def _do_open(url: str, headers: dict[str, str], body: Optional[bytes], method: str, total: float):
        urllib_req = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
        return opener.open(urllib_req, timeout=total)

    while True:
        url = current.with_params()
        if original_host is None:
            original_host = urlsplit(url).hostname
        headers = {"User-Agent": _user_agent(), **current.headers}
        if original_host and urlsplit(url).hostname != original_host:
            headers = {k: v for k, v in headers.items() if k.lower() != "authorization"}
        body = current.body
        if current.json is not None and body is None:
            body, headers = encode_body(json_body=current.json, headers=headers)

        started = time.perf_counter()
        total = timeout.total if timeout.total is not None else timeout.connect + timeout.read
        status = 0
        resp_headers: dict[str, str] = {}
        final_url = url
        content = b""
        raw_stream = None
        try:
            raw = _do_open(url, headers, body, current.method, total)
            try:
                status = raw.getcode() or 0
                resp_headers = {k: v for k, v in raw.headers.items()}
                final_url = raw.geturl()
                if stream and status < 400:
                    held = raw

                    def reader(chunk_size: int, _held: Any = held) -> Iterator[bytes]:
                        try:
                            while True:
                                chunk = _held.read(chunk_size or 8192)
                                if not chunk:
                                    break
                                yield chunk
                        finally:
                            try:
                                _held.close()
                            except Exception:
                                pass

                    raw_stream = reader
                else:
                    content = raw.read()
                    raw.close()
            except Exception:
                try:
                    raw.close()
                except Exception:
                    pass
                raise
        except urllib.error.HTTPError as exc:
            try:
                content = exc.read() if exc.fp else b""
            except Exception:
                content = b""
            status = exc.code
            try:
                resp_headers = {k: v for k, v in (exc.headers.items() if exc.headers else [])}
            except Exception:
                resp_headers = {}
            final_url = url
            if status == 401 and digest is not None:
                www = header_get(resp_headers, "WWW-Authenticate")
                if www and "digest" in www.lower():
                    authz = digest.build_response_header(current.method, _request_uri(url), www)
                    if authz:
                        retry_headers = dict(headers)
                        retry_headers["Authorization"] = authz
                        try:
                            raw2 = _do_open(url, retry_headers, body, current.method, total)
                            try:
                                status = raw2.getcode() or 0
                                resp_headers = {k: v for k, v in raw2.headers.items()}
                                final_url = raw2.geturl()
                                content = raw2.read()
                                raw2.close()
                            except Exception:
                                try:
                                    raw2.close()
                                except Exception:
                                    pass
                                raise
                        except urllib.error.HTTPError as exc2:
                            try:
                                content = exc2.read() if exc2.fp else b""
                            except Exception:
                                content = b""
                            status = exc2.code
                            try:
                                resp_headers = {k: v for k, v in (exc2.headers.items() if exc2.headers else [])}
                            except Exception:
                                resp_headers = {}
        except Exception as exc:
            raise _map_open_error(exc, current) from exc

        response = Response(
            status_code=int(status),
            headers=resp_headers,
            content=content,
            url=final_url,
            request=current,
            elapsed=time.perf_counter() - started,
            cookies=_extract_cookies(resp_headers),
        )
        if raw_stream is not None:
            response._stream_reader = raw_stream  # type: ignore[attr-defined]

        if not allow_redirects or not response.is_redirect:
            response.history = history
            return response

        location = header_get(resp_headers, "Location")
        if not location:
            response.history = history
            return response

        redirects += 1
        if redirects > max_redirects:
            raise TooManyRedirects(f"Exceeded {max_redirects} redirects for {req.url}", response=response)

        history.append(response)
        next_url = urljoin(final_url, location)
        next_method = current.method
        next_body = current.body
        next_headers = dict(current.headers)
        if response.status_code in (301, 302, 303) and current.method not in ("GET", "HEAD"):
            next_method = "GET"
            next_body = None
            next_headers.pop("Content-Length", None)
            next_headers.pop("Content-Type", None)

        current = PreparedRequest(
            method=next_method,
            url=next_url,
            headers=next_headers,
            body=next_body,
            params={},
        )
