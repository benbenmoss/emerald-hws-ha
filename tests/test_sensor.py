"""Tests for the monthly/weekly energy sensors' update logic.

update_energy_value is a plain instance method with no HA entity machinery
in its body, so a bare SimpleNamespace carrying the attributes it reads/sets
stands in for a real sensor -- no config_entry or hass fixtures needed.
"""

from types import SimpleNamespace

from homeassistant.util import dt as dt_util

from custom_components.emeraldenergy.sensor import (
    EmeraldMonthlyEnergySensor,
    EmeraldWeeklyEnergySensor,
)


def _fake_monthly_sensor(this_month, emerald_hws):
    return SimpleNamespace(
        _emerald_hws=emerald_hws,
        _hws_uuid="uuid-1",
        _attr_name="Test Monthly Energy",
        _this_month=this_month,
        _last_reset=dt_util.start_of_local_day(this_month) if this_month else None,
        _attr_native_value=None,
    )


def test_monthly_sensor_reports_zero_on_rollover_with_no_data_yet():
    """Mirrors the daily-sensor fix: no reading yet after rollover means 0, not unknown."""
    this_month = dt_util.now().date().replace(day=1)
    stub = SimpleNamespace()
    stub.getMonthlyEnergyUsage = lambda hws_uuid: None
    sensor = _fake_monthly_sensor(this_month=this_month, emerald_hws=stub)
    # Force a rollover by making update_energy_value think a month passed.
    sensor._this_month = None

    EmeraldMonthlyEnergySensor.update_energy_value(sensor)

    assert sensor._attr_native_value == 0


def test_monthly_sensor_reports_unknown_on_same_period_failure():
    """Same month, no rollover, API returned nothing: a real failure -> None."""
    this_month = dt_util.now().date().replace(day=1)
    stub = SimpleNamespace()
    stub.getMonthlyEnergyUsage = lambda hws_uuid: None
    sensor = _fake_monthly_sensor(this_month=this_month, emerald_hws=stub)

    EmeraldMonthlyEnergySensor.update_energy_value(sensor)

    assert sensor._attr_native_value is None


def test_monthly_sensor_reports_actual_reading():
    """A normal same-period reading is rounded to 3 decimal places."""
    this_month = dt_util.now().date().replace(day=1)
    stub = SimpleNamespace()
    stub.getMonthlyEnergyUsage = lambda hws_uuid: 12.3456
    sensor = _fake_monthly_sensor(this_month=this_month, emerald_hws=stub)

    EmeraldMonthlyEnergySensor.update_energy_value(sensor)

    assert sensor._attr_native_value == 12.346  # rounded to 3 places


def _fake_weekly_sensor(emerald_hws):
    return SimpleNamespace(
        _emerald_hws=emerald_hws,
        _hws_uuid="uuid-1",
        _attr_name="Test Weekly Energy",
        _attr_native_value=None,
    )


def test_weekly_sensor_has_no_reset_semantics_just_a_reading():
    """Unlike daily/monthly, a fresh empty week is a real 0, not a rollover case."""
    stub = SimpleNamespace()
    stub.getWeeklyEnergyUsage = lambda hws_uuid: 0.0  # sum({}) case, still a value
    sensor = _fake_weekly_sensor(stub)

    EmeraldWeeklyEnergySensor.update_energy_value(sensor)

    assert sensor._attr_native_value == 0.0


def test_weekly_sensor_reports_unknown_only_when_hws_not_found():
    """The library's weekly getter only returns None when the HWS can't be found."""
    stub = SimpleNamespace()
    stub.getWeeklyEnergyUsage = lambda hws_uuid: None
    sensor = _fake_weekly_sensor(stub)

    EmeraldWeeklyEnergySensor.update_energy_value(sensor)

    assert sensor._attr_native_value is None
