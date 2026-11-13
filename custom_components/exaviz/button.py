"""PoE Button Platform for Exaviz Integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import ExavizPoEBaseEntity, async_setup_port_entities
from .coordinator import ExavizDataUpdateCoordinator
from .switch import ExavizPoEPortSwitch

_LOGGER = logging.getLogger(__name__)

# One port action at a time, so two cannot race on the board.
PARALLEL_UPDATES = 1

# How long a reset keeps the port's power off.
RESET_POWER_OFF_SECONDS = 3

# How long Home Assistant's stop, or an unload of the entry, waits for a
# running reset, and then for a stuck one to turn the port back on once
# cancelled. A healthy reset takes the power-off wait plus a few serial
# writes (each capped at 7 s); a hung `ip link` holds the stop for at most
# twice this, inside Home Assistant's 100 s.
RESET_STOP_WAIT_SECONDS = 30


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PoE button entities from a config entry."""
    coordinator: ExavizDataUpdateCoordinator = config_entry.runtime_data
    async_setup_port_entities(
        coordinator,
        config_entry,
        async_add_entities,
        lambda poe_set, port: [
            ExavizPoEPortResetButton(coordinator, poe_set, port, config_entry.entry_id)
        ],
    )


class ExavizPoEPortResetButton(ExavizPoEBaseEntity, ButtonEntity):
    """Button for resetting a PoE port."""

    def __init__(
        self,
        coordinator: ExavizDataUpdateCoordinator,
        poe_set: str,
        port_number: int,
        entry_id: str,
    ) -> None:
        """Initialize the PoE port reset button."""
        super().__init__(
            coordinator=coordinator,
            poe_set=poe_set,
            port_number=port_number,
            entry_id=entry_id,
            entity_type="button",
            entity_suffix="reset",
            entity_name_suffix="Reset",
        )
        self._cycles: set[asyncio.Task] = set()
        # The stop and an unload can both wait; only one cancels.
        self._finishing = asyncio.Lock()

    async def async_added_to_hass(self) -> None:
        """Hold Home Assistant's stop until a running reset is finished."""
        await super().async_added_to_hass()
        # Removed at the end of async_will_remove_from_hass, not with
        # async_on_remove: a stop during an unload must still wait.
        self._unsub_stop = self.hass.bus.async_listen(
            EVENT_HOMEASSISTANT_STOP, self._async_finish_cycle
        )

    async def _async_finish_cycle(self, _event: Event) -> None:
        """Hold the stop for running power cycles.

        Home Assistant waits for this listener while it stops, but not for
        a task that was already running when the stop began.
        """
        await self._async_finish_cycles()

    async def async_will_remove_from_hass(self) -> None:
        """Hold the entry's unload for running power cycles.

        Unload waits 10 s for the entry's tasks and then leaves them
        running, so a cycle stuck in `ip link` would keep the port off.
        """
        try:
            await self._async_finish_cycles()
        finally:
            self._unsub_stop()
        await super().async_will_remove_from_hass()

    async def _async_finish_cycles(self) -> None:
        """Wait for running power cycles, so the port is not left off.

        There can be more than one: a cancelled press frees the button for
        another. A cycle still running after the wait is cancelled here,
        while the caller still waits, so its cancel path has time to turn
        the port back on.
        """
        async with self._finishing:
            if not self._cycles:
                return
            _, stuck = await asyncio.wait(self._cycles, timeout=RESET_STOP_WAIT_SECONDS)
            if stuck:
                _LOGGER.warning(
                    "Reset of PoE port %s:%d is stuck; cancelling it to turn the port back on",
                    self._poe_set, self._port_number,
                )
                for cycle in stuck:
                    cycle.cancel()
                await asyncio.wait(stuck, timeout=RESET_STOP_WAIT_SECONDS)

    @property
    def available(self) -> bool:
        """Unavailable on a read-only remote pairing and on add-on boards.

        Add-on boards are unavailable for the same reason as their switches:
        the kernel driver has no /proc/pse write interface.
        """
        if self._poe_set.startswith("addon_") or not self.coordinator.can_control:
            return False
        return super().available

    @property
    def device_class(self) -> ButtonDeviceClass:
        """Return the device class."""
        return ButtonDeviceClass.RESTART

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes."""
        port_data = self._get_port_data()
        if not port_data:
            return None

        connected_device = port_data.get("connected_device")
        attrs: dict[str, Any] = {
            "port_number": self._port_number,
            "poe_set": self._poe_set,
            "status": port_data.get("status", "unknown"),
        }
        if connected_device:
            attrs["device_name"] = connected_device.get("name")
            attrs["device_type"] = connected_device.get("device_type")
        if self._poe_set.startswith("addon_"):
            attrs["control_note"] = (
                "Reset not supported "
                "(kernel driver lacks /proc/pse write interface)"
            )
            attrs["control_available"] = False
        return attrs

    async def async_press(self) -> None:
        """Press the button to reset the PoE port (power cycle).

        Onboard ports: power-cycles the TPS23861 port through the ESP32
        on /dev/pse, plus ip link down/up for the network. Add-on board ports
        are unavailable (see `available`).
        """
        _LOGGER.info(
            "Resetting (power cycling) PoE port %s:%d",
            self._poe_set, self._port_number,
        )
        if self.coordinator.remote is not None:
            # The board runs the whole power cycle itself.
            await self.coordinator.async_port_action(self._port_number, "reset")
            return
        if self._poe_set.startswith("addon_"):
            raise HomeAssistantError(
                f"Reset is not supported on add-on board port {self._poe_set}:{self._port_number}"
            )
        try:
            await self._reset_onboard_port()
        except HomeAssistantError:
            raise
        except Exception as ex:
            # Raise so the UI and automations see the failure.
            raise HomeAssistantError(
                f"Could not reset PoE port {self._poe_set}:{self._port_number}: {ex}"
            ) from ex
        finally:
            await self.coordinator.async_request_refresh()

    async def _reset_onboard_port(self) -> None:
        """Power-cycle an onboard PoE port without rebooting the ESP32.

        Shielded, so a cancelled press (a restarted script, shutdown) still
        finishes the cycle, including the step that turns power back on. Nobody
        awaits a cancelled press, so the cycle then logs its own failure and
        refreshes the state once it is done.
        """
        # A config entry task: unloading the entry waits for it.
        cycle = self.coordinator.config_entry.async_create_task(
            self.hass,
            self._power_cycle_onboard_port(),
            f"reset PoE port {self._poe_set}:{self._port_number}",
        )
        self._cycles.add(cycle)
        cycle.add_done_callback(self._cycles.discard)
        try:
            await asyncio.shield(cycle)
        except asyncio.CancelledError:
            cycle.add_done_callback(self._after_cancelled_cycle)
            raise

    def _after_cancelled_cycle(self, cycle: asyncio.Future) -> None:
        """Report the outcome of a power cycle whose press was cancelled."""
        if not cycle.cancelled() and (err := cycle.exception()) is not None:
            _LOGGER.error(
                "Reset of PoE port %s:%d (press cancelled) failed: %s",
                self._poe_set, self._port_number, err,
            )
        self.hass.async_create_task(self.coordinator.async_request_refresh())

    async def _send_enable_port(self, pse_num: int, pse_port: int) -> bool:
        """Send enable-port; if shutdown cancels the write, send it once more.

        The write is killed when its caller is cancelled, and the runner
        cancels only once, so the second write goes through. A second write
        that will not stop is logged and the cancel stays the outcome.
        """
        command = f"enable-port {pse_num} {pse_port}"
        try:
            sent = await ExavizPoEPortSwitch._send_esp32_command(command)
        except asyncio.CancelledError:
            try:
                resent = await ExavizPoEPortSwitch._send_esp32_command(command)
            except HomeAssistantError as err:
                _LOGGER.error(
                    "Could not turn port poe%d back on: %s", self._port_number, err
                )
            else:
                if not resent:
                    _LOGGER.error(
                        "Could not turn port poe%d back on: the write failed",
                        self._port_number,
                    )
            raise
        if not sent:
            _LOGGER.error(
                "Could not turn port poe%d back on: the write failed",
                self._port_number,
            )
        return sent

    async def _power_cycle_onboard_port(self) -> None:
        """disable-port → link down → settle → link up → enable-port.

        Bare chip 'reset' is forbidden (mass re-power of siblings). Once
        disable-port has returned, enable-port is always sent. A disable-port
        write that cannot be stopped raises at once and nothing follows it,
        since it may still land. Raises HomeAssistantError when the port does
        not end up powered with its link up.
        """
        interface = f"poe{self._port_number}"
        pse_num, pse_port = ExavizPoEPortSwitch._linux_port_to_esp32(
            self._port_number
        )

        try:
            disabled = await ExavizPoEPortSwitch._send_esp32_command(
                f"disable-port {pse_num} {pse_port}"
            )
        except asyncio.CancelledError:
            # Shutdown cancelled the cycle itself with the write in flight. The
            # write is stopped by now but may have landed, so turn the port
            # back on before stopping. (A write that will not stop raises
            # HomeAssistantError instead, and nothing follows it.)
            await self._send_enable_port(pse_num, pse_port)
            raise
        if not disabled:
            # A timed-out write may still have landed, so turn the port back
            # on to be sure; on a port that stayed on this changes nothing.
            await self._send_enable_port(pse_num, pse_port)
            raise HomeAssistantError(
                f"The PoE controller did not disable port {interface}"
            )

        link_up = False
        restored: bool | None = None
        try:
            await ExavizPoEPortSwitch._run_ip_link(interface, "down")
            _LOGGER.info(
                "Port %s power cut for reset, waiting %d seconds...",
                interface, RESET_POWER_OFF_SECONDS,
            )
            await asyncio.sleep(RESET_POWER_OFF_SECONDS)
            link_up = await ExavizPoEPortSwitch._run_ip_link(interface, "up")
        except asyncio.CancelledError:
            # Shutdown cancelled the wait. Power first, so a stuck `ip link`
            # cannot keep the port off; then leave the link up too (the
            # switch reads a downed link as "off").
            # Set first: a restore write that will not stop raises, and
            # nothing may follow it, not even the restore in `finally`.
            restored = False
            restored = await self._send_enable_port(pse_num, pse_port)
            await ExavizPoEPortSwitch._run_ip_link(interface, "up")
            raise
        finally:
            if restored is None:
                restored = await self._send_enable_port(pse_num, pse_port)
        if not restored:
            raise HomeAssistantError(
                f"The PoE controller did not turn port {interface} back on after the reset"
            )
        if not link_up:
            raise HomeAssistantError(
                f"Port {interface} was power-cycled, but its network link did not come back up"
            )

        _LOGGER.info("Successfully reset PoE port %s", interface)
