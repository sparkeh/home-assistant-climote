"""Client for the Climote web interface.

Climote does not expose a public API. All communication is done through the
same endpoints the web UI uses (https://climote.climote.ie/manager/), hence
the login / CSRF token handling and the HTML/XML parsing in this module.

Status updates are delivered from the hub over SMS, so triggering a forced
refresh ("force=1") is slow and costs a message. Fetching the cached status
("force=0") is fast and free.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
import json
import logging
import re
from typing import Any

import aiohttp

from .const import DEFAULT_BOOST_DURATION

_LOGGER = logging.getLogger(__name__)

_LOGIN_URL = "https://climote.climote.ie/manager/login"
_LOGOUT_URL = "https://climote.climote.ie/manager/logout"
_SCHEDULE_ID_RE = re.compile(r"heatingScheduleId=(\d+)")

_STATUS_URL = "https://climote.climote.ie/manager/get-status"
_STATUS_RESPONSE_URL = "https://climote.climote.ie/manager/waiting-get-status-response"
_BOOST_URL = "https://climote.climote.ie/manager/boost"
_SET_TEMP_URL = "https://climote.climote.ie/manager/temperature"
_GET_SCHEDULE_URL = "https://climote.climote.ie/manager/get-heating-schedule?heatingScheduleId="

_HTTP_TIMEOUT = 30
_STATUS_POLL_INTERVAL = 10
_STATUS_POLL_TIMEOUT = 120

# The login form fields are not what their labels suggest:
#   "password" = the account email, "username" = the hub device number,
#   "passcode" = the account password/PIN.


class ClimoteError(Exception):
    """Base class for Climote errors."""


class ClimoteAuthenticationError(ClimoteError):
    """Login failed because the credentials were rejected."""


class ClimoteConnectionError(ClimoteError):
    """The Climote service could not be reached."""


class ClimoteRefreshTimeout(ClimoteError):
    """Timed out waiting for the hub to report its status."""


class ClimoteService:
    """Communicates with the Climote web interface."""

    def __init__(
        self,
        device_id: str,
        username: str,
        password: str,
        *,
        default_boost_duration: str = DEFAULT_BOOST_DURATION,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._device_id = device_id
        self._username = username
        self._password = password
        self._session = session or aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=_HTTP_TIMEOUT)
        )
        self._owns_session = session is None

        self._creds = {
            "password": username,
            "username": device_id,
            "passcode": password,
        }

        self.default_boost_duration = default_boost_duration
        self._zones_boost_duration: dict[int, str] = {}

        self.logged_in = False
        self._token = ""
        self.config_id: str | None = None
        self.zones: dict[int, str] = {}
        self.data: dict[str, Any] = {}
        self.last_forced_refresh: datetime | None = None

    @property
    def device_id(self) -> str:
        return self._device_id

    @staticmethod
    def sanitized_device_id(device_id: str) -> str:
        return f"******{device_id[-4:]}"

    def get_sanitized_device_id(self) -> str:
        return self.sanitized_device_id(self._device_id)

    def set_zone_boost_duration(self, zone: int, duration: str) -> None:
        self._zones_boost_duration[zone] = duration

    def get_zone_boost_duration(self, zone: int) -> str:
        return self._zones_boost_duration.get(zone, self.default_boost_duration)

    async def close(self) -> None:
        if self._owns_session and not self._session.closed:
            await self._session.close()

    async def async_login(self) -> bool:
        """Log in and store the CSRF token + schedule id."""
        try:
            async with self._session.post(_LOGIN_URL, data=self._creds) as resp:
                text = await resp.text()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise ClimoteConnectionError(f"Could not reach Climote: {err}") from err

        if resp.status != 200:
            _LOGGER.error("Login returned HTTP %s", resp.status)
            return False

        # The login page contains a form with id "loginForm"; the manager pages
        # do not, so its absence means authentication succeeded.
        if "loginForm" in text:
            _LOGGER.debug("Login rejected by Climote")
            return False

        self.logged_in = True
        self._token = self._extract_csrf_token(text)
        if config_id := _SCHEDULE_ID_RE.search(text):
            self.config_id = config_id.group(1)
        _LOGGER.debug("Logged in, token=%s, config_id=%s", bool(self._token), self.config_id)
        return True

    async def async_logout(self) -> None:
        if not self.logged_in:
            return
        try:
            await self._session.get(_LOGOUT_URL)
        except aiohttp.ClientError:
            _LOGGER.debug("Logout request failed", exc_info=True)
        finally:
            self.logged_in = False

    @staticmethod
    def _extract_csrf_token(text: str) -> str:
        """Find the CSRF token used by the boost/temperature forms."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(text, "html.parser")
        for element in soup.find_all("input"):
            if element.get("name") == "cs_token_rf" and element.get("value"):
                return element["value"]
        return ""

    async def async_get_status(self) -> dict[str, Any] | None:
        """Fetch the cached status without contacting the hub.

        Returns None when the hub has not reported a status yet (the endpoint
        returns "0") or the session is no longer valid.
        """
        try:
            async with self._session.get(
                _STATUS_URL, params={"force": 0}
            ) as resp:
                text = await resp.text()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise ClimoteConnectionError(f"Could not reach Climote: {err}") from err

        if resp.status != 200:
            return None
        text = text.strip()
        if text == "0":
            return None
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            _LOGGER.debug("Cached status response was not JSON", exc_info=True)
            return None

    async def async_request_status_refresh(self) -> dict[str, Any]:
        """Ask the hub to report its status and wait for the result.

        This triggers an SMS round trip to the hub, so it can take up to two
        minutes to return.
        """
        try:
            async with self._session.post(
                _STATUS_URL, params={"force": 1}, data=self._creds
            ) as resp:
                await resp.text()
            if resp.status != 200:
                raise ClimoteConnectionError(
                    f"Status refresh returned HTTP {resp.status}"
                )

            loop = asyncio.get_running_loop()
            deadline = loop.time() + _STATUS_POLL_TIMEOUT
            headers = {"X-Requested-With": "XMLHttpRequest"}
            while loop.time() < deadline:
                async with self._session.post(
                    _STATUS_RESPONSE_URL, data=self._creds, headers=headers
                ) as poll_resp:
                    text = await poll_resp.text()
                text = text.strip()
                if text and text != "0":
                    try:
                        return json.loads(text)
                    except (json.JSONDecodeError, ValueError) as err:
                        raise ClimoteConnectionError(
                            f"Unexpected status response: {err}"
                        ) from err
                await asyncio.sleep(_STATUS_POLL_INTERVAL)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise ClimoteConnectionError(f"Could not reach Climote: {err}") from err

        raise ClimoteRefreshTimeout("Timed out waiting for the hub to report status")

    async def async_fetch_zones(self) -> dict[int, str]:
        """Fetch the heating schedule config and return the active zones."""
        if not self.config_id:
            return {}
        try:
            async with self._session.get(
                _GET_SCHEDULE_URL + self.config_id
            ) as resp:
                text = await resp.text()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise ClimoteConnectionError(f"Could not reach Climote: {err}") from err

        if resp.status != 200:
            _LOGGER.error("Fetching schedule returned HTTP %s", resp.status)
            return {}

        try:
            from lxml import etree
        except ImportError as err:
            _LOGGER.error("lxml is required to fetch the heating schedule: %s", err)
            return {}

        try:
            root = etree.fromstring(text.encode("utf-8"))
        except etree.XMLSyntaxError as err:
            _LOGGER.error("Could not parse heating schedule: %s", err)
            return {}

        zones: dict[int, str] = {}
        for index, zone in enumerate(root.xpath(".//*[local-name()='zone']"), start=1):
            if self._local_child_text(zone, "active") == "1":
                if label := self._local_child_text(zone, "label"):
                    zones[index] = label
        self.zones = zones
        return zones

    @staticmethod
    def _local_child_text(node: etree._Element, name: str) -> str | None:
        """Return text of a direct child element matched by local name."""
        from lxml import etree

        for child in node:
            if etree.QName(child).localname == name:
                return child.text
        return None

    async def async_boost(self, zone: int) -> bool:
        """Start a boost (heat on) for a zone."""
        data = {
            f"zoneIds[{zone}]": self.get_zone_boost_duration(zone),
            "cs_token_rf": self._token,
        }
        try:
            async with self._session.post(_BOOST_URL, data=data) as resp:
                return resp.status == 200
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise ClimoteConnectionError(f"Could not reach Climote: {err}") from err

    async def async_turn_off(self, zone: int) -> bool:
        """Turn the heat off for a zone."""
        data = {f"zoneIds[{zone}]": "0", "cs_token_rf": self._token}
        try:
            async with self._session.post(_BOOST_URL, data=data) as resp:
                return resp.status == 200
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise ClimoteConnectionError(f"Could not reach Climote: {err}") from err

    async def async_set_target_temperature(self, zone: int, temperature: float) -> bool:
        """Set the target temperature for a zone."""
        data = {
            f"temp-set-input[{zone}]": temperature,
            "do": "Set",
            "cs_token_rf": self._token,
        }
        try:
            async with self._session.post(_SET_TEMP_URL, data=data) as resp:
                return resp.status == 200
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise ClimoteConnectionError(f"Could not reach Climote: {err}") from err
