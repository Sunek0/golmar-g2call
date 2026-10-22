"""Base entity for the Golmar G2Call+ integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_MODEL, DEFAULT_NAME, DOMAIN, MANUFACTURER
from .coordinator import GolmarDataCoordinator


class GolmarEntity(CoordinatorEntity[GolmarDataCoordinator]):
    """Base entity bound to the monitor device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GolmarDataCoordinator) -> None:
        super().__init__(coordinator)

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info shared by all entities."""
        data = self.coordinator.data
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.device_uid)},
            manufacturer=MANUFACTURER,
            model=data.model if data else DEFAULT_MODEL,
            sw_version=data.firmware if data else None,
            name=DEFAULT_NAME,
        )
