"""Data update coordinator for the Golmar G2Call+ integration.

Responsibilities:

- Poll the monitor identity over the local CGI (15 min). A sleeping CGI is a
  normal condition ("offline"), not a setup failure; a 401 is an auth failure
  and triggers reauth.
- Own the cloud token chain: refresh the access token proactively (5 min
  margin) in every cycle and before every cloud action. A rejected refresh
  chain triggers reauth; a network failure keeps a still-valid token.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import DeviceInfo, GolmarAuthError, GolmarLocalClient, GolmarUnavailable
from .const import DOMAIN, TOKEN_REFRESH_MARGIN, UPDATE_INTERVAL
from .oauth import CloudAuthError, CloudUnavailable, GolmarOAuth, TokenSet
from .origins import set_reauth_origin

_LOGGER = logging.getLogger(__name__)


class GolmarDataCoordinator(DataUpdateCoordinator[DeviceInfo | None]):
    """Coordinate monitor identity polling and cloud token lifecycle."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        config_entry: ConfigEntry,
        local: GolmarLocalClient,
        oauth: GolmarOAuth | None,
        tokens: TokenSet | None,
        device_uid: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=config_entry,
            update_interval=UPDATE_INTERVAL,
            always_update=False,
        )
        self._local = local
        self._oauth = oauth
        self._tokens = tokens
        self._token_lock = asyncio.Lock()
        self.device_uid = device_uid

    @property
    def tokens(self) -> TokenSet | None:
        """Return the current cloud token set (diagnostics/tests)."""
        return self._tokens

    async def async_get_token(self) -> str:
        """Return a valid access token, refreshing proactively if needed.

        Called by the cloud client before every request.
        """
        async with self._token_lock:
            if self._tokens is None:
                raise ConfigEntryAuthFailed("No cloud session available")
            if self._tokens.needs_refresh(TOKEN_REFRESH_MARGIN):
                self._tokens = await self._async_refresh_tokens()
            return self._tokens.access_token

    async def _async_refresh_tokens(self) -> TokenSet:
        """Refresh the token chain (caller holds the token lock)."""
        if self._oauth is None or self._tokens is None:
            raise ConfigEntryAuthFailed("Cloud session unavailable")
        try:
            return await self._oauth.refresh(self._tokens.refresh_token)
        except CloudAuthError as err:
            raise ConfigEntryAuthFailed("Cloud token chain rejected") from err
        except CloudUnavailable:
            # Keep a still-valid token; otherwise let the cloud path fail.
            if self._tokens.needs_refresh(timedelta(0)):
                raise
            _LOGGER.debug("Cloud unreachable during proactive refresh; keeping valid token")
            return self._tokens

    async def _async_update_data(self) -> DeviceInfo | None:
        """Poll the monitor identity; keep the cloud token chain warm."""
        if self._tokens is not None:
            try:
                await self.async_get_token()
            except ConfigEntryAuthFailed:
                raise
            except CloudUnavailable:
                _LOGGER.debug("Cloud unreachable; local polling continues")

        try:
            return await self._local.identify()
        except GolmarAuthError as err:
            set_reauth_origin(self.hass, self.config_entry.entry_id, "monitor")
            raise ConfigEntryAuthFailed("Monitor rejected the device password") from err
        except GolmarUnavailable:
            # The CGI is transient: a closed port means "asleep", not an error.
            _LOGGER.debug("Monitor CGI is not reachable (asleep)")
            return None
