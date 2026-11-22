"""Polling of the EcoTracker and the watchdog over its upstream switch."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_NOTIFY_ENTITIES,
    CONF_NOTIFY_SERVICES,
    CONF_OFFLINE_MINUTES,
    CONF_SCAN_INTERVAL,
    CONF_SWITCH,
    DEFAULT_OFFLINE_MINUTES,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LATE_HOURS,
    OFF_SECONDS,
    RETRY_MINUTES,
    RETRY_MINUTES_LATE,
)

_LOGGER = logging.getLogger(__name__)

type EcoTrackerConfigEntry = ConfigEntry[EcoTrackerCoordinator]


async def fetch(hass: HomeAssistant, host: str) -> dict[str, Any]:
    """Read /v1/json of the device."""
    session = async_get_clientsession(hass)
    async with asyncio.timeout(10):
        resp = await session.get(f"http://{host}/v1/json")
        resp.raise_for_status()
        data = await resp.json(content_type=None)
    if not isinstance(data, dict) or "power" not in data:
        raise ValueError("unexpected answer")
    return data


class EcoTrackerCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Reads the EcoTracker; restarts it over its socket while it is offline."""

    config_entry: EcoTrackerConfigEntry

    def __init__(self, hass: HomeAssistant, entry: EcoTrackerConfigEntry) -> None:
        """Initialize."""
        opts = {**entry.data, **entry.options}
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
        )
        self.host: str = entry.data[CONF_HOST]
        self.switch: str | None = opts.get(CONF_SWITCH) or None
        self.offline_minutes: float = opts.get(CONF_OFFLINE_MINUTES, DEFAULT_OFFLINE_MINUTES)
        self.notify_entities: list[str] = list(opts.get(CONF_NOTIFY_ENTITIES) or [])
        self.notify_services: list[str] = [s.strip() for s in (opts.get(CONF_NOTIFY_SERVICES) or []) if s.strip()]
        # watchdog state
        self.offline_since: datetime | None = None
        self.restarts = 0  # power cycles during the current outage
        self.next_restart: datetime | None = None
        self.last_restart: datetime | None = None
        self.restarting = False
        self.reported = False  # notification "first restart did not help" sent

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data = await fetch(self.hass, self.host)
        except (TimeoutError, aiohttp.ClientError, ValueError) as err:
            if self.offline_since is None:
                self.offline_since = dt_util.utcnow()
            raise UpdateFailed(f"EcoTracker not reachable: {err}") from err
        if self.offline_since is not None:
            await self._back_online()
        return data

    # --- watchdog ---------------------------------------------------------------------

    @callback
    def start_watchdog(self) -> None:
        """Check every 30 s whether a restart is due."""
        self.config_entry.async_on_unload(
            async_track_time_interval(self.hass, self._watchdog, timedelta(seconds=30))
        )

    async def _watchdog(self, now: datetime | None = None) -> None:
        if not self.switch or self.offline_since is None or self.restarting:
            return
        now = dt_util.utcnow()
        if now - self.offline_since < timedelta(minutes=self.offline_minutes):
            return
        if self.next_restart is not None and now < self.next_restart:
            return
        await self.restart()
        late = dt_util.utcnow() - self.offline_since >= timedelta(hours=LATE_HOURS)
        self.next_restart = dt_util.utcnow() + timedelta(minutes=RETRY_MINUTES_LATE if late else RETRY_MINUTES)
        if self.restarts == 2 and not self.reported:
            self.reported = True
            await self._notify(f"{self._name()} offline", self._text_offline())

    async def restart(self) -> None:
        """Power cycle over the upstream switch."""
        if not self.switch or self.restarting:
            return
        self.restarting = True
        try:
            _LOGGER.info("Restarting the EcoTracker over %s", self.switch)
            await self.hass.services.async_call("switch", "turn_off", {"entity_id": self.switch}, blocking=True)
            await asyncio.sleep(OFF_SECONDS)
            await self.hass.services.async_call("switch", "turn_on", {"entity_id": self.switch}, blocking=True)
        except Exception as err:  # noqa: BLE001 - the switch may be away; try again later
            _LOGGER.warning("Restart over %s failed: %s", self.switch, err)
        finally:
            self.restarting = False
        self.restarts += 1
        self.last_restart = dt_util.utcnow()
        self.async_update_listeners()

    async def _back_online(self) -> None:
        if self.restarts >= 2:
            await self._notify(f"{self._name()} wieder online", self._text_online())
        _LOGGER.info("EcoTracker back online after %s restarts", self.restarts)
        self.offline_since = None
        self.restarts = 0
        self.next_restart = None
        self.reported = False

    def _name(self) -> str:
        return self.config_entry.title or "EcoTracker"

    @staticmethod
    def _zeit(t: datetime) -> str:
        t = dt_util.as_local(t)
        return t.strftime("%H:%M") if t.date() == dt_util.now().date() else t.strftime("%d.%m. %H:%M")

    def _text_offline(self) -> str:
        assert self.offline_since is not None
        switch = self.hass.states.get(self.switch) if self.switch else None
        weg = " (Steckdose NICHT erreichbar, Zigbee?)" if switch is None or switch.state == STATE_UNAVAILABLE else ""
        return (
            f"Seit {self._zeit(self.offline_since)} offline, der erste Neustart \u00fcber die Steckdose hat nicht "
            f"geholfen{weg}. Ich versuche es alle {RETRY_MINUTES} Minuten weiter, nach {LATE_HOURS} Stunden "
            "st\u00fcndlich, und melde mich, sobald er wieder da ist."
        )

    def _text_online(self) -> str:
        assert self.offline_since is not None
        return (
            f"Offline seit: {self._zeit(self.offline_since)}  Neustarts: {self.restarts}  "
            f"Wieder online seit: {self._zeit(dt_util.utcnow())}"
        )

    async def _notify(self, title: str, message: str) -> None:
        for entity_id in self.notify_entities:
            try:
                await self.hass.services.async_call(
                    "notify", "send_message", {"entity_id": entity_id, "title": title, "message": message}, blocking=True
                )
            except Exception as err:  # noqa: BLE001 - one target must not stop the others
                _LOGGER.warning("Notification to %s failed: %s", entity_id, err)
        for service in self.notify_services:
            name = service.removeprefix("notify.")
            try:
                await self.hass.services.async_call(
                    "notify", name, {"title": title, "message": message, "data": {"tag": f"watchdog-{DOMAIN}"}},
                    blocking=True,
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Notification over notify.%s failed: %s", name, err)
