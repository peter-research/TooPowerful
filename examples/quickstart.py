"""Exemples TooPowerful."""

import toopowerful as tp
from toopowerful import AsyncClient, Client, MemoryCache, Retry


def sync_demo() -> None:
    r = tp.get("https://httpbin.org/get", params={"lib": "toopowerful"})
    print(r.status_code, r.url)

    with Client(
        base_url="https://httpbin.org",
        headers={"X-Lib": "TooPowerful"},
        retry=Retry(attempts=3),
        cache=MemoryCache(ttl=15),
    ) as http:
        first = http.get("/uuid")
        second = http.get("/uuid")
        print("cache hit?", second.from_cache, first.text == second.text)
        many = http.map("GET", ["/get", "/headers", "/user-agent"])
        print([m.status_code for m in many])


async def async_demo() -> None:
    async with AsyncClient(base_url="https://httpbin.org") as http:
        r = await http.get("/get")
        print("async", r.status_code)
        batch = await http.gather("GET", ["/uuid", "/uuid"])
        print("gather", [b.status_code for b in batch])


if __name__ == "__main__":
    sync_demo()
