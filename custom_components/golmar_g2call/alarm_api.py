"""Alarm/events server client for Golmar G2Call+ (Qualvision).

Home Assistant agnostic. Requires a :class:`GolmarJusClient` for the session.

Validated against the real service (docs/WORKLOG.md, Fase 8):

- ``POST https://r1-9.qvcloud.net:4443/UserAlarm`` (fallback ``r1-2:4443``)
- ``client-login`` with the exact app payload (notifylang/timezone/tokentype/type)
- ``client-query-recordlist`` with the app's event filter, ``maxid=0``
- error codes: ``1019`` stale JUS session, ``1013``/``1009`` payload problems
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import aiohttp

from .const import (
    ALARM_AUTHSERVER,
    ALARM_EVENT_TYPES,
    ALARM_HOSTS,
    ALARM_LOGIN_NOTIFY_LANG,
    ALARM_LOGIN_TIMEZONE,
    ALARM_PATH,
    ALARM_RESULT_DATA,
    ALARM_RESULT_SESSION,
    ALARM_TIMEOUT,
    CLOUD_APP_ID,
    CLOUD_OEM_ID,
)
from .jus import GolmarJusClient, JusAuthError, JusUnavailable

_LOGGER = logging.getLogger(__name__)


class AlarmError(Exception):
    """Base error for alarm-server operations."""


class AlarmAuthError(AlarmError):
    """Credentials rejected (reauth needed)."""


class AlarmSessionError(AlarmError):
    """The JUS session is stale (1019): renew and retry once."""


class AlarmPayloadError(AlarmError):
    """The server rejected the request payload (1013/1009)."""


class AlarmUnavailable(AlarmError):
    """The alarm server could not be reached."""


@dataclass(frozen=True)
class AlarmEvent:
    """One event as reported by the alarm server."""

    alarmid: str
    event_type: int
    time: str
    channel: str
    device_id: str
    state: int
    snapshot_url: str | None


class GolmarAlarmClient:
    """Client for the Qualvision alarm/events server."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        jus: GolmarJusClient,
        client_id: str,
        account_id: str = "",
        hosts: list[str] | None = None,
        timeout: float = ALARM_TIMEOUT,
        verify_tls: bool = False,
    ) -> None:
        self._session = session
        self._jus = jus
        self._client_id = client_id
        self._account_id = account_id
        self._hosts = list(hosts or ALARM_HOSTS)
        self._timeout = timeout
        self._verify_tls = verify_tls

    async def async_query_events(self, *, limit: int = 15) -> list[AlarmEvent]:
        """Return the latest events (renews the JUS session when needed)."""
        try:
            session = await self._jus.async_ensure_session()
        except JusAuthError as err:
            raise AlarmAuthError("JUS credentials rejected") from err
        except JusUnavailable as err:
            raise AlarmUnavailable("JUS unavailable") from err

        last_error: AlarmError | None = None
        relogged = False
        for host in self._hosts:
            try:
                return await self._query_host(host, session, limit)
            except AlarmSessionError:
                if relogged:
                    last_error = AlarmSessionError("JUS session rejected again")
                    continue
                relogged = True
                try:
                    session = await self._jus.async_ensure_session(force=True)
                except JusAuthError as err:
                    raise AlarmAuthError("JUS credentials rejected") from err
                except JusUnavailable as err:
                    raise AlarmUnavailable("JUS unavailable") from err
                try:
                    return await self._query_host(host, session, limit)
                except AlarmSessionError:
                    last_error = AlarmSessionError("JUS session rejected again")
                    continue
                except AlarmError as err:
                    last_error = err
                    continue
            except AlarmError as err:
                last_error = err
                continue
        raise last_error or AlarmUnavailable("No alarm host reachable")

    # -------------------------------------------------------------- internals
    async def _query_host(self, host: str, session: str, limit: int) -> list[AlarmEvent]:
        cookie = await self._login(host, session)
        raw = await self._post(
            host,
            cookie,
            "client-query-recordlist",
            self._query_content(limit),
            "com.quvii.qvweb.Alarm.bean.request.AlarmListQueryReqContent",
        )
        self._check_result(raw)
        return self._parse_events(raw)

    async def _login(self, host: str, session: str) -> str | None:
        # El account-id llega con la respuesta del login JUS (lazy).
        account_id = self._account_id or (self._jus.account_id or "")
        content = (
            "<client>"
            f"<appid>{CLOUD_APP_ID}</appid><id>{self._client_id}</id>"
            f"<notifylang>{ALARM_LOGIN_NOTIFY_LANG}</notifylang>"
            f"<oemid>{CLOUD_OEM_ID}</oemid>"
            f"<timezone>{ALARM_LOGIN_TIMEZONE}</timezone>"
            "<token></token><tokentype>1</tokentype><type>3</type>"
            "</client>"
            f"<account><authserver>{ALARM_AUTHSERVER}</authserver>"
            f"<id>{account_id}</id></account>"
        )
        _raw, cookie = await self._post(
            host,
            None,
            "client-login",
            content,
            "com.quvii.qvweb.Alarm.bean.request.AlarmLoginReqContent",
            return_cookie=True,
        )
        return cookie

    def _query_content(self, limit: int) -> str:
        types = "".join(f"<type>{t}</type>" for t in ALARM_EVENT_TYPES)
        return (
            f"<filter><devid/><event>{types}</event><peroid/></filter>"
            "<maxid>0</maxid>"
            f"<pagelinenum>{limit}</pagelinenum><pageno>0</pageno>"
        )

    @staticmethod
    def _envelope(session: str, command: str, content: str, content_class: str) -> bytes:
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<envelope><header>"
            f"<command>{command}</command><flag>tdkcloud</flag><seq>0</seq>"
            f"<session>{session}</session>"
            "</header>"
            f'<content class="{content_class}">{content}</content>'
            "</envelope>"
        )
        return xml.encode("utf-8")

    async def _post(
        self,
        host: str,
        cookie: str | None,
        command: str,
        content: str,
        content_class: str,
        *,
        return_cookie: bool = False,
    ) -> Any:
        session = self._jus.session_id or ""
        headers = {
            "Content-Type": "application/xml",
            "charset": "utf-8",
            "User-Agent": "okhttp/4.9.1",
            "Accept-Language": "es-ES",
            "Connection": "close",
        }
        if cookie:
            headers["Cookie"] = cookie
        try:
            async with self._session.post(
                f"https://{host}{ALARM_PATH}",
                data=self._envelope(session, command, content, content_class),
                headers=headers,
                ssl=None if self._verify_tls else False,
                timeout=aiohttp.ClientTimeout(total=self._timeout),
            ) as resp:
                raw = await resp.read()
                jsession = resp.cookies.get("jsessionid")
                new_cookie = f"jsessionid={jsession.value}" if jsession else cookie
        except (TimeoutError, aiohttp.ClientError) as err:
            raise AlarmUnavailable(f"Alarm request failed: {err}") from err
        if return_cookie:
            return raw, new_cookie
        return raw

    @staticmethod
    def _result(raw: bytes) -> str | None:
        try:
            root = ET.fromstring(raw.decode("utf-8", "replace"))
        except ET.ParseError:
            return None
        return root.findtext("header/result")

    def _check_result(self, raw: bytes) -> None:
        result = str(self._result(raw))
        if result == "0":
            return
        if result == ALARM_RESULT_SESSION:
            raise AlarmSessionError("JUS session stale (1019)")
        if result in (ALARM_RESULT_DATA, "1009"):
            raise AlarmPayloadError(f"Alarm payload rejected (result={result})")
        raise AlarmError(f"Alarm server error (result={result})")

    @staticmethod
    def _parse_events(raw: bytes) -> list[AlarmEvent]:
        try:
            root = ET.fromstring(raw.decode("utf-8", "replace"))
        except ET.ParseError as err:
            raise AlarmPayloadError("Malformed alarm response") from err
        events: list[AlarmEvent] = []
        for item in root.findall(".//data"):
            event_text = item.findtext("event") or ""
            if not event_text.isdigit():
                continue
            events.append(
                AlarmEvent(
                    alarmid=item.findtext("alarmid") or "",
                    event_type=int(event_text),
                    time=item.findtext("time") or item.findtext("alarmtime") or "",
                    channel=item.findtext("chname") or "",
                    device_id=item.findtext("devid") or "",
                    state=int(item.findtext("alarmstate") or "0"),
                    snapshot_url=item.findtext("recordsubresurl") or None,
                )
            )
        return events
