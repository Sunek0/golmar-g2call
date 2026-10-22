"""Diagnostics support for the Golmar G2Call+ integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ACCOUNT_PASSWORD,
    CONF_DEVICE_PASSWORD,
    CONF_UNLOCK_CODE,
)
from .runtime import GolmarRuntimeData

REDACTED = "**REDACTED**"
SENSITIVE_KEYS = {CONF_ACCOUNT_PASSWORD, CONF_DEVICE_PASSWORD, CONF_UNLOCK_CODE}


def _redact(values: dict[str, Any]) -> dict[str, Any]:
    return {
        key: (REDACTED if key in SENSITIVE_KEYS else value)
        for key, value in values.items()
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics with secrets and tokens redacted."""
    runtime: GolmarRuntimeData | None = entry.runtime_data
    tokens = runtime.coordinator.tokens if runtime else None
    data = runtime.coordinator.data if runtime else None

    return {
        "entry": {
            "data": _redact(dict(entry.data)),
            "options": _redact(dict(entry.options)),
            "unique_id": entry.unique_id,
        },
        "runtime": {
            "cloud_enabled": bool(runtime and runtime.cloud),
            "last_update_success": runtime.coordinator.last_update_success
            if runtime
            else None,
            "model": data.model if data else None,
            "firmware": data.firmware if data else None,
            "credentials_configured": {
                "account_password_hash": bool(
                    entry.data.get(CONF_ACCOUNT_PASSWORD)
                    or entry.options.get(CONF_ACCOUNT_PASSWORD)
                ),
                "device_password": bool(
                    (runtime.config if runtime else {}).get(CONF_DEVICE_PASSWORD)
                ),
                "unlock_code": bool(
                    (runtime.config if runtime else {}).get(CONF_UNLOCK_CODE)
                ),
            },
        },
        "tokens": {
            "access_token": REDACTED if tokens and tokens.access_token else None,
            "refresh_token": REDACTED if tokens and tokens.refresh_token else None,
            "access_expires_at": tokens.access_expires_at.isoformat()
            if tokens and tokens.access_expires_at
            else None,
            "refresh_expires_at": tokens.refresh_expires_at.isoformat()
            if tokens and tokens.refresh_expires_at
            else None,
        },
    }
