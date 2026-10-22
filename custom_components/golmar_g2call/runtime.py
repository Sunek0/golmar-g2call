"""Runtime data helpers for the Golmar G2Call+ integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry

from .alarm_api import GolmarAlarmClient
from .api import GolmarLocalClient
from .cloud_api import GolmarCloudClient
from .control import UnlockGate
from .coordinator import GolmarDataCoordinator
from .events_coordinator import GolmarEventsCoordinator
from .jus import GolmarJusClient


@dataclass
class GolmarRuntimeData:
    """Objects shared by all entities of a config entry."""

    local: GolmarLocalClient
    cloud: GolmarCloudClient | None
    coordinator: GolmarDataCoordinator
    config: dict[str, Any]
    gate: UnlockGate
    jus: GolmarJusClient
    alarm: GolmarAlarmClient
    events: GolmarEventsCoordinator


def entry_config(entry: ConfigEntry) -> dict[str, Any]:
    """Return the effective configuration (entry data overridden by options)."""
    merged = dict(entry.data)
    merged.update(entry.options)
    return merged
