"""everHome EcoTracker: local readings and a watchdog over its upstream switch."""

from __future__ import annotations

import asyncio

from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant

from .coordinator import EcoTrackerConfigEntry, EcoTrackerCoordinator
from .mdns import async_mdns_info

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: EcoTrackerConfigEntry) -> bool:
    """Set up from a config entry."""
    coordinator = EcoTrackerCoordinator(hass, entry)
    # an offline EcoTracker must not stop the watchdog; mDNS only adds the serial
    _, coordinator.mdns = await asyncio.gather(coordinator.async_refresh(), async_mdns_info(entry.data[CONF_HOST]))
    entry.runtime_data = coordinator
    coordinator.start_watchdog()
    entry.async_on_unload(entry.add_update_listener(_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _reload(hass: HomeAssistant, entry: EcoTrackerConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: EcoTrackerConfigEntry) -> bool:
    """Unload."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
