from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar


T = TypeVar("T")


class Cache(Protocol, Generic[T]):
    async def get(self, key: str) -> T | None: ...

    async def set(self, key: str, value: T, ttl_seconds: int | None = None) -> None: ...


@dataclass(slots=True)
class _Entry(Generic[T]):
    value: T
    expires_at: float


class MemoryTTLCache(Generic[T]):
    """Small process-local cache with lazy expiry and concurrency protection."""

    def __init__(self, default_ttl_seconds: int, max_entries: int = 1_000) -> None:
        self._default_ttl_seconds = default_ttl_seconds
        self._max_entries = max_entries
        self._entries: dict[str, _Entry[T]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> T | None:
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.expires_at <= time.monotonic():
                self._entries.pop(key, None)
                return None
            return entry.value

    async def set(self, key: str, value: T, ttl_seconds: int | None = None) -> None:
        ttl = ttl_seconds or self._default_ttl_seconds
        async with self._lock:
            if len(self._entries) >= self._max_entries:
                oldest_key = min(
                    self._entries,
                    key=lambda candidate: self._entries[candidate].expires_at,
                )
                self._entries.pop(oldest_key, None)
            self._entries[key] = _Entry(
                value=value,
                expires_at=time.monotonic() + ttl,
            )

    async def clear(self) -> None:
        async with self._lock:
            self._entries.clear()
