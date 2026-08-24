# Emerald HWS

[![GitHub Release][releases-shield]][releases]
[![GitHub Activity][commits-shield]][commits]
[![License][license-shield]](LICENSE)

[![hacs][hacsbadge]][hacs]
![Project Maintenance][maintenance-shield]

_Integration with [emerald_hws_py](https://github.com/ross-w/emerald_hws_py)._

**This integration will set up the following platforms.**

| Platform       | Description                                                        |
| -------------- | ------------------------------------------------------------------ |
| `water_heater` | Creates a water heater control for all Emerald HWS on your account |
| `sensor`       | Creates daily, weekly, and monthly energy usage sensors for all Emerald HWS on your account (configurable) |

## Installation

1. Using the tool of choice open the directory (folder) for your HA configuration (where you find `configuration.yaml`).
1. If you do not have a `custom_components` directory (folder) there, you need to create it.
1. In the `custom_components` directory (folder) create a new folder called `emeraldenergy`.
1. Download _all_ the files from the `custom_components/emeraldenergy/` directory (folder) in this repository.
1. Place the files you downloaded in the new directory (folder) you created.
1. Restart Home Assistant
1. In the HA UI go to "Configuration" -> "Integrations" click "+" and search for "Emerald HWS"

## Configuration is done in the UI

The integration setup includes the following options:

- **Username**: Your Emerald HWS account username
- **Password**: Your Emerald HWS account password
- **Connection Timeout**: How long to maintain connection before reconnecting (default: 12 hours)
- **Health Check Interval**: Maximum time expected between data updates before considering the connection unhealthy (default: 1 hour)
- **Enable Energy Monitoring**: Create energy usage sensors (default: enabled)

Each Emerald account can only be added once — adding the same username again re-opens the existing entry instead of creating a duplicate connection.

**Changing these later:** Connection Timeout, Health Check Interval, and Enable Energy Monitoring can be changed at any time from the integration's **Configure** button, without removing and re-adding it (this reloads the integration to apply the new values). If Emerald rejects the stored password (e.g. after you change it in the Emerald app), Home Assistant prompts for reauthentication automatically — look for a "reconfigure" notification on the integration, or **Settings → Devices & Services**.

### Energy Monitoring

When enabled, the integration creates three sensors per hot water system:

| Sensor  | Behavior |
| ------- | -------- |
| Daily   | Cumulative kWh for the current day; resets to 0 at local midnight. Appears on the Home Assistant Energy dashboard. |
| Weekly  | A rolling 7-day total (today plus the previous 6 days) — not a period that resets on a boundary, so it does **not** appear on the Energy dashboard; use it for at-a-glance trend, not long-term statistics. |
| Monthly | Cumulative kWh for the current calendar month; resets to 0 at the start of each month. Appears on the Energy dashboard. |

Please note Emerald only provides hourly energy data, and a sensor may briefly read 0 right after its reset boundary if the device hasn't pushed a reading for the new period yet.

## Mapping of Emerald terms to Home Assistant

To keep things consistent, the following mappings have been used between the Emerald terminology and Home Assistant's

| Emerald | HASS        |
| ------- | ----------- |
| Normal  | Heat Pump   |
| Boost   | Performance |
| Quiet   | Eco         |

## Usage in Automations

This integration provides several attributes that can be used in automations and templates. Here are some examples:

Replace `<serial>` with your water heater's serial number.

To read the current water temperature:
```yaml
{{ state_attr("water_heater.emerald_<serial>", "current_temperature") }}
```

To determine if the water heater is actively heating (not just turned on):
```yaml
{{ state_attr('water_heater.emerald_<serial>', "is_heating") }}
```

To read a derived estimate of remaining hot-water tank capacity as a percentage (clamped to 0–100). This is a local calculation from the current and target temperatures — the API does not return it directly, so treat it as indicative only:
```yaml
{{ state_attr('water_heater.emerald_<serial>', "tank_capacity_percent") }}
```

The same value rounded to the nearest 20%, matching the capacity figure shown in the official Emerald app:
```yaml
{{ state_attr('water_heater.emerald_<serial>', "tank_capacity_percent_rounded") }}
```

## Troubleshooting

### Login Issues
If you're unable to log in, verify your credentials using the Emerald mobile app or web portal first.

### No Data Appearing
If the integration connects but no water heater entities appear, check that your Emerald account has active devices and that you have the correct permissions.

### Integration Not Found
If you can't find "Emerald HWS" in the integrations list after installing via HACS, try restarting Home Assistant again.

### Error: "Timed out sending '...' to the Emerald hot water system"
Control commands are sent over MQTT and block until the Emerald cloud acknowledges them. This error means that acknowledgement never arrived within 20 seconds, so the command was **not** applied — the unit will not have changed state. It usually indicates the connection to the Emerald cloud has dropped, even though Home Assistant still holds an apparently open session.

- If it happens occasionally, the automation or script that triggered it can simply be retried.
- If it happens regularly, lower **Health Check Interval** (and, if needed, **Connection Timeout**) in the integration options — see [Configuration](#configuration-is-done-in-the-ui). A shorter health check makes the integration notice and rebuild a stale connection sooner.
- Reloading the integration forces an immediate reconnect.

### Errors mentioning `awscrt` during setup
Setup failures reporting either of:

- `function takes exactly 43 arguments (45 given)`
- `'ClientTlsContext' object has no attribute '_certificate_source'`

both mean the same thing: two different versions of `awscrt` are loaded at once. `awscrt` is a compiled extension whose Python files and native library have to match, and it is upgraded automatically whenever `awsiotsdk` moves.

Home Assistant loads `awscrt` long before this integration starts. `cloud` is set up in the first bootstrap stage, and it reaches `awscrt` through `hass_nabucasa` → `boto3`/`botocore`, whose compatibility module imports it unconditionally. If Home Assistant then upgrades `awscrt` on disk while installing this integration's requirements, everything imported afterwards comes from the new version while the modules already loaded stay on the old one, and the two halves meet when the integration connects.

When this happens, Home Assistant also raises a **Repair** (Settings → System → Repairs) with a one-click "Restart Home Assistant" fix — you don't need to dig through the logs to find this section unless you want the background.

- **Restart Home Assistant** (via the Repair card, or manually). That is the fix, and it is permanent — the next process loads one consistent copy from disk. Reloading the integration will not help: the mismatched modules are cached for the lifetime of the process, which is why setup keeps failing identically until a restart.
- Since `emerald_hws` 0.0.30 the integration no longer uses the `awscrt` code path responsible for the `_certificate_source` error, so that variant should not recur.
- If it survives a restart, the copy on disk is itself mixed. Force a clean reinstall, then restart Home Assistant: `pip install --force-reinstall --no-cache-dir awscrt` (run it where HA's Python lives: the SSH/Terminal add-on, `docker exec` into the container, or your activated venv). Depending on your install method, recreating the Docker container or updating HAOS achieves the same thing.

### Filing a bug report

From the integration's page (**Settings → Devices & Services → Emerald HWS**), the three-dot menu on the entry offers **Download diagnostics** — a redacted JSON dump (no username, password, or serial number) of the connection state and each hot water system's status, mode, and energy history. Attaching it to a bug report saves a lot of back-and-forth.

<!---->

## Contributions are welcome

If you want to contribute to this please read the [Contribution guidelines](CONTRIBUTING.md)

---

[license-shield]: https://img.shields.io/github/license/ross-w/emerald-hws-ha
[commits-shield]: https://img.shields.io/github/commit-activity/y/ross-w/emerald-hws-ha.svg?style=for-the-badge
[commits]: https://github.com/ross-w/emerald-hws-ha/commits/main
[hacs]: https://github.com/hacs/integration
[hacsbadge]: https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge
[forum]: https://community.home-assistant.io/
[releases-shield]: https://img.shields.io/github/release/ross-w/emerald-hws-ha.svg?style=for-the-badge
[releases]: https://github.com/ross-w/emerald-hws-ha/releases
[maintenance-shield]: https://img.shields.io/maintenance/yes/2026
