from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Mapping, MutableMapping, Optional, Sequence, Tuple, Union
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

Headers = MutableMapping[str, str]
JSONType = Any
QueryValue = Union[str, int, float, bool, None, Sequence[Union[str, int, float, bool, None]]]


@dataclass
class Timeout:
    connect: float = 10.0
    read: float = 30.0
    total: Optional[float] = 40.0

    @classmethod
    def coerce(cls, value: Union[None, float, Tuple[float, ...], List[float], "Timeout"]) -> "Timeout":
        if value is None:
            return cls()
        if isinstance(value, Timeout):
            return value
        if isinstance(value, (tuple, list)):
            parts = [float(v) for v in value]
            if len(parts) == 2:
                connect, read = parts
                return cls(connect=connect, read=read, total=connect + read)
            if len(parts) == 3:
                connect, read, total = parts
                return cls(connect=connect, read=read, total=total)
            raise ValueError("Timeout tuple must be (connect, read) or (connect, read, total)")
        return cls(connect=float(value), read=float(value), total=float(value))  # type: ignore[arg-type]


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


@dataclass
class PreparedRequest:
    method: str
    url: str
    headers: Headers = field(default_factory=dict)
    body: Optional[bytes] = None
    json: Optional[JSONType] = None
    params: Mapping[str, Any] = field(default_factory=dict)
    path_params: Mapping[str, Any] = field(default_factory=dict)

    def with_url(self) -> str:
        """Applique path_params (/users/{id}) puis les query params."""
        url = self.url
        if self.path_params:
            for key, val in self.path_params.items():
                url = url.replace("{" + str(key) + "}", _stringify(val))
        return url

    def with_params(self) -> str:
        base = self.with_url()
        if not self.params:
            return base
        parts = urlsplit(base)
        existing: list[tuple[str, str]] = parse_qsl(parts.query, keep_blank_values=True)
        extra: list[tuple[str, str]] = []
        for key, val in self.params.items():
            if isinstance(val, (list, tuple)):
                for item in val:
                    extra.append((str(key), _stringify(item)))
            else:
                extra.append((str(key), _stringify(val)))
        query = urlencode(existing + extra, doseq=True)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


_LINK_RE = re.compile(r'\s*<([^>]+)>\s*;\s*rel="([^"]+)"')


def parse_links(link_header: str) -> Dict[str, str]:
    """Parse un header Link RFC5988: <url>; rel="next", ... -> {rel: url}."""
    out: Dict[str, str] = {}
    if not link_header:
        return out
    for part in link_header.split(","):
        m = _LINK_RE.search(part)
        if m:
            out[m.group(2)] = m.group(1)
    return out


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
    _stream_reader: Optional[Callable[[int], Iterator[bytes]]] = field(default=None, repr=False, compare=False)

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400

    @property
    def is_informational(self) -> bool:
        return 100 <= self.status_code < 200

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    @property
    def is_redirect(self) -> bool:
        return self.status_code in (301, 302, 303, 307, 308)

    @property
    def is_client_error(self) -> bool:
        return 400 <= self.status_code < 500

    @property
    def is_server_error(self) -> bool:
        return 500 <= self.status_code < 600

    @property
    def content_type(self) -> str:
        ctype = self.headers.get("Content-Type") or self.headers.get("content-type") or ""
        return ctype.split(";")[0].strip().lower()

    @property
    def charset(self) -> str:
        ctype = self.headers.get("Content-Type") or self.headers.get("content-type") or ""
        low = ctype.lower()
        if "charset=" in low:
            return ctype.split("charset=", 1)[1].split(";")[0].strip().strip('"') or "utf-8"
        return "utf-8"

    @property
    def apparent_encoding(self) -> str:
        """Devine l'encodage: charset du header, sinon BOM/UTF-8."""
        ctype = self.headers.get("Content-Type") or self.headers.get("content-type") or ""
        if "charset=" in ctype.lower():
            return self.charset
        if self.content.startswith(b"\xef\xbb\xbf"):
            return "utf-8-sig"
        if self.content.startswith((b"\xff\xfe", b"\xfe\xff")):
            return "utf-16"
        return "utf-8"

    @property
    def text(self) -> str:
        return self.content.decode(self.apparent_encoding, errors="replace")

    @property
    def links(self) -> Dict[str, str]:
        raw = self.headers.get("Link") or self.headers.get("link") or ""
        return parse_links(raw)

    def json(self, **kw: Any) -> Any:
        try:
            return json.loads(self.content.decode("utf-8"), **kw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ResponseError(f"Invalid JSON from {self.url}: {exc}", response=self) from exc

    def raise_for_status(self) -> "Response":
        if self.status_code >= 400:
            body = self.text[:200]
            raise HTTPStatusError(f"{self.status_code} {self.url}: {body}", response=self)
        return self

    def iter_content(self, chunk_size: int = 8192) -> Iterator[bytes]:
        if self._stream_reader is not None:
            yield from self._stream_reader(chunk_size)
            return
        for i in range(0, len(self.content), chunk_size or len(self.content) or 1):
            yield self.content[i : i + chunk_size]

    def iter_lines(self) -> Iterator[str]:
        buf = b"".join(self.iter_content(8192))
        for line in buf.splitlines():
            yield line.decode(self.apparent_encoding, errors="replace")

    def download(self, path: str, chunk_size: int = 65536) -> int:
        """Ecrit le body sur disque. Retourne le nombre d'octets."""
        total = 0
        with open(path, "wb") as fh:
            for chunk in self.iter_content(chunk_size):
                fh.write(chunk)
                total += len(chunk)
        return total

    def __repr__(self) -> str:
        tag = " (cache)" if self.from_cache else ""
        return f"<Response [{self.status_code}] {self.url}{tag}>"


class TooPowerfulError(Exception):
    pass


class RequestError(TooPowerfulError):
    def __init__(self, message: str, *, request: Optional[PreparedRequest] = None) -> None:
        super().__init__(message)
        self.request = request


class HTTPStatusError(TooPowerfulError):
    def __init__(self, message: str, response: Response) -> None:
        super().__init__(message)
        self.response = response


class ResponseError(TooPowerfulError):
    """Body inattendu (JSON invalide, decode impossible)."""

    def __init__(self, message: str, response: Optional[Response] = None) -> None:
        super().__init__(message)
        self.response = response


class TimeoutError(TooPowerfulError):
    pass


class ConnectionError(TooPowerfulError):
    pass


class ProxyError(ConnectionError):
    pass


class SSLError(ConnectionError):
    pass


class TooManyRedirects(TooPowerfulError):
    def __init__(self, message: str, *, response: Optional[Response] = None) -> None:
        super().__init__(message)
        self.response = response


def join_url(base: Optional[str], url: str) -> str:
    if not base:
        return url
    if not url:
        return base
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        return url
    return urljoin(base if base.endswith("/") else base + "/", url.lstrip("/") if base.endswith("/") else url)


def header_get(headers: Mapping[str, str], name: str, default: str = "") -> str:
    lower = name.lower()
    for k, v in headers.items():
        if k.lower() == lower:
            return v
    return default


def merge_query(url: str, params: Optional[Mapping[str, Any]]) -> str:
    """Fusionne des query params dans une URL (supporte listes)."""
    if not params:
        return url
    req = PreparedRequest("GET", url, params=params)  # type: ignore[arg-type]
    return req.with_params()
