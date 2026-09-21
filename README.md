# TooPowerful

HTTP client Python **plus puissant que `requests` et `httpx`**.

API familière (`get`, `post`, `Client`), zéro dépendance, retries natifs, cache mémoire, middleware, parallèle sync **et** async.

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
| Cache GET | non | non | **natif** |
| Middleware before / after | limité | limité | **natif** |
| Parallèle (`map` / `gather`) | non | partiel | **natif** |
| Sync + async même modèle | non | oui | **oui** |
| Timeouts structurés | partiel | oui | **oui** |

Pas un wrapper marketing : le transport est `urllib` (stdlib). Les extras que tout le monde réécrit par-dessus requests sont **dans le cœur**.

---

## Installation

### Depuis GitHub (recommandé)

```bash
pip install git+https://github.com/peter-research/TooPowerful.git
```

### En local, depuis le clone

```bash
git clone https://github.com/peter-research/TooPowerful.git
cd TooPowerful
pip install -e .
```

### Dev + tests

```bash
pip install -e ".[dev]"
pytest
```

**Python ≥ 3.9.** Aucune dépendance runtime.

---

## Quickstart

### One-shot (comme requests)

```python
import toopowerful as tp

r = tp.get("https://httpbin.org/get")
r.raise_for_status()
print(r.text)
print(r.json())

tp.post("https://httpbin.org/post", json={"ok": True})
tp.post("https://httpbin.org/post", data={"form": "1"})
```

### Session persistante

```python
from toopowerful import Client, MemoryCache, Retry

with Client(
    base_url="https://httpbin.org",
    headers={"User-Agent": "TooPowerful"},
    timeout=20,
    retry=Retry(attempts=4, backoff=0.3),
    cache=MemoryCache(ttl=30),
) as http:
    a = http.get("/uuid")
    b = http.get("/uuid")          # cache hit
    print(b.from_cache)
    http.post("/post", json={"x": 1})
```

### Parallèle (sync)

```python
from toopowerful import Client

http = Client(base_url="https://httpbin.org")
pages = http.map("GET", ["/get", "/headers", "/user-agent"], max_workers=8)
print([p.status_code for p in pages])
```

### Async

```python
import asyncio
from toopowerful import AsyncClient

async def main():
    async with AsyncClient(base_url="https://httpbin.org") as http:
        r = await http.get("/get")
        batch = await http.gather("GET", ["/uuid", "/headers"])
        print(r.status_code, [x.status_code for x in batch])

asyncio.run(main())
```

### Middleware

```python
from toopowerful import Client, Middleware

mw = Middleware()

def add_trace(req):
    req.headers.setdefault("X-Trace", "1")
    return req

mw.use_before(add_trace)
mw.use_after(lambda resp: resp)
http = Client(middleware=mw)
```

---

## API

### Module

- `tp.request(method, url, **kw)`
- `tp.get` / `post` / `put` / `patch` / `delete` / `head` / `options`

### `Client` / `AsyncClient`

| Paramètre | Défaut | Rôle |
|---|---|---|
| `base_url` | `""` | Préfixe d’URL |
| `headers` | `{}` | Headers persistants |
| `timeout` | `30` | `float` ou `Timeout(connect, read, total)` |
| `retry` | `Retry(attempts=3)` | Politique de retry |
| `cache` | `None` | `MemoryCache` optionnel |
| `middleware` | vide | Hooks before / after |
| `verify` | `True` | Vérif TLS |

Méthodes : `request`, `get`, `post`, `put`, `patch`, `delete`, `head`, `options`.  
`Client.map(...)` — parallèle threads.  
`AsyncClient.gather(...)` — parallèle asyncio.

Kwargs communs : `params`, `headers`, `data`, `json`, `content`, `timeout`, `cache`.

### `Response`

- `status_code`, `headers`, `content`, `text`, `url`, `elapsed`, `from_cache`, `ok`
- `.json()`, `.raise_for_status()`

### `Retry`

```python
Retry(attempts=3, backoff=0.4, max_backoff=8.0, statuses=(429, 500, 502, 503, 504))
```

### `MemoryCache`

```python
MemoryCache(ttl=30, max_items=256)
```

Cache uniquement les GET 2xx si un cache est attaché au client.

---

## Layout du dépôt

```
TooPowerful/
├── src/toopowerful/     # package installable
│   ├── __init__.py
│   ├── client.py
│   ├── async_client.py
│   ├── transport.py
│   ├── models.py
│   ├── retry.py
│   ├── cache.py
│   └── middleware.py
├── tests/
├── examples/quickstart.py
├── pyproject.toml
└── README.md
```

---

## Roadmap

- [ ] HTTP/2 optionnel (extra)
- [ ] Cookie jar persistante
- [ ] Auth plugins (Bearer, HMAC)
- [ ] Publication PyPI `toopowerful`
- [ ] Streaming / SSE helpers

---

## Licence

MIT — voir `LICENSE`.

Repo : [github.com/peter-research/TooPowerful](https://github.com/peter-research/TooPowerful)
