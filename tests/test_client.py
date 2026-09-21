from toopowerful.models import PreparedRequest, Response, Timeout
from toopowerful.retry import Retry
from toopowerful.cache import MemoryCache
from toopowerful.auth import BasicAuth, BearerAuth
from toopowerful.transport import encode_body, encode_multipart


def test_version():
    import toopowerful as tp
    assert tp.__version__ == "0.0.1"


def test_timeout_coerce():
    t = Timeout.coerce(5)
    assert t.connect == 5 and t.read == 5


def test_prepared_params():
    req = PreparedRequest("GET", "https://example.com/x", params={"q": "a b"})
    assert "q=" in req.with_params()


def test_retry_delay():
    r = Retry(backoff=0.5, max_backoff=2)
    assert r.delay(0) == 0.5
    assert r.delay(3) == 2


def test_cache_roundtrip():
    cache = MemoryCache(ttl=10)
    req = PreparedRequest("GET", "https://example.com")
    resp = Response(200, {}, b'{"ok":true}', "https://example.com", req)
    cache.set("GET", "https://example.com", resp)
    hit = cache.get("GET", "https://example.com")
    assert hit is not None and hit.from_cache and hit.json()["ok"] is True


def test_basic_auth():
    h: dict = {}
    BasicAuth("u", "p").apply(h)
    assert h["Authorization"].startswith("Basic ")


def test_bearer_auth():
    h: dict = {}
    BearerAuth("tok").apply(h)
    assert h["Authorization"] == "Bearer tok"


def test_multipart_encodes():
    body, ctype = encode_multipart(data={"a": "1"}, files={"f": ("x.txt", b"hello")})
    assert b"hello" in body
    assert "multipart/form-data" in ctype
    assert b'name="a"' in body


def test_json_body():
    body, headers = encode_body(json_body={"x": 1}, headers={})
    assert body == b'{"x": 1}'
    assert "application/json" in headers["Content-Type"]
