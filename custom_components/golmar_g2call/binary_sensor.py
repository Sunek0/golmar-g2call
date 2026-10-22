"""Binary sensor for the Golmar G2Call+ connectivity state."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import GolmarDataCoordinator
from .entity import GolmarEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the connectivity sensor."""
    async_add_entities([GolmarOnlineSensor(entry.runtime_data.coordinator)])


class GolmarOnlineSensor(GolmarEntity, BinarySensorEntity):
    """Monitor reachable over the local CGI (last identify succeeded)."""

    _attr_translation_key = "online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: GolmarDataCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_uid}_online"

    @property
    def is_on(self) -> bool:
        """Return True when the last identify reached the monitor."""
        return self.coordinator.data is not None
