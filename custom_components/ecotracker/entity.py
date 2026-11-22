"""Base entity."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EcoTrackerCoordinator


class EcoTrackerEntity(CoordinatorEntity[EcoTrackerCoordinator]):
    """Entity of the EcoTracker device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: EcoTrackerCoordinator, key: str) -> None:
        """Initialize."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            name=entry.title,
            manufacturer="everHome",
            model="EcoTracker",
            configuration_url=f"http://{coordinator.host}/",
        )
