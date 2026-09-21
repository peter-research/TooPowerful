import os

import pytest

from toopowerful.models import PreparedRequest, Response, Timeout, join_url
from toopowerful.retry import Retry, parse_retry_after
from toopowerful.cache import MemoryCache, FileCache
from toopowerful.auth import BasicAuth, BearerAuth, ApiKeyAuth, DigestAuth, resolve_auth
from toopowerful.transport import (
    encode_body,
    encode_multipart,
    resolve_proxy,
    should_bypass_proxy,
)
from toopowerful import Client
from toopowerful.middleware import Middleware, add_header
from toopowerful.testing import MockClient, make_response, local_http_server


def test_version():
    import toopowerful as tp
    assert tp.__version__ == "0.1.0"


def test_timeout_coerce():
    t = Timeout.coerce(5)
    assert t.connect == 5 and t.read == 5
    t2 = Timeout.coerce((2, 7))
    assert (t2.connect, t2.read, t2.total) == (2, 7, 9)
    t3 = Timeout.coerce((1, 2, 10))
    assert (t3.connect, t3.read, t3.total) == (1, 2, 10)


def test_prepared_params():
    req = PreparedRequest("GET", "https://example.com/x", params={"q": "a b"})
    assert "q=" in req.with_params()


def test_prepared_params_list_and_path():
    req = PreparedRequest(
        "GET",
        "https://example.com/users/{id}",
        params={"tag": ["a", "b"], "q": "x y"},
        path_params={"id": 42},
    )
    url = req.with_params()
    assert "/users/42" in url
    assert url.count("tag=") == 2


def test_retry_delay():
    r = Retry(backoff=0.5, max_backoff=2)
    assert r.delay(0) == 0.5
    assert r.delay(3) == 2


def test_retry_after_parsing():
    assert parse_retry_after("3") == 3.0
    assert parse_retry_after("") is None
    assert parse_retry_after("not-a-date") is None
    r = Retry(backoff=0.1, max_backoff=8)
    assert r.sleep_secs(0, headers={"Retry-After": "5"}) >= 5.0
    assert r.sleep_secs(0, headers={}) == pytest.approx(0.1)


def test_cache_roundtrip():
    cache = MemoryCache(ttl=10)
    req = PreparedRequest("GET", "https://example.com")
    resp = Response(200, {}, b'{"ok":true}', "https://example.com", req)
    cache.set("GET", "https://example.com", resp)
    hit = cache.get("GET", "https://example.com")
    assert hit is not None and hit.from_cache and hit.json()["ok"] is True


def test_cache_lru_and_invalidate():
    cache = MemoryCache(ttl=60, max_items=2)
    req = PreparedRequest("GET", "https://example.com")
    for i in range(3):
        cache.set("GET", f"https://example.com/{i}", Response(200, {}, b"{}", f"https://example.com/{i}", req))
    assert len(cache) == 2
    assert cache.stats.evictions == 1
    cache.set("GET", "https://example.com/users/1", Response(200, {}, b"{}", "https://example.com/users/1", req))
    removed = cache.invalidate("*/users/*")
    assert removed >= 1


def test_file_cache_roundtrip(tmp_path):
    cache = FileCache(str(tmp_path), ttl=60)
    req = PreparedRequest("GET", "https://example.com/a")
    resp = Response(200, {"X-A": "1"}, b"hello", "https://example.com/a", req)
    cache.set("GET", "https://example.com/a", resp)
    hit = cache.get("GET", "https://example.com/a")
    assert hit is not None and hit.from_cache and hit.content == b"hello"
    assert cache.stats.hits == 1


def test_basic_auth():
    h: dict = {}
    BasicAuth("u", "p").apply(h)
    assert h["Authorization"].startswith("Basic ")


def test_bearer_auth():
    h: dict = {}
    BearerAuth("tok").apply(h)
    assert h["Authorization"] == "Bearer tok"


def test_apikey_auth_query_and_resolve():
    auth = ApiKeyAuth("KEY", query_param="api_key")
    url = auth.inject_url("https://example.com/x?a=1")
    assert "api_key=KEY" in url
    assert isinstance(resolve_auth({"api_key": "K", "query_param": "k"}), ApiKeyAuth)
    assert isinstance(resolve_auth("Bearer abc"), BearerAuth)
    assert isinstance(resolve_auth(("u", "p")), BasicAuth)


def test_digest_challenge():
    challenge = 'Digest realm="test", nonce="abc123", qop="auth", algorithm=MD5'
    parsed = DigestAuth.parse_challenge(challenge)
    assert parsed["realm"] == "test" and parsed["nonce"] == "abc123"
    header = DigestAuth("u", "p").build_response_header("GET", "/dir", challenge)
    assert header is not None and header.startswith("Digest ") and 'username="u"' in header


def test_multipart_encodes():
    body, ctype = encode_multipart(data={"a": "1"}, files={"f": ("x.txt", b"hello")})
    assert b"hello" in body
    assert "multipart/form-data" in ctype
    assert b'name="a"' in body


def test_multipart_file_like():
    import io

    body, ctype = encode_multipart(files={"f": ("doc.txt", io.BytesIO(b"file-bytes"))})
    assert b"file-bytes" in body
    assert "multipart/form-data" in ctype


def test_json_body():
    body, headers = encode_body(json_body={"x": 1}, headers={})
    assert body == b'{"x": 1}'
    assert "application/json" in headers["Content-Type"]


def test_response_helpers():
    req = PreparedRequest("GET", "https://example.com")
    r = Response(200, {"Link": '<https://api.com/p2>; rel="next"', "Content-Type": "text/plain"}, b"a\nb", "https://example.com", req)
    assert r.is_success and not r.is_client_error and not r.is_server_error
    assert r.links == {"next": "https://api.com/p2"}
    assert b"".join(r.iter_content(1)) == b"a\nb"
    assert list(r.iter_lines()) == ["a", "b"]
    assert r.content_type == "text/plain"
    e = Response(404, {}, b"nope", "https://example.com", req)
    assert e.is_client_error
    with pytest.raises(Exception):
        e.raise_for_status()
    bad = Response(200, {}, b"{invalid", "https://example.com", req)
    with pytest.raises(Exception):
        bad.json()


def test_join_url():
    assert join_url("https://a.com/base", "https://b.com/x") == "https://b.com/x"
    assert join_url("https://a.com/base", "/x") == "https://a.com/x"
    assert join_url("", "https://a.com") == "https://a.com"


def test_proxy_bypass(monkeypatch):
    monkeypatch.setenv("no_proxy", "example.com")
    assert should_bypass_proxy("https://example.com/x") is True
    assert should_bypass_proxy("https://other.com/x") is False
    assert resolve_proxy("https://example.com", {"http": "http://p:8080"}, trust_env=True) is None


def test_rate_limiter_fast():
    from toopowerful import RateLimiter

    rl = RateLimiter(rate_per_second=1000, burst=5)
    assert rl.acquire() == 0.0


def test_mock_client():
    mock = MockClient()
    mock.add("GET", "https://example.com/a", make_response(body={"ok": True}))
    r = mock.request("GET", "https://example.com/a")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert len(mock.calls) == 1


def _fake_transport_factory(responses):
    state = {"i": 0}

    def fake(req, timeout=None, **kw):
        item = responses[min(state["i"], len(responses) - 1)]
        state["i"] += 1
        if isinstance(item, BaseException):
            raise item
        item.request = req
        return item

    return fake


def test_client_retries_then_succeeds():
    ok = make_response(url="https://example.com/r", body=b"ok")
    bad = make_response(url="https://example.com/r", status=503, body=b"busy")
    c = Client(retry=Retry(attempts=3, backoff=0), transport=_fake_transport_factory([bad, ok]), request_id=False)
    r = c.get("https://example.com/r")
    assert r.status_code == 200
    assert c.stats["retries"] == 1
    assert c.stats["requests"] == 2


def test_client_cache_and_middleware_and_params():
    ok = make_response(url="https://example.com/x?a=1", body=b"{}")
    seen = {}

    def before(req):
        seen["rid"] = req.headers.get("X-Request-ID")
        return req

    mw = Middleware().use_before(before)
    c = Client(
        params={"a": "1"},
        cache=MemoryCache(ttl=60),
        middleware=mw,
        transport=_fake_transport_factory([ok]),
    )
    r1 = c.get("https://example.com/x")
    r2 = c.get("https://example.com/x")
    assert r2.from_cache and c.stats["cache_hits"] == 1
    assert seen["rid"]


def test_client_path_params_and_bulk_and_map():
    def fake(req, timeout=None, **kw):
        return make_response(method=req.method, url=req.with_params(), body=req.with_params().encode())

    c = Client(transport=fake, request_id=False)
    r = c.get("https://example.com/users/{id}", path_params={"id": 7})
    assert "/users/7" in r.url
    out = c.bulk([{"method": "GET", "url": "https://example.com/1"}, {"method": "GET", "url": "https://example.com/2"}])
    assert len(out) == 2
    mapped = c.map("GET", ["https://example.com/a", "https://example.com/b"])
    assert [m.url for m in mapped] == ["https://example.com/a", "https://example.com/b"]


def test_client_download_and_stream(tmp_path):
    import threading

    routes = {"/file": (200, {"Content-Type": "text/plain"}, b"x" * 100)}
    server, base = local_http_server(routes)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        c = Client(base_url=base, request_id=False)
        dest = str(tmp_path / "f.bin")
        n = c.download("/file", dest)
        assert n == 100 and os.path.getsize(dest) == 100
        s = c.stream("GET", f"{base}/file")
        assert b"".join(s.iter_content(32)) == b"x" * 100
    finally:
        server.shutdown()
        server.server_close()


def test_local_server_cache_integration():
    import threading

    routes = {"/data": (200, {"Content-Type": "application/json"}, {"v": 1})}
    server, base = local_http_server(routes)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        c = Client(base_url=base, cache=MemoryCache(ttl=60), request_id=False)
        a = c.get("/data")
        b = c.get("/data")
        assert a.json() == {"v": 1} and b.from_cache
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.asyncio
async def test_async_gather_with_mock():
    from toopowerful import AsyncClient

    def fake(req, timeout=None, **kw):
        return make_response(method=req.method, url=req.with_params(), body=b"ok")

    async with AsyncClient(transport=fake, request_id=False, max_concurrency=4) as http:
        batch = await http.gather("GET", ["https://example.com/1", "https://example.com/2"])
        assert len(batch) == 2
        one = await http.get("https://example.com/1")
        assert one.status_code == 200
