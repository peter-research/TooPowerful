"""TooPowerful 0.1.0 examples."""

import toopowerful as tp
from toopowerful import AsyncClient, BasicAuth, BearerAuth, Client, MemoryCache, Retry


def sync_demo() -> None:
    r = tp.get("https://httpbin.org/get", params={"lib": "toopowerful"})
    print("one-shot", r.status_code, r.url)

    with Client(
        base_url="https://httpbin.org",
        headers={"X-Lib": "TooPowerful"},
        retry=Retry(attempts=3),
        cache=MemoryCache(ttl=15),
        auth=BearerAuth("demo-token"),
    ) as http:
        first = http.get("/uuid")
        second = http.get("/uuid")
        print("cache hit?", second.from_cache)
        many = http.map("GET", ["/get", "/headers", "/user-agent"])
        print("map", [m.status_code for m in many])
        auth_r = http.get("/basic-auth/user/pass", auth=BasicAuth("user", "pass"))
        print("basic auth", auth_r.status_code)


async def async_demo() -> None:
    async with AsyncClient(base_url="https://httpbin.org") as http:
        r = await http.get("/get")
        batch = await http.gather("GET", ["/uuid", "/headers"])
        print("async", r.status_code, [b.status_code for b in batch])


if __name__ == "__main__":
    print("version", tp.__version__)
    sync_demo()
