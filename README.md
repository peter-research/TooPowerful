# TooPowerful

HTTP client Python **plus puissant que `requests` et `httpx`**.

**Version `0.0.1`** — alpha, zéro dépendance.

```bash
pip install git+https://github.com/peter-research/TooPowerful.git
```

```python
import toopowerful as tp

r = tp.get("https://httpbin.org/get", params={"q": "too"})
print(r.status_code, r.json())
```

---

## Pourquoi TooPowerful

| Capacité | requests | httpx | **TooPowerful** |
|---|---|---|---|
| API `get` / `post` / session | oui | oui | oui |
| Zéro dépendance | non | non | **oui** |
| Retries + backoff | add-on | add-on | **natif** |
| Cache GET TTL | non | non | **natif** |
| Middleware before / after | limité | limité | **natif** |
| Parallèle (`map` / `gather`) | non | partiel | **natif** |
| Sync + async même modèle | non | oui | **oui** |
| Auth Basic / Bearer | oui | oui | **oui** |
| Cookies session | oui | oui | **oui** |
| Redirects + history | oui | oui | **oui** |
| Multipart / fichiers | oui | oui | **oui** |
| Timeouts structurés | partiel | oui | **oui** |

Transport : `urllib` (stdlib).

---

## Installation

```bash
pip install git+https://github.com/peter-research/TooPowerful.git
```

```bash
git clone https://github.com/peter-research/TooPowerful.git
cd TooPowerful
pip install -e ".[dev]"
pytest
```

**Python ≥ 3.9.** Aucune dépendance runtime.

---

## Quickstart

### One-shot

```python
import toopowerful as tp

r = tp.get("https://httpbin.org/get")
r.raise_for_status()
tp.post("https://httpbin.org/post", json={"ok": True})
```

### Session + cache + retry + auth

```python
from toopowerful import BearerAuth, Client, MemoryCache, Retry

with Client(
    base_url="https://httpbin.org",
    timeout=20,
    retry=Retry(attempts=4, backoff=0.3),
    cache=MemoryCache(ttl=30),
    auth=BearerAuth("secret"),
) as http:
    a = http.get("/uuid")
    b = http.get("/uuid")  # cache hit
    print(b.from_cache)
```

### Auth Basic

```python
from toopowerful import BasicAuth, Client

http = Client(auth=BasicAuth("user", "pass"))
# ou : http.get(url, auth=("user", "pass"))
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

### Parallèle / Async

```python
from toopowerful import Client
Client(base_url="https://httpbin.org").map("GET", ["/get", "/headers"])
```

```python
import asyncio
from toopowerful import AsyncClient

async def main():
    async with AsyncClient(base_url="https://httpbin.org") as http:
        r = await http.get("/get")
        batch = await http.gather("GET", ["/uuid", "/headers"])

asyncio.run(main())
```

### Redirects

```python
from toopowerful import Client
r = Client(max_redirects=5).get("https://httpbin.org/redirect/2")
print(len(r.history), r.url)
```

---

## API

- Version : `toopowerful.__version__` → `"0.0.1"`
- Module : `request`, `get`, `post`, `put`, `patch`, `delete`, `head`, `options`
- `Client` / `AsyncClient` : `base_url`, `headers`, `timeout`, `retry`, `cache`, `middleware`, `auth`, `cookies`, `verify`, `allow_redirects`, `max_redirects`
- Kwargs : `params`, `headers`, `data`, `json`, `content`, `files`, `auth`, `timeout`, `cache`, `allow_redirects`
- `Response` : `status_code`, `headers`, `content`, `text`, `url`, `elapsed`, `from_cache`, `ok`, `cookies`, `history`, `is_redirect`, `.json()`, `.raise_for_status()`
- Auth : `BasicAuth`, `BearerAuth`, ou `auth=("user", "pass")`
- `Retry(attempts=3, backoff=0.4)`, `MemoryCache(ttl=30)`

---

## Licence

MIT — [github.com/peter-research/TooPowerful](https://github.com/peter-research/TooPowerful)
