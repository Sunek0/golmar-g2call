"""Door-opening buttons for the Golmar G2Call+ integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import GolmarAuthError, GolmarError, GolmarUnavailable
from .const import (
    CONF_DEVICE_PASSWORD,
    CONF_DEVICE_UID,
    CONF_DOORS,
    CONF_UNLOCK_CODE,
)
from .control import UnlockRateLimited
from .coordinator import GolmarDataCoordinator
from .entity import GolmarEntity
from .oauth import CloudAuthError, CloudError, CloudUnavailable
from .origins import set_reauth_origin
from .runtime import GolmarRuntimeData

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one button per configured door/lock."""
    runtime: GolmarRuntimeData = entry.runtime_data
    doors: dict[str, dict[str, Any]] = runtime.config.get(CONF_DOORS, {})
    async_add_entities(
        GolmarDoorButton(entry, runtime.coordinator, key, door)
        for key, door in doors.items()
    )


class GolmarDoorButton(GolmarEntity, ButtonEntity):
    """Open one door lock (cloud first, local CGI as fallback)."""

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: GolmarDataCoordinator,
        door_key: str,
        door_config: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._door = int(door_config["door"])
        self._lock = int(door_config["lock"])
        if door_key in ("principal", "portal"):
            self._attr_translation_key = f"unlock_{door_key}"
        else:
            self._attr_name = door_config.get("name") or f"Puerta {self._door}/{self._lock}"
        self._attr_unique_id = (
            f"{coordinator.device_uid}_door_{self._door}_lock_{self._lock}"
        )
        # D3: the Portal is created but disabled by default.
        self._attr_entity_registry_enabled_default = bool(door_config.get("enabled", True))

    async def async_press(self) -> None:
        """Open the lock: cloud first, local fallback, never both."""
        runtime: GolmarRuntimeData = self._entry.runtime_data
        try:
            async with runtime.gate:
                await self._async_open(runtime)
        except UnlockRateLimited as err:
            raise HomeAssistantError(
                "Apertura ignorada: espera unos segundos entre aperturas"
            ) from err

    async def _async_open(self, runtime: GolmarRuntimeData) -> None:
        config = runtime.config
        code = config.get(CONF_UNLOCK_CODE, "")
        cloud_error: Exception | None = None

        if runtime.cloud is not None:
            try:
                await runtime.cloud.unlock(
                    device_id=config[CONF_DEVICE_UID],
                    device_password=config[CONF_DEVICE_PASSWORD],
                    door=self._door,
                    lock=self._lock,
                    code=code,
                    user="homeassistant",
                )
                return
            except CloudAuthError as err:
                set_reauth_origin(self.hass, self._entry.entry_id, "cloud")
                self._entry.async_start_reauth(self.hass)
                raise HomeAssistantError(
                    "La sesión cloud fue rechazada; completa la reautenticación"
                ) from err
            except (CloudUnavailable, CloudError) as err:
                _LOGGER.debug("Cloud unlock failed (%s); trying the local path", err)
                cloud_error = err

        try:
            await runtime.local.unlock(door=self._door, lock=self._lock, code=code)
        except GolmarAuthError as err:
            set_reauth_origin(self.hass, self._entry.entry_id, "monitor")
            self._entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                "El monitor rechazó la contraseña del equipo; completa la reautenticación"
            ) from err
        except GolmarUnavailable as err:
            detail = f" (cloud: {cloud_error})" if cloud_error else ""
            raise HomeAssistantError(
                "No se pudo abrir: el monitor está dormido. Abre G2Call+ → Información "
                f"del dispositivo y vuelve a intentarlo{detail}"
            ) from err
        except GolmarError as err:
            raise HomeAssistantError(
                f"El monitor rechazó la apertura ({err})"
            ) from err
