"""OAuth2 client for the Golmar/Qualvision cloud.

Home Assistant agnostic: it receives an ``aiohttp.ClientSession`` so the
integration can inject Home Assistant's shared session.

Wire format validated on 2026-10-22 (see docs/02_autenticacion.md and
docs/WORKLOG.md, Fase 5):

- endpoint ``https://r1-2.qvcloud.net/qvoauthv2/token`` (the V3.3 ``oauth2r1``
  host hangs with real credentials for this deployment);
- ``pwd`` is the lowercase SHA-256 hex of the account password
  (server flag ``LoginPasswordHashCheck`` is enabled);
- ``region_id=1`` for this account (``0`` makes the backend hang);
- TLS uses the private QUALVISION CA, hence ``verify_tls`` is configurable.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp

from .const import (
    CLOUD_APP_ID,
    CLOUD_CLIENT_TYPE,
    CLOUD_OAUTH_HOST,
    CLOUD_OAUTH_PATH,
    CLOUD_OEM_ID,
    CLOUD_TIMEOUT,
    DEFAULT_REGION_ID,
    OAUTH_RESULT_PASSWORD_ERROR,
)

_LOGGER = logging.getLogger(__name__)


class CloudError(Exception):
    """Base error for Golmar cloud operations."""


class CloudAuthError(CloudError):
    """Invalid account credentials or a dead token chain (reauth needed)."""


class CloudUnavailable(CloudError):
    """The cloud service could not be reached."""


def hash_password(password: str) -> str:
    """Return the lowercase SHA-256 hex the protocol expects as ``pwd``."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def jwt_claims(token: str) -> dict[str, Any]:
    """Decode JWT claims without verifying the signature (expiry tracking only)."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    except (IndexError, ValueError, json.JSONDecodeError):
        return {}


def _expiry(token: str) -> datetime | None:
    exp = jwt_claims(token).get("exp")
    if not isinstance(exp, int):
        return None
    return datetime.fromtimestamp(exp, tz=UTC)


@dataclass(frozen=True)
class TokenSet:
    """Access/refresh tokens with their expiries."""

    access_token: str
    refresh_token: str
    access_expires_at: datetime | None
    refresh_expires_at: datetime | None

    def needs_refresh(self, margin: timedelta) -> bool:
        """Return True when the access token is inside the refresh margin."""
        if self.access_expires_at is None:
            return False
        return datetime.now(tz=UTC) >= self.access_expires_at - margin


class GolmarOAuth:
    """Minimal OAuth2 password/refresh client for the Golmar cloud."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        client_id: str,
        verify_tls: bool = False,
        region_id: int = DEFAULT_REGION_ID,
        host: str = CLOUD_OAUTH_HOST,
    ) -> None:
        self._session = session
        self._client_id = client_id
        self._verify_tls = verify_tls
        self._region_id = region_id
        self._host = host

    async def login(self, account: str, password: str) -> TokenSet:
        """Log in with the plaintext account password.

        The password is hashed in memory and never logged or stored.
        A single attempt is made: callers must not retry credentials
        automatically (account lockout risk).
        """
        return await self.login_with_hash(account, hash_password(password))

    async def login_with_hash(self, account: str, password_hash: str) -> TokenSet:
        """Log in with the pre-hashed password (stored form in the entry)."""
        return await self._request(
            {
                "grant_type": "password",
                "client_id": self._client_id,
                "client_type": CLOUD_CLIENT_TYPE,
                "oemid": CLOUD_OEM_ID,
                "appid": CLOUD_APP_ID,
                "usr": account,
                "pwd": password_hash,
                "region_id": str(self._region_id),
                "client_flag": "1",
            }
        )

    async def refresh(self, refresh_token: str) -> TokenSet:
        """Refresh the token chain (each call issues a new 24 h refresh token)."""
        return await self._request(
            {
                "grant_type": "refresh_token",
                "client_id": self._client_id,
                "client_type": CLOUD_CLIENT_TYPE,
                "oemid": CLOUD_OEM_ID,
                "appid": CLOUD_APP_ID,
                "region_id": str(self._region_id),
                "refresh_token": refresh_token,
                "client_flag": "1",
            }
        )

    async def _request(self, params: dict[str, str]) -> TokenSet:
        url = f"https://{self._host}{CLOUD_OAUTH_PATH}"
        try:
            async with self._session.get(
                url,
                params=params,
                ssl=None if self._verify_tls else False,
                timeout=aiohttp.ClientTimeout(total=CLOUD_TIMEOUT),
            ) as resp:
                status = resp.status
                try:
                    body: dict[str, Any] = await resp.json(content_type=None)
                except (json.JSONDecodeError, aiohttp.ContentTypeError):
                    body = {}
        except (TimeoutError, aiohttp.ClientError) as err:
            raise CloudUnavailable(f"OAuth request failed: {err}") from err

        access = body.get("access_token")
        refresh = body.get("refresh_token")
        if status == 200 and access and refresh:
            return TokenSet(
                access_token=access,
                refresh_token=refresh,
                access_expires_at=_expiry(access),
                refresh_expires_at=_expiry(refresh),
            )

        result = body.get("result")
        if status in (401, 403) or result == OAUTH_RESULT_PASSWORD_ERROR:
            raise CloudAuthError(f"OAuth rejected credentials (result={result})")
        raise CloudError(f"Unexpected OAuth response (HTTP {status}, result={result})")
