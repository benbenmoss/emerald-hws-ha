"""Tests for the diagnostics redaction/allowlist logic."""

from homeassistant.components.diagnostics import async_redact_data

from custom_components.emeraldenergy.diagnostics import TO_REDACT, _status_summary


def test_redact_data_strips_every_sensitive_key():
    """Every key in TO_REDACT is stripped, everything else passes through."""
    payload = {
        "entry_data": {
            "username": "someone@example.com",
            "password": "hunter2",
            "connection_timeout": 720,
        },
        "hot_water_systems": [{"info": {"serial_number": "SN12345", "brand": "Emerald"}}],
    }
    redacted = async_redact_data(payload, TO_REDACT)

    assert redacted["entry_data"]["password"] != "hunter2"
    assert redacted["entry_data"]["username"] != "someone@example.com"
    assert redacted["hot_water_systems"][0]["info"]["serial_number"] != "SN12345"
    # Fields not in TO_REDACT pass through untouched.
    assert redacted["entry_data"]["connection_timeout"] == 720
    assert redacted["hot_water_systems"][0]["info"]["brand"] == "Emerald"


def test_status_summary_drops_location_and_network_fields():
    """Regression: latitude/longitude/wifi_name/installer/customer IDs never leak."""
    # A shape modelled on the real API payload (confirmed against a live
    # account): far more fields than we want in a file that gets pasted into
    # public GitHub issues, including precise location and the home WiFi SSID.
    full_status = {
        "device_operation_status": 1,
        "is_online": True,
        "model": "EAHP-270",
        "latitude": -33.8688,
        "longitude": 151.2093,
        "wifi_name": "MyHomeNetwork",
        "agency_name": "Some Installer Pty Ltd",
        "customer_id": "cust-123",
        "mac_address": "AA:BB:CC:DD:EE:FF",
    }
    summary = _status_summary(full_status)

    assert "latitude" not in summary
    assert "longitude" not in summary
    assert "wifi_name" not in summary
    assert "agency_name" not in summary
    assert "customer_id" not in summary
    assert "mac_address" not in summary
    # Allowlisted fields still come through.
    assert summary["device_operation_status"] == 1
    assert summary["is_online"] is True
    assert summary["model"] == "EAHP-270"


def test_status_summary_handles_missing_status():
    """No status yet (None) or an empty payload both degrade to an empty dict."""
    assert _status_summary(None) == {}
    assert _status_summary({}) == {}
