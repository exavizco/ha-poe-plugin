"""Tests for tcpdump-based Bosch camera detection.

Covers: tcpdump dependency, broadcast detection, timeout handling,
and device identification fallback chain (ARP → tcpdump → Unknown).
"""
import pytest
from unittest.mock import AsyncMock, patch

from custom_components.exaviz.poe_readers import (
    _detect_bosch_camera,
    _get_connected_device_from_arp,
)


class TestBoschDetection:
    """Bosch camera detection via tcpdump packet capture."""

    @pytest.mark.asyncio
    async def test_tcpdump_not_installed(self):
        """Fails gracefully when tcpdump is missing."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"tcpdump: command not found")
        mock_proc.returncode = 127

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            assert await _detect_bosch_camera("poe6") is None

    @pytest.mark.asyncio
    async def test_bosch_broadcast_detected(self):
        """Detect Bosch camera from proprietary 0x2070 broadcast packets."""
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
            assert await _detect_bosch_camera("poe6") is None

    @pytest.mark.asyncio
    async def test_non_bosch_traffic_returns_none(self):
        generic_output = b"01:23:45.678901 IP 192.168.1.100 > 192.168.1.1: ICMP echo request\n"
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (generic_output, b"")
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            assert await _detect_bosch_camera("poe6") is None


class TestARPDeviceDetection:
    """Device detection from the ARP table."""

    @pytest.mark.asyncio
    async def test_device_found_in_arp(self):
        # ip neigh show dev poe0 → output omits "dev poeX"
        arp_output = b"192.168.1.100 lladdr 00:11:22:33:44:55 REACHABLE\n"
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (arp_output, b"")
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
             patch("custom_components.exaviz.poe_readers.enrich_device_info") as mock_enrich:
            mock_enrich.return_value = {
                "ip_address": "192.168.1.100",
                "mac_address": "00:11:22:33:44:55",
                "manufacturer": "GeoVision",
                "hostname": "camera-1",
            }
            result = await _get_connected_device_from_arp("poe0")

        assert result is not None
        assert result["ip_address"] == "192.168.1.100"
        assert result["manufacturer"] == "GeoVision"

    @pytest.mark.asyncio
    async def test_no_arp_entry_returns_none(self):
        # Empty output means no neighbor entries for this interface
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"")
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await _get_connected_device_from_arp("poe0")
        assert result is None

    @pytest.mark.asyncio
    async def test_arp_command_failure(self):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"Command not found")
        mock_proc.returncode = 1

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await _get_connected_device_from_arp("poe0")
        assert result is None
