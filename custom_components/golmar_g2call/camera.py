"""Camera entity with the last event snapshot for Golmar G2Call+."""

from __future__ import annotations

import logging

import aiohttp
from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import GolmarDataCoordinator
from .entity import GolmarEntity
from .events_coordinator import GolmarEventsCoordinator

_LOGGER = logging.getLogger(__name__)

SNAPSHOT_TIMEOUT = 10
SNAPSHOT_MAX_BYTES = 2 * 1024 * 1024


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the last-snapshot camera."""
    runtime = entry.runtime_data
    async_add_entities(
        [GolmarLastSnapshotCamera(runtime.coordinator, runtime.events, runtime)]
    )


class GolmarLastSnapshotCamera(GolmarEntity, Camera):
    """Last snapshot reported by an event (best effort, memory only)."""

    _attr_translation_key = "last_snapshot"

    def __init__(
        self,
        coordinator: GolmarDataCoordinator,
        events: GolmarEventsCoordinator,
        runtime,
    ) -> None:
        super().__init__(coordinator)
        # CoordinatorEntity no llama a super().__init__(): inicializar Camera a mano.
        Camera.__init__(self)
        self._events = events
        self._runtime = runtime
        self._attr_unique_id = f"{coordinator.device_uid}_snapshot"
        self._image: bytes | None = None
        self._fetched_url: str | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self._events.async_add_listener(self._handle_events_update)
        )

    @callback
    def _handle_events_update(self) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Available once a snapshot has been downloaded."""
        return self._image is not None

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return the cached image, fetching the newest snapshot on demand."""
        event = self._events.data.last_event if self._events.data else None
        url = event.snapshot_url if event else None
        if url and url != self._fetched_url:
            await self._async_fetch(url)
        return self._image

    async def _async_fetch(self, url: str) -> None:
        session = async_get_clientsession(self.hass)
        verify_tls = self._runtime.config.get("verify_tls", False)
        try:
            async with session.get(
                url,
                ssl=None if verify_tls else False,
                timeout=aiohttp.ClientTimeout(total=SNAPSHOT_TIMEOUT),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.debug("Snapshot download failed (HTTP %s)", resp.status)
                    return
                content_type = resp.headers.get("Content-Type", "")
                if content_type and not content_type.startswith("image/"):
                    _LOGGER.debug("Snapshot is not an image (%s)", content_type)
                    return
                data = await resp.read()
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.debug("Snapshot download error: %s", err)
            return
        if len(data) > SNAPSHOT_MAX_BYTES:
            _LOGGER.debug("Snapshot too large (%s bytes)", len(data))
            return
        self._image = data
        self._fetched_url = url
        self.async_write_ha_state()
