"""Tests for the pure water_heater logic: mode mapping and tank-capacity math."""

from types import SimpleNamespace

from homeassistant.components.water_heater import (
    STATE_ECO,
    STATE_HEAT_PUMP,
    STATE_PERFORMANCE,
)

from custom_components.emeraldenergy.water_heater import (
    EmeraldWaterHeater,
    tank_capacity_percent,
)


def _mode_to_op_state(mode):
    # modeToOpState only reads self._name (for its unknown-mode log line), so a
    # bare namespace stands in for a real entity.
    return EmeraldWaterHeater.modeToOpState(SimpleNamespace(_name="test"), mode)


def test_mode_to_op_state_known_modes():
    """The three documented mode ints map to their HASS states."""
    assert _mode_to_op_state(1) == STATE_HEAT_PUMP
    assert _mode_to_op_state(0) == STATE_PERFORMANCE
    assert _mode_to_op_state(2) == STATE_ECO


def test_mode_to_op_state_unknown_mode_returns_none():
    """Unrecognised mode -> None, so HA reports the state as unknown rather
    than a guessed operation the unit may not actually be in."""
    assert _mode_to_op_state(99) is None
    assert _mode_to_op_state(None) is None


def test_tank_capacity_percent_at_target():
    """At target temperature the tank reads full."""
    percent, rounded = tank_capacity_percent(current=50, target=50)
    assert percent == 100
    assert rounded == 100


def test_tank_capacity_percent_below_target():
    """10 degrees below target: 100 - 2.3*10 = 77, snapped to 80."""
    percent, rounded = tank_capacity_percent(current=40, target=50)
    assert percent == 77
    assert rounded == 80


def test_tank_capacity_percent_clamps_to_bounds():
    """Far below/above target clamps to 0/100 rather than going out of range."""
    percent, rounded = tank_capacity_percent(current=0, target=100)
    assert percent == 0
    assert rounded == 0

    percent, rounded = tank_capacity_percent(current=100, target=0)
    assert percent == 100
    assert rounded == 100
