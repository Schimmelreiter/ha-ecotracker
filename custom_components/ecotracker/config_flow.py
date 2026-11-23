"""Config flow: host; options: polling and the watchdog."""

from __future__ import annotations

import socket
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .const import (
    CONF_NOTIFY_ENTITIES,
    CONF_NOTIFY_SERVICES,
    CONF_OFFLINE_MINUTES,
    CONF_SCAN_INTERVAL,
    CONF_SWITCH,
    DEFAULT_HOST,
    DEFAULT_OFFLINE_MINUTES,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .coordinator import fetch
from .mdns import async_mdns_info


def _options_schema(opts: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_SCAN_INTERVAL, default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)): selector.NumberSelector(
                selector.NumberSelectorConfig(min=5, max=300, step=1, unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_SWITCH, description={"suggested_value": opts.get(CONF_SWITCH)}): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch")
            ),
            vol.Required(CONF_OFFLINE_MINUTES, default=opts.get(CONF_OFFLINE_MINUTES, DEFAULT_OFFLINE_MINUTES)): selector.NumberSelector(
                selector.NumberSelectorConfig(min=1, max=240, step=1, unit_of_measurement="min", mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_NOTIFY_ENTITIES, default=opts.get(CONF_NOTIFY_ENTITIES, [])): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="notify", multiple=True)
            ),
            vol.Optional(CONF_NOTIFY_SERVICES, default=opts.get(CONF_NOTIFY_SERVICES, [])): selector.TextSelector(
                selector.TextSelectorConfig(multiple=True)
            ),
        }
    )


class EcoTrackerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add an EcoTracker by its host name."""

    VERSION = 1

    _host: str = ""

    async def _ip(self, host: str) -> str | None:
        try:
            infos = await self.hass.loop.getaddrinfo(host, None, family=socket.AF_INET)
        except OSError:
            return None
        return infos[0][4][0] if infos else None

    async def _abort_if_known(self, host: str, serial: str | None) -> None:
        """Entries made before 0.2.0 use the host name as unique ID; match them by serial or IP."""
        ip = await self._ip(host)
        for entry in self._async_current_entries(include_ignore=False):
            other = entry.data.get(CONF_HOST, "")
            coordinator = getattr(entry, "runtime_data", None)
            if (
                entry.unique_id in {host, serial}
                or other == host
                or (serial and getattr(coordinator, "serial", None) == serial)
                or (ip and await self._ip(other) == ip)
            ):
                raise AbortFlow("already_configured")

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the host and check that it answers."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip().lower()
            try:
                data = await fetch(self.hass, host)
            except (TimeoutError, aiohttp.ClientError, ValueError):
                errors["base"] = "cannot_connect"
            else:
                serial = data.get("serial") or (await async_mdns_info(host)).get("serial")
                await self.async_set_unique_id(serial or host)
                self._abort_if_unique_id_configured()
                await self._abort_if_known(host, serial)
                return self.async_create_entry(title="EcoTracker", data={CONF_HOST: host})
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_HOST, default=DEFAULT_HOST): str}),
            errors=errors,
        )

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> ConfigFlowResult:
        """Found over mDNS (_everhome._tcp)."""
        host = str(discovery_info.ip_address)
        serial = discovery_info.properties.get("serial") or None
        await self.async_set_unique_id(serial or host)
        self._abort_if_unique_id_configured()  # keeps the host the user entered
        await self._abort_if_known(host, serial)
        self._host = host
        self.context["title_placeholders"] = {"name": f"EcoTracker {serial or host}"}
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask before adding the found EcoTracker."""
        if user_input is not None:
            try:
                await fetch(self.hass, self._host)
            except (TimeoutError, aiohttp.ClientError, ValueError):
                return self.async_abort(reason="cannot_connect")
            return self.async_create_entry(title="EcoTracker", data={CONF_HOST: self._host})
        self._set_confirm_only()
        return self.async_show_form(
            step_id="zeroconf_confirm", description_placeholders={"host": self._host}
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Options."""
        return EcoTrackerOptionsFlow()


class EcoTrackerOptionsFlow(OptionsFlow):
    """Polling interval and watchdog."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """One form."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(step_id="init", data_schema=_options_schema(dict(self.config_entry.options)))
