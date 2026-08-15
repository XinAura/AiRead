from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import (
    AbstractAsyncContextManager,
    AbstractContextManager,
    asynccontextmanager,
    contextmanager,
)
from typing import Protocol

from redis import Redis


class SlotLimiter(Protocol):
    def hold(self) -> AbstractContextManager[None]: ...

    def hold_async(self) -> AbstractAsyncContextManager[None]: ...


class NoopSlotLimiter:
    @contextmanager
    def hold(self) -> Iterator[None]:
        yield

    @asynccontextmanager
    async def hold_async(self) -> AsyncIterator[None]:
        yield


class RedisSlotLimiter:
    def __init__(
        self,
        redis_url: str,
        name: str,
        slots: int,
        *,
        lease_seconds: int = 180,
        acquire_timeout_seconds: int = 60,
    ) -> None:
        self.client = Redis.from_url(redis_url, decode_responses=True)
        self.name = name
        self.slots = slots
        self.lease_seconds = lease_seconds
        self.acquire_timeout_seconds = acquire_timeout_seconds

    @contextmanager
    def hold(self) -> Iterator[None]:
        slot, token = self._acquire()
        try:
            yield
        finally:
            self._release(slot, token)

    @asynccontextmanager
    async def hold_async(self) -> AsyncIterator[None]:
        deadline = time.monotonic() + self.acquire_timeout_seconds
        token = str(uuid.uuid4())
        slot: str | None = None
        while time.monotonic() < deadline and slot is None:
            slot = self._try_acquire(token)
            if slot is None:
                await asyncio.sleep(0.1)
        if slot is None:
            raise TimeoutError(f"等待 {self.name} 并发槽超时")
        try:
            yield
        finally:
            self._release(slot, token)

    def _acquire(self) -> tuple[str, str]:
        deadline = time.monotonic() + self.acquire_timeout_seconds
        token = str(uuid.uuid4())
        while time.monotonic() < deadline:
            slot = self._try_acquire(token)
            if slot is not None:
                return slot, token
            time.sleep(0.1)
        raise TimeoutError(f"等待 {self.name} 并发槽超时")

    def _try_acquire(self, token: str) -> str | None:
        for index in range(self.slots):
            key = f"airead:limit:{self.name}:{index}"
            if self.client.set(key, token, nx=True, ex=self.lease_seconds):
                return key
        return None

    def _release(self, key: str, token: str) -> None:
        self.client.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) else return 0 end",
            1,
            key,
            token,
        )
