"""DataUpdateCoordinator for the Climote integration."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .climote_service import (
    ClimoteAuthenticationError,
    ClimoteConnectionError,
    ClimoteRefreshTimeout,
    ClimoteService,
)
from .const import (
    DEFAULT_POLL_INTERVAL,
    DEFAULT_REFRESH_INTERVAL,
    DOMAIN,
    CONF_POLL_INTERVAL,
    CONF_REFRESH_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


def climote_device_info(device_id: str) -> DeviceInfo:
    """Return the shared device info for all Climote entities."""
    return DeviceInfo(
        identifiers={(DOMAIN, device_id)},
        name="Climote Hub",
        manufacturer="Climote",
        model="Remote Heating Controller",
    )


class ClimoteCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch the latest status from Climote on a schedule.

    The regular poll fetches the hub's cached status, which is fast and does
    not use any SMS credit. A full refresh (which asks the hub to report via
    SMS and can take a couple of minutes) runs on demand after a command and
    periodically at the configured refresh interval.
    """

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, climote: ClimoteService
    ) -> None:
        self._climote = climote
        self._entry = entry
        self._refresh_lock = asyncio.Lock()
        self._refresh_task: asyncio.Task | None = None

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=self.poll_interval),
        )

    @property
    def climote(self) -> ClimoteService:
        return self._climote

    @property
    def poll_interval(self) -> int:
        """Minutes between cheap cached-status polls."""
        return int(
            self._entry.options.get(
                CONF_POLL_INTERVAL,
                self._entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
            )
        )

    @property
    def refresh_interval(self) -> int:
        """Hours between full (SMS-based) refreshes."""
        return int(
            self._entry.options.get(
                CONF_REFRESH_INTERVAL,
                self._entry.data.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL),
            )
        )

    async def async_update_settings(self) -> None:
        """Apply a new options configuration."""
        self.update_interval = timedelta(minutes=self.poll_interval)
        await self.async_refresh()

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            if not self._climote.logged_in:
                await self._async_ensure_logged_in()
            data = await self._climote.async_get_status()
            if data is None:
                # Session may have expired; try once more after re-logging in.
                await self._async_ensure_logged_in()
                data = await self._climote.async_get_status()
        except ClimoteAuthenticationError as err:
            raise ConfigEntryAuthFailed("Climote credentials were rejected") from err
        except (ClimoteConnectionError, ClimoteRefreshTimeout) as err:
            raise UpdateFailed(str(err)) from err

        if data is not None:
            self._climote.data = data

        # Make sure a full refresh is (re)queued when it is due.
        if self._refresh_task is None:
            self._refresh_task = self.hass.async_create_task(
                self._async_periodic_refresh()
            )

        return self._climote.data

    async def _async_ensure_logged_in(self) -> None:
        if not await self._climote.async_login():
            raise ClimoteAuthenticationError("Login failed")
        if not self._climote.zones:
            await self._climote.async_fetch_zones()

    async def _async_periodic_refresh(self) -> None:
        task = asyncio.current_task()
        try:
            last = self._climote.last_forced_refresh
            if last is None or (
                datetime.now() - last
            ) >= timedelta(hours=self.refresh_interval):
                await self._async_forced_refresh()
        finally:
            if self._refresh_task is task:
                self._refresh_task = None

    def schedule_forced_refresh(self) -> None:
        """Trigger a full refresh in the background (used after commands)."""
        if self._refresh_task is None:
            self._refresh_task = self.hass.async_create_task(
                self._async_forced_refresh()
            )

    async def _async_forced_refresh(self) -> None:
        task = asyncio.current_task()
        async with self._refresh_lock:
            try:
                data = await self._climote.async_request_status_refresh()
                self._climote.data = data
                self._climote.last_forced_refresh = datetime.now()
                _LOGGER.debug("Forced status refresh complete")
            except (ClimoteConnectionError, ClimoteRefreshTimeout) as err:
                _LOGGER.warning("Forced status refresh failed: %s", err)
            finally:
                if self._refresh_task is task:
                    self._refresh_task = None
        self.async_set_updated_data(self._climote.data)
