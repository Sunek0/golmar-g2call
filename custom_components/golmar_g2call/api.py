"""Local CGI client for the Golmar ART4HW/G2+ monitor.

Validated against the real device (docs/03_protocolo_local.md §6):

- ``POST {scheme}://{host}:{port}/tdkcgi`` with an XML envelope;
- authentication travels in the envelope header (``security=username``,
  ``username=admin``, ``password=<device password>``); the CGI does not answer
  ``WWW-Authenticate``;
- the CGI is transient and single-threaded: requests are serialized, there is
  no port pre-check, and ``connection refused`` means "monitor asleep".

Home Assistant agnostic: it receives an ``aiohttp.ClientSession``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import aiohttp

from .const import (
    CGI_ERRORS,
    CGI_IDENTIFY_RETRY_DELAY,
    CGI_PATH,
    CGI_TIMEOUT,
    CGI_USERNAME,
    CMD_ATTACH_INFO,
    CMD_OPENDOOR,
    CMD_PRODUCT_INFO,
    CMD_SYSTEM_INFO,
    DEFAULT_CGI_PORT,
    DEFAULT_CGI_SCHEME,
    DEFAULT_MODEL,
)

_LOGGER = logging.getLogger(__name__)


class GolmarError(Exception):
    """Base error for local CGI operations."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class GolmarAuthError(GolmarError):
    """The monitor rejected the device credentials (reauth needed)."""


class GolmarUnavailable(GolmarError):
    """The monitor did not accept a connection (CGI asleep)."""


@dataclass(frozen=True)
class DeviceInfo:
    """Identity reported by the monitor."""

    model: str
    firmware: str
    raw: str = ""


@dataclass(frozen=True)
class DoorLock:
    """One door/lock pair exposed by the device attachment info."""

    door: int
    lock: int
    name: str | None = None


def sha256_hex(value: str) -> str:
    """Return the lowercase SHA-256 hex used by the protocol."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _first_text(element: ET.Element, names: set[str]) -> str | None:
    for child in element.iter():
        tag = child.tag.lower()
        if tag in names and child.text and child.text.strip():
            return child.text.strip()
    return None


class GolmarLocalClient:
    """Async client for the monitor's local CGI."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        host: str,
        device_password: str,
        port: int = DEFAULT_CGI_PORT,
        scheme: str = DEFAULT_CGI_SCHEME,
        verify_tls: bool = False,
        timeout: float = CGI_TIMEOUT,
    ) -> None:
        self._session = session
        self._host = host
        self._port = port
        self._scheme = scheme
        self._password = device_password
        self._verify_tls = verify_tls
        self._timeout = timeout
        self._lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        """Return the CGI endpoint URL."""
        return f"{self._scheme}://{self._host}:{self._port}{CGI_PATH}"

    def _envelope(self, command: str, content: str | None = None) -> str:
        content_xml = content or "<content/>"
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<envelope><header>"
            "<security>username</security>"
            f"<username>{CGI_USERNAME}</username>"
            f"<password>{self._password}</password>"
            "</header><body>"
            f"<command>{command}</command>"
            f"{content_xml}"
            "</body></envelope>"
        )

    async def identify(self) -> DeviceInfo:
        """Return the monitor identity (model + firmware) with one retry."""
        async with self._lock:
            try:
                product = await self._post_locked(CMD_PRODUCT_INFO)
            except GolmarUnavailable:
                _LOGGER.debug("identify: product info unavailable, retrying once")
                await asyncio.sleep(CGI_IDENTIFY_RETRY_DELAY)
                product = await self._post_locked(CMD_PRODUCT_INFO)
            system = await self._post_locked(CMD_SYSTEM_INFO)

        model = _first_text(product, {"model", "product", "devicemodel"}) or DEFAULT_MODEL
        firmware = _first_text(
            product, {"version", "softwareversion", "firmware", "fwversion"}
        ) or ""
        _LOGGER.debug("identify: system info=%s", system.tag if system is not None else None)
        return DeviceInfo(model=model, firmware=firmware)

    async def get_attachment_info(self) -> list[DoorLock]:
        """Return the door/lock pairs reported by ``get.device.attachInfo``."""
        async with self._lock:
            content = await self._post_locked(CMD_ATTACH_INFO)

        doors: list[DoorLock] = []
        for element in content.iter():
            if element.tag.lower() != "channel":
                continue
            door = _first_text(element, {"door", "doorno", "channel"})
            lock = _first_text(element, {"lock", "locknumber", "lockno"})
            name = _first_text(element, {"name", "chname", "channelname"})
            if door is None or lock is None:
                continue
            try:
                doors.append(DoorLock(door=int(door), lock=int(lock), name=name))
            except ValueError:
                continue
        return doors

    async def unlock(self, *, door: int, lock: int, code: str) -> None:
        """Open one lock via ``set.device.opendoor`` (single attempt, no retry)."""
        content = (
            f"<door>{door}</door>"
            f"<locknumber>{lock}</locknumber>"
            f"<password>{sha256_hex(code)}</password>"
            "<user></user>"
        )
        async with self._lock:
            await self._post_locked(CMD_OPENDOOR, content)

    async def _post_locked(self, command: str, content: str | None = None) -> ET.Element:
        """Send one envelope. Must be called while holding ``self._lock``."""
        body = self._envelope(command, content)
        try:
            async with self._session.post(
                self.base_url,
                data=body.encode("utf-8"),
                headers={
                    "Content-Type": "application/xml; charset=utf-8",
                    "Connection": "close",
                },
                ssl=None if self._verify_tls else False,
                timeout=aiohttp.ClientTimeout(total=self._timeout),
            ) as resp:
                status = resp.status
                raw = await resp.read()
        except (TimeoutError, aiohttp.ClientError) as err:
            raise GolmarUnavailable(f"CGI request failed: {err}") from err

        return self._parse_response(status, raw)

    @staticmethod
    def _parse_response(status: int, raw: bytes) -> ET.Element:
        if status == 401:
            raise GolmarAuthError("Monitor rejected the device credentials", code=401)

        text = raw.decode("utf-8", "replace").strip()
        if text.startswith("{"):
            try:
                data: dict[str, Any] = json.loads(text)
            except json.JSONDecodeError as err:
                raise GolmarError("Malformed JSON response") from err
            body = data.get("body", {}) if isinstance(data, dict) else {}
            error = body.get("error")
            content = body.get("content")
            if error in (0, "0", None):
                element = ET.Element("content")
                if isinstance(content, dict):
                    for key, value in content.items():
                        ET.SubElement(element, str(key)).text = str(value)
                return element
            code = int(error) if str(error).lstrip("-").isdigit() else None
            if code == 401:
                raise GolmarAuthError("Monitor rejected the device credentials", code=401)
            raise GolmarError(CGI_ERRORS.get(code, "unknown_error"), code=code)

        try:
            root = ET.fromstring(text)
        except ET.ParseError as err:
            raise GolmarError("Malformed CGI response") from err

        body = root.find("body")
        if body is None:
            body = root.find(".//body")
        error_el = body.find("error") if body is not None else root.find(".//error")
        error_text = (error_el.text or "").strip() if error_el is not None else ""
        content = body.find("content") if body is not None else None
        if content is None:
            content = root.find(".//content")

        if error_text in ("0", ""):
            return content if content is not None else ET.Element("content")

        try:
            code = int(error_text)
        except ValueError as err:
            raise GolmarError("Unexpected CGI error payload") from err
        if code == 401:
            raise GolmarAuthError("Monitor rejected the device credentials", code=401)
        raise GolmarError(CGI_ERRORS.get(code, "unknown_error"), code=code)
