"""Restart over the upstream switch by hand."""

from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import EcoTrackerConfigEntry, EcoTrackerCoordinator
from .entity import EcoTrackerEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: EcoTrackerConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Add the restart button when a switch is set."""
    if entry.runtime_data.switch:
        async_add_entities([Restart(entry.runtime_data)])


class Restart(EcoTrackerEntity, ButtonEntity):
    """Power cycle the EcoTracker."""

    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: EcoTrackerCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "neustart")

    @property
    def available(self) -> bool:
        """Also while the EcoTracker is offline."""
        return True

    async def async_press(self) -> None:
        """Switch off, wait, switch on."""
        await self.coordinator.restart()
