"""Events coordinator: polls the alarm server for doorbell/call events.

Runs on its own cycle (options: 15-120 s, default 30 s) and never affects the
identity coordinator or the local CGI. The first refresh only seeds the
seen-set (no historical triggers).
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .alarm_api import AlarmAuthError, AlarmError, AlarmEvent, AlarmUnavailable, GolmarAlarmClient
from .const import DEFAULT_EVENT_POLL_INTERVAL, DOMAIN
from .origins import set_reauth_origin

_LOGGER = logging.getLogger(__name__)

# Ventana de alarmid vistos (dedupe). 200 cubre de sobra el histórico reciente.
EVENT_SEEN_WINDOW = 200


@dataclass
class EventsData:
    """Result of one events poll."""

    new_events: list[AlarmEvent] = field(default_factory=list)
    last_event: AlarmEvent | None = None


class GolmarEventsCoordinator(DataUpdateCoordinator[EventsData]):
    """Poll the alarm server for doorbell/call events."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        config_entry: ConfigEntry,
        alarm: GolmarAlarmClient,
        poll_interval: int = DEFAULT_EVENT_POLL_INTERVAL,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_events",
            config_entry=config_entry,
            update_interval=timedelta(seconds=poll_interval),
            always_update=False,
        )
        self._alarm = alarm
        self._seen: deque[str] = deque()
        self._seen_set: set[str] = set()
        self._first_refresh = True

    @property
    def seen_count(self) -> int:
        """Number of alarm ids in the dedupe window (diagnostics)."""
        return len(self._seen_set)

    async def _async_update_data(self) -> EventsData:
        try:
            events = await self._alarm.async_query_events()
        except AlarmAuthError as err:
            set_reauth_origin(self.hass, self.config_entry.entry_id, "cloud")
            raise ConfigEntryAuthFailed("Alarm session rejected") from err
        except (AlarmUnavailable, AlarmError) as err:
            raise UpdateFailed(f"Alarm server unavailable: {err}") from err

        new_events: list[AlarmEvent] = []
        for event in events:
            if not event.alarmid or event.alarmid in self._seen_set:
                continue
            new_events.append(event)
            self._remember(event.alarmid)

        last_event = events[0] if events else (self.data.last_event if self.data else None)

        if self._first_refresh:
            # Seed: no disparar por el histórico al configurar.
            self._first_refresh = False
            new_events = []

        return EventsData(new_events=new_events, last_event=last_event)

    def _remember(self, alarmid: str) -> None:
        if len(self._seen) >= EVENT_SEEN_WINDOW:
            oldest = self._seen.popleft()
            self._seen_set.discard(oldest)
        self._seen.append(alarmid)
        self._seen_set.add(alarmid)
