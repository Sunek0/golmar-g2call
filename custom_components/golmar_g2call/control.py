"""Shared unlock serialization and rate limiting (cloud + local paths)."""

from __future__ import annotations

import asyncio
import time

from .const import UNLOCK_RATE_LIMIT


class UnlockRateLimited(Exception):
    """Raised when a second unlock is attempted inside the rate-limit window."""


class UnlockGate:
    """Serialize unlock attempts and enforce a minimum interval.

    The gate is shared by the cloud and local paths so a double press can
    never open the door twice, regardless of which path would serve it.
    """

    def __init__(self, min_interval: float = UNLOCK_RATE_LIMIT) -> None:
        self._lock = asyncio.Lock()
        self._min_interval = min_interval
        self._last_unlock = 0.0

    async def __aenter__(self) -> UnlockGate:
        await self._lock.acquire()
        now = time.monotonic()
        if self._last_unlock and now - self._last_unlock < self._min_interval:
            self._lock.release()
            raise UnlockRateLimited(
                f"Unlock attempted within {self._min_interval:.1f}s of the previous one"
            )
        self._last_unlock = now
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self._lock.release()
