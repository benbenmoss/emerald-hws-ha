"""Constants for the Emerald Hot Water System integration."""

DOMAIN = "emeraldenergy"

# Configuration constants
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_CONNECTION_TIMEOUT = "connection_timeout"
CONF_HEALTH_CHECK = "health_check"
CONF_ENABLE_ENERGY_MONITORING = "enable_energy_monitoring"

# Default values
DEFAULT_CONNECTION_TIMEOUT = 720  # 12 hours in minutes
DEFAULT_HEALTH_CHECK = 60  # 1 hour in minutes
DEFAULT_ENABLE_ENERGY_MONITORING = True

# Process-wide, not per-entry: the awscrt straddle (see
# helpers.is_awscrt_straddle_error) is a property of this Home Assistant
# process's sys.modules, not of any one config entry. repairs.py provides the
# matching one-click "Restart Home Assistant" fix flow.
AWSCRT_STRADDLE_ISSUE_ID = "awscrt_version_straddle"
