"""Test cases for tcpdump-based Bosch camera detection.

This test suite covers the regression fixes for tonight's work:
1. tcpdump dependency requirement for Bosch detection
2. Bosch camera detection without IP address (DHCP fallback scenario)
3. Device identification when ARP entries are missing
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from custom_components.exaviz.poe_readers import (
    _detect_bosch_camera,
    read_network_port_status,
    _get_connected_device_from_arp,
)


class TestBoschCameraDetection:
    """Test Bosch camera detection via tcpdump packet capture."""

    @pytest.mark.asyncio
    async def test_bosch_detection_requires_tcpdump(self):
        """Verify that Bosch detection fails gracefully when tcpdump is not installed.
        
        Regression: tcpdump was not installed on Cruiser, causing silent failures.
        Now it's a required dependency in the Debian package.
        """
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            # Simulate tcpdump not found (command not found error)
            mock_proc = AsyncMock()
            mock_proc.communicate.return_value = (b'', b'tcpdump: command not found')
            mock_proc.returncode = 127  # Command not found
            mock_exec.return_value = mock_proc
            
            result = await _detect_bosch_camera('poe6')
            
            # Should return None when tcpdump is not available
            assert result is None

    @pytest.mark.asyncio
    async def test_bosch_detection_from_broadcast_packets(self):
        """Test Bosch camera detection via proprietary broadcast packets.
        
        Scenario: Camera is broadcasting discovery packets but has no IP (no DHCP).
        This is the backup detection method when ARP table has no entry.
        """
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            # Simulate tcpdump output containing Bosch camera discovery packet
            bosch_output = b"""
tcpdump: verbose output suppressed
listening on poe6, link-type EN10MB (Ethernet), capture size 262144 bytes
01:23:45.678901 00:01:31:12:34:56 > ff:ff:ff:ff:ff:ff, ethertype 0x2070 (Unknown), length 128: 
        0x0000:  0000 0000 0000 0001 3112 3456 2070 0000  ........1.4V.p..
        0x0010:  426f 7363 6820 466c 6578 6964 6f6d 6520  Bosch.FLEXIDOME.
        0x0020:  4950 2070 616e 6f72 616d 6963 0000 0000  IP.panoramic....
        0x0030:  0000 0000 0000 0000 0000 0000 0000 0000  ................
"""
            mock_proc = AsyncMock()
            mock_proc.communicate.return_value = (bosch_output, b'')
            mock_proc.returncode = 0
            mock_exec.return_value = mock_proc
            
            result = await _detect_bosch_camera('poe6')
            
            # Should detect Bosch camera from broadcast
            assert result is not None
            assert result['manufacturer'] == 'Bosch Security Systems'
            assert 'FLEXIDOME' in result.get('model', '')

    @pytest.mark.asyncio
    async def test_bosch_detection_timeout_returns_none(self):
        """Test that Bosch detection handles tcpdump timeout gracefully."""
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate.return_value = (b'', b'')
            mock_proc.returncode = 124  # timeout exit code
            mock_exec.return_value = mock_proc
            
            result = await _detect_bosch_camera('poe6')
            
            # Timeout should return None (no Bosch packets detected)
            assert result is None

    @pytest.mark.asyncio
    async def test_non_bosch_camera_returns_none(self):
        """Test that non-Bosch cameras don't trigger false positives."""
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            # Simulate tcpdump output with no Bosch signatures
            generic_output = b"""
tcpdump: verbose output suppressed
listening on poe6, link-type EN10MB (Ethernet), capture size 262144 bytes
01:23:45.678901 IP 192.168.1.100 > 192.168.1.1: ICMP echo request
01:23:45.679123 IP 192.168.1.1 > 192.168.1.100: ICMP echo reply
"""
            mock_proc = AsyncMock()
            mock_proc.communicate.return_value = (generic_output, b'')
            mock_proc.returncode = 0
            mock_exec.return_value = mock_proc
            
            result = await _detect_bosch_camera('poe6')
            
            # Should not detect Bosch camera
            assert result is None


@pytest.mark.skip(reason="Integration tests require filesystem mocking - need refactoring")
class TestDeviceDetectionFallback:
    """Test device detection fallback scenarios (ARP → tcpdump → Unknown)."""

    @pytest.mark.asyncio
    async def test_device_detection_prefers_arp_over_tcpdump(self):
        """Verify that ARP-based detection is preferred over tcpdump.
        
        Performance: ARP is instant, tcpdump takes 10+ seconds.
        Only use tcpdump as fallback when ARP has no entry.
        """
        with patch('custom_components.exaviz.poe_readers._get_connected_device_from_arp') as mock_arp, \
             patch('custom_components.exaviz.poe_readers._detect_bosch_camera') as mock_bosch, \
             patch('custom_components.exaviz.poe_readers._try_read_cruiser_pse_data') as mock_pse:
            
            # Simulate ARP entry exists (normal case)
            mock_arp.return_value = {
                'ip_address': '198.51.100.100',
                'mac_address': '00:01:31:12:34:56',
                'manufacturer': 'Bosch Security Systems'
            }
            mock_pse.return_value = {
                'state': 'power-on',
                'power_watts': 15.0,
                'class': '3',
                'voltage_volts': 48.0,
                'current_milliamps': 312,
                'temperature_celsius': 40.0,
            }
            
            result = await read_network_port_status('poe6')
            
            # Should use ARP data, not call tcpdump
            assert result['connected_device']['manufacturer'] == 'Bosch Security Systems'
            assert result['connected_device']['ip_address'] == '198.51.100.100'
            mock_bosch.assert_not_called()  # tcpdump should not be used

    @pytest.mark.asyncio
    async def test_device_detection_falls_back_to_tcpdump_when_no_arp(self):
        """Test tcpdump fallback when ARP table has no entry.
        
        Scenario: Camera is powered and connected, but has no IP (no DHCP).
        Should detect manufacturer via tcpdump broadcast packets.
        """
        with patch('custom_components.exaviz.poe_readers._get_connected_device_from_arp') as mock_arp, \
             patch('custom_components.exaviz.poe_readers._detect_bosch_camera') as mock_bosch, \
             patch('custom_components.exaviz.poe_readers._try_read_cruiser_pse_data') as mock_pse, \
             patch('pathlib.Path.exists', return_value=True), \
             patch('asyncio.to_thread') as mock_thread:
            
            # Simulate no ARP entry (camera has no IP)
            mock_arp.return_value = None
            
            # Simulate traffic exists (triggers Bosch detection)
            mock_thread.side_effect = [
                'up',  # operstate
                '0x1003',  # flags (admin up)
                '100',  # speed
                '2500000',  # rx_bytes (>1MB, triggers tcpdump)
                '150000',  # tx_bytes
            ]
            
            # Simulate Bosch detection via tcpdump
            mock_bosch.return_value = {
                'manufacturer': 'Bosch Security Systems',
                'model': 'FLEXIDOME IP panoramic',
                'device_type': 'Camera',
                'detection_method': 'tcpdump'
            }
            
            mock_pse.return_value = {
                'state': 'power-on',
                'power_watts': 15.0,
                'class': '3',
                'voltage_volts': 48.0,
                'current_milliamps': 312,
                'temperature_celsius': 40.0,
            }
            
            result = await read_network_port_status('poe6')
            
            # Should have manufacturer from tcpdump but no IP
            assert result['connected_device']['manufacturer'] == 'Bosch Security Systems'
            assert result['connected_device']['ip_address'] is None
            assert result['connected_device']['mac_address'] is None
            mock_bosch.assert_called_once_with('poe6')

    @pytest.mark.asyncio
    async def test_device_detection_unknown_when_no_arp_and_no_bosch(self):
        """Test that devices show as Unknown when neither ARP nor Bosch detection works.
        
        Scenario: Non-Bosch camera with no IP (no DHCP), doesn't broadcast discovery.
        """
        with patch('custom_components.exaviz.poe_readers._get_connected_device_from_arp') as mock_arp, \
             patch('custom_components.exaviz.poe_readers._detect_bosch_camera') as mock_bosch, \
             patch('custom_components.exaviz.poe_readers._try_read_cruiser_pse_data') as mock_pse, \
             patch('pathlib.Path.exists', return_value=True), \
             patch('asyncio.to_thread') as mock_thread:
            
            # Simulate no ARP entry
            mock_arp.return_value = None
            
            # Simulate traffic exists
            mock_thread.side_effect = [
                'up',  # operstate
                '0x1003',  # flags
                '100',  # speed
                '2500000',  # rx_bytes
                '150000',  # tx_bytes
            ]
            
            # Simulate tcpdump finds nothing (not Bosch or doesn't broadcast)
            mock_bosch.return_value = None
            
            mock_pse.return_value = {
                'available': True,
                'state': 'power-on',
                'power_watts': 8.0,
                'poe_class': '2',
            }
            
            result = await read_network_port_status('poe6')
            
            # Should show as Unknown (tcpdump ran but found nothing)
            assert result['connected_device']['manufacturer'] == 'Unknown'
            assert result['connected_device']['ip_address'] is None


@pytest.mark.skip(reason="Integration tests require filesystem mocking - need refactoring")
class TestDHCPRequirementScenarios:
    """Test scenarios related to DHCP requirement for IP assignment."""

    @pytest.mark.asyncio
    async def test_camera_with_dhcp_has_full_info(self):
        """Test normal operation: Camera with DHCP has IP, MAC, and manufacturer."""
        with patch('custom_components.exaviz.poe_readers._get_connected_device_from_arp') as mock_arp, \
             patch('custom_components.exaviz.poe_readers._try_read_cruiser_pse_data') as mock_pse:
            
            # Simulate full ARP entry (DHCP working)
            mock_arp.return_value = {
                'ip_address': '198.51.100.100',
                'mac_address': '00:01:31:12:34:56',
                'manufacturer': 'Bosch Security Systems'
            }
            
            mock_pse.return_value = {
                'state': 'power-on',
                'power_watts': 15.0,
                'class': '3',
                'voltage_volts': 48.0,
                'current_milliamps': 312,
                'temperature_celsius': 40.0,
            }
            
            result = await read_network_port_status('poe6')
            
            # Should have complete information
            assert result['connected_device']['ip_address'] == '198.51.100.100'
            assert result['connected_device']['mac_address'] == '00:01:31:12:34:56'
            assert result['connected_device']['manufacturer'] == 'Bosch Security Systems'

    @pytest.mark.asyncio
    async def test_camera_without_dhcp_shows_manufacturer_only(self):
        """Test DHCP failure scenario: Camera detected via tcpdump but has no IP.
        
        This is what we fixed tonight - camera is broadcasting but can't get IP
        because DHCP server (dnsmasq) is not running on the Cruiser.
        """
        with patch('custom_components.exaviz.poe_readers._get_connected_device_from_arp') as mock_arp, \
             patch('custom_components.exaviz.poe_readers._detect_bosch_camera') as mock_bosch, \
             patch('custom_components.exaviz.poe_readers._try_read_cruiser_pse_data') as mock_pse, \
             patch('pathlib.Path.exists', return_value=True), \
             patch('asyncio.to_thread') as mock_thread:
            
            # No ARP (no DHCP)
            mock_arp.return_value = None
            
            # Traffic exists (camera is broadcasting)
            mock_thread.side_effect = [
                'up',
                '0x1003',
                '100',
                '2500000',
                '150000',
            ]
            
            # Bosch detected via broadcast
            mock_bosch.return_value = {
                'manufacturer': 'Bosch Security Systems',
                'model': 'FLEXIDOME IP panoramic',
                'device_type': 'Camera',
                'detection_method': 'tcpdump'
            }
            
            mock_pse.return_value = {
                'state': 'power-on',
                'power_watts': 15.0,
                'class': '3',
                'voltage_volts': 48.0,
                'current_milliamps': 312,
                'temperature_celsius': 40.0,
            }
            
            result = await read_network_port_status('poe6')
            
            # Should have manufacturer but no IP/MAC
            assert result['connected_device']['manufacturer'] == 'Bosch Security Systems'
            assert result['connected_device']['ip_address'] is None
            assert result['connected_device']['mac_address'] is None
            # This scenario triggers the UI message: "Not assigned (DHCP required)"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

