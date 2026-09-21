from toopowerful.models import PreparedRequest, Timeout
from toopowerful.retry import Retry
from toopowerful.cache import MemoryCache
from toopowerful.models import Response


def test_timeout_coerce():
    t = Timeout.coerce(5)
    assert t.connect == 5
    assert t.read == 5


def test_prepared_params():
    req = PreparedRequest("GET", "https://example.com/x", params={"q": "a b"})
    assert "q=a+b" in req.with_params() or "q=a%20b" in req.with_params()


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
    assert hit is not None
    assert hit.from_cache is True
    assert hit.json()["ok"] is True
