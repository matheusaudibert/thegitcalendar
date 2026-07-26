from __future__ import annotations

import asyncio
import os
import time
from typing import Awaitable, Callable, Generic, TypeVar

T = TypeVar("T")

DEFAULT_TTL_SECONDS = int(os.environ.get("GITCALLENDAR_CACHE_TTL", "3600"))


class TTLCache(Generic[T]):
    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self.ttl_seconds = ttl_seconds
        self._store: dict[str, tuple[float, T]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, key: str) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    async def get_or_fetch(self, key: str, fetch: Callable[[], Awaitable[T]]) -> T:
        cached = self._store.get(key)
        if cached is not None and cached[0] > time.time():
            return cached[1]

        async with self._lock_for(key):
            cached = self._store.get(key)
            if cached is not None and cached[0] > time.time():
                return cached[1]
            value = await fetch()
            self._store[key] = (time.time() + self.ttl_seconds, value)
            return value

    def clear(self) -> None:
        self._store.clear()
