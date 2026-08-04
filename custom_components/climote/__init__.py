"""The Climote integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .climote_service import ClimoteService
from .const import (
    CONF_BOOST_DURATION,
    CONF_CLIMOTE_ID,
    CONF_PASSWORD,
    CONF_USERNAME,
    DEFAULT_BOOST_DURATION,
    DOMAIN,
)
from .coordinator import ClimoteCoordinator

PLATFORMS = [Platform.CLIMATE, Platform.SELECT, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Climote from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    climote = ClimoteService(
        entry.data[CONF_CLIMOTE_ID],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        default_boost_duration=entry.data.get(
            CONF_BOOST_DURATION, DEFAULT_BOOST_DURATION
        ),
    )

    coordinator = ClimoteCoordinator(hass, entry, climote)

    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryAuthFailed as err:
        await climote.close()
        raise ConfigEntryAuthFailed from err
    except ConfigEntryNotReady as err:
        await climote.close()
        raise ConfigEntryNotReady from err

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    entry.async_on_unload(climote.close)

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options updates."""
    if coordinator := hass.data.get(DOMAIN, {}).get(entry.entry_id):
        await coordinator.async_update_settings()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    ):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
