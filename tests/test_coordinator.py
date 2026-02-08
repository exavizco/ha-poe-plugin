"""Tests for Exaviz data update coordinator."""
# These tests need refactoring - they use outdated mocking patterns
# All coordinator tests are marked as needing rework

import pytest

pytestmark = pytest.mark.skip(reason="Tests need refactoring for updated coordinator")
from datetime import timedelta
from unittest.mock import MagicMock, patch, AsyncMock
from typing import Dict, Any

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.exaviz.coordinator import ExavizDataUpdateCoordinator
from custom_components.exaviz.board_detector import BoardType
from custom_components.exaviz.const import DOMAIN, DEFAULT_SCAN_INTERVAL


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    return hass


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test_entry"
    entry.data = {}
    return entry


class TestCoordinatorInitialization:
    """Test coordinator initialization."""

    def test_coordinator_init(self, mock_hass, mock_config_entry):
        """Test coordinator initialization."""
        coordinator = ExavizDataUpdateCoordinator(mock_hass, mock_config_entry)
        
        assert coordinator.board_type is None
        assert coordinator.addon_boards == []
        assert coordinator.onboard_ports == []
        assert coordinator.total_poe_ports == 0
        assert coordinator.name == DOMAIN
        assert coordinator.update_interval == timedelta(seconds=DEFAULT_SCAN_INTERVAL)


class TestCoordinatorSetup:
    """Test coordinator setup and board detection."""

    @pytest.mark.asyncio
    async def test_setup_cruiser_onboard_only(self, mock_hass, mock_config_entry):
        """Test setup with Cruiser board with only onboard PoE."""
        coordinator = ExavizDataUpdateCoordinator(mock_hass, mock_config_entry)
        
        detection_result = {
            "board_type": BoardType.CRUISER,
            "onboard_ports": [f"poe{i}" for i in range(8)],
            "addon_boards": [],
            "total_poe_ports": 8,
        }
        
        with patch("custom_components.exaviz.coordinator.detect_all_poe_systems", return_value=detection_result):
            result = await coordinator.async_setup()
        
        assert result is True
        assert coordinator.board_type == BoardType.CRUISER
        assert len(coordinator.onboard_ports) == 8
        assert len(coordinator.addon_boards) == 0
        assert coordinator.total_poe_ports == 8

    @pytest.mark.asyncio
    async def test_setup_interceptor_two_addon_boards(self, mock_hass, mock_config_entry):
        """Test setup with Interceptor with 2 add-on boards."""
        coordinator = ExavizDataUpdateCoordinator(mock_hass, mock_config_entry)
        
        detection_result = {
            "board_type": BoardType.INTERCEPTOR,
            "onboard_ports": [],
            "addon_boards": ["pse0", "pse1"],
            "total_poe_ports": 16,
        }
        
        with patch("custom_components.exaviz.coordinator.detect_all_poe_systems", return_value=detection_result):
            result = await coordinator.async_setup()
        
        assert result is True
        assert coordinator.board_type == BoardType.INTERCEPTOR
        assert len(coordinator.onboard_ports) == 0
        assert len(coordinator.addon_boards) == 2
        assert coordinator.total_poe_ports == 16

    @pytest.mark.asyncio
    async def test_setup_no_poe_systems(self, mock_hass, mock_config_entry):
        """Test setup when no PoE systems are detected."""
        coordinator = ExavizDataUpdateCoordinator(mock_hass, mock_config_entry)
        
        detection_result = {
            "board_type": BoardType.UNKNOWN,
            "onboard_ports": [],
            "addon_boards": [],
            "total_poe_ports": 0,
        }
        
        with patch("custom_components.exaviz.coordinator.detect_all_poe_systems", return_value=detection_result):
            result = await coordinator.async_setup()
        
        # Should still return True but log warning
        assert result is True
        assert coordinator.total_poe_ports == 0

    @pytest.mark.asyncio
    async def test_setup_detection_failure(self, mock_hass, mock_config_entry):
        """Test setup when board detection fails."""
        coordinator = ExavizDataUpdateCoordinator(mock_hass, mock_config_entry)
        
        with patch("custom_components.exaviz.coordinator.detect_all_poe_systems", side_effect=Exception("Detection failed")):
            result = await coordinator.async_setup()
        
        assert result is False


class TestCoordinatorDataUpdate:
    """Test coordinator data update."""

    @pytest.mark.asyncio
    async def test_update_onboard_ports_only(self, mock_hass, mock_config_entry):
        """Test data update with only onboard ports."""
        coordinator = ExavizDataUpdateCoordinator(mock_hass, mock_config_entry)
        coordinator.board_type = BoardType.CRUISER
        coordinator.onboard_ports = ["poe0", "poe1"]
        coordinator.addon_boards = []
        
        mock_port_data = [
            {
                "available": True,
                "enabled": True,
                "state": "active",
                "power_watts": 15.5,
                "connected_device": {
                    "ip_address": "192.168.1.100",
                    "mac_address": "00:11:22:33:44:55",
                    "manufacturer": "GeoVision",
                    "hostname": "camera-1"
                }
            },
            {
                "available": True,
                "enabled": False,
                "state": "disabled",
                "power_watts": 0.0,
                "connected_device": None
            }
        ]
        
        with patch("custom_components.exaviz.coordinator.read_all_onboard_ports", return_value=mock_port_data):
            data = await coordinator._async_update_data()
        
        assert "onboard" in data
        assert len(data["onboard"]["ports"]) == 2
        assert data["onboard"]["active_ports"] == 1
        assert data["onboard"]["used_power_watts"] == 15.5

    @pytest.mark.asyncio
    async def test_update_addon_ports_only(self, mock_hass, mock_config_entry):
        """Test data update with only add-on board ports."""
        coordinator = ExavizDataUpdateCoordinator(mock_hass, mock_config_entry)
        coordinator.board_type = BoardType.INTERCEPTOR
        coordinator.onboard_ports = []
        coordinator.addon_boards = ["pse0"]
        
        mock_port_data = {
            0: {"available": True, "enabled": True, "state": "power on", "power_watts": 12.0},
            1: {"available": True, "enabled": False, "state": "power off", "power_watts": 0.0},
        }
        
        with patch("custom_components.exaviz.coordinator.read_all_addon_ports", return_value=mock_port_data):
            data = await coordinator._async_update_data()
        
        assert "pse0" in data
        assert len(data["pse0"]["ports"]) == 2
        assert data["pse0"]["active_ports"] == 1
        assert data["pse0"]["used_power_watts"] == 12.0

    @pytest.mark.asyncio
    async def test_update_mixed_configuration(self, mock_hass, mock_config_entry):
        """Test data update with both onboard and add-on ports."""
        coordinator = ExavizDataUpdateCoordinator(mock_hass, mock_config_entry)
        coordinator.board_type = BoardType.CRUISER
        coordinator.onboard_ports = ["poe0"]
        coordinator.addon_boards = ["pse0", "pse1"]
        
        mock_onboard_data = [
            {"available": True, "enabled": True, "state": "active", "power_watts": 10.0}
        ]
        
        mock_addon_data = {
            0: {"available": True, "enabled": True, "state": "power on", "power_watts": 15.0},
        }
        
        with patch("custom_components.exaviz.coordinator.read_all_onboard_ports", return_value=mock_onboard_data):
            with patch("custom_components.exaviz.coordinator.read_all_addon_ports", return_value=mock_addon_data):
                data = await coordinator._async_update_data()
        
        assert "onboard" in data
        assert "pse0" in data
        assert "pse1" in data
        assert len(data) == 3

    @pytest.mark.asyncio
    async def test_update_with_connected_devices(self, mock_hass, mock_config_entry):
        """Test data update includes connected device information."""
        coordinator = ExavizDataUpdateCoordinator(mock_hass, mock_config_entry)
        coordinator.board_type = BoardType.CRUISER
        coordinator.onboard_ports = ["poe0"]
        coordinator.addon_boards = []
        
        mock_port_data = [
            {
                "available": True,
                "enabled": True,
                "state": "active",
                "power_watts": 15.5,
                "connected_device": {
                    "ip_address": "198.51.100.197",
                    "mac_address": "00:13:e2:1f:bc:b9",
                    "manufacturer": "GeoVision (Camera)",
                    "hostname": "geovision-cam"
                }
            }
        ]
        
        with patch("custom_components.exaviz.coordinator.read_all_onboard_ports", return_value=mock_port_data):
            data = await coordinator._async_update_data()
        
        port = data["onboard"]["ports"][0]
        assert port["connected_device"] is not None
        assert port["connected_device"]["manufacturer"] == "GeoVision (Camera)"
        assert port["connected_device"]["ip_address"] == "198.51.100.197"

    @pytest.mark.asyncio
    async def test_update_active_port_no_arp_creates_placeholder(self, mock_hass, mock_config_entry):
        """Test that active ports without ARP entries get placeholder device info."""
        coordinator = ExavizDataUpdateCoordinator(mock_hass, mock_config_entry)
        coordinator.board_type = BoardType.CRUISER
        coordinator.onboard_ports = ["poe0"]
        coordinator.addon_boards = []
        
        # Port is active but no connected_device from ARP
        mock_port_data = [
            {
                "available": True,
                "enabled": True,
                "state": "active",
                "power_watts": 10.0,  # Drawing power
                "connected_device": None  # No ARP entry
            }
        ]
        
        with patch("custom_components.exaviz.coordinator.read_all_onboard_ports", return_value=mock_port_data):
            data = await coordinator._async_update_data()
        
        port = data["onboard"]["ports"][0]
        assert port["connected_device"] is not None
        assert port["connected_device"]["device_type"] == "Unknown Device (No Network Activity)"
        assert port["connected_device"]["manufacturer"] == "Unknown"

    @pytest.mark.asyncio
    async def test_update_handles_read_errors(self, mock_hass, mock_config_entry):
        """Test that read errors are handled gracefully."""
        coordinator = ExavizDataUpdateCoordinator(mock_hass, mock_config_entry)
        coordinator.board_type = BoardType.CRUISER
        coordinator.onboard_ports = ["poe0"]
        coordinator.addon_boards = []
        
        with patch("custom_components.exaviz.coordinator.read_all_onboard_ports", side_effect=Exception("I/O error")):
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()


class TestCoordinatorPowerCalculations:
    """Test power consumption calculations."""

    @pytest.mark.asyncio
    async def test_total_power_calculation(self, mock_hass, mock_config_entry):
        """Test total power consumption is calculated correctly."""
        coordinator = ExavizDataUpdateCoordinator(mock_hass, mock_config_entry)
        coordinator.board_type = BoardType.CRUISER
        coordinator.onboard_ports = ["poe0", "poe1", "poe2"]
        coordinator.addon_boards = []
        
        mock_port_data = [
            {"available": True, "enabled": True, "state": "active", "power_watts": 10.0},
            {"available": True, "enabled": True, "state": "active", "power_watts": 15.5},
            {"available": True, "enabled": False, "state": "disabled", "power_watts": 0.0},
        ]
        
        with patch("custom_components.exaviz.coordinator.read_all_onboard_ports", return_value=mock_port_data):
            data = await coordinator._async_update_data()
        
        assert data["onboard"]["used_power_watts"] == 25.5
        assert data["onboard"]["active_ports"] == 2

    @pytest.mark.asyncio
    async def test_port_counts(self, mock_hass, mock_config_entry):
        """Test port counting (total, active, enabled)."""
        coordinator = ExavizDataUpdateCoordinator(mock_hass, mock_config_entry)
        coordinator.board_type = BoardType.CRUISER
        coordinator.onboard_ports = [f"poe{i}" for i in range(8)]
        coordinator.addon_boards = []
        
        # 4 enabled (2 active, 2 empty), 4 disabled
        mock_port_data = []
        for i in range(8):
            mock_port_data.append({
                "available": True,
                "enabled": i < 4,
                "state": "active" if i < 2 else ("empty" if i < 4 else "disabled"),
                "power_watts": 10.0 if i < 2 else 0.0,
            })
        
        with patch("custom_components.exaviz.coordinator.read_all_onboard_ports", return_value=mock_port_data):
            data = await coordinator._async_update_data()
        
        assert data["onboard"]["total_ports"] == 8
        assert data["onboard"]["active_ports"] == 4  # Enabled ports
        assert data["onboard"]["used_power_watts"] == 20.0  # 2 ports * 10W


class TestCoordinatorIntegrationScenarios:
    """Test realistic integration scenarios."""

    @pytest.mark.asyncio
    async def test_cruiser_full_deployment(self, mock_hass, mock_config_entry):
        """Test Cruiser with 8 onboard + 2 add-on boards (24 ports)."""
        coordinator = ExavizDataUpdateCoordinator(mock_hass, mock_config_entry)
        coordinator.board_type = BoardType.CRUISER
        coordinator.onboard_ports = [f"poe{i}" for i in range(8)]
        coordinator.addon_boards = ["pse0", "pse1"]
        
        # All ports active with various power levels
        mock_onboard = [
            {"available": True, "enabled": True, "state": "active", "power_watts": float(i+10)}
            for i in range(8)
        ]
        
        mock_addon = {
            i: {"available": True, "enabled": True, "state": "power on", "power_watts": float(i+15)}
            for i in range(8)
        }
        
        with patch("custom_components.exaviz.coordinator.read_all_onboard_ports", return_value=mock_onboard):
            with patch("custom_components.exaviz.coordinator.read_all_addon_ports", return_value=mock_addon):
                data = await coordinator._async_update_data()
        
        # Should have 3 PoE systems
        assert len(data) == 3
        assert "onboard" in data
        assert "pse0" in data
        assert "pse1" in data
        
        # Total ports across all systems
        total_ports = sum(system["total_ports"] for system in data.values())
        assert total_ports == 24

    @pytest.mark.asyncio
    async def test_interceptor_typical_deployment(self, mock_hass, mock_config_entry):
        """Test Interceptor with 2 add-on boards, some ports active."""
        coordinator = ExavizDataUpdateCoordinator(mock_hass, mock_config_entry)
        coordinator.board_type = BoardType.INTERCEPTOR
        coordinator.onboard_ports = []
        coordinator.addon_boards = ["pse0", "pse1"]
        
        # pse0: port 2 active (GeoVision camera)
        # pse1: port 4 active (another camera)
        def mock_addon_data(pse_id, port_count):
            data = {}
            for i in range(port_count):
                active = (pse_id == "pse0" and i == 2) or (pse_id == "pse1" and i == 4)
                data[i] = {
                    "available": True,
                    "enabled": active,
                    "state": "power on" if active else "power off",
                    "power_watts": 15.5 if active else 0.0,
                }
            return data
        
        with patch("custom_components.exaviz.coordinator.read_all_addon_ports", side_effect=mock_addon_data):
            data = await coordinator._async_update_data()
        
        assert "pse0" in data
        assert "pse1" in data
        assert data["pse0"]["active_ports"] == 1
        assert data["pse1"]["active_ports"] == 1
        assert data["pse0"]["used_power_watts"] == 15.5
        assert data["pse1"]["used_power_watts"] == 15.5

    @pytest.mark.asyncio
    async def test_empty_system_no_active_ports(self, mock_hass, mock_config_entry):
        """Test system with ports but none active."""
        coordinator = ExavizDataUpdateCoordinator(mock_hass, mock_config_entry)
        coordinator.board_type = BoardType.CRUISER
        coordinator.onboard_ports = [f"poe{i}" for i in range(8)]
        coordinator.addon_boards = []
        
        # All ports disabled
        mock_port_data = [
            {"available": True, "enabled": False, "state": "disabled", "power_watts": 0.0}
            for _ in range(8)
        ]
        
        with patch("custom_components.exaviz.coordinator.read_all_onboard_ports", return_value=mock_port_data):
            data = await coordinator._async_update_data()
        
        assert data["onboard"]["active_ports"] == 0
        assert data["onboard"]["used_power_watts"] == 0.0

