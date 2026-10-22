"""Diagnostic sensors (model and firmware) for Golmar G2Call+."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import GolmarDataCoordinator
from .entity import GolmarEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the diagnostic sensors."""
    coordinator: GolmarDataCoordinator = entry.runtime_data.coordinator
    async_add_entities(
        [GolmarModelSensor(coordinator), GolmarFirmwareSensor(coordinator)]
    )


class _GolmarDiagnosticSensor(GolmarEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: GolmarDataCoordinator) -> None:
        super().__init__(coordinator)


class GolmarModelSensor(_GolmarDiagnosticSensor):
    """Monitor model reported by get.product.info."""

    _attr_translation_key = "model"

    def __init__(self, coordinator: GolmarDataCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_uid}_model"

    @property
    def native_value(self) -> str | None:
        return self.coordinator.data.model if self.coordinator.data else None


class GolmarFirmwareSensor(_GolmarDiagnosticSensor):
    """Monitor firmware reported by get.product.info."""

    _attr_translation_key = "firmware"

    def __init__(self, coordinator: GolmarDataCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_uid}_firmware"

    @property
    def native_value(self) -> str | None:
        return self.coordinator.data.firmware if self.coordinator.data else None
