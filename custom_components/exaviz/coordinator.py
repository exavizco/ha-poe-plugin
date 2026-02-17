"""DataUpdateCoordinator for Exaviz local board PoE management."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .board_detector import BoardType, detect_all_poe_systems
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, PLUGIN_VERSION
from .poe_readers import read_all_addon_ports, read_all_onboard_ports

_LOGGER = logging.getLogger(__name__)


class ExavizDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching PoE data from local Cruiser/Interceptor board."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.board_type: BoardType | None = None
        self.addon_boards: list[str] = []
        self.onboard_ports: list[str] = []
        self.total_poe_ports = 0
        self.system_info: dict[str, str] = {}

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    async def async_setup(self) -> bool:
        """Detect board type and PoE systems."""
        try:
            detection_result = await detect_all_poe_systems()
            
            self.board_type = detection_result["board_type"]
            self.addon_boards = detection_result["addon_boards"]
            self.onboard_ports = detection_result["onboard_ports"]
            self.total_poe_ports = detection_result["total_poe_ports"]
            
            if self.total_poe_ports == 0:
                _LOGGER.warning(
                    "No PoE systems detected on %s board",
                    self.board_type.value if self.board_type else "unknown",
                )
                return False
            
            _LOGGER.info(
                "Detected %s board: %d PoE ports (%d add-on, %d onboard)",
                self.board_type.value if self.board_type else "unknown",
                self.total_poe_ports,
                len(self.addon_boards) * 8,
                len(self.onboard_ports),
            )

            # Gather static system info (runs once at startup)
            self.system_info = await self._gather_system_info()

            return True
            
        except Exception as ex:
            _LOGGER.error("Failed to detect PoE systems: %s", ex)
            return False

    def _is_port_active(self, port_status: dict[str, Any]) -> bool:
        """Check if a port is actively powered regardless of system type.

        Works for both addon ("power on") and onboard ("active") states.
        """
        state = port_status.get("state", "")
        if state in ("power on", "active"):
            return True
        return port_status.get("power_watts", 0) > 0

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch PoE port data from local board."""
        try:
            poe_data: dict[str, Any] = {}
            
            for idx, pse_id in enumerate(self.addon_boards):
                port_data = await read_all_addon_ports(pse_id, port_count=8)
                pse_num = pse_id.replace("pse", "")
                
                ports_list = []
                for port_num, port_status in sorted(port_data.items()):
                    if not port_status.get("available", False):
                        continue

                    interface = f"poe{int(pse_num) * 8 + port_num}"
                    is_active = self._is_port_active(port_status)
                    connected_device = self._build_device_info(
                        port_status, interface, is_active, "Add-on PoE",
                    )
                    
                    ports_list.append({
                        "port": port_num,
                        "interface": interface,
                        "enabled": port_status.get("enabled", False),
                        "status": port_status.get("state", "unknown"),
                        "power_consumption_watts": port_status.get("power_watts", 0.0),
                        "allocated_power_watts": port_status.get("allocated_power_watts", 15.4),
                        "voltage_volts": port_status.get("voltage_volts", 0.0),
                        "current_milliamps": port_status.get("current_milliamps", 0),
                        "temperature_celsius": port_status.get("temperature_celsius", 0.0),
                        "poe_class": port_status.get("class", "?"),
                        "poe_system": "addon",
                        "connected_device": connected_device,
                    })
                
                # Always use addon_{idx} for add-on boards.  This gives
                # Interceptor entities like switch.addon_0_port0 and
                # switch.addon_1_port0 — matching what users expect.
                # The hardware PSE ID (pse0/pse1) is stored as "pse_id"
                # so the control path can find /proc/pse{N}.
                poe_set_key = f"addon_{idx}"

                poe_data[poe_set_key] = {
                    "pse_id": pse_id,
                    "total_ports": 8,
                    "active_ports": len([p for p in ports_list if p["enabled"]]),
                    "used_power_watts": sum(p["power_consumption_watts"] for p in ports_list),
                    "total_power_budget": 240.0,
                    "ports": ports_list,
                }
            
            if self.onboard_ports:
                onboard_data = await read_all_onboard_ports(self.onboard_ports)
                
                ports_list = []
                for interface in sorted(self.onboard_ports):
                    port_status = onboard_data.get(interface, {})
                    if not port_status.get("available", False):
                        continue

                    port_num = int(interface.replace("poe", ""))
                    is_active = self._is_port_active(port_status)
                    connected_device = self._build_device_info(
                        port_status, interface, is_active, "Onboard PoE",
                    )
                    
                    ports_list.append({
                        "port": port_num,
                        "interface": interface,
                        "enabled": port_status.get("enabled", False),
                        "status": port_status.get("state", "unknown"),
                        "power_consumption_watts": port_status.get("power_watts", 0.0),
                        "allocated_power_watts": port_status.get("allocated_power_watts", 15.4),
                        "power_mocked": port_status.get("power_mocked", True),
                        "poe_class": port_status.get("class", "?"),
                        "voltage_volts": port_status.get("voltage_volts", 0.0),
                        "current_milliamps": port_status.get("current_milliamps", 0),
                        "link_state": port_status.get("link_state", "unknown"),
                        "speed_mbps": port_status.get("speed_mbps", 0),
                        "rx_bytes": port_status.get("rx_bytes", 0),
                        "tx_bytes": port_status.get("tx_bytes", 0),
                        "poe_system": "onboard",
                        "connected_device": connected_device,
                    })
                
                poe_data["onboard"] = {
                    "total_ports": len(self.onboard_ports),
                    "active_ports": len([p for p in ports_list if p["enabled"]]),
                    "used_power_watts": sum(p["power_consumption_watts"] for p in ports_list),
                    "total_power_budget": len(self.onboard_ports) * 30.0,
                    "power_mocked": True,
                    "ports": ports_list,
                }
            
            total_active = sum(s["active_ports"] for s in poe_data.values())
            total_power = sum(s["used_power_watts"] for s in poe_data.values())
            
            # Read CM SoC temperature (millidegrees → degrees)
            board_temp = await self._read_board_temperature()

            return {
                "board_type": self.board_type.value if self.board_type else "unknown",
                "total_poe_ports": self.total_poe_ports,
                "total_enabled_ports": total_active,
                "total_power_watts": round(total_power, 2),
                "board_temperature_celsius": board_temp,
                "poe": poe_data,
                "hardware": {
                    "hardware_type": self.board_type.value if self.board_type else "unknown",
                    "poe_capable": True,
                    "model": f"Exaviz {self.board_type.value.title()}" if self.board_type else "Unknown",
                    "addon_boards": len(self.addon_boards),
                    "onboard_ports": len(self.onboard_ports),
                },
                "last_updated": datetime.now().isoformat(),
            }
            
        except Exception as ex:
            raise UpdateFailed(f"Error fetching PoE data: {ex}") from ex

    @staticmethod
    def _build_device_info(
        port_status: dict[str, Any],
        interface: str,
        is_active: bool,
        power_class_label: str,
    ) -> dict[str, Any] | None:
        """Build the connected_device dict from port status data."""
        if port_status.get("connected_device"):
            dev = port_status["connected_device"]
            return {
                "name": f"Device on {interface}",
                "device_type": dev.get("manufacturer", "Network Device"),
                "ip_address": dev.get("ip_address"),
                "mac_address": dev.get("mac_address"),
                "manufacturer": dev.get("manufacturer", "Unknown"),
                "hostname": dev.get("hostname"),
                "power_class": f"Unknown ({power_class_label})",
            }
        if is_active:
            return {
                "name": f"Device on {interface}",
                "device_type": "Unknown Device (No Network Activity)",
                "ip_address": None,
                "mac_address": None,
                "manufacturer": "Unknown",
                "hostname": None,
                "power_class": f"Unknown ({power_class_label})",
            }
        return None

    async def async_shutdown(self) -> None:
        """Shutdown coordinator and clean up resources."""
        _LOGGER.debug("Coordinator shutdown complete")

    @property
    def board_info(self) -> dict[str, Any]:
        """Get board information including system details."""
        info: dict[str, Any] = {
            "board_type": self.board_type.value if self.board_type else "unknown",
            "addon_boards": len(self.addon_boards),
            "onboard_ports": len(self.onboard_ports),
            "total_poe_ports": self.total_poe_ports,
        }
        info.update(self.system_info)
        return info

    # ------------------------------------------------------------------
    # Live board metrics (read every poll cycle)
    # ------------------------------------------------------------------

    @staticmethod
    async def _read_board_temperature() -> float | None:
        """Read CM5 SoC temperature from thermal_zone0.

        Returns temperature in degrees Celsius, or None if unavailable.
        The sysfs file reports millidegrees (e.g. 55100 = 55.1°C).
        """
        thermal_path = Path("/sys/class/thermal/thermal_zone0/temp")
        try:
            raw = await asyncio.to_thread(thermal_path.read_text)
            return round(int(raw.strip()) / 1000.0, 1)
        except (OSError, ValueError):
            return None

    # ------------------------------------------------------------------
    # System info gathering (runs once during setup, not every poll)
    # ------------------------------------------------------------------

    # Known compute module identifiers from /proc/device-tree/compatible.
    # Maps the first compatible string to a human-readable name.
    # Format: "vendor,description" → "Human Readable Name"
    _COMPATIBLE_CM_MAP: dict[str, str] = {
        "raspberrypi,5-compute-module": "Raspberry Pi CM5",
        "raspberrypi,4-compute-module": "Raspberry Pi CM4",
        "raspberrypi,3-compute-module": "Raspberry Pi CM3",
        # BPi CM4 — exact string TBD, add when hardware is available
        # "sinovoip,bpi-cm4": "Banana Pi CM4",
    }

    @classmethod
    def _parse_compute_module(cls, compatible_raw: bytes) -> str:
        """Derive the compute module name from /proc/device-tree/compatible.

        The compatible file contains null-separated strings, most-specific
        first.  Examples:
          Cruiser CM5:     "raspberrypi,5-compute-module\\0brcm,bcm2712\\0"
          Interceptor CM4: "raspberrypi,4-compute-module\\0brcm,bcm2711\\0"

        We match the first entry against our known map.  If unknown, we
        return the raw string cleaned up for display.
        """
        entries = [
            e for e in compatible_raw.decode(errors="replace").split("\x00") if e
        ]
        if not entries:
            return "Unknown"

        first = entries[0].strip()
        if first in cls._COMPATIBLE_CM_MAP:
            return cls._COMPATIBLE_CM_MAP[first]

        # Unknown but present — clean up "vendor,description" for display
        # e.g. "sinovoip,bpi-cm4" → "Sinovoip BPI CM4"
        return first.replace(",", " ").replace("-", " ").title()

    @staticmethod
    async def _run_cmd(*args: str) -> str:
        """Run a shell command and return stripped stdout, or '' on error."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await proc.communicate()
            return stdout.decode(errors="replace").strip()
        except OSError:
            return ""

    async def _gather_system_info(self) -> dict[str, str]:
        """Collect static board/OS/driver info once at startup."""
        info: dict[str, str] = {}

        # Plugin version (always available)
        info["plugin_version"] = PLUGIN_VERSION

        try:
            # Compute module from /proc/device-tree/compatible
            # This is the most reliable source — always identifies just the
            # compute module, never polluted by the carrier board name.
            #   Cruiser:     "raspberrypi,5-compute-module\0brcm,bcm2712\0"
            #   Interceptor: "raspberrypi,4-compute-module\0brcm,bcm2711\0"
            cm_gen = ""  # "4" or "5" — used for model number construction
            compat_path = Path("/proc/device-tree/compatible")
            if compat_path.exists():
                raw = await asyncio.to_thread(compat_path.read_bytes)
                info["compute_module"] = self._parse_compute_module(raw)
                # Extract generation for model number (e.g., "4" from CM4)
                first = raw.decode(errors="replace").split("\x00")[0].strip()
                if "5-compute-module" in first:
                    cm_gen = "5"
                elif "4-compute-module" in first:
                    cm_gen = "4"
                elif "3-compute-module" in first:
                    cm_gen = "3"

            # --- CM model number (e.g., CM4102000) ---
            # Detect RAM, WiFi, and eMMC to construct the full model string.
            cm_model_info = await self._detect_cm_model(cm_gen)
            info.update(cm_model_info)

            # OS version from os-release
            os_release = Path("/etc/os-release")
            if os_release.exists():
                text = await asyncio.to_thread(os_release.read_text)
                for line in text.splitlines():
                    if line.startswith("PRETTY_NAME="):
                        info["os_version"] = line.split("=", 1)[1].strip('"')
                        break

            # Kernel version
            kernel = await self._run_cmd("uname", "-r")
            if kernel:
                info["kernel_version"] = kernel

            # Exaviz package versions (integration-relevant only)
            dpkg_out = await self._run_cmd(
                "dpkg-query", "-W", "-f",
                "${Package} ${Version}\n",
                "exaviz-dkms", "exaviz-netplan",
            )
            for line in dpkg_out.splitlines():
                parts = line.strip().split(None, 1)
                if len(parts) == 2:
                    pkg, ver = parts
                    if pkg == "exaviz-dkms":
                        info["dkms_driver_version"] = ver
                    elif pkg == "exaviz-netplan":
                        info["netplan_version"] = ver

            # PoE controller type (derived from board type)
            if self.board_type == BoardType.CRUISER:
                info["poe_controller"] = "TPS23861 (Texas Instruments)"
            elif self.board_type == BoardType.INTERCEPTOR:
                info["poe_controller"] = "IP808AR (IC Plus)"

            # Board-specific info: ESP32 (Cruiser) or /proc/pse header (Interceptor)
            esp32_info = await self._query_esp32_info()
            info.update(esp32_info)

            # If no ESP32, try /proc/pse header (Interceptor kernel driver)
            # Header format: "Axzez Interceptor PoE driver version 2.0"
            if "esp32_firmware_version" not in info:
                proc_pse_info = await self._query_proc_pse_header()
                info.update(proc_pse_info)

            # Fallback: derive board name from detected board type if
            # neither ESP32 nor /proc/pse provided one
            if "board_model_esp32" not in info and self.board_type:
                info["board_model_esp32"] = self.board_type.value.title()

            # Board serial from device tree (fallback for non-ESP32 boards)
            if "board_serial" not in info:
                board_dt = Path("/proc/device-tree/chosen/board")
                if board_dt.exists():
                    raw = await asyncio.to_thread(board_dt.read_bytes)
                    dt_board = raw.decode(errors="replace").rstrip("\x00").strip()
                    # Format: "interceptor-raspberrypi-cm4" — not a serial,
                    # but useful as a board identifier
                    info["board_identifier"] = dt_board

        except Exception as ex:
            _LOGGER.warning("Error gathering system info: %s", ex)

        return info

    # Standard RAM sizes in GB for rounding MemTotal to nearest tier.
    _RAM_TIERS_GB = (1, 2, 4, 8, 16)

    async def _detect_cm_model(self, cm_gen: str) -> dict[str, str]:
        """Detect CM model number, total RAM, WiFi, and eMMC presence.

        Constructs a model string like CM4102000 or CM5108032:
          CM{gen}{ram_gb}{wifi}{emmc_gb:03d}
            gen   = 4, 5, etc.
            ram   = 1, 2, 4, 8 (GB)
            wifi  = 0 (none) or 1 (WiFi+BT)
            emmc  = 000 (Lite), 008, 016, 032, 064 (GB)

        Returns dict with:
          cm_model:      "CM4102000"
          total_ram_gb:  "2 GB"
          has_wifi:      "Yes" / "No"
          emmc_storage:  "None (Lite)" / "32 GB"
        """
        result: dict[str, str] = {}
        if not cm_gen:
            return result

        # --- RAM ---
        mem_total_kb = 0
        try:
            meminfo = Path("/proc/meminfo")
            text = await asyncio.to_thread(meminfo.read_text)
            for line in text.splitlines():
                if line.startswith("MemTotal:"):
                    mem_total_kb = int(line.split()[1])
                    break
        except (OSError, ValueError):
            pass

        # MemTotal is less than physical RAM (kernel/GPU reservation).
        # Round up to nearest standard tier.
        mem_total_gb = mem_total_kb / (1024 * 1024)  # KB → GB
        ram_gb = 1
        for tier in self._RAM_TIERS_GB:
            if mem_total_gb <= tier:
                ram_gb = tier
                break
        else:
            ram_gb = self._RAM_TIERS_GB[-1]

        result["total_ram_gb"] = f"{ram_gb} GB"

        # --- WiFi ---
        wlan_path = Path("/sys/class/net/wlan0")
        has_wifi = await asyncio.to_thread(wlan_path.exists)
        result["has_wifi"] = "Yes" if has_wifi else "No"

        # --- eMMC ---
        # eMMC devices have boot partitions; SD cards do not.
        emmc_gb = 0
        emmc_boot = Path("/sys/block/mmcblk0boot0")
        has_emmc = await asyncio.to_thread(emmc_boot.exists)

        if has_emmc:
            try:
                size_path = Path("/sys/block/mmcblk0/size")
                raw = await asyncio.to_thread(size_path.read_text)
                sectors = int(raw.strip())
                emmc_bytes = sectors * 512
                # Round to nearest standard eMMC size (8, 16, 32, 64, 128 GB)
                raw_gb = emmc_bytes / (1024 ** 3)
                for std in (8, 16, 32, 64, 128, 256):
                    if raw_gb <= std * 1.1:  # 10% tolerance
                        emmc_gb = std
                        break
            except (OSError, ValueError):
                emmc_gb = 0

        if emmc_gb > 0:
            result["emmc_storage"] = f"{emmc_gb} GB"
        else:
            result["emmc_storage"] = "None (Lite)"

        # --- Construct model number ---
        wifi_digit = 1 if has_wifi else 0
        emmc_str = f"{emmc_gb:03d}"
        model = f"CM{cm_gen}{ram_gb}{wifi_digit}{emmc_str}"
        result["cm_model"] = model

        return result

    async def _query_proc_pse_header(self) -> dict[str, str]:
        """Parse the /proc/pse header line for Interceptor PoE driver info.

        The Interceptor's IP808AR kernel driver writes a header line:
            "Axzez Interceptor PoE driver version 2.0"

        Only called once at startup. Returns empty dict if /proc/pse
        doesn't exist (i.e., on Cruiser boards).
        """
        info: dict[str, str] = {}
        pse_file = Path("/proc/pse")
        if not pse_file.exists():
            return info

        try:
            import subprocess

            result = await asyncio.to_thread(
                subprocess.run,
                ["head", "-1", str(pse_file)],
                capture_output=True,
                text=True,
                timeout=5,
            )
            header = result.stdout.strip()

            # Parse: "Axzez Interceptor PoE driver version 2.0"
            if "version" in header.lower():
                parts = header.rsplit("version", 1)
                if len(parts) == 2:
                    info["poe_driver_version"] = parts[1].strip()

                # Extract board name from header (e.g., "Interceptor")
                if "Interceptor" in header:
                    info["board_model_esp32"] = "Interceptor"
                elif "Cruiser" in header:
                    info["board_model_esp32"] = "Cruiser"

        except (OSError, subprocess.TimeoutExpired) as exc:
            _LOGGER.debug("Could not read /proc/pse header: %s", exc)

        return info

    async def _query_esp32_info(self) -> dict[str, str]:
        """Query the ESP32 for firmware version and board identity.

        Sends the 'info' command to /dev/pse and parses the response.
        Only called once at startup (static info).
        """
        info: dict[str, str] = {}
        pse_dev = Path("/dev/pse")
        if not pse_dev.exists():
            pse_dev = Path("/dev/ttyAMA3")
        if not pse_dev.exists():
            return info

        try:
            # Configure serial port
            stty_proc = await asyncio.create_subprocess_exec(
                "stty", "-F", str(pse_dev), "115200", "raw", "-echo",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await stty_proc.communicate()

            # Send "info" command and read response (timeout 3s)
            proc = await asyncio.create_subprocess_exec(
                "bash", "-c",
                f"echo 'info' > {pse_dev} && timeout 3 cat {pse_dev}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await proc.communicate()
            output = stdout.decode(errors="replace")

            for line in output.splitlines():
                line = line.strip()
                if line.startswith("Exaviz PoE monitor version "):
                    info["esp32_firmware_version"] = line.split(
                        "version ", 1
                    )[1].strip()
                elif line.startswith("board model:"):
                    info["board_model_esp32"] = line.split(":", 1)[1].strip().title()
                elif line.startswith("board version:"):
                    info["board_hw_version"] = line.split(":", 1)[1].strip()
                elif line.startswith("board serial:"):
                    info["board_serial"] = line.split(":", 1)[1].strip()

        except (OSError, asyncio.TimeoutError) as exc:
            _LOGGER.debug("Could not query ESP32 info: %s", exc)

        return info
