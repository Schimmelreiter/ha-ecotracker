"""Config flow: host; options: polling and the watchdog."""

from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers import selector

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

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the host and check that it answers."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip().lower()
            await self.async_set_unique_id(host)
            self._abort_if_unique_id_configured()
            try:
                await fetch(self.hass, host)
            except (TimeoutError, aiohttp.ClientError, ValueError):
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title="EcoTracker", data={CONF_HOST: host})
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_HOST, default=DEFAULT_HOST): str}),
            errors=errors,
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
