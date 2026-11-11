"""PoE Button Platform for Exaviz Integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import ExavizPoEBaseEntity, async_setup_port_entities
from .coordinator import ExavizDataUpdateCoordinator
from .switch import ExavizPoEPortSwitch

_LOGGER = logging.getLogger(__name__)

# One port action at a time, so two cannot race on the board.
PARALLEL_UPDATES = 1


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
        finishes the cycle and never leaves the port without power.
        """
        await asyncio.shield(self._power_cycle_onboard_port())

    async def _power_cycle_onboard_port(self) -> None:
        """disable-port → link down → settle → link up → enable-port.

        Bare chip 'reset' is forbidden (mass re-power of siblings). Once
        power is cut, enable-port is always sent. Raises HomeAssistantError
        when the port does not end up powered with its link up.
        """
        interface = f"poe{self._port_number}"
        pse_num, pse_port = ExavizPoEPortSwitch._linux_port_to_esp32(
            self._port_number
        )

        if not await ExavizPoEPortSwitch._send_esp32_command(
            f"disable-port {pse_num} {pse_port}"
        ):
            raise HomeAssistantError(
                f"The PoE controller did not disable port {interface}"
            )

        link_up = False
        try:
            await ExavizPoEPortSwitch._run_ip_link(interface, "down")
            _LOGGER.info("Port %s power cut for reset, waiting 3 seconds...", interface)
            await asyncio.sleep(3)
            link_up = await ExavizPoEPortSwitch._run_ip_link(interface, "up")
        finally:
            restored = await ExavizPoEPortSwitch._send_esp32_command(
                f"enable-port {pse_num} {pse_port}"
            )
        if not restored:
            raise HomeAssistantError(
                f"The PoE controller did not turn port {interface} back on after the reset"
            )
        if not link_up:
            raise HomeAssistantError(
                f"Port {interface} was power-cycled, but its network link did not come back up"
            )

        _LOGGER.info("Successfully reset PoE port %s", interface)
