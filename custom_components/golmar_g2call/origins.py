"""Reauth origin bookkeeping (monitor password vs cloud token chain)."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .const import DOMAIN

REAUTH_ORIGINS_KEY = "reauth_origins"


def set_reauth_origin(hass: HomeAssistant, entry_id: str, origin: str) -> None:
    """Remember which credential set needs reauth for this entry."""
    origins = hass.data.setdefault(DOMAIN, {}).setdefault(REAUTH_ORIGINS_KEY, {})
    origins[entry_id] = origin


def pop_reauth_origin(hass: HomeAssistant, entry_id: str) -> str:
    """Return (and clear) the reauth origin; defaults to the monitor."""
    origins = hass.data.get(DOMAIN, {}).get(REAUTH_ORIGINS_KEY, {})
    return origins.pop(entry_id, "monitor")
