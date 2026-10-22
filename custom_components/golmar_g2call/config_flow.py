"""Config, reauth, reconfigure and options flows for Golmar G2Call+."""

from __future__ import annotations

import logging
import secrets
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GolmarAuthError, GolmarError, GolmarLocalClient, GolmarUnavailable
from .const import (
    CONF_ACCOUNT,
    CONF_ACCOUNT_PASSWORD,
    CONF_CLIENT_ID,
    CONF_DEVICE_PASSWORD,
    CONF_DEVICE_UID,
    CONF_DOORS,
    CONF_ENABLE_PORTAL,
    CONF_EVENT_POLL_INTERVAL,
    CONF_HOST,
    CONF_PORT,
    CONF_REGION_ID,
    CONF_SCHEME,
    CONF_UNLOCK_CODE,
    CONF_VERIFY_TLS,
    DEFAULT_CGI_PORT,
    DEFAULT_CGI_SCHEME,
    DEFAULT_DOORS,
    DEFAULT_EVENT_POLL_INTERVAL,
    DEFAULT_REGION_ID,
    DOMAIN,
    MAX_EVENT_POLL_INTERVAL,
    MIN_EVENT_POLL_INTERVAL,
)
from .oauth import CloudAuthError, CloudUnavailable, GolmarOAuth, hash_password
from .origins import pop_reauth_origin
from .runtime import entry_config

_LOGGER = logging.getLogger(__name__)

PASSWORD = selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)


def _known_door_key(door: int, lock: int) -> str:
    """Map a door/lock pair to a stable key (known pairs get translated names)."""
    if (door, lock) == (9, 1):
        return "principal"
    if (door, lock) == (1, 1):
        return "portal"
    return f"door_{door}_{lock}"


def _client_id() -> str:
    return "003-4053-" + secrets.token_hex(8)


def _user_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_ACCOUNT, default=defaults.get(CONF_ACCOUNT, "")): str,
            # The account password is stored only as SHA-256: never prefill it
            # (submitting the hash would hash it twice). Empty = keep current.
            vol.Optional(CONF_ACCOUNT_PASSWORD, default=""): selector.TextSelector(PASSWORD),
            vol.Required(CONF_DEVICE_UID, default=defaults.get(CONF_DEVICE_UID, "")): str,
            vol.Optional(
                CONF_DEVICE_PASSWORD, default=defaults.get(CONF_DEVICE_PASSWORD, "")
            ): selector.TextSelector(PASSWORD),
            vol.Optional(
                CONF_UNLOCK_CODE, default=defaults.get(CONF_UNLOCK_CODE, "")
            ): selector.TextSelector(PASSWORD),
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_CGI_PORT)): int,
            vol.Required(
                CONF_SCHEME, default=defaults.get(CONF_SCHEME, DEFAULT_CGI_SCHEME)
            ): vol.In(["https", "http"]),
            vol.Required(
                CONF_VERIFY_TLS, default=defaults.get(CONF_VERIFY_TLS, False)
            ): bool,
        }
    )


class GolmarG2CallConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Golmar G2Call+ config and reauth flows."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._local_unreachable = False
        self._door_options: dict[str, dict[str, Any]] = {
            key: dict(cfg) for key, cfg in DEFAULT_DOORS.items()
        }

    # ------------------------------------------------------------------ user
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect account + device credentials and validate them."""
        errors: dict[str, str] = {}
        if user_input is not None:
            device_uid = user_input[CONF_DEVICE_UID].strip()
            await self.async_set_unique_id(device_uid)
            self._abort_if_unique_id_configured()

            account = user_input[CONF_ACCOUNT].strip()
            password = user_input.get(CONF_ACCOUNT_PASSWORD) or ""
            if not password:
                errors["base"] = "invalid_auth"
            else:
                oauth = GolmarOAuth(
                    async_get_clientsession(self.hass),
                    client_id=_client_id(),
                    verify_tls=user_input[CONF_VERIFY_TLS],
                )
                try:
                    await oauth.login(account, password)
                except CloudAuthError:
                    errors["base"] = "invalid_auth"
                except CloudUnavailable:
                    errors["base"] = "cannot_connect"
                else:
                    self._data = {
                        **user_input,
                        CONF_ACCOUNT: account,
                        CONF_ACCOUNT_PASSWORD: hash_password(password),
                        CONF_DEVICE_UID: device_uid,
                        CONF_CLIENT_ID: _client_id(),
                        CONF_REGION_ID: DEFAULT_REGION_ID,
                    }
                    self._data.pop(CONF_ENABLE_PORTAL, None)

            if not errors:
                errors = await self._validate_device(self._data)

            if not errors:
                return await self.async_step_doors()

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(user_input or {}),
            errors=errors,
        )

    async def _validate_device(self, data: dict[str, Any]) -> dict[str, str]:
        """Validate the device password when the monitor CGI is awake (optional)."""
        if not data.get(CONF_HOST) or not data.get(CONF_DEVICE_PASSWORD):
            self._local_unreachable = True
            return {}
        local = GolmarLocalClient(
            async_get_clientsession(self.hass),
            host=data[CONF_HOST],
            device_password=data[CONF_DEVICE_PASSWORD],
            port=data[CONF_PORT],
            scheme=data[CONF_SCHEME],
            verify_tls=data[CONF_VERIFY_TLS],
        )
        try:
            await local.identify()
        except GolmarUnavailable:
            # Transient CGI: do not block the setup, the local path is a fallback.
            self._local_unreachable = True
        except GolmarAuthError:
            return {"base": "invalid_device_auth"}
        return {}

    async def async_step_doors(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick which door/lock pairs to expose (principal on, Portal off — D3)."""
        if user_input is not None:
            doors = {
                key: {
                    **cfg,
                    "enabled": bool(user_input.get(f"enable_{key}", cfg["enabled"])),
                }
                for key, cfg in self._door_options.items()
            }
            data = {**self._data, CONF_DOORS: doors}
            return self.async_create_entry(
                title=f"Golmar G2Call+ ({data[CONF_DEVICE_UID]})",
                data=data,
            )

        self._door_options = await self._async_discover_doors()
        schema = {
            vol.Required(f"enable_{key}", default=cfg["enabled"]): bool
            for key, cfg in self._door_options.items()
        }
        return self.async_show_form(step_id="doors", data_schema=vol.Schema(schema))

    async def _async_discover_doors(self) -> dict[str, dict[str, Any]]:
        """Read the door/lock pairs from get.device.attachInfo (defaults if asleep)."""
        options: dict[str, dict[str, Any]] = {
            key: dict(cfg) for key, cfg in DEFAULT_DOORS.items()
        }
        data = self._data
        if not data.get(CONF_HOST) or not data.get(CONF_DEVICE_PASSWORD):
            return options
        local = GolmarLocalClient(
            async_get_clientsession(self.hass),
            host=data[CONF_HOST],
            device_password=data[CONF_DEVICE_PASSWORD],
            port=data[CONF_PORT],
            scheme=data[CONF_SCHEME],
            verify_tls=data[CONF_VERIFY_TLS],
        )
        try:
            discovered = await local.get_attachment_info()
        except (GolmarUnavailable, GolmarAuthError, GolmarError):
            return options
        for door in discovered:
            key = _known_door_key(door.door, door.lock)
            if key in options:
                continue
            options[key] = {
                "door": door.door,
                "lock": door.lock,
                "enabled": False,
                "name": door.name or f"Puerta {door.door}/{door.lock}",
            }
        return options

    # ------------------------------------------------------------ reconfigure
    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Update connection data and credentials without recreating the entry."""
        entry = self._get_reconfigure_entry()
        current = entry_config(entry)
        errors: dict[str, str] = {}

        if user_input is not None:
            data = dict(entry.data)
            password = user_input.get(CONF_ACCOUNT_PASSWORD) or ""
            if password:
                oauth = GolmarOAuth(
                    async_get_clientsession(self.hass),
                    client_id=current.get(CONF_CLIENT_ID) or _client_id(),
                    verify_tls=user_input[CONF_VERIFY_TLS],
                )
                try:
                    await oauth.login(user_input[CONF_ACCOUNT], password)
                except CloudAuthError:
                    errors["base"] = "invalid_auth"
                except CloudUnavailable:
                    errors["base"] = "cannot_connect"
                else:
                    data[CONF_ACCOUNT] = user_input[CONF_ACCOUNT].strip()
                    data[CONF_ACCOUNT_PASSWORD] = hash_password(password)

            if not errors:
                device_password = user_input.get(CONF_DEVICE_PASSWORD) or ""
                if device_password:
                    local = GolmarLocalClient(
                        async_get_clientsession(self.hass),
                        host=user_input[CONF_HOST],
                        device_password=device_password,
                        port=user_input[CONF_PORT],
                        scheme=user_input[CONF_SCHEME],
                        verify_tls=user_input[CONF_VERIFY_TLS],
                    )
                    try:
                        await local.identify()
                    except GolmarUnavailable:
                        pass  # asleep: accept, the fallback path will report it
                    except GolmarAuthError:
                        errors["base"] = "invalid_device_auth"
                    else:
                        data[CONF_DEVICE_PASSWORD] = device_password

            if not errors:
                doors = {
                    key: dict(cfg)
                    for key, cfg in current.get(CONF_DOORS, DEFAULT_DOORS).items()
                }
                for key in ("principal", "portal"):
                    if key in doors:
                        doors[key]["enabled"] = bool(
                            user_input.get(f"enable_{key}", doors[key].get("enabled", False))
                        )
                data.update(
                    {
                        CONF_ACCOUNT: user_input[CONF_ACCOUNT].strip(),
                        CONF_DEVICE_UID: user_input[CONF_DEVICE_UID].strip(),
                        CONF_HOST: user_input[CONF_HOST].strip(),
                        CONF_PORT: user_input[CONF_PORT],
                        CONF_SCHEME: user_input[CONF_SCHEME],
                        CONF_VERIFY_TLS: user_input[CONF_VERIFY_TLS],
                        CONF_DOORS: doors,
                    }
                )
                if user_input.get(CONF_UNLOCK_CODE):
                    data[CONF_UNLOCK_CODE] = user_input[CONF_UNLOCK_CODE]
                return self.async_update_reload_and_abort(
                    entry, data=data, reason="reconfigure_successful"
                )

        doors = current.get(CONF_DOORS, DEFAULT_DOORS)
        schema = _user_schema({**current, **entry.options}).extend(
            {
                vol.Required(
                    "enable_principal",
                    default=doors.get("principal", {}).get("enabled", True),
                ): bool,
                vol.Required(
                    "enable_portal",
                    default=doors.get("portal", {}).get("enabled", False),
                ): bool,
            }
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
            errors=errors,
        )

    # ----------------------------------------------------------------- reauth
    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Start reauth for either the monitor password or the cloud chain."""
        entry = self._get_reauth_entry()
        self._reauth_origin = pop_reauth_origin(self.hass, entry.entry_id)
        if self._reauth_origin == "cloud":
            return await self.async_step_reauth_confirm_cloud()
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the monitor device password."""
        entry = self._get_reauth_entry()
        current = entry_config(entry)
        errors: dict[str, str] = {}

        if user_input is not None:
            value = user_input.get(CONF_DEVICE_PASSWORD) or ""
            local = GolmarLocalClient(
                async_get_clientsession(self.hass),
                host=current[CONF_HOST],
                device_password=value,
                port=current[CONF_PORT],
                scheme=current[CONF_SCHEME],
                verify_tls=current[CONF_VERIFY_TLS],
            )
            try:
                await local.identify()
            except GolmarAuthError:
                errors["base"] = "invalid_device_auth"
            except GolmarUnavailable:
                errors["base"] = "cannot_connect"
            else:
                data = dict(entry.data)
                data[CONF_DEVICE_PASSWORD] = value
                self.hass.config_entries.async_update_entry(entry, data=data)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {vol.Required(CONF_DEVICE_PASSWORD, default=""): selector.TextSelector(PASSWORD)}
            ),
            errors=errors,
        )

    async def async_step_reauth_confirm_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the cloud account password."""
        entry = self._get_reauth_entry()
        current = entry_config(entry)
        errors: dict[str, str] = {}

        if user_input is not None:
            value = user_input.get(CONF_ACCOUNT_PASSWORD) or ""
            oauth = GolmarOAuth(
                async_get_clientsession(self.hass),
                client_id=current[CONF_CLIENT_ID],
                verify_tls=current[CONF_VERIFY_TLS],
            )
            try:
                await oauth.login(current[CONF_ACCOUNT], value)
            except CloudAuthError:
                errors["base"] = "invalid_auth"
            except CloudUnavailable:
                errors["base"] = "cannot_connect"
            else:
                data = dict(entry.data)
                data[CONF_ACCOUNT_PASSWORD] = hash_password(value)
                self.hass.config_entries.async_update_entry(entry, data=data)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm_cloud",
            data_schema=vol.Schema(
                {vol.Required(CONF_ACCOUNT_PASSWORD, default=""): selector.TextSelector(PASSWORD)}
            ),
            errors=errors,
        )

    # ---------------------------------------------------------------- options
    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return GolmarOptionsFlow()


class GolmarOptionsFlow(OptionsFlow):
    """Options for the Golmar G2Call+ entry."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        current = entry_config(self.config_entry)
        doors = {
            key: dict(cfg) for key, cfg in current.get(CONF_DOORS, DEFAULT_DOORS).items()
        }

        if user_input is not None:
            options = dict(self.config_entry.options)
            for key in ("principal", "portal"):
                if key in doors:
                    doors[key]["enabled"] = bool(
                        user_input.get(f"enable_{key}", doors[key].get("enabled", False))
                    )
            options[CONF_DOORS] = doors
            if user_input.get(CONF_UNLOCK_CODE):
                options[CONF_UNLOCK_CODE] = user_input[CONF_UNLOCK_CODE]
            options[CONF_VERIFY_TLS] = bool(user_input.get(CONF_VERIFY_TLS, False))
            if user_input.get(CONF_DEVICE_PASSWORD):
                options[CONF_DEVICE_PASSWORD] = user_input[CONF_DEVICE_PASSWORD]
            options[CONF_EVENT_POLL_INTERVAL] = int(
                user_input.get(CONF_EVENT_POLL_INTERVAL, DEFAULT_EVENT_POLL_INTERVAL)
            )
            return self.async_create_entry(data=options)

        code_status = (
            "configurado" if current.get(CONF_UNLOCK_CODE) else "no configurado"
        )
        device_status = (
            "configurada" if current.get(CONF_DEVICE_PASSWORD) else "no configurada"
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "enable_principal",
                        default=doors.get("principal", DEFAULT_DOORS["principal"]).get(
                            "enabled", True
                        ),
                    ): bool,
                    vol.Required(
                        "enable_portal",
                        default=doors.get("portal", DEFAULT_DOORS["portal"]).get(
                            "enabled", False
                        ),
                    ): bool,
                    vol.Required(
                        CONF_EVENT_POLL_INTERVAL,
                        default=current.get(
                            CONF_EVENT_POLL_INTERVAL, DEFAULT_EVENT_POLL_INTERVAL
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=MIN_EVENT_POLL_INTERVAL,
                            max=MAX_EVENT_POLL_INTERVAL,
                            step=5,
                            mode=selector.NumberSelectorMode.BOX,
                            unit_of_measurement="s",
                        )
                    ),
                    vol.Optional(
                        CONF_UNLOCK_CODE, default=current.get(CONF_UNLOCK_CODE, "")
                    ): selector.TextSelector(PASSWORD),
                    vol.Required(
                        CONF_VERIFY_TLS, default=current.get(CONF_VERIFY_TLS, False)
                    ): bool,
                    vol.Optional(
                        CONF_DEVICE_PASSWORD, default=current.get(CONF_DEVICE_PASSWORD, "")
                    ): selector.TextSelector(PASSWORD),
                }
            ),
            description_placeholders={
                "device_uid": current.get(CONF_DEVICE_UID, "?"),
                "host": current.get(CONF_HOST, "?"),
                "code_status": code_status,
                "device_status": device_status,
            },
        )
