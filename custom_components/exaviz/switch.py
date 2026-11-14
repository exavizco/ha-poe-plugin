"""PoE Switch Platform for Exaviz Integration."""
from __future__ import annotations

import asyncio
import logging
import weakref
from functools import partial
from pathlib import Path
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import ExavizPoEBaseEntity, async_setup_port_entities
from .coordinator import ExavizDataUpdateCoordinator
from .utils import sudo_argv

_LOGGER = logging.getLogger(__name__)

# One port action at a time, so two cannot race on the board.
PARALLEL_UPDATES = 1

# ---------------------------------------------------------------------------
# ESP32 serial command interface (/dev/pse)
#
# Commands are written as text lines to /dev/pse (symlink to /dev/ttyAMA3).
# Available commands: disable-port, enable-port, reset-port, reset
#
# Port mapping (Linux poeX → ESP32 PSE/port):
#   Linux poe0-3 → PSE 1, ports 0-3  (left side of Cruiser board)
#   Linux poe4-7 → PSE 0, ports 0-3  (right side of Cruiser board)
#
# Requires ESP32 firmware that re-arms detect_class_enable on
# enable-from-disabled (os-support #57 / 1.1.0+4d918bf or later).
# Do NOT send bare "reset" after enable — that reboots the chip and
# re-inits every port (mass re-power of previously disabled siblings).
# ---------------------------------------------------------------------------

# Device path for ESP32 serial interface (udev symlink or direct UART)
_PSE_DEVICE_PATHS = [Path("/dev/pse"), Path("/dev/ttyAMA3")]

# Seconds one command write may take; a blocked serial device must not hang
# the action (or leave a reset cycle half done).
ESP32_WRITE_TIMEOUT = 5
ESP32_KILL_WAIT = 2

# Seconds `ip link set` may take. It normally returns at once; one that hangs
# must not hold a switch action, a reset, or Home Assistant's stop.
IP_LINK_TIMEOUT = 10
# Seconds to wait for a stopped `ip link` after each signal.
IP_LINK_STOP_WAIT = 2

# Per interface, the start of an `ip link` that did not stop when told to.
# It may still change the link, so no other `ip link` runs on that interface
# until it has ended: a stuck `down` must not land after a later `up`.
_stuck_ip_link: dict[str, asyncio.Future] = {}
# Per event loop and interface: one `ip link` at a time, held through its
# stop, so a run that is still being stopped is recorded before the next
# one checks. (A lock belongs to one loop; tests run many.)
_ip_link_locks: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop, dict[str, asyncio.Lock]
] = weakref.WeakKeyDictionary()


def _ip_link_lock(interface: str) -> asyncio.Lock:
    """The interface's turn for `ip link` runs (and a reset's power cut)."""
    locks = _ip_link_locks.setdefault(asyncio.get_running_loop(), {})
    return locks.setdefault(interface, asyncio.Lock())


# Where running processes are listed (Linux).
_PROC = Path("/proc")


def _ip_link_in_proc(interface: str) -> bool:
    """True if an `ip link set <interface> ...` is running.

    Called with the interface's lock held and nothing of ours recorded as
    running, so it finds one left by an earlier Home Assistant run: under
    sudo, a stuck one outlives the process that started it.
    """
    try:
        entries = list(_PROC.iterdir())
    except OSError:
        return False
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            argv = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue  # it ended meanwhile
        if (
            argv[0].rsplit(b"/", 1)[-1] == b"ip"
            and argv[1:4] == [b"link", b"set", interface.encode()]
        ):
            return True
    return False


async def _ip_link_blocked(interface: str) -> bool:
    """True while an `ip link` on the interface may still change the link."""
    return _ip_link_stuck(interface) or await asyncio.to_thread(
        _ip_link_in_proc, interface
    )


def _ip_link_stuck(interface: str) -> bool:
    """True while an `ip link` on the interface that did not stop runs."""
    stuck = _stuck_ip_link.get(interface)
    if stuck is None:
        return False
    if _ip_link_running(stuck):
        return True
    _stuck_ip_link.pop(interface, None)
    return False


def _ip_link_running(spawn: asyncio.Future) -> bool:
    """True until a recorded `ip link` has ended (or failed to start).

    A start that was itself cancelled (the loop shutting down) may have left
    `ip` running with sudo SIGKILLed, so it counts as running for good.
    """
    if not spawn.done() or spawn.cancelled():
        return True
    if spawn.exception() is not None:
        return False
    return spawn.result().returncode is None


def _stop_when_started(under_sudo: bool, spawn: asyncio.Future) -> None:
    """Stop an `ip link` started after its caller was cancelled: SIGTERM,
    and run without sudo, SIGKILL if it still runs after the stop wait."""
    if spawn.cancelled() or spawn.exception() is not None:
        return
    proc = spawn.result()
    try:
        proc.terminate()
    except ProcessLookupError:
        return  # it ended already
    if not under_sudo:
        asyncio.get_running_loop().call_later(IP_LINK_STOP_WAIT, _kill_if_running, proc)


def _kill_if_running(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass


async def _stop_ip_link(proc: asyncio.subprocess.Process, under_sudo: bool) -> bool:
    """Stop an `ip link` that timed out or whose caller was cancelled.

    Returns True once it has ended. SIGTERM first, which sudo passes on to
    `ip`. Run without sudo (Home Assistant as root), `ip` then gets SIGKILL.
    Under sudo it does not: a SIGKILL would end only sudo and leave `ip`,
    a root process this one cannot signal, running unseen, while sudo stays
    until `ip` ends. A second cancel while waiting counts as not ended.
    """
    signals = (proc.terminate,) if under_sudo else (proc.terminate, proc.kill)
    for send_signal in signals:
        try:
            send_signal()
        except ProcessLookupError:
            return True  # it ended just now
        try:
            await asyncio.wait_for(proc.wait(), timeout=IP_LINK_STOP_WAIT)
            return True
        except asyncio.TimeoutError:
            pass
        except asyncio.CancelledError:
            if not under_sudo:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            return False
    return False


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PoE switch entities from a config entry."""
    coordinator: ExavizDataUpdateCoordinator = config_entry.runtime_data
    async_setup_port_entities(
        coordinator,
        config_entry,
        async_add_entities,
        lambda poe_set, port: [
            ExavizPoEPortSwitch(coordinator, poe_set, port, config_entry.entry_id)
        ],
    )


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
        """Check if this is an add-on board port (addon_0/addon_1)."""
        return self._poe_set.startswith("addon_")

    @property
    def available(self) -> bool:
        """Return if entity is available.
        
        Add-on board switches are disabled until kernel driver supports
        /proc/pse write interface.
        """
        if self._is_addon_board or not self.coordinator.can_control:
            return False
        return super().available

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

    @staticmethod
    async def _run_ip_link(interface: str, action: str) -> bool:
        """Run 'ip link set' asynchronously. Returns True on success.

        A run that times out, or whose caller is cancelled, is stopped. One
        that does not stop may still change the link later, so it raises
        HomeAssistantError and the caller must not run `ip link` after it.
        It also raises while an earlier one on the same interface is still
        running that way, whoever started it. Runs on one interface take
        turns, so the next waits until the one before has been stopped.
        """
        async with _ip_link_lock(interface):
            return await ExavizPoEPortSwitch._run_ip_link_alone(interface, action)

    @staticmethod
    async def _run_ip_link_alone(interface: str, action: str) -> bool:
        """_run_ip_link, with the interface's lock held."""
        if await _ip_link_blocked(interface):
            raise HomeAssistantError(
                f"An earlier ip link on port {interface} has not ended; "
                "the link's state is unknown, so nothing more is run on it"
            )
        argv = sudo_argv("ip", "link", "set", interface, action)
        spawn = asyncio.ensure_future(asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        ))
        cancelled = False
        try:
            # Shielded: a start cancelled half way is SIGKILLed by asyncio,
            # which under sudo ends only sudo and leaves `ip` running.
            proc = await asyncio.shield(spawn)
        except OSError as exc:
            _LOGGER.error("Could not run ip link to %s port %s: %s", action, interface, exc)
            return False
        except asyncio.CancelledError:
            if not spawn.done() or spawn.cancelled() or spawn.exception() is not None:
                # Not known to have stopped: let it start, then ask it to stop.
                spawn.add_done_callback(partial(_stop_when_started, argv[0] == "sudo"))
                _stuck_ip_link[interface] = spawn
                raise HomeAssistantError(
                    f"ip link to {action} port {interface} was cancelled while it "
                    "started and did not stop; the link's state is unknown"
                ) from None
            proc, cancelled = spawn.result(), True  # it had just started

        async def stop() -> None:
            if not await _stop_ip_link(proc, under_sudo=argv[0] == "sudo"):
                _stuck_ip_link[interface] = spawn
                _LOGGER.warning(
                    "ip link to %s port %s (pid %s) did not stop", action, interface, proc.pid
                )
                raise HomeAssistantError(
                    f"ip link to {action} port {interface} timed out or was cancelled "
                    "and did not stop; the link's state is unknown"
                )

        if cancelled:
            await stop()
            raise asyncio.CancelledError
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=IP_LINK_TIMEOUT)
        except asyncio.TimeoutError:
            await stop()
            if proc.returncode == 0:
                return True  # it finished just before the stop
            _LOGGER.error("ip link to %s port %s timed out", action, interface)
            return False
        except asyncio.CancelledError:
            await stop()
            raise
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

        Returns True if the command was written successfully. A write that
        times out is killed and not retried on another path: /dev/pse is
        usually a symlink to /dev/ttyAMA3, the same UART. Raises
        HomeAssistantError if the killed write does not stop.
        """
        for device_path in _PSE_DEVICE_PATHS:
            if not await asyncio.to_thread(device_path.exists):
                continue

            try:
                proc = await asyncio.create_subprocess_exec(
                    "bash", "-c", f"echo '{command}' > {device_path}",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                async def stop_write() -> None:
                    """Kill the write; raise if it does not stop."""
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass  # it finished just now
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=ESP32_KILL_WAIT)
                    except (asyncio.TimeoutError, asyncio.CancelledError):
                        # (A cancel during this wait counts as not stopped.)
                        # The write may still land later, so no caller may
                        # follow it with another command (a reset's restore).
                        raise HomeAssistantError(
                            f"The write of '{command}' to {device_path} timed out "
                            "or was cancelled and did not stop; the port's state is unknown"
                        ) from None

                try:
                    _, stderr = await asyncio.wait_for(
                        proc.communicate(), timeout=ESP32_WRITE_TIMEOUT
                    )
                except asyncio.CancelledError:
                    # Do not leave the write running behind the caller.
                    await stop_write()
                    raise
                except asyncio.TimeoutError:
                    await stop_write()
                    if proc.returncode == 0:
                        # It finished just before the kill.
                        _LOGGER.info("Sent ESP32 command: %s → %s", command, device_path)
                        return True
                    _LOGGER.error(
                        "ESP32 command '%s' timed out on %s", command, device_path
                    )
                    return False
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
        """Enable a port on the TPS23861 via ESP32 enable-port command."""
        pse_num, pse_port = self._linux_port_to_esp32(self._port_number)
        return await self._send_esp32_command(
            f"enable-port {pse_num} {pse_port}"
        )

    async def _control_onboard_port(self, action: str) -> None:
        """Enable or disable an onboard PoE port.

        Uses both ESP32 commands (for actual PoE power control via TPS23861)
        and ip link (for network interface admin state, which is what the
        switch shows). Raises HomeAssistantError when a step fails, saying
        what did happen; the state is refreshed either way.
        """
        interface = f"poe{self._port_number}"

        try:
            if action == "disable":
                # Cut PoE power first, then bring down the network interface.
                # If the power cut fails the port is still on, so leave the link.
                if not await self._esp32_disable_port():
                    raise HomeAssistantError(
                        f"The PoE controller did not disable port {interface}"
                    )
                if not await self._run_ip_link(interface, "down"):
                    raise HomeAssistantError(
                        f"Port {interface} power is off, but its network link did not go down"
                    )
                _LOGGER.info("Disabled onboard PoE port %s (power cut + link down)", interface)
            else:
                # Bring up network interface, then restore PoE power (even if
                # the link step failed, power is what the user asked for)
                try:
                    link_up = await self._run_ip_link(interface, "up")
                except HomeAssistantError:
                    # The link step is stuck, but the serial port is not.
                    if not await self._esp32_enable_port():
                        _LOGGER.error(
                            "The PoE controller did not enable port %s either", interface
                        )
                    raise
                if not await self._esp32_enable_port():
                    raise HomeAssistantError(
                        f"The PoE controller did not enable port {interface}"
                    )
                if not link_up:
                    raise HomeAssistantError(
                        f"Port {interface} power is on, but its network link did not come up"
                    )
                _LOGGER.info("Enabled onboard PoE port %s (link up + power restored)", interface)
        finally:
            await self.coordinator.async_request_refresh()

    def _get_pse_num(self) -> int:
        """Look up the numeric PSE ID from coordinator data.

        The coordinator stores the hardware pse_id (e.g. "pse0") in each
        poe_set dict.  We extract the number for /proc/pse{N} paths.
        """
        poe_data = (self.coordinator.data or {}).get("poe", {})
        pse_id = poe_data.get(self._poe_set, {}).get("pse_id", self._poe_set)
        return int(pse_id.replace("pse", ""))

    async def _control_pse_port(self, action: str) -> None:
        """Control add-on board port via /proc/pse interface.

        Args:
            action: "enable" or "disable"
        """
        pse_id = self._get_pse_num()

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

    def _is_onboard_poe_system(self) -> bool:
        """Return True when this port uses the onboard (ESP32) control path."""
        port_data = self._get_port_data()
        if port_data:
            return port_data.get("poe_system") == "onboard"
        # Fallback: key name
        return self._poe_set == "onboard"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the PoE port."""
        if self.coordinator.remote is not None:
            await self.coordinator.async_port_action(self._port_number, "enable")
            return
        try:
            if self._is_onboard_poe_system():
                await self._control_onboard_port("enable")
            else:
                await self._control_pse_port("enable")
                await self.coordinator.async_request_refresh()
        except HomeAssistantError:
            raise
        except Exception as e:
            # Raise so the UI and automations see the failure.
            raise HomeAssistantError(
                f"Could not enable PoE port {self._poe_set}:{self._port_number}: {e}"
            ) from e

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the PoE port."""
        if self.coordinator.remote is not None:
            await self.coordinator.async_port_action(self._port_number, "disable")
            return
        try:
            if self._is_onboard_poe_system():
                await self._control_onboard_port("disable")
            else:
                await self._control_pse_port("disable")
                await self.coordinator.async_request_refresh()
        except HomeAssistantError:
            raise
        except Exception as e:
            raise HomeAssistantError(
                f"Could not disable PoE port {self._poe_set}:{self._port_number}: {e}"
            ) from e
