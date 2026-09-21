from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Mapping, MutableMapping, Optional, Protocol


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


def resolve_auth(auth: Optional[object]) -> Optional[Auth]:
    if auth is None:
        return None
    if hasattr(auth, "apply"):
        return auth  # type: ignore[return-value]
    if isinstance(auth, tuple) and len(auth) == 2:
        return BasicAuth(str(auth[0]), str(auth[1]))
    if isinstance(auth, Mapping) and "token" in auth:
        return BearerAuth(str(auth["token"]))
    raise TypeError("auth must be BasicAuth, BearerAuth, (user, pass), or {'token': '...'}")
