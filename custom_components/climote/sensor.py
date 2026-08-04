"""Sensor platform for the Climote integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ClimoteCoordinator, climote_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Climote sensor entities."""
    coordinator: ClimoteCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        ClimoteBoostRemaining(coordinator, zone_id, region)
        for zone_id, region in coordinator.climote.zones.items()
    )


class ClimoteBoostRemaining(CoordinatorEntity[ClimoteCoordinator], SensorEntity):
    """Report the boost time remaining for a zone as reported by the hub."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_icon = "mdi:clock"
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def __init__(
        self, coordinator: ClimoteCoordinator, zone_id: int, region: str
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._zone_id = zone_id
        self._attr_name = f"{region} Boost Remaining"
        self._attr_unique_id = f"boost_remaining_{zone_id}"
        self._attr_device_info = climote_device_info(coordinator.climote.device_id)

    @property
    def native_value(self) -> float | None:
        """Return the boost time remaining in minutes."""
        value: Any = self.coordinator.data.get(
            f"zone{self._zone_id}", {}
        ).get("timeRemaining")
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
