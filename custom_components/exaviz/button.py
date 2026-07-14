"""PoE Button Platform for Exaviz Integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .base_entity import ExavizPoEBaseEntity
from .const import DOMAIN
from .coordinator import ExavizDataUpdateCoordinator
from .switch import ExavizPoEPortSwitch
from .utils import sudo_argv

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PoE button entities from a config entry."""
    coordinator: ExavizDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    
    entities = []
    if coordinator.data and "poe" in coordinator.data:
        poe_data = coordinator.data["poe"]
        
        for poe_set_name, poe_set_data in poe_data.items():
            if isinstance(poe_set_data, dict) and "ports" in poe_set_data:
                for port in poe_set_data["ports"]:
                    port_num = port.get("port", 0)
                    entities.append(
                        ExavizPoEPortResetButton(
                            coordinator,
                            poe_set_name,
                            port_num,
                            config_entry.entry_id
                        )
                    )
    
    async_add_entities(entities)


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
    def device_class(self) -> ButtonDeviceClass:
        """Return the device class."""
        return ButtonDeviceClass.RESTART

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.coordinator.data is not None

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
        return attrs

    async def async_press(self) -> None:
        """Press the button to reset the PoE port (power cycle).

        For onboard ports: sends reset-port to the ESP32 via /dev/pse which
        power-cycles the TPS23861 port, plus ip link down/up for the network.

        For add-on boards: writes to /proc/pse reset file (kernel driver).
        """
        _LOGGER.info(
            "Resetting (power cycling) PoE port %s:%d",
            self._poe_set, self._port_number,
        )
        try:
            port_data = self._get_port_data()
            is_onboard = (
                port_data.get("poe_system") == "onboard"
                if port_data
                else self._poe_set == "onboard"
            )
            if is_onboard:
                await self._reset_onboard_port()
            else:
                await self._reset_addon_port()

            await self.coordinator.async_request_refresh()

        except Exception as ex:
            _LOGGER.error(
                "Failed to reset PoE port %s:%d: %s",
                self._poe_set, self._port_number, ex,
            )

    async def _reset_onboard_port(self) -> None:
        """Power-cycle an onboard PoE port without rebooting the ESP32.

        disable-port → link down → settle → link up → enable-port.
        Bare chip 'reset' is forbidden (mass re-power of siblings).
        """
        interface = f"poe{self._port_number}"
        pse_num, pse_port = ExavizPoEPortSwitch._linux_port_to_esp32(
            self._port_number
        )

        await ExavizPoEPortSwitch._send_esp32_command(
            f"disable-port {pse_num} {pse_port}"
        )

        proc = await asyncio.create_subprocess_exec(
            *sudo_argv("ip", "link", "set", interface, "down"),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        _LOGGER.info("Port %s power cut for reset, waiting 3 seconds...", interface)
        await asyncio.sleep(3)

        proc = await asyncio.create_subprocess_exec(
            *sudo_argv("ip", "link", "set", interface, "up"),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        await ExavizPoEPortSwitch._send_esp32_command(
            f"enable-port {pse_num} {pse_port}"
        )

        _LOGGER.info("Successfully reset PoE port %s", interface)

    def _get_pse_id(self) -> str:
        """Look up the hardware PSE ID (e.g. 'pse0') from coordinator data."""
        poe_data = (self.coordinator.data or {}).get("poe", {})
        return poe_data.get(self._poe_set, {}).get("pse_id", self._poe_set)

    async def _reset_addon_port(self) -> None:
        """Reset an add-on board port via /proc/pse interface."""
        pse_id = self._get_pse_id()
        reset_file = f"/proc/{pse_id}/port{self._port_number}/reset"
        try:
            proc = await asyncio.create_subprocess_exec(
                *sudo_argv("tee", reset_file),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate(input=b"0\n")
            if proc.returncode != 0:
                _LOGGER.error("Failed to write to %s", reset_file)
                return

            _LOGGER.info(
                "Port %s:%d disabled for reset, waiting 3 seconds...",
                self._poe_set, self._port_number,
            )
            await asyncio.sleep(3)

            proc = await asyncio.create_subprocess_exec(
                *sudo_argv("tee", reset_file),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate(input=b"1\n")
            if proc.returncode != 0:
                _LOGGER.error("Failed to re-enable %s", reset_file)
                return

            _LOGGER.info(
                "Successfully reset PoE port %s:%d",
                self._poe_set, self._port_number,
            )
        except OSError as ex:
            _LOGGER.error(
                "Failed to reset add-on board port %s:%d: %s",
                self._poe_set, self._port_number, ex,
            )
