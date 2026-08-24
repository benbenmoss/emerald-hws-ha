"""Implementation of the Sensor platform for Emerald HWS energy monitoring."""

from __future__ import annotations

import logging

from homeassistant import config_entries
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from emerald_hws.emeraldhws import EmeraldHWS

from .const import (
    DOMAIN,
    CONF_ENABLE_ENERGY_MONITORING,
)
from .helpers import effective_config

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities,
):
    """Set up the energy monitoring sensors for Emerald HWS."""
    # Check if energy monitoring is enabled in config (data or options, the
    # latter set later via the options flow)
    if not effective_config(config_entry).get(CONF_ENABLE_ENERGY_MONITORING, True):
        _LOGGER.info("Energy monitoring is disabled in configuration")
        return True

    # Get the shared EmeraldHWS data from hass.data
    entry_data = hass.data[DOMAIN].get(config_entry.entry_id)
    if not entry_data:
        # __init__.py always populates this before forwarding to platforms, so
        # reaching here means that invariant broke -- fail loudly rather than
        # silently returning False, which HA's forwarder ignores anyway.
        raise HomeAssistantError("No Emerald HWS data found in hass data")

    emerald_hws_instance = entry_data["instance"]
    callback_dispatcher = entry_data["dispatcher"]

    sensors = []
    # Fetch the list of hot water systems (UUIDs)
    hot_water_systems = await hass.async_add_executor_job(emerald_hws_instance.listHWS)

    # Create energy sensors for each hot water system
    for hws_uuid in hot_water_systems:
        sensor = EmeraldEnergySensor(
            hass, emerald_hws_instance, hws_uuid, callback_dispatcher
        )
        sensors.append(sensor)

    # Add energy sensors to Home Assistant
    if sensors:
        async_add_entities(sensors, True)
        _LOGGER.info(f"Added {len(sensors)} energy monitoring sensors")

    return True


class EmeraldEnergySensor(SensorEntity):
    """Representation of an Emerald HWS energy usage sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        emerald_hws_instance: EmeraldHWS,
        hws_uuid: str,
        callback_dispatcher,
    ):
        """Initialize the energy sensor."""
        self._hass = hass
        self._emerald_hws = emerald_hws_instance
        self._hws_uuid = hws_uuid
        self._callback_dispatcher = callback_dispatcher
        self._attr_name = None
        self._attr_unique_id = None
        self._attr_native_value = None
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_icon = "mdi:lightning-bolt"
        self._today = dt_util.now().date()
        # Set at construction, not left None until the first observed day
        # rollover -- HA's statistics layer expects a tz-aware last_reset for a
        # TOTAL state_class, and a day-one sensor otherwise has no reset marker
        # at all until the first midnight is caught by an MQTT callback.
        self._last_reset = dt_util.start_of_local_day(self._today)

        # Get device info for proper integration
        gi = emerald_hws_instance.getInfo(hws_uuid)
        self._serial_number = gi.get("serial_number")
        self._brand = gi.get("brand", "Emerald")

        # Set up sensor properties
        self._attr_name = f"{self._brand} {self._serial_number} Daily Energy"
        self._attr_unique_id = f"{DOMAIN}_{hws_uuid}_daily_energy"

        # Set up device info for proper grouping with water heater
        self._attr_device_info = {
            "identifiers": {(DOMAIN, hws_uuid)},
            "name": f"{self._brand} {self._serial_number}",
            "manufacturer": self._brand,
            "model": "Hot Water System",
            "serial_number": self._serial_number,
        }

        # Register for updates with callback dispatcher
        callback_dispatcher.register_callback(self.update_callback)

        # Energy value is left unset here: async_setup_entry calls
        # async_add_entities(sensors, True), which runs update() via the
        # executor before this entity's state is ever written to HA -- fetching
        # it here too just duplicated that call.

    @property
    def last_reset(self):
        """Return the time when the sensor was last reset (midnight)."""
        return self._last_reset

    def update_callback(self):
        """Schedules an update within HASS when data changes (module thread)."""
        _LOGGER.debug(f"Energy sensor callback for {self._attr_name}")
        if self.hass is None:
            # The emerald_hws MQTT thread can fire callbacks before the entity
            # is added to HASS (or after removal). schedule_update_ha_state is
            # thread-safe, but with self.hass is None it would raise
            # "'NoneType' object has no attribute 'create_task'".
            _LOGGER.debug(
                "Dropping callback for %s; hass not set (entity not added yet "
                "or already removed)",
                self._attr_name,
            )
            return
        self.schedule_update_ha_state(True)

    def update_energy_value(self):
        """Update the energy value from the API."""
        try:
            # Check if we need to reset (new day)
            today = dt_util.now().date()
            rolled_over = today != self._today
            if rolled_over:
                self._today = today
                self._last_reset = dt_util.start_of_local_day(today)
                _LOGGER.info(f"Daily energy sensor reset for {self._attr_name}")

            # Get daily energy usage
            daily_energy = self._emerald_hws.getDailyEnergyUsage(self._hws_uuid)
            if daily_energy is not None:
                self._attr_native_value = round(
                    daily_energy, 3
                )  # Round to 3 decimal places
            elif rolled_over:
                # No reading for today yet: the device reports on its own
                # schedule and may not have pushed one since midnight. This is
                # the expected value right after a TOTAL reset, not a failure
                # -- reporting it as unknown would leave a daily gap in the
                # statistics graph instead of a real zero.
                self._attr_native_value = 0
            else:
                _LOGGER.warning(f"Failed to get daily energy for {self._hws_uuid}")
                self._attr_native_value = None
        except Exception as e:
            _LOGGER.error(f"Error updating energy value for {self._hws_uuid}: {e}")
            self._attr_native_value = None

    def update(self):
        """Update the sensor state."""
        _LOGGER.debug(f"Updating energy sensor {self._attr_name}")
        self.update_energy_value()

    async def async_update(self) -> None:
        """Update the sensor state asynchronously."""
        await self._hass.async_add_executor_job(self.update)

    async def async_will_remove_from_hass(self) -> None:
        """Clean up when entity is removed from Home Assistant."""
        # Unregister from callback dispatcher
        self._callback_dispatcher.unregister_callback(self.update_callback)
        await super().async_will_remove_from_hass()
