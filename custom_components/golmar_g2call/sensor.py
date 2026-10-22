"""Diagnostic and event sensors for Golmar G2Call+."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import EVENT_TYPE_MAP
from .coordinator import GolmarDataCoordinator
from .entity import GolmarEntity
from .events_coordinator import GolmarEventsCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the diagnostic and event sensors."""
    runtime = entry.runtime_data
    coordinator: GolmarDataCoordinator = runtime.coordinator
    async_add_entities(
        [
            GolmarModelSensor(coordinator),
            GolmarFirmwareSensor(coordinator),
            GolmarLastEventSensor(coordinator, runtime.events),
        ]
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


class GolmarLastEventSensor(GolmarEntity, SensorEntity):
    """Timestamp and details of the last doorbell/call event."""

    _attr_translation_key = "last_event"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self, coordinator: GolmarDataCoordinator, events: GolmarEventsCoordinator
    ) -> None:
        super().__init__(coordinator)
        self._events = events
        self._attr_unique_id = f"{coordinator.device_uid}_last_event"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self._events.async_add_listener(self._handle_events_update)
        )

    @callback
    def _handle_events_update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> datetime | None:
        event = self._events.data.last_event if self._events.data else None
        if event is None or not event.time:
            return None
        parsed = dt_util.parse_datetime(event.time)
        if parsed is None:
            try:
                parsed = datetime.strptime(event.time, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        return parsed

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        event = self._events.data.last_event if self._events.data else None
        if event is None:
            return {}
        return {
            "event_type": EVENT_TYPE_MAP.get(event.event_type, "unknown"),
            "channel": event.channel,
            "device_id": event.device_id,
            "alarm_id": event.alarmid,
            "has_snapshot": bool(event.snapshot_url),
        }
