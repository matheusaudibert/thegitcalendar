"""Cross-instance cache backed by Upstash Redis (REST API).

On Vercel every serverless instance has its own memory, so the in-process
TTLCache alone can't stop several instances from each hitting GitHub for the
same profile. This layer stores fetched data in Redis so one GitHub fetch
serves every instance, and a short Redis lock makes concurrent cold requests
for the same key wait for that single fetch instead of all fetching at once.

Redis is purely an optimization: when it isn't configured, or a Redis call
fails, requests fall back to fetching directly and still succeed.

Configured by the env vars the Vercel Upstash integration creates —
``KV_REST_API_URL``/``KV_REST_API_TOKEN`` or
``UPSTASH_REDIS_REST_URL``/``UPSTASH_REDIS_REST_TOKEN``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from typing import Any, Awaitable, Callable, Generic, TypeVar

import httpx

T = TypeVar("T")

logger = logging.getLogger(__name__)

KEY_PREFIX = "gitcalendar:"
REDIS_TIMEOUT = 3.0
LOCK_TTL_SECONDS = 30
WAIT_FOR_LOCK_SECONDS = 15.0
POLL_INTERVAL_SECONDS = 0.25


class RedisError(Exception):
    pass


class SharedCache(Generic[T]):
    def __init__(
        self,
        *,
        url: str | None,
        token: str | None,
        ttl_seconds: int,
        encode: Callable[[T], str],
        decode: Callable[[str], T],
    ):
        self.url = url.rstrip("/") if url else None
        self.token = token
        self.ttl_seconds = ttl_seconds
        self.encode = encode
        self.decode = decode

    @classmethod
    def from_env(
        cls, *, ttl_seconds: int, encode: Callable[[T], str], decode: Callable[[str], T]
    ) -> SharedCache[T]:
        url = os.environ.get("KV_REST_API_URL") or os.environ.get("UPSTASH_REDIS_REST_URL")
        token = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("UPSTASH_REDIS_REST_TOKEN")
        return cls(url=url, token=token, ttl_seconds=ttl_seconds, encode=encode, decode=decode)

    @property
    def enabled(self) -> bool:
        return bool(self.url and self.token)

    async def _command(self, *args: str | int) -> Any:
        try:
            async with httpx.AsyncClient(timeout=REDIS_TIMEOUT) as client:
                resp = await client.post(
                    self.url,
                    json=[str(a) for a in args],
                    headers={"Authorization": f"Bearer {self.token}"},
                )
        except httpx.HTTPError as exc:
            raise RedisError(f"Redis request failed: {exc}") from exc
        if resp.status_code != 200:
            raise RedisError(f"Redis returned HTTP {resp.status_code}: {resp.text[:200]}")
        payload = resp.json()
        if "error" in payload:
            raise RedisError(payload["error"])
        return payload.get("result")

    async def _read(self, key: str) -> T | None:
        try:
            raw = await self._command("GET", key)
            return self.decode(raw) if raw is not None else None
        except Exception as exc:  # a bad/corrupt entry is just a miss
            logger.warning("shared cache read failed for %s: %s", key, exc)
            return None

    async def _write(self, key: str, value: T) -> None:
        try:
            await self._command("SET", key, self.encode(value), "EX", self.ttl_seconds)
        except RedisError as exc:
            logger.warning("shared cache write failed for %s: %s", key, exc)

    async def get_or_fetch(self, key: str, fetch: Callable[[], Awaitable[T]]) -> T:
        if not self.enabled:
            return await fetch()

        data_key = f"{KEY_PREFIX}{key}"
        lock_key = f"{data_key}:lock"

        cached = await self._read(data_key)
        if cached is not None:
            return cached

        owner = uuid.uuid4().hex
        try:
            acquired = await self._command("SET", lock_key, owner, "NX", "EX", LOCK_TTL_SECONDS) == "OK"
        except RedisError as exc:
            logger.warning("shared cache lock failed for %s: %s", key, exc)
            return await fetch()

        if not acquired:
            # Another instance is already fetching this profile — wait for
            # its result instead of hitting GitHub again. If it never lands
            # (that fetch failed or is very slow), fetch it ourselves.
            deadline = time.monotonic() + WAIT_FOR_LOCK_SECONDS
            while time.monotonic() < deadline:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                cached = await self._read(data_key)
                if cached is not None:
                    return cached
                try:
                    if await self._command("EXISTS", lock_key) == 0:
                        break  # the other fetch gave up without a result
                except RedisError:
                    break
            return await fetch()

        try:
            value = await fetch()
            await self._write(data_key, value)
            return value
        finally:
            try:
                # Only release the lock if it's still ours.
                if await self._command("GET", lock_key) == owner:
                    await self._command("DEL", lock_key)
            except RedisError:
                pass  # it expires on its own after LOCK_TTL_SECONDS
