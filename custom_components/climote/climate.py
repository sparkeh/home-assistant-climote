"""Climate platform for the Climote integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, PRECISION_WHOLE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ClimoteCoordinator, climote_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Climote climate entities."""
    coordinator: ClimoteCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        ClimoteClimate(coordinator, zone_id, region)
        for zone_id, region in coordinator.climote.zones.items()
    )


def _to_temperature(value: Any) -> float | None:
    if value in (None, "--", ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class ClimoteClimate(CoordinatorEntity[ClimoteCoordinator], ClimateEntity):
    """Representation of a Climote zone."""

    _attr_has_entity_name = True
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_max_temp = 30
    _attr_min_temp = 10
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_target_temperature_step = PRECISION_WHOLE
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(
        self, coordinator: ClimoteCoordinator, zone_id: int, region: str
    ) -> None:
        """Initialize the zone."""
        super().__init__(coordinator)
        self._zone_id = zone_id
        self._attr_name = region
        self._attr_unique_id = f"climate_{zone_id}"
        self._attr_device_info = climote_device_info(coordinator.climote.device_id)

    @property
    def _zone_data(self) -> dict[str, Any]:
        return self.coordinator.data.get(f"zone{self._zone_id}", {})

    @property
    def hvac_mode(self) -> HVACMode:
        """Return the current operating mode."""
        return (
            HVACMode.HEAT if self._zone_data.get("status") == "5" else HVACMode.OFF
        )

    @property
    def hvac_action(self) -> HVACAction:
        """Return the current running action."""
        return (
            HVACAction.HEATING if self._zone_data.get("burner") == 1 else HVACAction.IDLE
        )

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return _to_temperature(self._zone_data.get("temperature"))

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""
        return _to_temperature(self._zone_data.get("thermostat"))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the operating mode."""
        climote = self.coordinator.climote
        if hvac_mode == HVACMode.HEAT:
            _LOGGER.info("Boosting zone %s", self._zone_id)
            success = await climote.async_boost(self._zone_id)
        elif hvac_mode == HVACMode.OFF:
            _LOGGER.info("Turning off zone %s", self._zone_id)
            success = await climote.async_turn_off(self._zone_id)
        else:
            return
        if success:
            self.coordinator.schedule_forced_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        _LOGGER.info("Setting zone %s temperature to %s", self._zone_id, temperature)
        success = await self.coordinator.climote.async_set_target_temperature(
            self._zone_id, float(temperature)
        )
        if success:
            self.coordinator.schedule_forced_refresh()
