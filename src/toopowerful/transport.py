from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.request
from typing import Mapping, Optional
from urllib.parse import urlencode

from .models import PreparedRequest, Response, Timeout, TimeoutError, TooPowerfulError


def encode_body(
    data: Optional[Mapping[str, object]] = None,
    json_body: object = None,
    content: Optional[bytes] = None,
    headers: Optional[dict[str, str]] = None,
) -> tuple[Optional[bytes], dict[str, str]]:
    headers = dict(headers or {})
    if content is not None:
        return content, headers
    if json_body is not None:
        payload = json.dumps(json_body).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
        return payload, headers
    if data is not None:
        payload = urlencode(data).encode("utf-8")
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        return payload, headers
    return None, headers


def send(req: PreparedRequest, timeout: Timeout, verify: bool = True) -> Response:
    url = req.with_params()
    headers = {"User-Agent": "TooPowerful/0.1.0", **req.headers}
    body = req.body
    if req.json is not None and body is None:
        body, headers = encode_body(json_body=req.json, headers=headers)

    context = ssl.create_default_context() if verify else ssl._create_unverified_context()
    urllib_req = urllib.request.Request(url, data=body, headers=headers, method=req.method.upper())
    started = time.perf_counter()
    total = timeout.total if timeout.total is not None else timeout.connect + timeout.read
    try:
        with urllib.request.urlopen(urllib_req, timeout=total, context=context) as raw:
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

    return Response(
        status_code=int(status),
        headers=resp_headers,
        content=content,
        url=final_url,
        request=req,
        elapsed=time.perf_counter() - started,
    )
