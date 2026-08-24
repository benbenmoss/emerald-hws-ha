"""Diagnostics support for the Emerald Hot Water System integration."""

from __future__ import annotations

from typing import Any

from emerald_hws.emeraldhws import EmeraldHWS
from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .helpers import effective_config

# serial_number identifies the physical unit, not useful for debugging a
# connection or state issue, so it's redacted alongside the credentials.
TO_REDACT = {CONF_USERNAME, CONF_PASSWORD, "serial_number"}

# getFullStatus's raw payload also carries latitude/longitude, wifi_name, and
# installer/agency identifiers (confirmed against a live account) -- fields
# with no debugging value and real privacy cost in a file that gets pasted
# into public GitHub issues. An explicit allowlist means a field the API adds
# later defaults to excluded, not leaked.
_STATUS_SUMMARY_FIELDS = (
    "device_operation_status",
    "is_online",
    "is_maintenance_required",
    "fault_code",
    "fault_description",
    "model",
    "device_type",
    "heat_pump_type",
    "series_type",
    "connection_type",
    "status",
    "last_seen",
)


def _status_summary(full_status: dict[str, Any] | None) -> dict[str, Any]:
    """Extract only the allowlisted fields from a raw getFullStatus() payload."""
    if not full_status:
        return {}
    return {key: full_status.get(key) for key in _STATUS_SUMMARY_FIELDS}


def _collect_hws_diagnostics(instance: EmeraldHWS) -> list[dict[str, Any]]:
    """Blocking: gather everything below in one executor job.

    getFullStatus (and everything built on it: getInfo/isOn/isHeating/
    currentMode/getHistoricalConsumption) triggers a full connect() -- HTTP
    login, MQTT connect, subscribe -- whenever _setup_complete is False, which
    disconnect() can flip mid-collection on a reconnect. Doing the whole loop
    as one executor job closes that window instead of leaving it open between
    listHWS and the per-HWS calls that follow it.
    """
    result = []
    for hws_uuid in instance.listHWS():
        result.append(
            {
                "info": instance.getInfo(hws_uuid),
                "is_on": instance.isOn(hws_uuid),
                "is_heating": instance.isHeating(hws_uuid),
                "current_mode": instance.currentMode(hws_uuid),
                "energy_usage": instance.getHistoricalConsumption(hws_uuid),
                "status_summary": _status_summary(instance.getFullStatus(hws_uuid)),
            }
        )
    return result


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    entry_data = hass.data[DOMAIN].get(entry.entry_id)
    diagnostics: dict[str, Any] = {
        "entry_data": effective_config(entry),
        "entry_loaded": entry_data is not None,
        "hot_water_systems": [],
    }

    if entry_data is not None:
        instance = entry_data["instance"]
        dispatcher = entry_data["dispatcher"]
        diagnostics["registered_entity_callbacks"] = dispatcher.callback_count

        try:
            diagnostics["hot_water_systems"] = await hass.async_add_executor_job(
                _collect_hws_diagnostics, instance
            )
        except Exception as err:
            # Surfacing the failure itself is the diagnostic value here.
            diagnostics["collection_error"] = str(err)

    return async_redact_data(diagnostics, TO_REDACT)
