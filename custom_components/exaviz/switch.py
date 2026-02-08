"""PoE Switch Platform for Exaviz Integration."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .base_entity import ExavizPoEBaseEntity
from .const import DOMAIN
from .coordinator import ExavizDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ESP32 serial command interface (/dev/pse)
#
# The ESP32 firmware exposes a UART command interface for PoE port control.
# Commands are written as text lines to /dev/pse (symlink to /dev/ttyAMA3).
# Available commands: disable-port, enable-port, reset-port, reset
#
# Port mapping (Linux poeX → ESP32 PSE/port):
#   Linux poe0-3 → PSE 1, ports 0-3  (left side of Cruiser board)
#   Linux poe4-7 → PSE 0, ports 0-3  (right side of Cruiser board)
#
# ⚠️ WORKAROUND (remove when firmware is updated):
# The ESP32 firmware has a bug where enable-port sets the operating_mode
# back to semi_auto but does NOT re-write the detect_class_enable
# register. This leaves the port stuck in "detecting" state. As a
# workaround, after enabling a port we send a full "reset" command
# which reboots the ESP32 and re-runs init(), properly re-writing
# detect_class_enable. The hardware maintains power to other ports
# during the reboot, so other ports are NOT disrupted.
#
# TODO(firmware-fix): Once the firmware fix is deployed:
#   1. Remove the "reset" call in _esp32_enable_port()
#   2. Remove the ESP32_RESET_SETTLE_SECONDS sleep
#   3. Just send "enable-port <pse> <port>" directly
# ---------------------------------------------------------------------------

# Device path for ESP32 serial interface (udev symlink or direct UART)
_PSE_DEVICE_PATHS = [Path("/dev/pse"), Path("/dev/ttyAMA3")]

# Seconds to wait after ESP32 reset for re-init + PoE detection cycle
# The ESP32 reboots (~1s), runs init() (~0.5s), then TPS23861 needs
# time to detect and classify the device (~3-5s for full cycle)
ESP32_RESET_SETTLE_SECONDS = 8


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PoE switch entities from a config entry."""
    coordinator: ExavizDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    
    entities = []
    if coordinator.data and "poe" in coordinator.data:
        poe_data = coordinator.data["poe"]
        
        for poe_set_name, poe_set_data in poe_data.items():
            if isinstance(poe_set_data, dict) and "ports" in poe_set_data:
                for port in poe_set_data["ports"]:
                    port_num = port.get("port", 0)
                    entities.append(
                        ExavizPoEPortSwitch(
                            coordinator,
                            poe_set_name,
                            port_num,
                            config_entry.entry_id
                        )
                    )
    
    async_add_entities(entities)


class ExavizPoEPortSwitch(ExavizPoEBaseEntity, SwitchEntity):
    """Representation of a PoE port enable/disable switch."""

    def __init__(
        self,
        coordinator: ExavizDataUpdateCoordinator,
        poe_set: str,
        port_number: int,
        entry_id: str,
    ) -> None:
        """Initialize the PoE port switch."""
        super().__init__(
            coordinator=coordinator,
            poe_set=poe_set,
            port_number=port_number,
            entry_id=entry_id,
            entity_type="switch",
            entity_suffix="",
            entity_name_suffix="",
        )

    @property
    def device_class(self) -> SwitchDeviceClass:
        """Return the device class."""
        return SwitchDeviceClass.OUTLET

    @property
    def is_on(self) -> bool | None:
        """Return true if the PoE port is enabled."""
        if not self.coordinator.data:
            return None
        port_data = self._get_port_data()
        if port_data is None:
            return None
        return port_data.get("enabled", False)

    @property
    def _is_addon_board(self) -> bool:
        """Check if this is an add-on board port (pse0/pse1)."""
        return self._poe_set.startswith("pse")

    @property
    def available(self) -> bool:
        """Return if entity is available.
        
        Add-on board switches are disabled until kernel driver supports
        /proc/pse write interface.
        """
        if self._is_addon_board:
            return False
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
            "power_consumption_watts": port_data.get("power_consumption_watts", 0),
            "voltage_volts": port_data.get("voltage_volts", 0),
            "current_milliamps": port_data.get("current_milliamps", 0),
            "poe_system": port_data.get("poe_system", "unknown"),
        }

        if port_data.get("power_mocked"):
            attrs["power_note"] = "Power metrics estimated (TPS23861 driver pending)"
            attrs["power_mocked"] = True

        if self._is_addon_board:
            attrs["control_note"] = (
                "Enable/Disable not supported "
                "(kernel driver lacks /proc/pse write interface)"
            )
            attrs["control_available"] = False

        if self.coordinator.board_type:
            attrs["board_type"] = self.coordinator.board_type.value

        if port_data.get("interface"):
            attrs["interface"] = port_data.get("interface")
            attrs["link_state"] = port_data.get("link_state", "unknown")
            attrs["speed_mbps"] = port_data.get("speed_mbps", 0)

        if connected_device:
            attrs.update({
                "device_name": connected_device.get("name"),
                "device_type": connected_device.get("device_type"),
                "device_ip": connected_device.get("ip_address"),
                "device_mac": connected_device.get("mac_address"),
                "device_manufacturer": connected_device.get("manufacturer"),
                "device_hostname": connected_device.get("hostname"),
            })

        return attrs

    # ------------------------------------------------------------------
    # Port control helpers (async, non-blocking)
    # ------------------------------------------------------------------

    async def _run_ip_link(self, interface: str, action: str) -> bool:
        """Run 'ip link set' asynchronously. Returns True on success."""
        proc = await asyncio.create_subprocess_exec(
            "sudo", "ip", "link", "set", interface, action,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            _LOGGER.error(
                "Failed to %s port %s: %s", action, interface,
                stderr.decode(errors="replace").strip(),
            )
            return False
        return True

    @staticmethod
    def _linux_port_to_esp32(linux_port: int) -> tuple[int, int]:
        """Convert Linux poeX number to ESP32 (pse_num, port_num).

        Linux poe0-3 → PSE 1 ports 0-3 (left side of Cruiser board)
        Linux poe4-7 → PSE 0 ports 0-3 (right side of Cruiser board)
        """
        pse_num = 1 if linux_port < 4 else 0
        pse_port = linux_port % 4
        return pse_num, pse_port

    @staticmethod
    async def _send_esp32_command(command: str) -> bool:
        """Send a text command to the ESP32 via /dev/pse serial interface.

        Returns True if the command was written successfully.
        """
        for device_path in _PSE_DEVICE_PATHS:
            if not device_path.exists():
                continue

            try:
                proc = await asyncio.create_subprocess_exec(
                    "bash", "-c", f"echo '{command}' > {device_path}",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await proc.communicate()
                if proc.returncode == 0:
                    _LOGGER.info("Sent ESP32 command: %s → %s", command, device_path)
                    return True
                _LOGGER.warning(
                    "ESP32 command '%s' failed on %s: %s",
                    command, device_path,
                    stderr.decode(errors="replace").strip(),
                )
            except OSError as exc:
                _LOGGER.warning("Could not write to %s: %s", device_path, exc)

        _LOGGER.error("No ESP32 serial device found for command: %s", command)
        return False

    async def _esp32_disable_port(self) -> bool:
        """Disable a port on the TPS23861 via ESP32 command.

        Sends 'disable-port <pse> <port>' which immediately cuts PoE power.
        """
        pse_num, pse_port = self._linux_port_to_esp32(self._port_number)
        return await self._send_esp32_command(
            f"disable-port {pse_num} {pse_port}"
        )

    async def _esp32_enable_port(self) -> bool:
        """Enable a port on the TPS23861 via ESP32 command.

        ⚠️ BANDAID WORKAROUND: The firmware's enable-port command has a bug
        where it does not re-write detect_class_enable after changing the
        operating_mode register from OFF to SEMI_AUTO. The port gets stuck
        in 'detecting' state forever.

        As a workaround, we send 'reset' which reboots the ESP32 and runs
        init(), properly re-writing detect_class_enable = 0xff. The TPS23861
        hardware maintains power to other active ports during the reboot.

        TODO(firmware-fix): Replace this entire method body with:
            pse_num, pse_port = self._linux_port_to_esp32(self._port_number)
            return await self._send_esp32_command(
                f"enable-port {pse_num} {pse_port}"
            )
        """
        # Step 1: Send enable-port (sets internal state to .detecting)
        pse_num, pse_port = self._linux_port_to_esp32(self._port_number)
        await self._send_esp32_command(f"enable-port {pse_num} {pse_port}")

        # Step 2: BANDAID — full ESP32 reset to force detect_class_enable
        # re-write. Remove this once firmware is fixed.
        _LOGGER.info(
            "Sending ESP32 reset (bandaid for detect_class_enable bug) "
            "— waiting %ds for re-init and PoE detection cycle",
            ESP32_RESET_SETTLE_SECONDS,
        )
        ok = await self._send_esp32_command("reset")
        if ok:
            await asyncio.sleep(ESP32_RESET_SETTLE_SECONDS)
        return ok

    async def _control_onboard_port(self, action: str) -> None:
        """Enable or disable an onboard PoE port.

        Uses both ESP32 commands (for actual PoE power control via TPS23861)
        and ip link (for network interface admin state).
        """
        interface = f"poe{self._port_number}"

        if action == "disable":
            # Cut PoE power first, then bring down the network interface
            await self._esp32_disable_port()
            await self._run_ip_link(interface, "down")
            _LOGGER.info("Disabled onboard PoE port %s (power cut + link down)", interface)
        else:
            # Bring up network interface, then restore PoE power
            await self._run_ip_link(interface, "up")
            await self._esp32_enable_port()
            _LOGGER.info("Enabled onboard PoE port %s (link up + power restored)", interface)

        await self.coordinator.async_request_refresh()

    async def _control_pse_port(self, action: str) -> None:
        """Control add-on board port via /proc/pse interface.

        Args:
            action: "enable", "disable", or "reset"
        """
        pse_id = int(self._poe_set.replace("pse", ""))

        if action == "reset":
            reset_file = Path(f"/proc/pse{pse_id}/port{self._port_number}/reset")
            if not reset_file.exists():
                raise HomeAssistantError(f"Reset file not found: {reset_file}")

            proc = await asyncio.create_subprocess_exec(
                "sudo", "tee", str(reset_file),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate(input=b"1\n")
            if proc.returncode != 0:
                raise HomeAssistantError("Failed to reset port")
            _LOGGER.info(
                "Reset PSE port %s:%d via %s",
                self._poe_set, self._port_number, reset_file,
            )
        else:
            interface = f"poe{pse_id}-{self._port_number}"
            link_action = "up" if action == "enable" else "down"
            if not await self._run_ip_link(interface, link_action):
                raise HomeAssistantError(f"Failed to {action} port via {interface}")
            _LOGGER.info(
                "%s PSE port %s:%d via interface %s",
                action.title(), self._poe_set, self._port_number, interface,
            )

    # ------------------------------------------------------------------
    # HA switch interface
    # ------------------------------------------------------------------

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the PoE port."""
        try:
            if self._poe_set == "onboard":
                await self._control_onboard_port("enable")
            else:
                await self._control_pse_port("enable")
                await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error(
                "Error enabling PoE port %s:%d - %s",
                self._poe_set, self._port_number, e,
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the PoE port."""
        try:
            if self._poe_set == "onboard":
                await self._control_onboard_port("disable")
            else:
                await self._control_pse_port("disable")
                await self.coordinator.async_request_refresh()
        except Exception as e:
            _LOGGER.error(
                "Error disabling PoE port %s:%d - %s",
                self._poe_set, self._port_number, e,
            )
