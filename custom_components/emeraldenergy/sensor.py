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
from .helpers import device_info_for, effective_config

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
        sensors.append(
            EmeraldEnergySensor(hass, emerald_hws_instance, hws_uuid, callback_dispatcher)
        )
        sensors.append(
            EmeraldWeeklyEnergySensor(
                hass, emerald_hws_instance, hws_uuid, callback_dispatcher
            )
        )
        sensors.append(
            EmeraldMonthlyEnergySensor(
                hass, emerald_hws_instance, hws_uuid, callback_dispatcher
            )
        )

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


class EmeraldMonthlyEnergySensor(SensorEntity):
    """Representation of an Emerald HWS monthly energy usage sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        emerald_hws_instance: EmeraldHWS,
        hws_uuid: str,
        callback_dispatcher,
    ):
        """Initialize the monthly energy sensor."""
        self._hass = hass
        self._emerald_hws = emerald_hws_instance
        self._hws_uuid = hws_uuid
        self._callback_dispatcher = callback_dispatcher
        self._attr_native_value = None
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_icon = "mdi:calendar-month"
        self._this_month = dt_util.now().date().replace(day=1)
        # Same reasoning as the daily sensor's last_reset: set at construction,
        # tz-aware, not left None until the first observed month rollover.
        self._last_reset = dt_util.start_of_local_day(self._this_month)

        gi = emerald_hws_instance.getInfo(hws_uuid)
        self._serial_number = gi.get("serial_number")
        self._brand = gi.get("brand", "Emerald")

        self._attr_name = f"{self._brand} {self._serial_number} Monthly Energy"
        self._attr_unique_id = f"{DOMAIN}_{hws_uuid}_monthly_energy"
        self._attr_device_info = device_info_for(hws_uuid, self._brand, self._serial_number)

        callback_dispatcher.register_callback(self.update_callback)
        # Value left unset: async_add_entities(..., True) runs update() via
        # the executor before this entity's state is ever written to HA.

    @property
    def last_reset(self):
        """Return the time when the sensor was last reset (start of month)."""
        return self._last_reset

    def update_callback(self):
        """Schedules an update within HASS when data changes (module thread)."""
        _LOGGER.debug(f"Monthly energy sensor callback for {self._attr_name}")
        if self.hass is None:
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
            current_month = dt_util.now().date().replace(day=1)
            rolled_over = current_month != self._this_month
            if rolled_over:
                self._this_month = current_month
                self._last_reset = dt_util.start_of_local_day(current_month)
                _LOGGER.info(f"Monthly energy sensor reset for {self._attr_name}")

            monthly_energy = self._emerald_hws.getMonthlyEnergyUsage(self._hws_uuid)
            if monthly_energy is not None:
                self._attr_native_value = round(monthly_energy, 3)
            elif rolled_over:
                # Same reasoning as the daily sensor: no reading for this
                # month yet is the expected value right after a TOTAL reset,
                # not a failure.
                self._attr_native_value = 0
            else:
                _LOGGER.warning(f"Failed to get monthly energy for {self._hws_uuid}")
                self._attr_native_value = None
        except Exception as e:
            _LOGGER.error(f"Error updating monthly energy value for {self._hws_uuid}: {e}")
            self._attr_native_value = None

    def update(self):
        """Update the sensor state."""
        self.update_energy_value()

    async def async_update(self) -> None:
        """Update the sensor state asynchronously."""
        await self._hass.async_add_executor_job(self.update)

    async def async_will_remove_from_hass(self) -> None:
        """Clean up when entity is removed from Home Assistant."""
        self._callback_dispatcher.unregister_callback(self.update_callback)
        await super().async_will_remove_from_hass()


class EmeraldWeeklyEnergySensor(SensorEntity):
    """Representation of an Emerald HWS rolling 7-day energy usage sensor.

    This is a rolling sum (today plus the previous 6 days), not a period
    total that resets on a boundary -- MEASUREMENT is the correct state_class
    here, not TOTAL or TOTAL_INCREASING. Modelling a rolling window as either
    would corrupt long-term statistics: a real drop in daily usage would read
    as a meter reset. See getWeeklyEnergyUsage in emerald_hws.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        emerald_hws_instance: EmeraldHWS,
        hws_uuid: str,
        callback_dispatcher,
    ):
        """Initialize the weekly energy sensor."""
        self._hass = hass
        self._emerald_hws = emerald_hws_instance
        self._hws_uuid = hws_uuid
        self._callback_dispatcher = callback_dispatcher
        self._attr_native_value = None
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:calendar-week"

        gi = emerald_hws_instance.getInfo(hws_uuid)
        self._serial_number = gi.get("serial_number")
        self._brand = gi.get("brand", "Emerald")

        self._attr_name = f"{self._brand} {self._serial_number} Weekly Energy"
        self._attr_unique_id = f"{DOMAIN}_{hws_uuid}_weekly_energy"
        self._attr_device_info = device_info_for(hws_uuid, self._brand, self._serial_number)

        callback_dispatcher.register_callback(self.update_callback)
        # Value left unset: async_add_entities(..., True) runs update() via
        # the executor before this entity's state is ever written to HA.

    def update_callback(self):
        """Schedules an update within HASS when data changes (module thread)."""
        _LOGGER.debug(f"Weekly energy sensor callback for {self._attr_name}")
        if self.hass is None:
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
            weekly_energy = self._emerald_hws.getWeeklyEnergyUsage(self._hws_uuid)
            if weekly_energy is not None:
                self._attr_native_value = round(weekly_energy, 3)
            else:
                # getWeeklyEnergyUsage only returns None when the HWS itself
                # can't be found (no full_status at all) -- unlike the daily
                # sensor, a rolling sum has no "not reported for this period
                # yet" state, since sum({}) is just 0.
                _LOGGER.warning(f"Failed to get weekly energy for {self._hws_uuid}")
                self._attr_native_value = None
        except Exception as e:
            _LOGGER.error(f"Error updating weekly energy value for {self._hws_uuid}: {e}")
            self._attr_native_value = None

    def update(self):
        """Update the sensor state."""
        self.update_energy_value()

    async def async_update(self) -> None:
        """Update the sensor state asynchronously."""
        await self._hass.async_add_executor_job(self.update)

    async def async_will_remove_from_hass(self) -> None:
        """Clean up when entity is removed from Home Assistant."""
        self._callback_dispatcher.unregister_callback(self.update_callback)
        await super().async_will_remove_from_hass()
