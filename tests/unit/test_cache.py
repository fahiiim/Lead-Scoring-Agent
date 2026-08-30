from __future__ import annotations

from app.utils.cache import MemoryTTLCache


async def test_memory_cache_get_set_and_clear() -> None:
    cache = MemoryTTLCache[str](default_ttl_seconds=60)
    await cache.set("company", "result")

    assert await cache.get("company") == "result"

    await cache.clear()
    assert await cache.get("company") is None


async def test_memory_cache_evicts_earliest_expiry() -> None:
    cache = MemoryTTLCache[str](default_ttl_seconds=60, max_entries=2)
    await cache.set("short", "first", ttl_seconds=1)
    await cache.set("long", "second", ttl_seconds=60)
    await cache.set("new", "third", ttl_seconds=60)

    assert await cache.get("short") is None
    assert await cache.get("long") == "second"
    assert await cache.get("new") == "third"
