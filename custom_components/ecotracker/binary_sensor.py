"""Whether the EcoTracker answers."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import EcoTrackerConfigEntry, EcoTrackerCoordinator
from .entity import EcoTrackerEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: EcoTrackerConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Add the connectivity sensor."""
    async_add_entities([Online(entry.runtime_data)])


class Online(EcoTrackerEntity, BinarySensorEntity):
    """On while the last poll worked."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: EcoTrackerCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "erreichbar")

    @property
    def available(self) -> bool:
        """Always: it reports the outage itself."""
        return True

    @property
    def is_on(self) -> bool:
        """Answered last time."""
        return self.coordinator.last_update_success
