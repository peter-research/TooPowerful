from __future__ import annotations

from typing import Any, Callable, Dict, Mapping, Optional
from urllib.parse import urlsplit

from .models import PreparedRequest, Response


def make_response(
    method: str = "GET",
    url: str = "https://example.com/",
    status: int = 200,
    body: bytes | str | dict = b"",
    headers: Optional[Mapping[str, str]] = None,
) -> Response:
    if isinstance(body, dict):
        import json as _json

        raw = _json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json", **(headers or {})}
    elif isinstance(body, str):
        raw = body.encode("utf-8")
    else:
        raw = body
    req = PreparedRequest(method.upper(), url, headers=dict(headers or {}))
    return Response(status, dict(headers or {}), raw, url, req)


class MockClient:
    """Client factice pour tests: mappe (METHOD, URL) -> Response ou exception.

    - routes: {('GET', 'https://...'): Response | callable | Exception}
    - default: reponse si aucune route ne matche (sinon TooPowerfulError)
    - enregistre chaque appel dans .calls
    """

    def __init__(self, default: Optional[Response] = None) -> None:
        from .models import TooPowerfulError

        self._routes: Dict[tuple[str, str], Any] = {}
        self.calls: list[PreparedRequest] = []
        self.default = default
        self._error = TooPowerfulError

    def add(
        self,
        method: str,
        url: str,
        response: Response | Callable[[PreparedRequest], Response] | BaseException,
    ) -> "MockClient":
        self._routes[(method.upper(), url)] = response
        return self

    def get(self, method: str, url: str) -> Any:
        return self._routes.get((method.upper(), url))

    def _lookup(self, req: PreparedRequest) -> Response:
        from .models import TooPowerfulError

        handler = self._routes.get((req.method.upper(), req.with_params()))
        if handler is None:
            bare = req.with_url()
            for (m, u), h in self._routes.items():
                if m == req.method.upper() and (u == bare or u == req.with_params()):
                    handler = h
                    break
        if handler is None:
            if self.default is not None:
                return self.default
            raise TooPowerfulError(f"No mock for {req.method} {req.with_params()}")
        if isinstance(handler, BaseException):
            raise handler
        if callable(handler):
            return handler(req)
        return handler

    def request(self, method: str, url: str, **kw: Any) -> Response:
        from .models import PreparedRequest as PR

        params = kw.get("params") or {}
        path_params = kw.get("path_params") or {}
        req = PR(method.upper(), url, headers=dict(kw.get("headers") or {}), params=params, path_params=path_params)
        self.calls.append(req)
        resp = self._lookup(req)
        resp.request = req
        return resp

    def get_call(self, url: str, **kw: Any) -> Response:
        return self.request("GET", url, **kw)

    def fetch(self, method: str, url: str, **kw: Any) -> Response:
        return self.request(method, url, **kw)


def mock_transport_handler(client: MockClient) -> Callable[..., Response]:
    """Adapte un MockClient en transport injectable dans Client(transport=...)."""

    def handler(req: PreparedRequest, **kw: Any) -> Response:
        return client.request(req.method, req.url, params=req.params, headers=req.headers)

    return handler


def local_http_server(routes: Optional[Dict[str, Any]] = None):
    """Petit serveur HTTP local (thread) pour tests d'integration offline.

    routes: {path: (status, headers, body)} — body: bytes|str|dict
    Retourne (server, base_url). Appeler server.shutdown() + server.server_close().
    """
    import json as _json
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import urlsplit

    routes = routes or {}

    class Handler(BaseHTTPRequestHandler):
        def _serve(self) -> None:
            path = urlsplit(self.path).path
            status, headers, body = routes.get(path, (404, {}, b"not found"))
            if isinstance(body, dict):
                raw = _json.dumps(body).encode()
                headers = {"Content-Type": "application/json", **headers}
            elif isinstance(body, str):
                raw = body.encode()
            else:
                raw = body
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            if self.command != "HEAD":
                try:
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        do_GET = _serve
        do_POST = _serve
        do_PUT = _serve
        do_DELETE = _serve
        do_PATCH = _serve
        do_HEAD = _serve
        do_OPTIONS = _serve

        def log_message(self, *args: Any) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    return server, f"http://127.0.0.1:{port}"
