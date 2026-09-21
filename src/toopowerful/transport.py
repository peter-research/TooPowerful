from __future__ import annotations

import json
import mimetypes
import ssl
import time
import uuid
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from typing import Any, Mapping, Optional, Tuple, Union
from urllib.parse import urlencode, urljoin

from .models import (
    PreparedRequest,
    Response,
    Timeout,
    TimeoutError,
    TooManyRedirects,
    TooPowerfulError,
    header_get,
)

FileValue = Union[bytes, Tuple[str, bytes], Tuple[str, bytes, str]]


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
        part(str(key), str(val).encode("utf-8"))

    for key, item in (files or {}).items():
        if isinstance(item, bytes):
            part(str(key), item, filename="file")
        elif len(item) == 2:
            filename, content = item  # type: ignore[misc]
            part(str(key), content, filename=str(filename))
        else:
            filename, content, ctype = item  # type: ignore[misc]
            part(str(key), content, filename=str(filename), content_type=str(ctype))

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
        payload = urlencode(data).encode("utf-8")
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


def send(
    req: PreparedRequest,
    timeout: Timeout,
    *,
    verify: bool = True,
    cookiejar: Optional[CookieJar] = None,
    allow_redirects: bool = True,
    max_redirects: int = 10,
) -> Response:
    history: list[Response] = []
    current = req
    redirects = 0
    jar = cookiejar if cookiejar is not None else CookieJar()
    context = ssl.create_default_context() if verify else ssl._create_unverified_context()
    opener = urllib.request.build_opener(
        _NoRedirect(),
        urllib.request.HTTPCookieProcessor(jar),
        urllib.request.HTTPSHandler(context=context),
    )

    while True:
        url = current.with_params()
        headers = {"User-Agent": "TooPowerful/0.0.1", **current.headers}
        body = current.body
        if current.json is not None and body is None:
            body, headers = encode_body(json_body=current.json, headers=headers)

        urllib_req = urllib.request.Request(url, data=body, headers=headers, method=current.method.upper())
        started = time.perf_counter()
        total = timeout.total if timeout.total is not None else timeout.connect + timeout.read
        try:
            with opener.open(urllib_req, timeout=total) as raw:
                content = raw.read()
                status = raw.getcode() or 0
                resp_headers = {k: v for k, v in raw.headers.items()}
                final_url = raw.geturl()
        except urllib.error.HTTPError as exc:
            content = exc.read() if exc.fp else b""
            status = exc.code
            resp_headers = {k: v for k, v in (exc.headers.items() if exc.headers else [])}
            final_url = url
        except OSError as exc:
            name = type(exc).__name__
            if "timed out" in str(exc).lower() or name == "TimeoutError":
                raise TimeoutError(str(exc)) from exc
            raise TooPowerfulError(str(exc)) from exc

        response = Response(
            status_code=int(status),
            headers=resp_headers,
            content=content,
            url=final_url,
            request=current,
            elapsed=time.perf_counter() - started,
            cookies=_extract_cookies(resp_headers),
        )

        if not allow_redirects or not response.is_redirect:
            response.history = history
            return response

        location = header_get(resp_headers, "Location")
        if not location:
            response.history = history
            return response

        redirects += 1
        if redirects > max_redirects:
            raise TooManyRedirects(f"Exceeded {max_redirects} redirects for {req.url}")

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
