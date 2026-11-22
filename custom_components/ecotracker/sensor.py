"""Readings of the EcoTracker and the watchdog's counter."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import EcoTrackerConfigEntry, EcoTrackerCoordinator
from .entity import EcoTrackerEntity


@dataclass(frozen=True, kw_only=True)
class EcoTrackerSensorDescription(SensorEntityDescription):
    """A value of /v1/json."""

    value: Callable[[dict[str, Any]], Any]


def _num(key: str, factor: float = 1.0, digits: int | None = None) -> Callable[[dict[str, Any]], Any]:
    def get(data: dict[str, Any]) -> Any:
        v = data.get(key)
        if not isinstance(v, (int, float)):
            return None
        v = v * factor
        return round(v, digits) if digits is not None else v

    return get


POWER = {"device_class": SensorDeviceClass.POWER, "state_class": SensorStateClass.MEASUREMENT,
         "native_unit_of_measurement": UnitOfPower.WATT}
ENERGY = {"device_class": SensorDeviceClass.ENERGY, "state_class": SensorStateClass.TOTAL_INCREASING,
          "native_unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR, "suggested_display_precision": 2}

SENSORS = (
    EcoTrackerSensorDescription(key="aktueller_verbrauch", value=_num("power"), **POWER),
    EcoTrackerSensorDescription(key="durchschnittlicher_verbrauch", value=_num("powerAvg"), **POWER),
    EcoTrackerSensorDescription(key="leistung_l1", value=_num("powerPhase1"), **POWER),
    EcoTrackerSensorDescription(key="leistung_l2", value=_num("powerPhase2"), **POWER),
    EcoTrackerSensorDescription(key="leistung_l3", value=_num("powerPhase3"), **POWER),
    EcoTrackerSensorDescription(key="bezug", value=_num("energyCounterIn", 0.001, 3), **ENERGY),
    EcoTrackerSensorDescription(key="einspeisung", value=_num("energyCounterOut", 0.001, 3), **ENERGY),
    EcoTrackerSensorDescription(
        key="signalstaerke", value=_num("rssi"), device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT, state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC, entity_registry_enabled_default=False,
    ),
    EcoTrackerSensorDescription(
        key="alter_messwert", value=_num("agePower", 0.001, 1), device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS, state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC, entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: EcoTrackerConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Add the sensors."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [EcoTrackerSensor(coordinator, d) for d in SENSORS]
    entities.append(WatchdogRestarts(coordinator))
    async_add_entities(entities)


class EcoTrackerSensor(EcoTrackerEntity, SensorEntity):
    """One reading."""

    entity_description: EcoTrackerSensorDescription

    def __init__(self, coordinator: EcoTrackerCoordinator, description: EcoTrackerSensorDescription) -> None:
        """Initialize."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Value from the last answer."""
        return self.entity_description.value(self.coordinator.data or {})


class WatchdogRestarts(EcoTrackerEntity, SensorEntity):
    """Restarts by the watchdog during the current outage (0 while it is online)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: EcoTrackerCoordinator) -> None:
        """Initialize."""
        super().__init__(coordinator, "watchdog_neustarts")

    @property
    def available(self) -> bool:
        """Also while the EcoTracker is offline."""
        return True

    @property
    def native_value(self) -> int:
        """Number of power cycles."""
        return self.coordinator.restarts

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Times of the watchdog."""
        c = self.coordinator
        return {
            "offline_seit": c.offline_since.isoformat() if c.offline_since else None,
            "letzter_neustart": c.last_restart.isoformat() if c.last_restart else None,
            "naechster_neustart": c.next_restart.isoformat() if c.next_restart else None,
            "schalter": c.switch,
        }
