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


def _bosch_capture(ascii_column: str) -> bytes:
    """A 0x2070 broadcast as tcpdump -XX prints it, with our text in the ASCII column."""
    return (
        b"listening on poe6, link-type EN10MB (Ethernet)\n"
        b"01:23:45.678901 00:01:31:12:34:56 > ff:ff:ff:ff:ff:ff, ethertype 0x2070, length 128:\n"
        b"        0x0010:  426f 7363 6820 466c 6578 6964 6f6d 6520  "
        + ascii_column.encode()
        + b"\n"
    )


async def _detect(output: bytes):
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (output, b"")
    mock_proc.returncode = 0
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        return await _detect_bosch_camera("poe6")


class TestBoschModelName:
    """The model name is read from the capture without cutting it short."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "ascii_column, expected",
        [
            # A lowercase "n" used to end the match: the pattern was [^\\n]
            # (not backslash, not "n") in a raw string, and case-blind.
            ("Bosch.FLEXIDOME.indoor.5000i", "FLEXIDOME.indoor.5000i"),
            ("Bosch.DINION.inteox.7100i", "DINION.inteox.7100i"),
            ("Bosch.AUTODOME.inteox.7000i", "AUTODOME.inteox.7000i"),
            ("Bosch.NBN-73013-BA", "NBN-73013-BA"),
        ],
    )
    async def test_full_model_name(self, ascii_column, expected):
        result = await _detect(_bosch_capture(ascii_column))
        assert result is not None
        assert result["model"] == expected

    @pytest.mark.asyncio
    async def test_family_match_is_not_case_blind(self):
        """'mic' inside another word is not the MIC camera family."""
        output = _bosch_capture("Bosch.dynamic.cfg") + (
            b"        0x0020:  4d49 432e 4950 2e73 7461 726c 6967 6874  MIC.IP.starlight.7100i\n"
        )
        result = await _detect(output)
        assert result is not None
        assert result["model"] == "MIC.IP.starlight.7100i"

    @pytest.mark.asyncio
    async def test_bosch_without_known_family_keeps_unknown_model(self):
        result = await _detect(_bosch_capture("Bosch.Security.Systems"))
        assert result is not None
        assert result["model"] == "Unknown Model"


class TestVcsConfirmedAsBosch:
    """A VCS OUI is confirmed as Bosch over IPv4 and IPv6 alike."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "arp_line",
        [
            b"192.168.1.50 lladdr 00:07:5f:12:34:56 REACHABLE\n",
            b"fe80::207:5fff:fe12:3456 lladdr 00:07:5f:12:34:56 STALE\n",
        ],
    )
    async def test_vcs_replaced_with_bosch(self, arp_line):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (arp_line, b"")
        mock_proc.returncode = 0
        bosch = {
            "manufacturer": "Bosch Security Systems",
            "model": "FLEXIDOME.IP.5000i",
            "device_type": "Camera",
            "detection_method": "Bosch proprietary protocol",
        }
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
             patch("custom_components.exaviz.poe_readers.enrich_device_info") as mock_enrich, \
             patch("custom_components.exaviz.poe_readers._detect_bosch_camera", return_value=bosch):
            mock_enrich.side_effect = lambda info: {
                **info,
                "manufacturer": "VCS Video Communication Systems AG",
            }
            result = await _get_connected_device_from_arp("poe2")

        assert result["manufacturer"] == "Bosch"
        assert result["model"] == "FLEXIDOME.IP.5000i"

    @pytest.mark.asyncio
    async def test_non_vcs_skips_capture(self):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"192.168.1.60 lladdr 00:11:22:33:44:55 REACHABLE\n", b"")
        mock_proc.returncode = 0
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
             patch("custom_components.exaviz.poe_readers.enrich_device_info") as mock_enrich, \
             patch("custom_components.exaviz.poe_readers._detect_bosch_camera") as mock_detect:
            mock_enrich.side_effect = lambda info: {**info, "manufacturer": "Axis Communications AB"}
            result = await _get_connected_device_from_arp("poe2")

        mock_detect.assert_not_called()
        assert result["manufacturer"] == "Axis Communications AB"
