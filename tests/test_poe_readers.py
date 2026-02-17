"""Tests for PoE port readers."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.exaviz.poe_readers import (
    get_allocated_power_watts,
    read_pse_port_status,
    read_network_port_status,
    read_all_onboard_ports,
    read_all_addon_ports,
    _get_connected_device_from_arp,
    _detect_bosch_camera,
)


# ---------------------------------------------------------------------------
# PoE class power allocation
# ---------------------------------------------------------------------------

class TestAllocatedPower:
    @pytest.mark.parametrize("poe_class,expected", [
        ("0", 15.4), ("1", 4.0), ("2", 7.0), ("3", 15.4), ("4", 30.0),
        ("?", 15.4), ("unknown", 15.4),
    ])
    def test_allocation(self, poe_class, expected):
        assert get_allocated_power_watts(poe_class) == expected


# ---------------------------------------------------------------------------
# /proc/pse parsing (add-on board via IP808AR)
# ---------------------------------------------------------------------------

PROC_PSE_SAMPLE = """\
Axzez Interceptor PoE driver version 2.0
0-0: power-on 0 15.50 47.9375 0.05950/0.80000 33.1250/150.0000
0-1: backoff ? 0.00 47.9375 0.00000/0.80000 34.6250/150.0000
0-2: disabled ? 0.00 47.9375 0.00000/0.80000 34.6250/150.0000
0: 47.9375/40.0000-60.0000 0.05950/2.50000 15.50/120
"""


class TestReadPSEPortStatus:
    """Test reading individual PSE port status from /proc/pse."""

    @pytest.mark.asyncio
    async def test_active_port(self):
        mock_result = MagicMock(stdout=PROC_PSE_SAMPLE, stderr="")
        with patch("pathlib.Path.exists", return_value=True), \
             patch("asyncio.to_thread", return_value=mock_result):
            result = await read_pse_port_status("pse0", 0)

        assert result["available"] is True
        assert result["state"] == "power-on"
        assert result["class"] == "0"
        assert result["voltage_volts"] == 47.94
        assert result["current_milliamps"] == 59
        assert result["enabled"] is True

    @pytest.mark.asyncio
    async def test_backoff_port_is_enabled(self):
        """Regression: backoff must be treated as enabled (Oct 2025 fix)."""
        mock_result = MagicMock(stdout=PROC_PSE_SAMPLE, stderr="")
        with patch("pathlib.Path.exists", return_value=True), \
             patch("asyncio.to_thread", return_value=mock_result):
            result = await read_pse_port_status("pse0", 1)

        assert result["state"] == "backoff"
        assert result["enabled"] is True

    @pytest.mark.asyncio
    async def test_disabled_port(self):
        mock_result = MagicMock(stdout=PROC_PSE_SAMPLE, stderr="")
        with patch("pathlib.Path.exists", return_value=True), \
             patch("asyncio.to_thread", return_value=mock_result):
            result = await read_pse_port_status("pse0", 2)

        assert result["state"] == "disabled"
        assert result["enabled"] is False

    @pytest.mark.asyncio
    async def test_proc_pse_not_found(self):
        with patch("pathlib.Path.exists", return_value=False):
            result = await read_pse_port_status("pse0", 0)

        assert result["available"] is False
        assert result["state"] == "unavailable"

    @pytest.mark.asyncio
    async def test_io_error(self):
        with patch("pathlib.Path.exists", side_effect=IOError("Permission denied")):
            result = await read_pse_port_status("pse0", 0)

        assert result["available"] is False


# ---------------------------------------------------------------------------
# PSE-to-port mapping (Cruiser TPS23861 → ESP32)
# ---------------------------------------------------------------------------

class TestCruiserPSEMapping:
    """Verify PSE index calculation: ports 0-3 → PSE 1, ports 4-7 → PSE 0."""

    @pytest.mark.parametrize("linux_port,expected_pse,expected_pse_port", [
        (0, 1, 0), (1, 1, 1), (2, 1, 2), (3, 1, 3),
        (4, 0, 0), (5, 0, 1), (6, 0, 2), (7, 0, 3),
    ])
    def test_forward_mapping(self, linux_port, expected_pse, expected_pse_port):
        pse_num = 1 if linux_port < 4 else 0
        pse_port = linux_port % 4
        assert (pse_num, pse_port) == (expected_pse, expected_pse_port)

    def test_real_world_camera_scenario(self):
        """Cameras on P2, P6, P7, P8 → poe1, poe5, poe6, poe7."""
        esp32_powered = {(1, 1), (0, 1), (0, 2), (0, 3)}
        expected_linux = {1, 5, 6, 7}
        actual_linux = set()
        for pse, port in esp32_powered:
            linux = port + (0 if pse == 1 else 4)
            actual_linux.add(linux)
        assert actual_linux == expected_linux


# ---------------------------------------------------------------------------
# Bulk port reads
# ---------------------------------------------------------------------------

class TestReadAllOnboardPorts:

    @pytest.mark.asyncio
    async def test_eight_ports(self):
        async def mock_read(interface, esp32_data_map=None):
            port_num = int(interface.replace("poe", ""))
            return {
                "available": True,
                "enabled": port_num % 2 == 0,
                "state": "active" if port_num % 2 == 0 else "disabled",
                "power_watts": 10.0 if port_num % 2 == 0 else 0.0,
            }

        with patch("custom_components.exaviz.poe_readers.read_network_port_status", side_effect=mock_read), \
             patch("custom_components.exaviz.poe_readers._get_connected_device_from_arp", return_value=None):
            result = await read_all_onboard_ports([f"poe{i}" for i in range(8)])

        assert len(result) == 8
        assert result["poe0"]["enabled"] is True
        assert result["poe1"]["enabled"] is False

    @pytest.mark.asyncio
    async def test_empty_list(self):
        result = await read_all_onboard_ports([])
        assert len(result) == 0


class TestReadAllAddonPorts:

    @pytest.mark.asyncio
    async def test_eight_ports(self):
        async def mock_read(pse_id, port_num):
            return {
                "available": True,
                "enabled": port_num < 4,
                "state": "power on" if port_num < 4 else "power off",
                "power_watts": 12.0 if port_num < 4 else 0.0,
                "voltage_volts": 48.0,
                "current_milliamps": 250 if port_num < 4 else 0,
                "temperature_celsius": 35.0,
                "class": "3",
            }

        with patch("custom_components.exaviz.poe_readers.read_pse_port_status", side_effect=mock_read), \
             patch("custom_components.exaviz.poe_readers._get_connected_device_from_arp", return_value=None):
            result = await read_all_addon_ports("pse0", port_count=8)

        assert len(result) == 8
        assert result[0]["enabled"] is True
        assert result[5]["enabled"] is False

    @pytest.mark.asyncio
    async def test_error_in_single_port_does_not_crash(self):
        call_count = 0

        async def mock_read(pse_id, port_num):
            nonlocal call_count
            call_count += 1
            if port_num == 3:
                raise Exception("Simulated I/O error")
            return {"available": True, "enabled": True, "state": "power on", "power_watts": 10.0}

        with patch("custom_components.exaviz.poe_readers.read_pse_port_status", side_effect=mock_read), \
             patch("custom_components.exaviz.poe_readers._get_connected_device_from_arp", return_value=None):
            result = await read_all_addon_ports("pse0", port_count=5)

        assert call_count == 5
        assert len(result) == 5
        assert result[3].get("available") is False or "error" in result[3]


# ---------------------------------------------------------------------------
# Bosch camera detection via tcpdump
# ---------------------------------------------------------------------------

class TestBoschCameraDetection:

    @pytest.mark.asyncio
    async def test_tcpdump_not_installed(self):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"tcpdump: command not found")
        mock_proc.returncode = 127

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await _detect_bosch_camera("poe6")
        assert result is None

    @pytest.mark.asyncio
    async def test_bosch_broadcast_detected(self):
        bosch_output = (
            b"tcpdump: verbose output suppressed\n"
            b"listening on poe6, link-type EN10MB (Ethernet)\n"
            b'01:23:45.678901 00:01:31:12:34:56 > ff:ff:ff:ff:ff:ff, ethertype 0x2070, length 128:\n'
            b"        0x0010:  426f 7363 6820 466c 6578 6964 6f6d 6520  Bosch.FLEXIDOME.\n"
        )
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (bosch_output, b"")
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await _detect_bosch_camera("poe6")

        assert result is not None
        assert result["manufacturer"] == "Bosch Security Systems"
        assert "FLEXIDOME" in result.get("model", "")

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 124

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await _detect_bosch_camera("poe6")
        assert result is None

    @pytest.mark.asyncio
    async def test_non_bosch_traffic_returns_none(self):
        generic_output = b"01:23:45.678901 IP 192.168.1.100 > 192.168.1.1: ICMP echo request\n"
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (generic_output, b"")
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await _detect_bosch_camera("poe6")
        assert result is None


# ---------------------------------------------------------------------------
# Integration scenarios
# ---------------------------------------------------------------------------

class TestIntegrationScenarios:

    @pytest.mark.asyncio
    async def test_cruiser_full_config(self):
        async def mock_read(interface, esp32_data_map=None):
            port_num = int(interface.replace("poe", ""))
            return {"available": True, "enabled": True, "state": "active", "power_watts": 10.0 + port_num}

        with patch("custom_components.exaviz.poe_readers.read_network_port_status", side_effect=mock_read), \
             patch("custom_components.exaviz.poe_readers._get_connected_device_from_arp", return_value=None):
            result = await read_all_onboard_ports([f"poe{i}" for i in range(8)])

        assert len(result) == 8
        assert result["poe0"]["power_watts"] == 10.0
        assert result["poe7"]["power_watts"] == 17.0

    @pytest.mark.asyncio
    async def test_interceptor_two_addon_boards(self):
        async def mock_read(pse_id, port_num):
            return {
                "available": True,
                "enabled": port_num in [2, 4],
                "state": "power on" if port_num in [2, 4] else "power off",
                "power_watts": 15.5 if port_num in [2, 4] else 0.0,
            }

        with patch("custom_components.exaviz.poe_readers.read_pse_port_status", side_effect=mock_read), \
             patch("custom_components.exaviz.poe_readers._get_connected_device_from_arp", return_value=None):
            pse0 = await read_all_addon_ports("pse0", port_count=8)
            pse1 = await read_all_addon_ports("pse1", port_count=8)

        assert len(pse0) == 8
        assert len(pse1) == 8
        active = [p for p in pse0.values() if p["enabled"]]
        assert len(active) == 2
