from __future__ import annotations

from typing import Callable, List

from .models import PreparedRequest, Response

BeforeHook = Callable[[PreparedRequest], PreparedRequest]
AfterHook = Callable[[Response], Response]


class Middleware:
    """Pipeline of before/after hooks."""

    def __init__(self) -> None:
        self.before: List[BeforeHook] = []
        self.after: List[AfterHook] = []

    def use_before(self, hook: BeforeHook) -> "Middleware":
        self.before.append(hook)
        return self

    def use_after(self, hook: AfterHook) -> "Middleware":
        self.after.append(hook)
        return self

    def apply_before(self, req: PreparedRequest) -> PreparedRequest:
        for hook in self.before:
            req = hook(req)
        return req

    def apply_after(self, resp: Response) -> Response:
        for hook in self.after:
            resp = hook(resp)
        return resp
