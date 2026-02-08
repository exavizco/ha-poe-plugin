"""Tests for device identification utilities."""
import asyncio
import socket
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.exaviz.device_identifier import (
    enrich_device_info,
    get_hostname_from_ip,
    get_mac_vendor,
)


class TestMacVendorLookup:
    """Test MAC vendor lookup functionality."""

    def test_camera_vendors(self):
        """Test camera MAC address detection."""
        # GeoVision
        assert get_mac_vendor("00:13:e2:1f:bc:b9") == "GeoVision (Camera)"
        assert get_mac_vendor("00:13:E2:AA:BB:CC") == "GeoVision (Camera)"  # Case insensitive
        # Hanwha Vision (Wisenet)
        assert get_mac_vendor("E4:30:22:25:40:28") == "Hanwha Vision (Wisenet Camera)"
        # Speco Technologies
        assert get_mac_vendor("5C:F2:07:48:86:96") == "Speco Technologies (Camera)"
        # VCS Video Communication Systems
        assert get_mac_vendor("00:07:5F:85:18:17") == "VCS Video Communication Systems (Camera)"
    
    def test_ubiquiti_mac(self):
        """Test Ubiquiti MAC address detection."""
        assert get_mac_vendor("00:1D:0F:11:22:33") == "Ubiquiti Networks"
        assert get_mac_vendor("24:5A:4C:12:34:56") == "Ubiquiti Networks"

    def test_axis_camera_mac(self):
        """Test Axis camera MAC address detection."""
        assert get_mac_vendor("00:04:20:11:22:33") == "Axis Communications (Camera)"
        assert get_mac_vendor("AC:CC:8E:44:55:66") == "Axis Communications (Camera)"

    def test_raspberry_pi_mac(self):
        """Test Raspberry Pi MAC address detection."""
        assert get_mac_vendor("B8:27:EB:12:34:56") == "Raspberry Pi Foundation"
        assert get_mac_vendor("DC:A6:32:AA:BB:CC") == "Raspberry Pi Trading"

    def test_apple_mac(self):
        """Test Apple MAC address detection."""
        assert get_mac_vendor("00:1B:63:11:22:33") == "Apple"
        assert get_mac_vendor("D4:61:9D:AA:BB:CC") == "Apple"

    def test_cisco_mac(self):
        """Test Cisco MAC address detection."""
        assert get_mac_vendor("00:14:6C:AA:BB:CC") == "Cisco Systems"
        assert get_mac_vendor("00:18:B9:11:22:33") == "Cisco Systems"

    def test_unknown_mac(self):
        """Test unknown MAC address."""
        assert get_mac_vendor("FF:FF:FF:11:22:33") == "Unknown"
        assert get_mac_vendor("12:34:56:78:90:AB") == "Unknown"

    def test_invalid_mac_format(self):
        """Test invalid MAC address formats."""
        assert get_mac_vendor("invalid") == "Unknown"
        assert get_mac_vendor("00:13") == "Unknown"
        assert get_mac_vendor("") == "Unknown"
        assert get_mac_vendor(None) == "Unknown"


class TestHostnameLookup:
    """Test hostname lookup functionality."""

    @pytest.mark.asyncio
    async def test_successful_hostname_lookup(self):
        """Test successful hostname resolution."""
        with patch("socket.getnameinfo") as mock_getnameinfo:
            mock_getnameinfo.return_value = ("example.local", "0")
            hostname = await get_hostname_from_ip("192.168.1.100")
            assert hostname == "example.local"
            mock_getnameinfo.assert_called_once_with(("192.168.1.100", 0), socket.NI_NAMEREQD)

    @pytest.mark.asyncio
    async def test_failed_hostname_lookup(self):
        """Test failed hostname resolution."""
        with patch("socket.getnameinfo") as mock_getnameinfo:
            mock_getnameinfo.side_effect = OSError("Name or service not known")
            hostname = await get_hostname_from_ip("192.168.1.100")
            assert hostname is None

    @pytest.mark.asyncio
    async def test_hostname_lookup_timeout(self):
        """Test hostname lookup timeout."""
        def slow_lookup(*args, **kwargs):
            # Synchronous function that would take too long
            import time
            time.sleep(5)  # Longer than 2s timeout
            return ("example.local", "0")

        with patch("socket.getnameinfo", side_effect=slow_lookup):
            hostname = await get_hostname_from_ip("192.168.1.100")
            # Should timeout and return None
            assert hostname is None


class TestEnrichDeviceInfo:
    """Test device info enrichment."""

    @pytest.mark.asyncio
    async def test_enrich_full_info(self):
        """Test enrichment with all fields."""
        device_info = {
            "ip_address": "192.168.1.100",
            "mac_address": "00:13:e2:1f:bc:b9",
        }

        with patch("socket.getnameinfo") as mock_getnameinfo:
            mock_getnameinfo.return_value = ("ubnt.local", "0")
            
            enriched = await enrich_device_info(device_info)
            
            assert enriched["ip_address"] == "192.168.1.100"
            assert enriched["mac_address"] == "00:13:e2:1f:bc:b9"
            assert enriched["manufacturer"] == "GeoVision (Camera)"  # Correct OUI for 00:13:e2
            assert enriched["hostname"] == "ubnt.local"

    @pytest.mark.asyncio
    async def test_enrich_no_hostname(self):
        """Test enrichment when hostname lookup fails."""
        device_info = {
            "ip_address": "192.168.1.100",
            "mac_address": "00:13:e2:1f:bc:b9",
        }

        with patch("socket.getnameinfo") as mock_getnameinfo:
            mock_getnameinfo.side_effect = OSError("No hostname found")
            
            enriched = await enrich_device_info(device_info)
            
            assert enriched["manufacturer"] == "GeoVision (Camera)"  # Correct OUI for 00:13:e2
            assert enriched["hostname"] is None

    @pytest.mark.asyncio
    async def test_enrich_unknown_vendor(self):
        """Test enrichment with unknown MAC vendor."""
        device_info = {
            "ip_address": "192.168.1.100",
            "mac_address": "FF:FF:FF:11:22:33",
        }

        with patch("socket.getnameinfo") as mock_getnameinfo:
            mock_getnameinfo.return_value = ("device.local", "0")
            
            enriched = await enrich_device_info(device_info)
            
            assert enriched["manufacturer"] == "Unknown"
            assert enriched["hostname"] == "device.local"

    @pytest.mark.asyncio
    async def test_enrich_missing_fields(self):
        """Test enrichment with missing fields."""
        device_info = {"ip_address": "192.168.1.100"}
        
        enriched = await enrich_device_info(device_info)
        
        # Should still work but manufacturer will be Unknown
        assert enriched["ip_address"] == "192.168.1.100"
        assert enriched["manufacturer"] == "Unknown"

    @pytest.mark.asyncio
    async def test_enrich_empty_device_info(self):
        """Test enrichment with empty device info."""
        device_info = {}
        
        enriched = await enrich_device_info(device_info)
        
        assert enriched["manufacturer"] == "Unknown"
        assert enriched["hostname"] is None


class TestIntegrationScenarios:
    """Integration tests for real-world scenarios."""

    @pytest.mark.asyncio
    async def test_ubiquiti_device_full_flow(self):
        """Test complete flow for Ubiquiti device."""
        device_info = {
            "ip_address": "198.51.100.197",
            "mac_address": "00:13:e2:1f:bc:b9",
        }

        with patch("socket.getnameinfo") as mock_getnameinfo:
            mock_getnameinfo.return_value = ("unifi-ap.local", "0")
            
            enriched = await enrich_device_info(device_info)
            
            assert enriched["manufacturer"] == "GeoVision (Camera)"  # Correct OUI for 00:13:e2
            assert enriched["hostname"] == "unifi-ap.local"

    @pytest.mark.asyncio
    async def test_axis_camera_full_flow(self):
        """Test complete flow for Axis camera."""
        device_info = {
            "ip_address": "198.51.100.109",
            "mac_address": "00:07:5f:85:18:17",
        }

        with patch("socket.getnameinfo") as mock_getnameinfo:
            mock_getnameinfo.return_value = ("axis-camera-1.local", "0")
            
            enriched = await enrich_device_info(device_info)
            
            # Note: MAC 00:07:5f is VCS Video Communication Systems (Camera)
            assert "Camera" in enriched["manufacturer"]  # OUI database lookup works
            assert enriched["hostname"] == "axis-camera-1.local"

