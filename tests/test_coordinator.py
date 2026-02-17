"""Tests for the data update coordinator."""
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.exaviz.coordinator import ExavizDataUpdateCoordinator
from custom_components.exaviz.board_detector import BoardType
from custom_components.exaviz.const import DOMAIN, DEFAULT_SCAN_INTERVAL


@pytest.fixture
def coordinator(mock_hass, mock_config_entry):
    """Create a coordinator with mocked HA core."""
    c = ExavizDataUpdateCoordinator(mock_hass, mock_config_entry)
    c._read_board_temperature = AsyncMock(return_value=42.0)
    return c


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestInit:
    def test_defaults(self, coordinator):
        assert coordinator.board_type is None
        assert coordinator.addon_boards == []
        assert coordinator.onboard_ports == []
        assert coordinator.total_poe_ports == 0
        assert coordinator.name == DOMAIN
        assert coordinator.update_interval == timedelta(seconds=DEFAULT_SCAN_INTERVAL)


# ---------------------------------------------------------------------------
# Setup / board detection
# ---------------------------------------------------------------------------

class TestSetup:

    @pytest.mark.asyncio
    async def test_cruiser_onboard_only(self, coordinator):
        detection = {
            "board_type": BoardType.CRUISER,
            "onboard_ports": [f"poe{i}" for i in range(8)],
            "addon_boards": [],
            "total_poe_ports": 8,
        }
        with patch("custom_components.exaviz.coordinator.detect_all_poe_systems", return_value=detection), \
             patch.object(coordinator, "_gather_system_info", new_callable=AsyncMock, return_value={}):
            assert await coordinator.async_setup() is True

        assert coordinator.board_type == BoardType.CRUISER
        assert len(coordinator.onboard_ports) == 8
        assert coordinator.total_poe_ports == 8

    @pytest.mark.asyncio
    async def test_interceptor_two_addon(self, coordinator):
        detection = {
            "board_type": BoardType.INTERCEPTOR,
            "onboard_ports": [],
            "addon_boards": ["pse0", "pse1"],
            "total_poe_ports": 16,
        }
        with patch("custom_components.exaviz.coordinator.detect_all_poe_systems", return_value=detection), \
             patch.object(coordinator, "_gather_system_info", new_callable=AsyncMock, return_value={}):
            assert await coordinator.async_setup() is True

        assert coordinator.board_type == BoardType.INTERCEPTOR
        assert len(coordinator.addon_boards) == 2
        assert coordinator.total_poe_ports == 16

    @pytest.mark.asyncio
    async def test_no_poe_systems_returns_false(self, coordinator):
        detection = {
            "board_type": BoardType.UNKNOWN,
            "onboard_ports": [],
            "addon_boards": [],
            "total_poe_ports": 0,
        }
        with patch("custom_components.exaviz.coordinator.detect_all_poe_systems", return_value=detection), \
             patch.object(coordinator, "_gather_system_info", new_callable=AsyncMock, return_value={}):
            assert await coordinator.async_setup() is False

    @pytest.mark.asyncio
    async def test_detection_exception_returns_false(self, coordinator):
        with patch("custom_components.exaviz.coordinator.detect_all_poe_systems", side_effect=Exception("boom")):
            assert await coordinator.async_setup() is False


# ---------------------------------------------------------------------------
# Data updates
# ---------------------------------------------------------------------------

class TestDataUpdate:

    @pytest.mark.asyncio
    async def test_onboard_only(self, coordinator):
        coordinator.board_type = BoardType.CRUISER
        coordinator.onboard_ports = ["poe0", "poe1"]
        coordinator.addon_boards = []

        mock_port_data = {
            "poe0": {"available": True, "enabled": True, "state": "active", "power_watts": 15.5,
                      "connected_device": {"ip_address": "192.168.1.100", "mac_address": "00:11:22:33:44:55",
                                           "manufacturer": "GeoVision", "hostname": "cam-1"}},
            "poe1": {"available": True, "enabled": False, "state": "disabled", "power_watts": 0.0,
                      "connected_device": None},
        }

        with patch("custom_components.exaviz.coordinator.read_all_onboard_ports", return_value=mock_port_data):
            data = await coordinator._async_update_data()

        poe = data["poe"]
        assert "onboard" in poe
        assert len(poe["onboard"]["ports"]) == 2
        assert poe["onboard"]["used_power_watts"] == 15.5

    @pytest.mark.asyncio
    async def test_addon_only(self, coordinator):
        coordinator.board_type = BoardType.INTERCEPTOR
        coordinator.onboard_ports = []
        coordinator.addon_boards = ["pse0"]

        mock_port_data = {
            0: {"available": True, "enabled": True, "state": "power on", "power_watts": 12.0,
                "voltage_volts": 48.0, "current_milliamps": 250, "temperature_celsius": 35.0,
                "class": "3", "allocated_power_watts": 15.4, "connected_device": None},
            1: {"available": True, "enabled": False, "state": "disabled", "power_watts": 0.0,
                "voltage_volts": 0.0, "current_milliamps": 0, "temperature_celsius": 35.0,
                "class": "?", "allocated_power_watts": 15.4, "connected_device": None},
        }

        with patch("custom_components.exaviz.coordinator.read_all_addon_ports", return_value=mock_port_data):
            data = await coordinator._async_update_data()

        poe = data["poe"]
        assert "addon_0" in poe
        assert len(poe["addon_0"]["ports"]) == 2
        assert poe["addon_0"]["used_power_watts"] == 12.0

    @pytest.mark.asyncio
    async def test_active_port_without_arp_gets_placeholder(self, coordinator):
        """Active port with no ARP entry should get 'Unknown Device' placeholder."""
        coordinator.board_type = BoardType.CRUISER
        coordinator.onboard_ports = ["poe0"]
        coordinator.addon_boards = []

        mock_port_data = {
            "poe0": {"available": True, "enabled": True, "state": "active",
                      "power_watts": 10.0, "connected_device": None},
        }

        with patch("custom_components.exaviz.coordinator.read_all_onboard_ports", return_value=mock_port_data):
            data = await coordinator._async_update_data()

        port = data["poe"]["onboard"]["ports"][0]
        assert port["connected_device"] is not None
        assert port["connected_device"]["device_type"] == "Unknown Device (No Network Activity)"

    @pytest.mark.asyncio
    async def test_read_error_raises_update_failed(self, coordinator):
        coordinator.board_type = BoardType.CRUISER
        coordinator.onboard_ports = ["poe0"]
        coordinator.addon_boards = []

        with patch("custom_components.exaviz.coordinator.read_all_onboard_ports", side_effect=Exception("I/O error")):
            with pytest.raises(Exception, match="Error fetching PoE data"):
                await coordinator._async_update_data()


# ---------------------------------------------------------------------------
# Power calculations
# ---------------------------------------------------------------------------

class TestPowerCalculations:

    @pytest.mark.asyncio
    async def test_total_power(self, coordinator):
        coordinator.board_type = BoardType.CRUISER
        coordinator.onboard_ports = ["poe0", "poe1", "poe2"]
        coordinator.addon_boards = []

        mock_port_data = {
            "poe0": {"available": True, "enabled": True, "state": "active", "power_watts": 10.0, "connected_device": None},
            "poe1": {"available": True, "enabled": True, "state": "active", "power_watts": 15.5, "connected_device": None},
            "poe2": {"available": True, "enabled": False, "state": "disabled", "power_watts": 0.0, "connected_device": None},
        }

        with patch("custom_components.exaviz.coordinator.read_all_onboard_ports", return_value=mock_port_data):
            data = await coordinator._async_update_data()

        assert data["poe"]["onboard"]["used_power_watts"] == 25.5
        assert data["poe"]["onboard"]["active_ports"] == 2
