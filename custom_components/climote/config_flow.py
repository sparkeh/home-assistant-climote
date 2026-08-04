"""Config flow for the Climote integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .climote_service import ClimoteConnectionError, ClimoteService
from .const import (
    CONF_BOOST_DURATION,
    CONF_CLIMOTE_ID,
    CONF_PASSWORD,
    CONF_POLL_INTERVAL,
    CONF_REFRESH_INTERVAL,
    CONF_USERNAME,
    DEFAULT_BOOST_DURATION,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_REFRESH_INTERVAL,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MAX_REFRESH_INTERVAL,
    MIN_POLL_INTERVAL,
    MIN_REFRESH_INTERVAL,
    VALID_BOOST_VALUES,
)

_LOGGER = logging.getLogger(__name__)


def _interval_validator(min_value: int, max_value: int):
    return vol.All(
        vol.Coerce(int), vol.Range(min=min_value, max=max_value)
    )


def _user_schema() -> vol.Schema:
    """Build the user step schema."""
    return vol.Schema(
        {
            vol.Required(CONF_CLIMOTE_ID): str,
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Required(
                CONF_BOOST_DURATION, default=DEFAULT_BOOST_DURATION
            ): vol.In(VALID_BOOST_VALUES),
            vol.Required(
                CONF_REFRESH_INTERVAL, default=DEFAULT_REFRESH_INTERVAL
            ): _interval_validator(MIN_REFRESH_INTERVAL, MAX_REFRESH_INTERVAL),
            vol.Required(
                CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL
            ): _interval_validator(MIN_POLL_INTERVAL, MAX_POLL_INTERVAL),
        }
    )


async def _validate_input(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Validate that the user input allows us to connect."""
    service = ClimoteService(
        data[CONF_CLIMOTE_ID],
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        default_boost_duration=data[CONF_BOOST_DURATION],
    )
    try:
        logged_in = await service.async_login()
    except ClimoteConnectionError as err:
        raise CannotConnect from err
    finally:
        await service.close()

    if not logged_in:
        raise InvalidAuth


class ClimoteConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Climote."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=_user_schema())

        errors: dict[str, str] = {}
        try:
            await _validate_input(self.hass, user_input)
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected exception during Climote setup")
            errors["base"] = "unknown"
        else:
            await self.async_set_unique_id(user_input[CONF_CLIMOTE_ID])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=ClimoteService.sanitized_device_id(user_input[CONF_CLIMOTE_ID]),
                data=user_input,
            )

        return self.async_show_form(
            step_id="user", data_schema=_user_schema(), errors=errors
        )

    async def async_step_reauth(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Perform reauth upon an API authentication error."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Dialog that informs the user that reauth is required."""
        errors: dict[str, str] = {}
        if user_input is not None:
            updated = {
                **self._reauth_entry.data,
                CONF_USERNAME: user_input[CONF_USERNAME],
                CONF_PASSWORD: user_input[CONF_PASSWORD],
            }
            try:
                await _validate_input(self.hass, updated)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected exception during Climote reauth")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    self._reauth_entry,
                    data_updates={
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_USERNAME, default=self._reauth_entry.data[CONF_USERNAME]
                ): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=schema, errors=errors
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return ClimoteOptionsFlow(config_entry)


class ClimoteOptionsFlow(config_entries.OptionsFlow):
    """Handle options for the Climote integration."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_REFRESH_INTERVAL,
                    default=self._entry.options.get(
                        CONF_REFRESH_INTERVAL,
                        self._entry.data.get(
                            CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL
                        ),
                    ),
                ): _interval_validator(MIN_REFRESH_INTERVAL, MAX_REFRESH_INTERVAL),
                vol.Required(
                    CONF_POLL_INTERVAL,
                    default=self._entry.options.get(
                        CONF_POLL_INTERVAL,
                        self._entry.data.get(
                            CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
                        ),
                    ),
                ): _interval_validator(MIN_POLL_INTERVAL, MAX_POLL_INTERVAL),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
