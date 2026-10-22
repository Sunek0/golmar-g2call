"""JUS duplex client (tdkcloud) — session for the alarm/events server.

Home Assistant agnostic: receives an ``aiohttp.ClientSession``.

Protocol validated against the real service (docs/WORKLOG.md, Fase 8):

1. ``GET  https://r1-1.qvcloud.net/auth/user;jus_duplex=down``  -> ``jsessionid`` cookie
2. ``POST https://r1-1.qvcloud.net/auth/user;jus_duplex=up``    -> 200 (login envelope)
3. The login response arrives on the **down channel** (poll GETs, correlate by seq).

The session expires in ~25-30 minutes, so the client re-logs silently with the
stored SHA-256 password hash (never the plaintext).
"""

from __future__ import annotations

import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from typing import Any

import aiohttp

from .const import (
    CLOUD_APP_ID,
    CLOUD_CLIENT_TYPE,
    CLOUD_JUS_HOST,
    CLOUD_OEM_ID,
    JUS_PATH_DOWN,
    JUS_PATH_UP,
    JUS_SESSION_TTL,
    JUS_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)

# Resultados que implican credenciales/sesión rechazadas (reauth, sin reintentos).
AUTH_RESULT_CODES = {
    "100004",
    "100100002",
    "100100003",
    "100101001",
    "100101002",
    "100101004",
}


class JusError(Exception):
    """Base error for JUS operations."""


class JusAuthError(JusError):
    """Credentials rejected (reauth needed)."""


class JusUnavailable(JusError):
    """The JUS service could not be reached."""


class GolmarJusClient:
    """Minimal duplex JUS client used to open alarm-server sessions."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        account: str,
        client_id: str,
        password_hash: str,
        host: str = CLOUD_JUS_HOST,
        timeout: float = JUS_TIMEOUT,
        verify_tls: bool = False,
    ) -> None:
        self._session = session
        self._account = account
        self._client_id = client_id
        self._password_hash = password_hash
        self._host = host
        self._timeout = timeout
        self._verify_tls = verify_tls
        self._lock = asyncio.Lock()
        self._cookie: str | None = None
        self._session_id: str | None = None
        self._account_id: str | None = None
        self._logged_in_at: float = 0.0

    # ------------------------------------------------------------------ props
    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def account_id(self) -> str | None:
        return self._account_id

    @property
    def is_session_fresh(self) -> bool:
        return bool(self._session_id) and (
            time.monotonic() - self._logged_in_at < JUS_SESSION_TTL
        )

    # ------------------------------------------------------------------- api
    async def async_ensure_session(self, *, force: bool = False) -> str:
        """Return a valid JUS session id, re-logging in when needed."""
        async with self._lock:
            if not force and self.is_session_fresh:
                return self._session_id  # type: ignore[return-value]
            await self._async_login()
            return self._session_id  # type: ignore[return-value]

    # -------------------------------------------------------------- internals
    def _envelope(self) -> bytes:
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<envelope><header><client>"
            f"<app>{CLOUD_APP_ID}</app><id>{self._client_id}</id>"
            f"<oem>{CLOUD_OEM_ID}</oem><type>{CLOUD_CLIENT_TYPE}</type>"
            "</client>"
            "<command>login</command><flag>tdkcloud</flag><seq>0</seq>"
            "<session></session><user-data></user-data><version></version>"
            "</header><content>"
            f"<account>{self._account}</account>"
            f"<password>{self._password_hash}</password>"
            "<auth-type>0</auth-type><auth-code></auth-code>"
            "<ip-region-id>0</ip-region-id>"
            "</content></envelope>"
        )
        return xml.encode("utf-8")

    async def _request(self, method: str, path: str, *, data: bytes | None = None):
        url = f"https://{self._host}{path}"
        headers = {
            "User-Agent": "okhttp/4.9.1",
            "Accept-Language": "es-ES",
            "charset": "utf-8",
            "Connection": "close",
        }
        if self._cookie:
            headers["Cookie"] = self._cookie
        if data is not None:
            headers["Content-Type"] = "application/xml"
        try:
            async with self._session.request(
                method,
                url,
                data=data,
                headers=headers,
                ssl=None if self._verify_tls else False,
                timeout=aiohttp.ClientTimeout(total=self._timeout),
            ) as resp:
                cookie = resp.cookies.get("jsessionid")
                if cookie is not None:
                    self._cookie = f"jsessionid={cookie.value}"
                return resp.status, await resp.read()
        except (TimeoutError, aiohttp.ClientError) as err:
            raise JusUnavailable(f"JUS request failed: {err}") from err

    @staticmethod
    def _parse(raw: bytes) -> dict[str, Any] | None:
        text = raw.decode("utf-8", "replace").strip()
        if not text.startswith("<"):
            return None
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return None
        header = root.find("header")
        if header is None:
            return None
        session = header.find("session")
        content = root.find("content")
        return {
            "result": header.findtext("result"),
            "session_id": session.findtext("id") if session is not None else None,
            "content": {child.tag: (child.text or "") for child in content}
            if content is not None
            else {},
        }

    async def _async_login(self) -> None:
        _LOGGER.debug("JUS: iniciando login duplex")
        # 1) Abrir el canal down (obtiene la cookie de transporte).
        await self._request("GET", JUS_PATH_DOWN)
        # 2) Enviar el login por el canal up.
        status, _ = await self._request("POST", JUS_PATH_UP, data=self._envelope())
        if status != 200:
            raise JusError(f"JUS login HTTP {status}")
        # 3) Leer la respuesta por el canal down (correlación por seq).
        response: dict[str, Any] | None = None
        for _attempt in range(8):
            _status, raw = await self._request("GET", JUS_PATH_DOWN)
            parsed = self._parse(raw)
            if parsed is not None:
                response = parsed
                break
            await asyncio.sleep(1.0)
        if response is None:
            raise JusUnavailable("JUS: sin respuesta por el canal down")

        result = str(response.get("result"))
        if result != "0":
            if result in AUTH_RESULT_CODES:
                raise JusAuthError(f"JUS rejected the credentials (result={result})")
            raise JusError(f"JUS login failed (result={result})")

        self._session_id = response.get("session_id") or ""
        self._account_id = str(response["content"].get("account-id") or "")
        self._logged_in_at = time.monotonic()
        _LOGGER.debug("JUS: sesión renovada (account-id presente=%s)", bool(self._account_id))
