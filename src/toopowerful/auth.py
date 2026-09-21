from __future__ import annotations

import base64
import hashlib
import os
import random
from dataclasses import dataclass, field
from typing import Callable, Mapping, MutableMapping, Optional, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class Auth(Protocol):
    def apply(self, headers: MutableMapping[str, str]) -> None: ...


@dataclass(frozen=True)
class BasicAuth:
    username: str
    password: str

    def apply(self, headers: MutableMapping[str, str]) -> None:
        token = base64.b64encode(f"{self.username}:{self.password}".encode()).decode("ascii")
        headers["Authorization"] = f"Basic {token}"


@dataclass(frozen=True)
class BearerAuth:
    token: str

    def apply(self, headers: MutableMapping[str, str]) -> None:
        headers["Authorization"] = f"Bearer {self.token}"


@dataclass(frozen=True)
class ApiKeyAuth:
    """Cle API dans un header, la query ou un cookie."""

    api_key: str
    header_name: str = "X-API-Key"
    query_param: Optional[str] = None
    cookie_name: Optional[str] = None

    def apply(self, headers: MutableMapping[str, str]) -> None:
        headers[self.header_name] = self.api_key

    def inject_url(self, url: str) -> str:
        """Ajoute la cle a la query string si query_param est defini."""
        if not self.query_param:
            return url
        parts = urlsplit(url)
        query = parse_qsl(parts.query, keep_blank_values=True)
        query.append((self.query_param, self.api_key))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@dataclass
class DigestAuth:
    """Digest HTTP RFC 2617 (qop=auth). Rejoue le challenge 401 cote transport."""

    username: str
    password: str
    last_challenge: dict = field(default_factory=dict, repr=False)

    def apply(self, headers: MutableMapping[str, str]) -> None:
        pass

    @staticmethod
    def parse_challenge(header_value: str) -> dict:
        value = header_value.strip()
        if value.lower().startswith("digest "):
            value = value[7:]
        out: dict[str, str] = {}
        key, buf, in_quotes = "", "", False
        pairs: list[str] = []
        for ch in value:
            if ch == '"':
                in_quotes = not in_quotes
                buf += ch
            elif ch == "," and not in_quotes:
                pairs.append(buf)
                buf = ""
            else:
                buf += ch
        if buf.strip():
            pairs.append(buf)
        for pair in pairs:
            if "=" not in pair:
                continue
            k, v = pair.split("=", 1)
            v = v.strip()
            if len(v) >= 2 and v.startswith('"') and v.endswith('"'):
                v = v[1:-1]
            out[k.strip()] = v
        return out

    def _digest(self, method: str, uri: str, challenge: dict) -> str:
        realm = challenge.get("realm", "")
        nonce = challenge.get("nonce", "")
        qop = (challenge.get("qop") or "").split(",")[0].strip() or "auth"
        algorithm = (challenge.get("algorithm") or "MD5").upper()
        opaque = challenge.get("opaque")

        def H(s: str) -> str:
            data = s.encode("utf-8")
            if algorithm == "SHA-256":
                return hashlib.sha256(data).hexdigest()
            if algorithm == "SHA-512":
                return hashlib.sha512(data).hexdigest()
            return hashlib.md5(data).hexdigest()

        ha1 = H(f"{self.username}:{realm}:{self.password}")
        ha2 = H(f"{method.upper()}:{uri}")
        cnonce = hashlib.sha256(os.urandom(16)).hexdigest()[:16]
        nc = f"{random.randint(1, 99999999):08x}"
        if qop:
            resp = H(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}")
        else:
            resp = H(f"{ha1}:{nonce}:{ha2}")
        parts = [
            f'username="{self.username}"',
            f'realm="{realm}"',
            f'nonce="{nonce}"',
            f'uri="{uri}"',
            f'response="{resp}"',
        ]
        if algorithm != "MD5":
            parts.append(f"algorithm={algorithm}")
        if opaque:
            parts.append(f'opaque="{opaque}"')
        if qop:
            parts.extend([f"qop={qop}", f"nc={nc}", f'cnonce="{cnonce}"'])
        return "Digest " + ", ".join(parts)

    def build_response_header(self, method: str, uri: str, www_authenticate: str) -> Optional[str]:
        challenge = self.parse_challenge(www_authenticate)
        if not challenge or "nonce" not in challenge:
            return None
        self.last_challenge = challenge
        return self._digest(method, uri, challenge)


@dataclass(frozen=True)
class CallableAuth:
    """Auth custom via callable(headers) -> None."""

    func: Callable[[MutableMapping[str, str]], None]

    def apply(self, headers: MutableMapping[str, str]) -> None:
        self.func(headers)


def resolve_auth(auth: Optional[object]) -> Optional[Auth]:
    if auth is None:
        return None
    if hasattr(auth, "apply"):
        return auth  # type: ignore[return-value]
    if isinstance(auth, tuple) and len(auth) == 2:
        return BasicAuth(str(auth[0]), str(auth[1]))
    if isinstance(auth, str):
        text = auth.strip()
        if text.lower().startswith("bearer "):
            return BearerAuth(text[7:].strip())
        if text.lower().startswith("basic "):
            return BearerAuth(text)
        return BearerAuth(text)
    if isinstance(auth, Mapping):
        mapping = dict(auth)
        if "api_key" in mapping:
            return ApiKeyAuth(
                str(mapping["api_key"]),
                header_name=str(mapping.get("header", "X-API-Key")),
                query_param=mapping.get("query_param"),
                cookie_name=mapping.get("cookie"),
            )
        if "token" in mapping:
            return BearerAuth(str(mapping["token"]))
        if "username" in mapping and "password" in mapping:
            if str(mapping.get("scheme", "basic")).lower() == "digest":
                return DigestAuth(str(mapping["username"]), str(mapping["password"]))
            return BasicAuth(str(mapping["username"]), str(mapping["password"]))
    if callable(auth):
        return CallableAuth(auth)  # type: ignore[arg-type]
    raise TypeError(
        "auth must be BasicAuth, BearerAuth, DigestAuth, ApiKeyAuth, "
        "(user, pass), 'Bearer xxx', {'token': ...}, {'api_key': ...} ou callable"
    )
