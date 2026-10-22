"""Binary sensor for the Golmar G2Call+ connectivity state."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .const import EVENT_TYPE_MAP
from .coordinator import GolmarDataCoordinator
from .entity import GolmarEntity
from .events_coordinator import GolmarEventsCoordinator

RINGING_TIMEOUT = 30  # segundos que el timbre queda activo


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the connectivity and ringing sensors."""
    runtime = entry.runtime_data
    async_add_entities(
        [
            GolmarOnlineSensor(runtime.coordinator),
            GolmarRingingSensor(runtime.coordinator, runtime.events),
        ]
    )


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


class GolmarRingingSensor(GolmarEntity, BinarySensorEntity):
    """Active for 30 s after a ring/call event."""

    _attr_translation_key = "ringing"
    _attr_icon = "mdi:bell-ring"

    def __init__(
        self, coordinator: GolmarDataCoordinator, events: GolmarEventsCoordinator
    ) -> None:
        super().__init__(coordinator)
        self._events = events
        self._attr_unique_id = f"{coordinator.device_uid}_ringing"
        self._attr_is_on = False
        self._timer: CALLBACK_TYPE | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self._events.async_add_listener(self._handle_events_update)
        )
        self.async_on_remove(self._async_cancel_timer)

    @callback
    def _handle_events_update(self) -> None:
        data = self._events.data
        if data and any(
            EVENT_TYPE_MAP.get(event.event_type) in ("ring", "call")
            for event in data.new_events
        ):
            self._async_turn_on()

    @callback
    def _async_turn_on(self) -> None:
        self._async_cancel_timer()
        self._attr_is_on = True
        self._timer = async_call_later(self.hass, RINGING_TIMEOUT, self._async_turn_off)
        self.async_write_ha_state()

    @callback
    def _async_turn_off(self, _now=None) -> None:
        self._timer = None
        self._attr_is_on = False
        self.async_write_ha_state()

    @callback
    def _async_cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer()
            self._timer = None
