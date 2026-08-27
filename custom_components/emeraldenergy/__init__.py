"""The Emerald Hot Water System integration."""

from __future__ import annotations

import logging
import threading
from collections.abc import Mapping
from typing import Any

from emerald_hws.emeraldhws import EmeraldHWS
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady

from .const import DOMAIN
from .helpers import create_hws, is_awscrt_straddle_error

_LOGGER = logging.getLogger(__name__)

# TODO List the platforms that you want to support.
# For your initial PR, limit it to 1 platform.
PLATFORMS: list[Platform] = [Platform.WATER_HEATER, Platform.SENSOR]


class CallbackDispatcher:
    """Dispatcher to handle multiple callbacks for the same Emerald HWS instance."""

    def __init__(self):
        """Initialize the callback dispatcher."""
        self._callbacks = []
        # Guards _callbacks: register/unregister run on the event-loop thread,
        # dispatch() runs on the emerald_hws MQTT thread. Without this, list
        # mutation and the dispatch snapshot below race.
        self._lock = threading.Lock()

    def register_callback(self, callback):
        """Register a callback function."""
        with self._lock:
            if callback in self._callbacks:
                return
            self._callbacks.append(callback)
            count = len(self._callbacks)
        _LOGGER.debug(f"Registered callback. Total callbacks: {count}")

    def unregister_callback(self, callback):
        """Unregister a callback function."""
        with self._lock:
            if callback not in self._callbacks:
                return
            self._callbacks.remove(callback)
            count = len(self._callbacks)
        _LOGGER.debug(f"Unregistered callback. Total callbacks: {count}")

    def dispatch(self):
        """Dispatch the callback to all registered listeners."""
        # Snapshot under the lock so this can't race register/unregister. A
        # callback unregistered right after the snapshot is taken still fires
        # once more -- holding the lock across the callback() calls below would
        # close that too, but callback() runs into entity code that can call
        # back into hass, so holding a lock across it risks deadlocking with
        # the event loop thread. That residual window is accepted, not fixed.
        with self._lock:
            callbacks = list(self._callbacks)
        _LOGGER.debug(f"Dispatching callback to {len(callbacks)} listeners")
        for callback in callbacks:
            try:
                callback()
            except Exception:
                _LOGGER.exception("Error in callback %r", callback)

    def __call__(self):
        """Make the dispatcher callable."""
        self.dispatch()


def _create_and_connect(config: Mapping[str, Any]) -> EmeraldHWS:
    """Build an EmeraldHWS client and open its connection.

    Blocking, and both halves reach into awsiotsdk/awscrt, so they run as a single
    executor job rather than two.
    """
    instance = create_hws(config)
    instance.connect()
    return instance


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Emerald Hot Water System from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Create and store the EmeraldHWS instance for shared access
    try:
        emerald_hws_instance = await hass.async_add_executor_job(
            _create_and_connect, entry.data
        )
    except Exception as err:
        # emerald_hws raises bare Exceptions, and its awsiotsdk/awscrt stack can fail
        # in ways only the traceback identifies, so log the full trace rather than
        # just the message.
        _LOGGER.exception("Failed to create Emerald HWS API instance")
        if is_awscrt_straddle_error(err):
            # Unrecoverable until Home Assistant restarts, so fail permanently
            # with the remedy rather than looping. See is_awscrt_straddle_error.
            raise ConfigEntryError(
                "The installed awscrt package is a mix of two versions, so the "
                "connection to the Emerald cloud cannot be established in this "
                "Home Assistant process. Restart Home Assistant to clear it. See "
                "the integration README section 'Errors mentioning awscrt during "
                f"setup' if it persists. Underlying error: {err}"
            ) from err
        # Anything else is assumed transient, so let HA retry with backoff.
        raise ConfigEntryNotReady(
            f"Failed to connect to the Emerald cloud: {err}"
        ) from err

    # Past this point the instance holds a live MQTT connection with its own threads
    # and timers, so anything that fails has to hand it back before HA retries setup.
    try:
        # Create and store callback dispatcher for this instance
        callback_dispatcher = CallbackDispatcher()
        emerald_hws_instance.replaceCallback(callback_dispatcher)

        # Store both the instance and dispatcher for platforms to access
        hass.data[DOMAIN][entry.entry_id] = {
            "instance": emerald_hws_instance,
            "dispatcher": callback_dispatcher,
        }
        _LOGGER.info(
            "Emerald HWS API instance and callback dispatcher created and stored"
        )

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        # BaseException, not Exception: HA cancels in-flight setup tasks on shutdown
        # and when a reload races setup, and CancelledError would otherwise skip the
        # disconnect below and strand the MQTT threads. Nothing is swallowed -- the
        # bare raise at the end re-raises whatever arrived, cancellation included.
        _LOGGER.warning(
            "Emerald HWS setup did not complete after the connection was "
            "established; disconnecting so nothing is left holding MQTT threads"
        )
        # Nothing in this block may raise: hass.data[DOMAIN] is set up above, but a
        # subscript here would mask the real failure if that ever stopped holding.
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        try:
            # The executor job is submitted as soon as this is called, so disconnect
            # still runs on its thread even if cancellation interrupts the await.
            await hass.async_add_executor_job(emerald_hws_instance.disconnect)
        except Exception:
            # Cleanup must never replace the failure that triggered it, so this is
            # logged and swallowed; the bare raise below re-raises the real cause.
            _LOGGER.exception(
                "Failed to disconnect the Emerald HWS instance during cleanup"
            )
        raise

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        # Clean up stored EmeraldHWS instance and stop MQTT/timers
        entry_data = hass.data[DOMAIN].pop(entry.entry_id, None)
        if entry_data:
            instance = entry_data["instance"]
            await hass.async_add_executor_job(instance.disconnect)

    return unload_ok
