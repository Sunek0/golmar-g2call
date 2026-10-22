"""Doorbell/call event entity for Golmar G2Call+."""

from __future__ import annotations

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import EVENT_TYPE_MAP
from .coordinator import GolmarDataCoordinator
from .entity import GolmarEntity
from .events_coordinator import GolmarEventsCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the doorbell event entity."""
    runtime = entry.runtime_data
    async_add_entities([GolmarDoorbellEvent(runtime.coordinator, runtime.events)])


class GolmarDoorbellEvent(GolmarEntity, EventEntity):
    """Doorbell/call events from the alarm server."""

    _attr_translation_key = "doorbell"
    _attr_device_class = EventDeviceClass.DOORBELL
    _attr_event_types = ["ring", "call", "missed", "unlock"]

    def __init__(
        self, coordinator: GolmarDataCoordinator, events: GolmarEventsCoordinator
    ) -> None:
        super().__init__(coordinator)
        self._events = events
        self._attr_unique_id = f"{coordinator.device_uid}_doorbell"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self._events.async_add_listener(self._handle_events_update)
        )

    @callback
    def _handle_events_update(self) -> None:
        data = self._events.data
        if data:
            for event in data.new_events:
                mapped = EVENT_TYPE_MAP.get(event.event_type)
                if mapped in self._attr_event_types:
                    self._trigger_event(
                        mapped,
                        {
                            "alarm_id": event.alarmid,
                            "channel": event.channel,
                            "device_id": event.device_id,
                            "time": event.time,
                        },
                    )
        self.async_write_ha_state()
