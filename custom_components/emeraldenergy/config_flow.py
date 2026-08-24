"""Config flow for Emerald Hot Water System integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import requests
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DOMAIN,
    CONF_CONNECTION_TIMEOUT,
    CONF_HEALTH_CHECK,
    CONF_ENABLE_ENERGY_MONITORING,
    DEFAULT_CONNECTION_TIMEOUT,
    DEFAULT_HEALTH_CHECK,
    DEFAULT_ENABLE_ENERGY_MONITORING,
)
from .helpers import create_hws, effective_config

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_CONNECTION_TIMEOUT, default=DEFAULT_CONNECTION_TIMEOUT): int,
        vol.Optional(CONF_HEALTH_CHECK, default=DEFAULT_HEALTH_CHECK): int,
        vol.Optional(
            CONF_ENABLE_ENERGY_MONITORING, default=DEFAULT_ENABLE_ENERGY_MONITORING
        ): bool,
    }
)


def _create_and_login(config: Mapping[str, Any]) -> bool:
    """Build an EmeraldHWS client and check the credentials are accepted.

    Blocking, and both halves reach into awsiotsdk/awscrt, so they run as a single
    executor job rather than two.
    """
    return bool(create_hws(config).getLoginToken())


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    try:
        logged_in = await hass.async_add_executor_job(_create_and_login, data)
    except requests.exceptions.RequestException as err:
        # emerald_hws makes the sign-in request with plain requests calls and lets
        # network failures (DNS, timeout, connection refused) propagate as-is,
        # rather than wrapping them -- so this is the only place that
        # distinguishes "can't reach the Emerald API" from "reached it, bad
        # credentials".
        raise CannotConnect from err
    except Exception as err:
        # A response was received but rejected: getLoginToken raises a bare
        # Exception("Failed to log into Emerald API with supplied credentials")
        # for a non-200 sign-in response, with no narrower type to catch.
        raise InvalidAuth from err
    if not logged_in:
        raise InvalidAuth

    # Return info that you want to store in the config entry.
    return {"title": "Emerald HWS"}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Emerald Hot Water System."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_USERNAME])
            self._abort_if_unique_id_configured()
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> FlowResult:
        """Handle reauth triggered by ConfigEntryAuthFailed (e.g. password change)."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask for the new password and revalidate against the existing entry."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()
        if user_input is not None:
            data = {**reauth_entry.data, **user_input}
            try:
                await validate_input(self.hass, data)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(reauth_entry, data=data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlow:
        """Get the options flow for this handler."""
        return OptionsFlow()


class OptionsFlow(config_entries.OptionsFlow):
    """Let connection_timeout/health_check/energy monitoring change without re-adding."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = effective_config(self.config_entry)
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_CONNECTION_TIMEOUT,
                    default=current.get(
                        CONF_CONNECTION_TIMEOUT, DEFAULT_CONNECTION_TIMEOUT
                    ),
                ): int,
                vol.Optional(
                    CONF_HEALTH_CHECK,
                    default=current.get(CONF_HEALTH_CHECK, DEFAULT_HEALTH_CHECK),
                ): int,
                vol.Optional(
                    CONF_ENABLE_ENERGY_MONITORING,
                    default=current.get(
                        CONF_ENABLE_ENERGY_MONITORING, DEFAULT_ENABLE_ENERGY_MONITORING
                    ),
                ): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
