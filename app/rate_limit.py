from __future__ import annotations

import asyncio
import time

_locks: dict[str, asyncio.Lock] = {}
_last_request_at: dict[str, float] = {}


async def wait_for_provider_slot(provider: str, min_interval_seconds: float) -> None:
    if min_interval_seconds <= 0:
        return

    lock = _locks.setdefault(provider, asyncio.Lock())
    async with lock:
        now = time.monotonic()
        last_request_at = _last_request_at.get(provider)
        if last_request_at is not None:
            wait_seconds = min_interval_seconds - (now - last_request_at)
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
        _last_request_at[provider] = time.monotonic()

