# TooPowerful

**Client HTTP Python plus puissant que `requests` et `httpx`.**

Sync + async. Retries. Cache. Middleware. Auth. Parallèle. **Zéro dépendance.**

[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
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

## Sommaire

- [Pourquoi TooPowerful](#pourquoi-toopowerful)
- [Installation](#installation)
- [Quickstart](#quickstart)
- [API](#api)
- [Comparaison](#comparaison)
- [Développement](#développement)
- [Licence](#licence)

---

## Pourquoi TooPowerful

`requests` est simple. `httpx` est moderne. **TooPowerful** rassemble les deux et ajoute ce qui manque en natif.

| Capacité | requests | httpx | TooPowerful |
|---|:---:|:---:|:---:|
| API `get` / `post` / session | oui | oui | oui |
| Zéro dépendance runtime | non | non | **oui** |
| Retries + backoff | add-on | add-on | **natif** |
| Cache GET (TTL) | non | non | **natif** |
| Middleware before / after | limité | limité | **natif** |
| Parallèle (`map` / `gather`) | non | partiel | **natif** |
| Sync + async, même modèle | non | oui | **oui** |
| Auth Basic / Bearer | oui | oui | **oui** |
| Cookies de session | oui | oui | **oui** |
| Redirects + history | oui | oui | **oui** |
| Multipart / fichiers | oui | oui | **oui** |
| Timeouts structurés | partiel | oui | **oui** |

Transport : `urllib` (stdlib). Rien à installer à part Python.

---

## Installation

**Python ≥ 3.9.** Aucune dépendance runtime.

### Depuis GitHub (recommandé)

```bash
pip install git+https://github.com/peter-research/TooPowerful.git
```

### Clone + install éditable

```bash
git clone https://github.com/peter-research/TooPowerful.git
cd TooPowerful
pip install -e .
```

### Avec les outils de dev (pytest)

```bash
pip install -e ".[dev]"
pytest
```

Vérifier :

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

Mêmes verbes que `requests` : `get`, `post`, `put`, `patch`, `delete`, `head`, `options`, `request`.

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

### Parallèle (sync)

```python
from toopowerful import Client

Client(base_url="https://httpbin.org").map("GET", ["/get", "/headers"])
```

### Async

```python
import asyncio
from toopowerful import AsyncClient

async def main():
    async with AsyncClient(base_url="https://httpbin.org") as http:
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

---

## API

### Module

| Symbole | Rôle |
|---|---|
| `toopowerful.__version__` | `"0.0.1"` |
| `request` / `get` / `post` / `put` / `patch` / `delete` / `head` / `options` | one-shot |
| `Client` | session synchrone |
| `AsyncClient` | session asynchrone |

### `Client` / `AsyncClient`

Paramètres constructeur : `base_url`, `headers`, `timeout`, `retry`, `cache`, `middleware`, `auth`, `cookies`, `verify`, `allow_redirects`, `max_redirects`.

Kwargs par requête : `params`, `headers`, `data`, `json`, `content`, `files`, `auth`, `timeout`, `cache`, `allow_redirects`.

### `Response`

`status_code`, `headers`, `content`, `text`, `url`, `elapsed`, `from_cache`, `ok`, `cookies`, `history`, `is_redirect`, `.json()`, `.raise_for_status()`.

### Auth, retry, cache

- `BasicAuth(user, password)` ou `auth=("user", "pass")`
- `BearerAuth(token)`
- `Retry(attempts=3, backoff=0.4)`
- `MemoryCache(ttl=30)`

### Exceptions

`TooPowerfulError`, `HTTPStatusError`, `TimeoutError`, `TooManyRedirects`.

---

## Comparaison

TooPowerful n’essaie pas d’être un clone. Il vise **une seule API** pour ce que les gens empilent habituellement : `requests` + `urllib3.Retry` + un cache maison + un petit pool.

- **vs requests** : async, cache, retry, `map`, middleware, zéro dépendance.
- **vs httpx** : cache TTL, retries natifs, `map`/`gather`, zéro dépendance (pas de httpcore / h11).

Alpha `0.0.1`. API encore mobile.

---

## Développement

```bash
git clone https://github.com/peter-research/TooPowerful.git
cd TooPowerful
pip install -e ".[dev]"
pytest
```

Layout :

```
src/toopowerful/     # package
tests/               # pytest
examples/quickstart.py
```

---

## Licence

MIT — [peter-research/TooPowerful](https://github.com/peter-research/TooPowerful)
