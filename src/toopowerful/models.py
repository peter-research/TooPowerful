from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, List, Mapping, MutableMapping, Optional, Union
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

Headers = MutableMapping[str, str]
JSONType = Any


@dataclass
class Timeout:
    connect: float = 10.0
    read: float = 30.0
    total: Optional[float] = 40.0

    @classmethod
    def coerce(cls, value: Union[None, float, "Timeout"]) -> "Timeout":
        if value is None:
            return cls()
        if isinstance(value, Timeout):
            return value
        return cls(connect=float(value), read=float(value), total=float(value))


@dataclass
class PreparedRequest:
    method: str
    url: str
    headers: Headers = field(default_factory=dict)
    body: Optional[bytes] = None
    json: Optional[JSONType] = None
    params: Mapping[str, Any] = field(default_factory=dict)

    def with_params(self) -> str:
        if not self.params:
            return self.url
        parts = urlsplit(self.url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query.update({k: "" if v is None else str(v) for k, v in self.params.items()})
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@dataclass
class Response:
    status_code: int
    headers: Mapping[str, str]
    content: bytes
    url: str
    request: PreparedRequest
    elapsed: float = 0.0
    from_cache: bool = False
    history: List["Response"] = field(default_factory=list)
    cookies: Mapping[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400

    @property
    def is_redirect(self) -> bool:
        return self.status_code in (301, 302, 303, 307, 308)

    @property
    def text(self) -> str:
        charset = "utf-8"
        ctype = self.headers.get("Content-Type") or self.headers.get("content-type") or ""
        if "charset=" in ctype.lower():
            charset = ctype.split("charset=", 1)[1].split(";")[0].strip() or "utf-8"
        return self.content.decode(charset, errors="replace")

    def json(self) -> Any:
        return json.loads(self.content.decode("utf-8"))

    def raise_for_status(self) -> "Response":
        if self.status_code >= 400:
            raise HTTPStatusError(f"{self.status_code} for {self.url}", response=self)
        return self

    def __repr__(self) -> str:
        tag = " (cache)" if self.from_cache else ""
        return f"<Response [{self.status_code}] {self.url}{tag}>"


class TooPowerfulError(Exception):
    pass


class HTTPStatusError(TooPowerfulError):
    def __init__(self, message: str, response: Response) -> None:
        super().__init__(message)
        self.response = response


class TimeoutError(TooPowerfulError):
    pass


class TooManyRedirects(TooPowerfulError):
    pass


def join_url(base: Optional[str], url: str) -> str:
    if not base:
        return url
    return urljoin(base if base.endswith("/") else base + "/", url)


def header_get(headers: Mapping[str, str], name: str, default: str = "") -> str:
    lower = name.lower()
    for k, v in headers.items():
        if k.lower() == lower:
            return v
    return default
