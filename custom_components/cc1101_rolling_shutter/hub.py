"""Coordination between the firmware and Home Assistant.

One hub per config entry, i.e. per CC1101 module. It owns the serial port,
turns the firmware's JSON lines into Home Assistant events, correlates the
commands it sends with the firmware's acknowledgements, and keeps track of the
shutters heard on the air but not configured yet.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BAUDRATE,
    CONF_PORT,
    CONF_SHUTTERS,
    COUNTER_SOURCE_AIR,
    COUNTER_SOURCE_SENT,
    EVENT_ERROR,
    EVENT_RX,
    EVENT_TX,
    SERIAL_TIMEOUT,
    SIGNAL_DISCOVERY,
    SIGNAL_SHUTTER_EVENT,
    cover_key,
    is_shutter_id,
    normalise_shutter_id,
)
from .serial_controller import SerialController

_LOGGER = logging.getLogger(__name__)


@dataclass
class DiscoveredShutter:
    """A shutter heard on the air that is not configured yet."""

    shutter_id: str
    last_command: str | None = None
    last_seen: Any = None
    rssi: int | None = None


@dataclass
class ShutterTelemetry:
    """What the firmware last reported about one shutter.

    Kept on the hub rather than on the entities so it survives a platform
    reload, and so the counter is tracked even for a shutter whose diagnostic
    sensors are disabled.
    """

    # Rolling counter, 0-255. Bumped by our own transmissions and resynchronised
    # from every frame heard on the air, exactly like the firmware's own table.
    counter: int | None = None
    counter_source: str | None = None
    # RSSI only ever comes from the air: our own "tx" events carry no signal.
    rssi: int | None = None
    last_command: str | None = None
    last_seen: Any = None


class CC1101Hub:
    """Drive one CC1101 module and fan its events out to the entities."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.discovered: dict[str, DiscoveredShutter] = {}
        self.telemetry: dict[str, ShutterTelemetry] = {}
        self._controller = SerialController(
            port=entry.data[CONF_PORT],
            baudrate=entry.data[CONF_BAUDRATE],
            on_event=self._on_event_threadsafe,
        )
        # Serialises transmissions: the firmware handles one burst at a time,
        # and its "tx" acknowledgement is what tells us the burst is over.
        self._lock = asyncio.Lock()
        # At most one command is in flight thanks to the lock above, so a
        # single slot is enough to correlate the acknowledgement.
        self._pending: asyncio.Future[None] | None = None
        self._pending_id: str | None = None

    # -- lifecycle ---------------------------------------------------------
    async def async_start(self) -> None:
        """Open the port and start listening."""
        await self.hass.async_add_executor_job(self._controller.start)

    async def async_stop(self) -> None:
        """Stop listening and close the port."""
        await self.hass.async_add_executor_job(self._controller.stop)

    # -- sending -----------------------------------------------------------
    async def async_send(self, shutter_id: str, action: str) -> None:
        """Send a command and wait for the firmware to confirm it.

        The firmware prints its ``tx`` event once the whole burst has been
        transmitted, so awaiting it both reports failures and keeps the next
        command from overlapping on the air.
        """
        async with self._lock:
            future: asyncio.Future[None] = self.hass.loop.create_future()
            self._pending = future
            self._pending_id = shutter_id
            try:
                await self.hass.async_add_executor_job(
                    self._controller.send_command, shutter_id, action
                )
                async with asyncio.timeout(SERIAL_TIMEOUT):
                    await future
            except TimeoutError as err:
                raise HomeAssistantError(
                    f"Timed out waiting for the module to confirm {action!r} "
                    f"on shutter {shutter_id}"
                ) from err
            except HomeAssistantError:
                raise
            except Exception as err:  # noqa: BLE001 - surfaced as a HA error
                raise HomeAssistantError(
                    f"Serial link failure for shutter {shutter_id}: {err}"
                ) from err
            finally:
                self._pending = None
                self._pending_id = None

    # -- receiving ---------------------------------------------------------
    def _on_event_threadsafe(self, event: dict[str, Any]) -> None:
        """Hop from the reader thread onto the event loop."""
        self.hass.loop.call_soon_threadsafe(self._handle_event, event)

    @callback
    def _handle_event(self, event: dict[str, Any]) -> None:
        """Handle one firmware event, on the event loop."""
        kind = event.get("event")
        if kind == EVENT_TX:
            self._handle_tx(event)
        elif kind == EVENT_RX:
            self._handle_rx(event)
        elif kind == EVENT_ERROR:
            self._handle_error(event)
        else:
            # ready / status / raw are informational.
            _LOGGER.debug("Firmware event: %s", event)

    @callback
    def _handle_tx(self, event: dict[str, Any]) -> None:
        """The firmware finished transmitting a burst."""
        _LOGGER.debug("Firmware confirmed: %s", event)
        if self._pending is not None and not self._pending.done():
            self._pending.set_result(None)

        # Our own transmission advanced this shutter's counter.
        shutter_id = self._event_shutter_id(event)
        if shutter_id is None:
            return
        telemetry = self.telemetry_for(shutter_id)
        counter = event.get("counter")
        if isinstance(counter, int):
            telemetry.counter = counter
            telemetry.counter_source = COUNTER_SOURCE_SENT
        self._notify(shutter_id, event)

    @callback
    def _handle_error(self, event: dict[str, Any]) -> None:
        """The firmware rejected the command."""
        reason = event.get("reason", "unknown error")
        detail = event.get("input", "")
        _LOGGER.error("Firmware rejected %r: %s", detail, reason)
        if self._pending is not None and not self._pending.done():
            self._pending.set_exception(
                HomeAssistantError(
                    f"The module rejected the command for shutter "
                    f"{self._pending_id}: {reason}"
                )
            )

    @callback
    def _handle_rx(self, event: dict[str, Any]) -> None:
        """A frame was heard on the air, from one of the original remotes."""
        shutter_id = self._event_shutter_id(event)
        if shutter_id is None:
            _LOGGER.debug("Ignoring rx event without a usable id: %s", event)
            return
        command = event.get("command") or event.get("cmd")

        if shutter_id in self._configured_ids():
            telemetry = self.telemetry_for(shutter_id)
            counter = event.get("counter")
            if isinstance(counter, int):
                telemetry.counter = counter
                telemetry.counter_source = COUNTER_SOURCE_AIR
            rssi = event.get("rssi")
            if isinstance(rssi, int):
                telemetry.rssi = rssi
            telemetry.last_command = command
            telemetry.last_seen = dt_util.utcnow()
            self._notify(shutter_id, event)
            return

        # Not configured: remember it so the options flow can offer it.
        known = shutter_id in self.discovered
        self.discovered[shutter_id] = DiscoveredShutter(
            shutter_id=shutter_id,
            last_command=command,
            last_seen=dt_util.utcnow(),
            rssi=event.get("rssi"),
        )
        if not known:
            _LOGGER.info(
                "Discovered shutter %s (heard %r). Add it from the integration "
                "options.",
                shutter_id,
                command,
            )
        async_dispatcher_send(
            self.hass, SIGNAL_DISCOVERY.format(self.entry.entry_id)
        )

    # -- helpers -----------------------------------------------------------
    @callback
    def _notify(self, shutter_id: str, event: dict[str, Any]) -> None:
        """Tell this shutter's entities that the firmware said something."""
        async_dispatcher_send(
            self.hass,
            SIGNAL_SHUTTER_EVENT.format(self.entry.entry_id, shutter_id),
            event,
        )

    @staticmethod
    def _event_shutter_id(event: dict[str, Any]) -> str | None:
        """Canonical shutter ID carried by an event, if it has a usable one."""
        raw_id = event.get("id")
        if not raw_id or not is_shutter_id(raw_id):
            return None
        return normalise_shutter_id(raw_id)

    def telemetry_for(self, shutter_id: str) -> ShutterTelemetry:
        """Telemetry for a shutter, created on first use."""
        return self.telemetry.setdefault(shutter_id, ShutterTelemetry())

    def _configured_ids(self) -> set[str]:
        """IDs currently declared in the options."""
        return {
            cover_key(shutter)
            for shutter in self.entry.options.get(CONF_SHUTTERS, [])
        }

    def available_discoveries(self) -> list[DiscoveredShutter]:
        """Discovered shutters that are not configured yet, newest first."""
        configured = self._configured_ids()
        pending = [
            shutter
            for shutter_id, shutter in self.discovered.items()
            if shutter_id not in configured
        ]
        return sorted(pending, key=lambda s: s.last_seen or 0, reverse=True)
