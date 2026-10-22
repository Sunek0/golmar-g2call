"""The Golmar G2Call+ integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GolmarLocalClient
from .cloud_api import GolmarCloudClient
from .const import (
    CONF_ACCOUNT,
    CONF_ACCOUNT_PASSWORD,
    CONF_CLIENT_ID,
    CONF_DEVICE_PASSWORD,
    CONF_DEVICE_UID,
    CONF_HOST,
    CONF_PORT,
    CONF_REGION_ID,
    CONF_SCHEME,
    CONF_VERIFY_TLS,
    DEFAULT_REGION_ID,
)
from .control import UnlockGate
from .coordinator import GolmarDataCoordinator
from .oauth import CloudAuthError, CloudUnavailable, GolmarOAuth
from .origins import set_reauth_origin
from .runtime import GolmarRuntimeData, entry_config

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Golmar G2Call+ from a config entry."""
    config = entry_config(entry)
    session = async_get_clientsession(hass)

    local = GolmarLocalClient(
        session,
        host=config[CONF_HOST],
        device_password=config[CONF_DEVICE_PASSWORD],
        port=config[CONF_PORT],
        scheme=config[CONF_SCHEME],
        verify_tls=config[CONF_VERIFY_TLS],
    )
    oauth = GolmarOAuth(
        session,
        client_id=config[CONF_CLIENT_ID],
        verify_tls=config[CONF_VERIFY_TLS],
        region_id=config.get(CONF_REGION_ID, DEFAULT_REGION_ID),
    )

    tokens = None
    try:
        # One login attempt per setup: never retry credentials automatically.
        tokens = await oauth.login_with_hash(
            config[CONF_ACCOUNT], config[CONF_ACCOUNT_PASSWORD]
        )
    except CloudAuthError as err:
        set_reauth_origin(hass, entry.entry_id, "cloud")
        raise ConfigEntryAuthFailed("Cloud credentials rejected") from err
    except CloudUnavailable:
        # Cloud down at startup: keep the local fallback alive.
        _LOGGER.warning(
            "Golmar cloud unreachable during setup; door opening will use the local path"
        )

    coordinator = GolmarDataCoordinator(
        hass,
        config_entry=entry,
        local=local,
        oauth=oauth,
        tokens=tokens,
        device_uid=config[CONF_DEVICE_UID],
    )
    cloud = (
        GolmarCloudClient(
            session,
            token_provider=coordinator.async_get_token,
            verify_tls=config[CONF_VERIFY_TLS],
        )
        if tokens is not None
        else None
    )

    entry.runtime_data = GolmarRuntimeData(
        local=local, cloud=cloud, coordinator=coordinator, config=config, gate=UnlockGate()
    )

    # A sleeping CGI is not a setup failure by design (data=None, entities offline).
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry.runtime_data = None
    return unload_ok


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change (door map, unlock code)."""
    await hass.config_entries.async_reload(entry.entry_id)
