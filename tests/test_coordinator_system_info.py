"""Coordinator local-board paths: system info, temperature, port skipping.

Filesystem reads go to a fake root under tmp_path: the module-level `Path`
in coordinator.py is replaced by one that re-roots absolute paths, so the
code reads real-format /proc, /sys and /etc text from files we write.
Subprocesses are faked at asyncio.create_subprocess_exec.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.exaviz.board_detector import BoardType
from custom_components.exaviz.const import CONF_SCOPE, PLUGIN_VERSION, SCOPE_CONTROL
from custom_components.exaviz.coordinator import (
    ExavizDataUpdateCoordinator,
    parse_esp32_info,
)

pytestmark = pytest.mark.asyncio

COORD = "custom_components.exaviz.coordinator"

# Real-format inputs, as read on Cruiser (CM5) and Interceptor (CM4) boards.
COMPAT_CM5 = b"raspberrypi,5-compute-module\x00brcm,bcm2712\x00"
COMPAT_CM4 = b"raspberrypi,4-compute-module\x00brcm,bcm2711\x00"
COMPAT_CM3 = b"raspberrypi,3-compute-module\x00brcm,bcm2837\x00"
MEMINFO_8GB = "MemTotal:        8245312 kB\nMemFree:         7012345 kB\n"
MEMINFO_2GB = "MemTotal:        1939408 kB\nMemFree:         1500000 kB\n"
EMMC_32GB_SECTORS = "61071360\n"  # 29.1 GiB, sold as 32 GB
OS_RELEASE = (
    'PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"\n'
    'NAME="Debian GNU/Linux"\n'
    'VERSION_ID="12"\n'
)
ESP32_INFO = (
    "Exaviz PoE monitor version 1.1.2+c951f9d\n"
    "firmware variant: zigbee\n"
    "board model: cruiser\n"
    "board version: 1.2\n"
    "board serial: CRU-000012\n"
)
PROC_PSE = (
    "Axzez Interceptor PoE driver version 2.0\n"
    "0-0: power-on 0 15.50 47.9375 0.05950/0.80000 33.1250/150.0000\n"
)
DPKG_OUT = "exaviz-dkms 1.4.2\nexaviz-netplan 0.3.1\n"
KERNEL = "6.12.25+rpt-rpi-2712\n"


@pytest.fixture
def coordinator(mock_hass, mock_config_entry):
    return ExavizDataUpdateCoordinator(mock_hass, mock_config_entry)


@pytest.fixture
def root(tmp_path):
    """Fake filesystem root; coordinator.Path("/x/y") becomes root/x/y."""
    with patch(f"{COORD}.Path", lambda p: tmp_path / str(p).lstrip("/")):
        yield tmp_path


def put(root: Path, path: str, content: str | bytes = "") -> Path:
    """Create a file (or a directory when path ends in '/') under root."""
    target = root / path.strip("/")
    if path.endswith("/"):
        target.mkdir(parents=True, exist_ok=True)
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        target.write_bytes(content)
    else:
        target.write_text(content)
    return target


class FakeExec:
    """Stand-in for asyncio.create_subprocess_exec that records argv."""

    def __init__(self, outputs: dict[str, str] | None = None, error: Exception | None = None):
        self.outputs = outputs or {}
        self.error = error
        self.calls: list[tuple[str, ...]] = []

    async def __call__(self, *args: str, **_kwargs: Any) -> MagicMock:
        self.calls.append(args)
        if self.error:
            raise self.error
        proc = MagicMock()
        proc.communicate = AsyncMock(
            return_value=(self.outputs.get(args[0], "").encode(), None)
        )
        return proc


# ---------------------------------------------------------------------------
# parse_esp32_info and compatible-string parsing
# ---------------------------------------------------------------------------

async def test_parse_esp32_info_reads_every_field():
    assert parse_esp32_info(ESP32_INFO) == {
        "esp32_firmware_version": "1.1.2+c951f9d",
        "esp32_firmware_variant": "zigbee",
        "board_model_esp32": "Cruiser",
        "board_hw_version": "1.2",
        "board_serial": "CRU-000012",
    }


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (COMPAT_CM5, "Raspberry Pi CM5"),
        (COMPAT_CM4, "Raspberry Pi CM4"),
        (COMPAT_CM3, "Raspberry Pi CM3"),
        # Unknown module: shown cleaned up, not dropped.
        (b"sinovoip,bpi-cm4\x00rockchip,rk3568\x00", "Sinovoip Bpi Cm4"),
        (b"\x00", "Unknown"),
        (b"", "Unknown"),
    ],
)
async def test_parse_compute_module(raw, expected):
    assert ExavizDataUpdateCoordinator._parse_compute_module(raw) == expected


# ---------------------------------------------------------------------------
# Board temperature
# ---------------------------------------------------------------------------

async def test_board_temperature_millidegrees_to_celsius(root):
    put(root, "/sys/class/thermal/thermal_zone0/temp", "55123\n")
    assert await ExavizDataUpdateCoordinator._read_board_temperature() == 55.1


@pytest.mark.parametrize("content", [None, "garbage\n"])
async def test_board_temperature_unavailable_is_none(root, content):
    if content is not None:
        put(root, "/sys/class/thermal/thermal_zone0/temp", content)
    assert await ExavizDataUpdateCoordinator._read_board_temperature() is None


# ---------------------------------------------------------------------------
# _run_cmd
# ---------------------------------------------------------------------------

async def test_run_cmd_returns_stripped_stdout():
    assert await ExavizDataUpdateCoordinator._run_cmd("echo", "  6.12.25  ") == "6.12.25"


async def test_run_cmd_missing_binary_returns_empty():
    assert await ExavizDataUpdateCoordinator._run_cmd("/nonexistent/uname-xyz") == ""


# ---------------------------------------------------------------------------
# CM model detection
# ---------------------------------------------------------------------------

async def test_cm_model_no_generation_returns_nothing(coordinator, root):
    put(root, "/proc/meminfo", MEMINFO_8GB)
    assert await coordinator._detect_cm_model("") == {}


async def test_cm_model_cm5_8gb_wifi_32gb_emmc(coordinator, root):
    put(root, "/proc/meminfo", MEMINFO_8GB)
    put(root, "/sys/class/net/wlan0/")
    put(root, "/sys/block/mmcblk0boot0/")
    put(root, "/sys/block/mmcblk0/size", EMMC_32GB_SECTORS)
    result = await coordinator._detect_cm_model("5")
    assert result["total_ram_gb"] == "8 GB"
    assert result["has_wifi"] == "Yes"
    assert result["emmc_storage"] == "32 GB"


async def test_cm_model_string_matches_raspberry_pi_part_number(coordinator, root):
    put(root, "/proc/meminfo", MEMINFO_8GB)
    put(root, "/sys/class/net/wlan0/")
    put(root, "/sys/block/mmcblk0boot0/")
    put(root, "/sys/block/mmcblk0/size", EMMC_32GB_SECTORS)
    result = await coordinator._detect_cm_model("5")
    assert result["cm_model"] == "CM5108032"


async def test_cm_model_lite_no_wifi(coordinator, root):
    """CM4 Lite: SD card only, so no mmcblk0boot0 and no wlan0."""
    put(root, "/proc/meminfo", MEMINFO_2GB)
    result = await coordinator._detect_cm_model("4")
    assert result == {
        "total_ram_gb": "2 GB",
        "has_wifi": "No",
        "emmc_storage": "None (Lite)",
        "cm_model": "CM4002000",
    }


async def test_cm_model_unreadable_meminfo_and_emmc_size(coordinator, root):
    """No /proc/meminfo: smallest tier. Bad eMMC size: treated as Lite."""
    put(root, "/sys/block/mmcblk0boot0/")
    put(root, "/sys/block/mmcblk0/size", "not-a-number\n")
    result = await coordinator._detect_cm_model("4")
    assert result["total_ram_gb"] == "1 GB"
    assert result["emmc_storage"] == "None (Lite)"


async def test_cm_model_clamps_to_largest_tiers(coordinator, root):
    """Above the top RAM tier clamps to 16 GB; eMMC above 256 GB is not a tier."""
    put(root, "/proc/meminfo", "MemTotal:       33554432 kB\n")  # 32 GiB
    put(root, "/sys/block/mmcblk0boot0/")
    put(root, "/sys/block/mmcblk0/size", str(600 * 1024**3 // 512))
    result = await coordinator._detect_cm_model("5")
    assert result["total_ram_gb"] == "16 GB"
    assert result["emmc_storage"] == "None (Lite)"


# ---------------------------------------------------------------------------
# ESP32 info query and /proc/pse header
# ---------------------------------------------------------------------------

async def test_esp32_query_parses_reply_from_dev_pse(coordinator, root):
    put(root, "/dev/pse")
    fake = FakeExec({"bash": ESP32_INFO})
    with patch("asyncio.create_subprocess_exec", fake):
        info = await coordinator._query_esp32_info()
    assert info["esp32_firmware_version"] == "1.1.2+c951f9d"
    assert info["board_serial"] == "CRU-000012"
    dev = str(root / "dev/pse")
    assert fake.calls[0] == ("stty", "-F", dev, "115200", "raw", "-echo")
    assert fake.calls[1] == ("bash", "-c", f"echo 'info' > {dev} && timeout 3 cat {dev}")


async def test_esp32_query_falls_back_to_ttyama3(coordinator, root):
    put(root, "/dev/ttyAMA3")
    fake = FakeExec({"bash": ESP32_INFO})
    with patch("asyncio.create_subprocess_exec", fake):
        info = await coordinator._query_esp32_info()
    assert info["board_model_esp32"] == "Cruiser"
    assert fake.calls[0][2] == str(root / "dev/ttyAMA3")


async def test_esp32_query_no_device_runs_nothing(coordinator, root):
    fake = FakeExec({"bash": ESP32_INFO})
    with patch("asyncio.create_subprocess_exec", fake):
        assert await coordinator._query_esp32_info() == {}
    assert fake.calls == []


async def test_esp32_query_subprocess_error_returns_empty(coordinator, root):
    put(root, "/dev/pse")
    with patch("asyncio.create_subprocess_exec", FakeExec(error=OSError("no stty"))):
        assert await coordinator._query_esp32_info() == {}


async def test_proc_pse_header_interceptor(coordinator, root):
    put(root, "/proc/pse", PROC_PSE)
    assert await coordinator._query_proc_pse_header() == {
        "poe_driver_version": "2.0",
        "board_model_esp32": "Interceptor",
    }


async def test_proc_pse_header_absent(coordinator, root):
    assert await coordinator._query_proc_pse_header() == {}


async def test_proc_pse_header_without_version_is_ignored(coordinator, root):
    put(root, "/proc/pse", "0-0: power-on 0 15.50 47.9375 0.05950/0.80000\n")
    assert await coordinator._query_proc_pse_header() == {}


async def test_proc_pse_header_timeout_returns_empty(coordinator, root):
    put(root, "/proc/pse", PROC_PSE)
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("head", 5)):
        assert await coordinator._query_proc_pse_header() == {}


# ---------------------------------------------------------------------------
# _gather_system_info end to end
# ---------------------------------------------------------------------------

async def test_gather_cruiser(coordinator, root):
    coordinator.board_type = BoardType.CRUISER
    put(root, "/proc/device-tree/compatible", COMPAT_CM5)
    put(root, "/proc/meminfo", MEMINFO_8GB)
    put(root, "/sys/class/net/wlan0/")
    put(root, "/sys/block/mmcblk0boot0/")
    put(root, "/sys/block/mmcblk0/size", EMMC_32GB_SECTORS)
    put(root, "/etc/os-release", OS_RELEASE)
    put(root, "/dev/pse")
    # The ESP32 serial wins, so the device-tree board name is not used.
    put(root, "/proc/device-tree/chosen/board", b"cruiser-raspberrypi-cm5\x00")
    fake = FakeExec({"uname": KERNEL, "dpkg-query": DPKG_OUT, "bash": ESP32_INFO})
    with patch("asyncio.create_subprocess_exec", fake):
        info = await coordinator._gather_system_info()

    info.pop("cm_model")  # covered by the part-number tests above
    assert info == {
        "plugin_version": PLUGIN_VERSION,
        "compute_module": "Raspberry Pi CM5",
        "total_ram_gb": "8 GB",
        "has_wifi": "Yes",
        "emmc_storage": "32 GB",
        "os_version": "Debian GNU/Linux 12 (bookworm)",
        "kernel_version": "6.12.25+rpt-rpi-2712",
        "dkms_driver_version": "1.4.2",
        "netplan_version": "0.3.1",
        "poe_controller": "TPS23861 (Texas Instruments)",
        "esp32_firmware_version": "1.1.2+c951f9d",
        "esp32_firmware_variant": "zigbee",
        "board_model_esp32": "Cruiser",
        "board_hw_version": "1.2",
        "board_serial": "CRU-000012",
    }
    assert ("uname", "-r") in fake.calls


async def test_gather_interceptor(coordinator, root):
    coordinator.board_type = BoardType.INTERCEPTOR
    put(root, "/proc/device-tree/compatible", COMPAT_CM4)
    put(root, "/proc/meminfo", MEMINFO_2GB)
    put(root, "/proc/pse", PROC_PSE)
    put(root, "/proc/device-tree/chosen/board", b"interceptor-raspberrypi-cm4\x00")
    # dpkg-query output with a stray line and an unrelated package.
    fake = FakeExec({"uname": KERNEL, "dpkg-query": "exaviz-dkms 1.4.2\nbroken\nfoo 1.0\n"})
    with patch("asyncio.create_subprocess_exec", fake):
        info = await coordinator._gather_system_info()

    assert info["compute_module"] == "Raspberry Pi CM4"
    assert info["cm_model"].startswith("CM4")
    assert info["emmc_storage"] == "None (Lite)"
    assert info["poe_controller"] == "IP808AR (IC Plus)"
    assert info["poe_driver_version"] == "2.0"
    assert info["board_model_esp32"] == "Interceptor"
    assert info["board_identifier"] == "interceptor-raspberrypi-cm4"
    assert info["dkms_driver_version"] == "1.4.2"
    assert "netplan_version" not in info
    assert "esp32_firmware_version" not in info
    assert "os_version" not in info


async def test_gather_cm3_without_chosen_board(coordinator, root):
    put(root, "/proc/device-tree/compatible", COMPAT_CM3)
    put(root, "/proc/meminfo", "MemTotal:         948304 kB\n")
    put(root, "/etc/os-release", 'NAME="Debian GNU/Linux"\n')
    with patch("asyncio.create_subprocess_exec", FakeExec()):
        info = await coordinator._gather_system_info()
    assert info["compute_module"] == "Raspberry Pi CM3"
    assert info["cm_model"].startswith("CM30")
    assert "os_version" not in info  # no PRETTY_NAME line
    assert "board_identifier" not in info
    assert "board_model_esp32" not in info  # no board type to fall back on


async def test_gather_unknown_module_has_no_cm_model(coordinator, root):
    coordinator.board_type = BoardType.CRUISER
    put(root, "/proc/device-tree/compatible", b"sinovoip,bpi-cm4\x00")
    with patch("asyncio.create_subprocess_exec", FakeExec(error=OSError("not found"))):
        info = await coordinator._gather_system_info()
    assert info == {
        "plugin_version": PLUGIN_VERSION,
        "compute_module": "Sinovoip Bpi Cm4",
        "poe_controller": "TPS23861 (Texas Instruments)",
        # Neither ESP32 nor /proc/pse named the board: fall back to the type.
        "board_model_esp32": "Cruiser",
    }


async def test_gather_unexpected_error_keeps_partial_info(coordinator, root, caplog):
    # A directory where a file is expected: read_bytes raises.
    put(root, "/proc/device-tree/compatible/")
    with caplog.at_level(logging.WARNING):
        info = await coordinator._gather_system_info()
    assert info == {"plugin_version": PLUGIN_VERSION}
    assert "Error gathering system info" in caplog.text


# ---------------------------------------------------------------------------
# Poll: ports the reader marks unavailable are skipped
# ---------------------------------------------------------------------------

async def test_unavailable_addon_port_is_skipped(coordinator):
    coordinator.board_type = BoardType.INTERCEPTOR
    coordinator.addon_boards = ["pse1"]
    coordinator._read_board_temperature = AsyncMock(return_value=None)
    port_data = {
        0: {"available": True, "enabled": True, "state": "power on", "power_watts": 4.0},
        1: {"available": False},
    }
    with patch(f"{COORD}.read_all_addon_ports", AsyncMock(return_value=port_data)):
        data = await coordinator._async_update_data()
    ports = data["poe"]["addon_0"]["ports"]
    assert [p["port"] for p in ports] == [0]
    assert ports[0]["interface"] == "poe8"  # pse1 port 0
    assert data["poe"]["addon_0"]["pse_id"] == "pse1"
    assert data["board_temperature_celsius"] is None


async def test_unavailable_onboard_port_is_skipped(coordinator):
    coordinator.board_type = BoardType.CRUISER
    coordinator.onboard_ports = ["poe0", "poe1", "poe2"]
    coordinator._read_board_temperature = AsyncMock(return_value=48.2)
    port_data = {
        "poe0": {"available": True, "enabled": True, "state": "active", "power_watts": 6.5},
        "poe1": {"available": False},
        # poe2 missing from the reader output entirely
    }
    with patch(f"{COORD}.read_all_onboard_ports", AsyncMock(return_value=port_data)):
        data = await coordinator._async_update_data()
    assert [p["interface"] for p in data["poe"]["onboard"]["ports"]] == ["poe0"]
    assert data["total_enabled_ports"] == 1
    assert data["board_temperature_celsius"] == 48.2


# ---------------------------------------------------------------------------
# Remote port action on a port the board never reported
# ---------------------------------------------------------------------------

async def test_port_action_unknown_port_refused_without_request(coordinator):
    coordinator.entry.data = {CONF_SCOPE: SCOPE_CONTROL}
    coordinator.remote = MagicMock()
    coordinator.remote.port_action = AsyncMock()
    coordinator._remote_ports = [{"port": 0, "pse": 0, "index": 0}]
    with pytest.raises(Exception, match="has not reported port 5"):
        await coordinator.async_port_action(5, "enable")
    coordinator.remote.port_action.assert_not_called()
