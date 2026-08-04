"""Select platform for the Climote integration."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, VALID_BOOST_VALUES
from .coordinator import ClimoteCoordinator, climote_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Climote select entities."""
    coordinator: ClimoteCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        ClimoteBoostDuration(coordinator, zone_id, region)
        for zone_id, region in coordinator.climote.zones.items()
    )


class ClimoteBoostDuration(CoordinatorEntity[ClimoteCoordinator], SelectEntity):
    """Select how long the boost runs for a zone."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:clock"
    _attr_options = VALID_BOOST_VALUES

    def __init__(
        self, coordinator: ClimoteCoordinator, zone_id: int, region: str
    ) -> None:
        """Initialize the select."""
        super().__init__(coordinator)
        self._zone_id = zone_id
        self._attr_name = f"{region} Boost Duration"
        self._attr_unique_id = f"boost_duration_{zone_id}"
        self._attr_device_info = climote_device_info(coordinator.climote.device_id)

    @property
    def current_option(self) -> str:
        """Return the currently selected boost duration."""
        return self.coordinator.climote.get_zone_boost_duration(self._zone_id)

    async def async_select_option(self, option: str) -> None:
        """Set the boost duration for this zone."""
        self.coordinator.climote.set_zone_boost_duration(self._zone_id, option)
        self.async_write_ha_state()
