"""Cloud OpenAPI client for Golmar G2Call+ (door opening).

Home Assistant agnostic: receives an ``aiohttp.ClientSession`` and an async
``token_provider`` callable so the coordinator owns the token lifecycle.

Protocol validated on 2026-10-22 (docs/WORKLOG.md Fase 5):

- ``GET  /openapi-tdk/client/user/findUserServerInfo`` -> token check (read only)
- ``POST /openapi-tdk/devctr/synccontrol/singledev`` -> device command
- header ``token: <access_token>``
- body ``{"deviceId", "password", "command", "content"}`` where ``deviceId`` is
  the device UID and ``password`` is the device password from the label.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

from .const import (
    CLOUD_API_HOST,
    CLOUD_SERVER_INFO_PATH,
    CLOUD_SYNC_PATH,
    CLOUD_TIMEOUT,
)
from .oauth import CloudAuthError, CloudError, CloudUnavailable, hash_password

_LOGGER = logging.getLogger(__name__)

CMD_OPENDOOR = "set.device.opendoor"


class GolmarCloudClient:
    """Minimal client for the Golmar cloud OpenAPI."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        token_provider: Callable[[], Awaitable[str]],
        verify_tls: bool = False,
        host: str = CLOUD_API_HOST,
    ) -> None:
        self._session = session
        self._token_provider = token_provider
        self._verify_tls = verify_tls
        self._host = host

    async def get_server_info(self) -> dict[str, Any]:
        """Return the user server info payload (validates the token, no side effects)."""
        return await self._request("GET", CLOUD_SERVER_INFO_PATH)

    async def unlock(
        self,
        *,
        device_id: str,
        device_password: str,
        door: int,
        lock: int,
        code: str,
        user: str,
    ) -> None:
        """Send ``set.device.opendoor`` for one lock.

        Raises:
            CloudAuthError: invalid token (reauth needed).
            CloudError: the server rejected the command (never retried here).
            CloudUnavailable: network failure.
        """
        body = {
            "deviceId": device_id,
            "password": device_password,
            "command": CMD_OPENDOOR,
            "content": {
                "password": hash_password(code),
                "door": door,
                "locknumber": lock,
                "user": user,
            },
        }
        await self._request("POST", CLOUD_SYNC_PATH, body=body)

    async def _request(
        self, method: str, path: str, *, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        token = await self._token_provider()
        url = f"https://{self._host}{path}"
        headers = {
            "token": token,
            "Accept": "application/json",
        }
        data = None
        if body is not None:
            data = json.dumps(body, separators=(",", ":"))
            headers["Content-Type"] = "application/json"

        try:
            async with self._session.request(
                method,
                url,
                data=data,
                headers=headers,
                ssl=None if self._verify_tls else False,
                timeout=aiohttp.ClientTimeout(total=CLOUD_TIMEOUT),
            ) as resp:
                status = resp.status
                try:
                    payload: dict[str, Any] = await resp.json(content_type=None)
                except (json.JSONDecodeError, aiohttp.ContentTypeError):
                    payload = {}
        except (TimeoutError, aiohttp.ClientError) as err:
            raise CloudUnavailable(f"Cloud request failed: {err}") from err

        if status in (401, 403):
            raise CloudAuthError(f"Cloud rejected the token (HTTP {status})")
        if status >= 500:
            raise CloudUnavailable(f"Cloud server error (HTTP {status})")
        if status != 200:
            raise CloudError(f"Cloud error (HTTP {status})")

        result = payload.get("result")
        if result not in (0, "0", None):
            raise CloudError(f"Cloud command failed (result={result})")

        inner = payload.get("payload")
        if isinstance(inner, str) and inner:
            try:
                inner = json.loads(inner)
            except json.JSONDecodeError as err:
                raise CloudError("Malformed cloud payload") from err
        if isinstance(inner, dict):
            error = inner.get("error")
            if error not in (0, "0", None):
                raise CloudError(f"Cloud command rejected (error={error})")

        return payload
