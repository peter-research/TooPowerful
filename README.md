# TooPowerful

**A Python HTTP client more powerful than `requests` and `httpx`.**

Sync + async. Retries. Cache. Middleware. Auth. Parallel. Streaming. **Zero dependencies.**

[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![version](https://img.shields.io/badge/version-0.1.0-blue.svg)](#changelog)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![deps](https://img.shields.io/badge/dependencies-0-brightgreen.svg)](#installation)

```bash
pip install git+https://github.com/peter-research/TooPowerful.git
```

```python
import toopowerful as tp

r = tp.get("https://httpbin.org/get", params={"q": "too"})
print(r.status_code, r.json())
```

---

## Contents

- [Why TooPowerful](#why-toopowerful)
- [Installation](#installation)
- [Quickstart](#quickstart)
- [API](#api)
- [Comparison](#comparison)
- [Changelog](#changelog)
- [Development](#development)
- [License](#license)

---

## Why TooPowerful

`requests` is simple. `httpx` is modern. **TooPowerful** brings both together and adds what is natively missing.

| Capability | requests | httpx | TooPowerful |
|---|:---:|:---:|:---:|
| `get` / `post` / session API | yes | yes | yes |
| Zero runtime dependencies | no | no | **yes** |
| Retries + backoff + jitter + `Retry-After` | add-on | add-on | **built-in** |
| GET cache: memory TTL + disk | no | no | **built-in** |
| Middleware before / after + event hooks | limited | limited | **built-in** |
| Parallel (`map` / `gather` / `bulk`) | no | partial | **built-in** |
| Rate limiting | no | no | **built-in** |
| Sync + async, same model | no | yes | **yes** |
| Auth Basic / Bearer / Digest / API key | partial | partial | **yes** |
| Session cookies | yes | yes | **yes** |
| Redirects + history + cross-host auth stripping | yes | yes | **yes** |
| Multipart / file uploads (incl. file-like) | yes | yes | **yes** |
| Structured timeouts | partial | yes | **yes** |
| Streaming + `download()` | partial | yes | **yes** |
| Proxies + `no_proxy` + env support | yes | yes | **yes** |
| Test helpers (`MockClient`, local server) | no | no | **yes** |

Transport: `urllib` (stdlib). Nothing to install besides Python.

---

## Installation

**Python ≥ 3.9.** No runtime dependencies.

### From GitHub (recommended)

```bash
pip install git+https://github.com/peter-research/TooPowerful.git
```

### Clone + editable install

```bash
git clone https://github.com/peter-research/TooPowerful.git
cd TooPowerful
pip install -e .
```

### With dev tools (pytest)

```bash
pip install -e ".[dev]"
pytest
```

Verify:

```bash
python -c "import toopowerful as tp; print(tp.__version__)"
```

---

## Quickstart

### One-shot

```python
import toopowerful as tp

r = tp.get("https://httpbin.org/get")
r.raise_for_status()
print(r.status_code, r.text[:80])

tp.post("https://httpbin.org/post", json={"ok": True})
```

Same verbs as `requests`: `get`, `post`, `put`, `patch`, `delete`, `head`, `options`, `request`.

### Session + cache + retry + auth

```python
from toopowerful import BearerAuth, Client, MemoryCache, Retry

with Client(
    base_url="https://httpbin.org",
    timeout=20,
    retry=Retry(attempts=4, backoff=0.3, jitter=0.2),
    cache=MemoryCache(ttl=30),
    auth=BearerAuth("secret"),
) as http:
    a = http.get("/uuid")
    b = http.get("/uuid")  # cache hit
    print(b.from_cache)
```

### Auth: Basic, Digest, API key

```python
from toopowerful import ApiKeyAuth, BasicAuth, Client, DigestAuth

http = Client(auth=BasicAuth("user", "pass"))
http.get(url, auth=("user", "pass"))          # tuple shortcut
http.get(url, auth="Bearer my-token")         # string shortcut
http.get(url, auth=DigestAuth("user", "pass"))
http.get(url, auth=ApiKeyAuth("key", query_param="api_key"))
```

### Path + query params

```python
http.get("https://api.example.com/users/{id}", path_params={"id": 7})
http.get("https://api.example.com/search", params={"tag": ["a", "b"]})
```

### Multipart

```python
from toopowerful import Client

Client().post(
    "https://httpbin.org/post",
    data={"title": "doc"},
    files={"file": ("readme.txt", b"hello")},
)
```

### Parallel (sync)

```python
from toopowerful import Client

Client(base_url="https://httpbin.org").map("GET", ["/get", "/headers"])
Client(base_url="https://httpbin.org").bulk([
    {"method": "GET", "url": "/get"},
    {"method": "POST", "url": "/post", "json": {"x": 1}},
])
```

### Async

```python
import asyncio
from toopowerful import AsyncClient

async def main():
    async with AsyncClient(base_url="https://httpbin.org", max_concurrency=8) as http:
        r = await http.get("/get")
        batch = await http.gather("GET", ["/uuid", "/headers"])
        print(r.status_code, len(batch))

asyncio.run(main())
```

### Redirects

```python
from toopowerful import Client

r = Client(max_redirects=5).get("https://httpbin.org/redirect/2")
print(len(r.history), r.url)
```

### Streaming + download

```python
from toopowerful import Client

http = Client(base_url="https://example.com")
http.download("/big-file.zip", "big-file.zip")
resp = http.stream("GET", "/big-file.zip")
for chunk in resp.iter_content(65536):
    ...
```

### Disk cache + rate limiting

```python
from toopowerful import Client, FileCache, RateLimiter

http = Client(
    cache=FileCache("./.http-cache", ttl=300),
    limiter=RateLimiter(rate_per_second=5),
)
```

### Proxies

```python
from toopowerful import Client

http = Client(
    proxies={"https": "http://proxy:8080"},
    trust_env=True,  # also reads http_proxy/https_proxy/no_proxy
)
```

---

## API

### Module

| Symbol | Role |
|---|---|
| `toopowerful.__version__` | `"0.1.0"` |
| `request` / `get` / `post` / `put` / `patch` / `delete` / `head` / `options` | one-shot |
| `Client` | synchronous session |
| `AsyncClient` | asynchronous session |

### `Client` / `AsyncClient`

Constructor: `base_url`, `headers`, `params` (defaults merged into every request), `timeout`, `retry`, `cache`, `middleware`, `event_hooks`, `auth`, `cookies`, `verify` (bool or CA bundle path), `cert` (client cert), `proxies`, `trust_env`, `limiter`, `transport` (injectable, for tests), `allow_redirects` / `follow_redirects`, `max_redirects`, `max_concurrency` (async), `request_id` (auto `X-Request-ID`, default on).

Per-request kwargs: `params`, `path_params`, `headers`, `data`, `json`, `content`, `files`, `auth`, `timeout`, `cache`, `allow_redirects` / `follow_redirects`, `stream`.

Helpers: `stream(method, url)`, `download(url, path)`, `bulk(operations)`, `map(method, urls)`, `gather(method, urls)` (async), `get_cookies()` / `clear_cookies()`, `stats` (`requests`, `retries`, `cache_hits`, `errors`).

### `Response`

`status_code`, `headers`, `content`, `text`, `url`, `elapsed`, `from_cache`, `ok`, `is_success`, `is_client_error`, `is_server_error`, `is_redirect`, `cookies`, `history`, `content_type`, `charset`, `apparent_encoding`, `links` (parsed RFC5988 `Link` header), `.json()`, `.raise_for_status()`, `.iter_content(chunk_size)`, `.iter_lines()`, `.download(path)`.

### Auth, retry, cache

- `BasicAuth(user, password)` or `auth=("user", "pass")`
- `BearerAuth(token)` or `auth="Bearer xxx"` or `auth={"token": ...}`
- `DigestAuth(user, password)` (RFC 2617, auto-replay on 401)
- `ApiKeyAuth(key)` / `auth={"api_key": ...}` (header, query or cookie)
- `Retry(attempts=3, backoff=0.4, jitter=0.0, respect_retry_after=True, on_retry=...)`
- `MemoryCache(ttl=30)` (true LRU + `stats` + `invalidate(pattern)`)
- `FileCache(dir, ttl=300)` (persistent on-disk cache)
- `RateLimiter(rate_per_second=5, burst=1)`

### Middleware & hooks

- `Middleware().use_before(fn).use_after(fn)` or `event_hooks={"request": [...], "response": [...]} on the client`
- Ready-made: `add_header`, `request_id`, `log_requests`, `log_timing`

### Testing

```python
from toopowerful.testing import MockClient, make_response, local_http_server

mock = MockClient()
mock.add("GET", "https://api/x", make_response(body={"ok": True}))
```

Or inject any callable as `Client(transport=...)`, or spin up `local_http_server(routes)` for offline integration tests.

### Exceptions

`TooPowerfulError`, `RequestError`, `HTTPStatusError`, `ResponseError`, `TimeoutError`, `ConnectionError`, `ProxyError`, `SSLError`, `TooManyRedirects`.

---

## Comparison

TooPowerful does not try to be a clone. It targets **one single API** for what people usually stack: `requests` + `urllib3.Retry` + a homemade cache + a small pool.

- **vs requests**: async, cache, retry, `map`/`bulk`, middleware, rate limiting, zero dependencies.
- **vs httpx**: TTL/disk cache, native retries with `Retry-After`, `map`/`bulk`, test helpers, zero dependencies (no httpcore / h11).

`0.1.0` — API stabilizing.

---

## Changelog

### 0.1.0

- Auth: Digest (RFC 2617 auto-replay), API key (header/query/cookie), string/tuple/dict shortcuts, callable auth
- Cache: true-LRU `MemoryCache` with stats + `invalidate()`, persistent `FileCache`
- Retry: jitter, `Retry-After` support, `on_retry` callback
- Response: `is_success` / `is_client_error` / `is_server_error`, `links`, `content_type` / `charset` / `apparent_encoding`, `iter_content` / `iter_lines` / `download`
- Requests: `path_params`, multi-value params, default client params, file-like uploads
- Transport: proxies + `no_proxy` + env, CA bundle + client certs, streaming, cross-host auth stripping, typed errors (`RequestError`, `ResponseError`, `ConnectionError`, `ProxyError`, `SSLError`)
- Client: `download` / `bulk` / `stats` / cookie management, `map` with `return_exceptions`, auto `X-Request-ID`, `event_hooks`, injectable transport
- Async: `max_concurrency` semaphore, `stream` / `download` / `bulk` / `map` parity
- Testing: `MockClient`, `make_response`, `local_http_server` — 27 offline tests, zero `#` comments in source

---

## Development

```bash
git clone https://github.com/peter-research/TooPowerful.git
cd TooPowerful
pip install -e ".[dev]"
pytest
```

Layout:

```
src/toopowerful/     # package
tests/               # pytest (offline, no external network)
examples/quickstart.py
```

---

## License

MIT — [peter-research/TooPowerful](https://github.com/peter-research/TooPowerful)
