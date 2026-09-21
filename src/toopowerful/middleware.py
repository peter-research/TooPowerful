from __future__ import annotations

import logging
import time
import uuid
from typing import Callable, Dict, List

from .models import PreparedRequest, Response

BeforeHook = Callable[[PreparedRequest], PreparedRequest]
AfterHook = Callable[[Response], Response]

log = logging.getLogger("toopowerful")


class Middleware:
    """Pipeline of before/after hooks (backward-compat)."""

    def __init__(self) -> None:
        self.before: List[BeforeHook] = []
        self.after: List[AfterHook] = []

    def use_before(self, hook: BeforeHook) -> "Middleware":
        self.before.append(hook)
        return self

    def use_after(self, hook: AfterHook) -> "Middleware":
        self.after.append(hook)
        return self

    def on_request(self, hook: BeforeHook) -> "Middleware":
        return self.use_before(hook)

    def on_response(self, hook: AfterHook) -> "Middleware":
        return self.use_after(hook)

    def apply_before(self, req: PreparedRequest) -> PreparedRequest:
        for hook in self.before:
            req = hook(req)
        return req

    def apply_after(self, resp: Response) -> Response:
        for hook in self.after:
            resp = hook(resp)
        return resp


def add_header(name: str, value: str, overwrite: bool = False) -> BeforeHook:
    def hook(req: PreparedRequest) -> PreparedRequest:
        if overwrite or name not in req.headers:
            req.headers[name] = value
        return req

    hook.__name__ = f"add_header_{name}"
    return hook


def request_id(header: str = "X-Request-ID") -> BeforeHook:
    """Injecte un ID unique par requete si absent."""

    def hook(req: PreparedRequest) -> PreparedRequest:
        if header not in req.headers:
            req.headers[header] = uuid.uuid4().hex[:16]
        return req

    hook.__name__ = "request_id"
    return hook


def log_requests(logger: logging.Logger | None = None, level: int = logging.DEBUG) -> AfterHook:
    logger = logger or log

    def hook(resp: Response) -> Response:
        tag = "CACHE" if resp.from_cache else "LIVE"
        logger.log(
            level,
            "%s %s -> %s (%.1fms) [%s]",
            resp.request.method,
            resp.url,
            resp.status_code,
            resp.elapsed * 1000,
            tag,
        )
        return resp

    hook.__name__ = "log_requests"
    return hook


def log_timing(threshold: float = 1.0, logger: logging.Logger | None = None) -> AfterHook:
    """Log uniquement les requetes lentes (>= threshold secondes)."""
    logger = logger or log

    def hook(resp: Response) -> Response:
        if resp.elapsed >= threshold and not resp.from_cache:
            logger.warning(
                "slow request: %s %s took %.2fs",
                resp.request.method,
                resp.url,
                resp.elapsed,
            )
        return resp

    hook.__name__ = "log_timing"
    return hook


def strip_auth_on_cross_host() -> AfterHook:
    """Securite: ne conserve pas l'historique d'Authorization (marqueur).

    Le transport retire deja Authorization lors d'un changement d'hote.
    Ce hook est un garde-fou documentaire (no-op sur la reponse).
    """

    def hook(resp: Response) -> Response:
        return resp

    hook.__name__ = "strip_auth_on_cross_host"
    return hook


EventHooks = Dict[str, list]


def build_middleware(
    middleware: Middleware | None = None,
    event_hooks: EventHooks | None = None,
) -> Middleware:
    """Fusionne un Middleware existant + des event_hooks style requests.

    event_hooks: {'request': [fn(req)->req], 'response': [fn(resp)->resp]}
    """
    mw = middleware or Middleware()
    if not event_hooks:
        return mw
    for fn in event_hooks.get("request", []) or []:
        mw.use_before(fn)
    for fn in event_hooks.get("response", []) or []:
        mw.use_after(fn)
    return mw


__all__ = [
    "Middleware",
    "add_header",
    "request_id",
    "log_requests",
    "log_timing",
    "strip_auth_on_cross_host",
    "build_middleware",
]
