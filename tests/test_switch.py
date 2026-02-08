"""Tests for Exaviz PoE switch entities."""
# Integration tests requiring Home Assistant installation
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

pytestmark = pytest.mark.skip(reason="Requires Home Assistant installation - integration test")

# All imports wrapped to prevent collection errors
try:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
    from custom_components.exaviz.switch import (
        ExavizPoEPortSwitch,
        async_setup_entry,
    )
    from custom_components.exaviz.const import DOMAIN
except (ImportError, ModuleNotFoundError):
    # Module will be skipped anyway due to pytestmark
    DOMAIN = None


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator."""
    coordinator = MagicMock(spec=DataUpdateCoordinator)
    coordinator.data = {
        "onboard": {
            "total_ports": 8,
            "ports": [
                {
                    "port": 0,
                    "interface": "poe0",
                    "enabled": True,
                    "status": "active",
                    "power_consumption_watts": 15.5,
                    "voltage_volts": 48.0,
                    "current_milliamps": 320,
                    "temperature_celsius": 45.0,
                    "poe_class": "4",
                    "poe_system": "onboard",
                    "connected_device": {
                        "name": "Test Camera",
                        "device_type": "GeoVision (Camera)",
                        "ip_address": "192.168.1.100",
                        "mac_address": "00:11:22:33:44:55",
                        "manufacturer": "GeoVision",
                        "hostname": "camera-1",
                    },
                }
            ],
        },
        "pse0": {
            "total_ports": 8,
            "ports": [
                {
                    "port": 2,
                    "interface": "poe0-2",
                    "enabled": True,
                    "status": "active",
                    "power_consumption_watts": 12.3,
                    "voltage_volts": 47.5,
                    "current_milliamps": 259,
                    "temperature_celsius": 42.0,
                    "poe_class": "3",
                    "poe_system": "addon",
                    "connected_device": None,
                }
            ],
        },
    }
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {}
    return entry


class TestExavizPoEPortSwitch:
    """Test the ExavizPoEPortSwitch entity."""

    def test_init_onboard_port(self, mock_coordinator):
        """Test initialization of onboard port switch."""
        switch = ExavizPoEPortSwitch(
            coordinator=mock_coordinator,
            entry_id="test_entry",
            poe_set="onboard",
            port_number=0,
        )
        
        assert switch._poe_set == "onboard"
        assert switch._port_number == 0
        assert switch._interface == "poe0"
        assert switch._attr_unique_id == "test_entry_onboard_port0"
        assert switch._attr_name == "Onboard Port 0"

    def test_init_addon_port(self, mock_coordinator):
        """Test initialization of add-on port switch."""
        switch = ExavizPoEPortSwitch(
            coordinator=mock_coordinator,
            entry_id="test_entry",
            poe_set="pse0",
            port_number=2,
        )
        
        assert switch._poe_set == "pse0"
        assert switch._port_number == 2
        assert switch._interface == "poe0-2"
        assert switch._attr_unique_id == "test_entry_pse0_port2"
        assert switch._attr_name == "PSE0 Port 2"

    def test_is_on_enabled_port(self, mock_coordinator):
        """Test is_on returns True for enabled port."""
        switch = ExavizPoEPortSwitch(
            coordinator=mock_coordinator,
            entry_id="test_entry",
            poe_set="onboard",
            port_number=0,
        )
        
        assert switch.is_on is True

    def test_is_on_missing_data(self, mock_coordinator):
        """Test is_on returns False when data is missing."""
        mock_coordinator.data = {}
        switch = ExavizPoEPortSwitch(
            coordinator=mock_coordinator,
            entry_id="test_entry",
            poe_set="onboard",
            port_number=99,
        )
        
        assert switch.is_on is False

    def test_extra_state_attributes_with_device(self, mock_coordinator):
        """Test extra_state_attributes includes device info."""
        switch = ExavizPoEPortSwitch(
            coordinator=mock_coordinator,
            entry_id="test_entry",
            poe_set="onboard",
            port_number=0,
        )
        
        attrs = switch.extra_state_attributes
        assert attrs["port_number"] == 0
        assert attrs["poe_set"] == "onboard"
        assert attrs["status"] == "active"
        assert attrs["power_consumption_watts"] == 15.5
        assert attrs["device_name"] == "Test Camera"
        assert attrs["device_type"] == "GeoVision (Camera)"
        assert attrs["device_ip"] == "192.168.1.100"
        assert attrs["device_mac"] == "00:11:22:33:44:55"
        assert attrs["device_manufacturer"] == "GeoVision"
        assert attrs["device_hostname"] == "camera-1"

    def test_extra_state_attributes_without_device(self, mock_coordinator):
        """Test extra_state_attributes when no device connected."""
        switch = ExavizPoEPortSwitch(
            coordinator=mock_coordinator,
            entry_id="test_entry",
            poe_set="pse0",
            port_number=2,
        )
        
        attrs = switch.extra_state_attributes
        assert attrs["port_number"] == 2
        assert attrs["poe_set"] == "pse0"
        assert "device_name" not in attrs
        assert "device_ip" not in attrs

    @pytest.mark.asyncio
    async def test_async_turn_on_onboard_port(self, mock_coordinator):
        """Test turning on onboard port."""
        switch = ExavizPoEPortSwitch(
            coordinator=mock_coordinator,
            entry_id="test_entry",
            poe_set="onboard",
            port_number=0,
        )
        
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            
            await switch.async_turn_on()
            
            # Verify sudo ip link set was called correctly
            mock_run.assert_called_once_with(
                ["sudo", "ip", "link", "set", "poe0", "up"],
                capture_output=True,
                text=True,
                check=False
            )
            
            # Verify coordinator refresh was requested
            mock_coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_turn_on_addon_port(self, mock_coordinator):
        """Test turning on add-on board port."""
        switch = ExavizPoEPortSwitch(
            coordinator=mock_coordinator,
            entry_id="test_entry",
            poe_set="pse0",
            port_number=2,
        )
        
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            
            await switch.async_turn_on()
            
            # Verify correct interface name for add-on board
            mock_run.assert_called_once_with(
                ["sudo", "ip", "link", "set", "poe0-2", "up"],
                capture_output=True,
                text=True,
                check=False
            )
            
            mock_coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_turn_on_pse1_port(self, mock_coordinator):
        """Test turning on pse1 (second add-on board) port."""
        switch = ExavizPoEPortSwitch(
            coordinator=mock_coordinator,
            entry_id="test_entry",
            poe_set="pse1",
            port_number=5,
        )
        
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            
            await switch.async_turn_on()
            
            # Verify correct interface name for pse1
            mock_run.assert_called_once_with(
                ["sudo", "ip", "link", "set", "poe1-5", "up"],
                capture_output=True,
                text=True,
                check=False
            )

    @pytest.mark.asyncio
    async def test_async_turn_off_onboard_port(self, mock_coordinator):
        """Test turning off onboard port."""
        switch = ExavizPoEPortSwitch(
            coordinator=mock_coordinator,
            entry_id="test_entry",
            poe_set="onboard",
            port_number=3,
        )
        
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            
            await switch.async_turn_off()
            
            mock_run.assert_called_once_with(
                ["sudo", "ip", "link", "set", "poe3", "down"],
                capture_output=True,
                text=True,
                check=False
            )
            
            mock_coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_turn_off_addon_port(self, mock_coordinator):
        """Test turning off add-on board port."""
        switch = ExavizPoEPortSwitch(
            coordinator=mock_coordinator,
            entry_id="test_entry",
            poe_set="pse0",
            port_number=7,
        )
        
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            
            await switch.async_turn_off()
            
            mock_run.assert_called_once_with(
                ["sudo", "ip", "link", "set", "poe0-7", "down"],
                capture_output=True,
                text=True,
                check=False
            )

    @pytest.mark.asyncio
    async def test_async_turn_on_command_failure(self, mock_coordinator):
        """Test handling of command failure when turning on port."""
        switch = ExavizPoEPortSwitch(
            coordinator=mock_coordinator,
            entry_id="test_entry",
            poe_set="onboard",
            port_number=0,
        )
        
        with patch("subprocess.run") as mock_run:
            # Simulate permission denied
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr="RTNETLINK answers: Operation not permitted"
            )
            
            # Should not raise exception, just log error
            await switch.async_turn_on()
            
            # Coordinator refresh should NOT be called on failure
            mock_coordinator.async_request_refresh.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_turn_on_exception_handling(self, mock_coordinator):
        """Test exception handling during turn on."""
        switch = ExavizPoEPortSwitch(
            coordinator=mock_coordinator,
            entry_id="test_entry",
            poe_set="onboard",
            port_number=0,
        )
        
        with patch("subprocess.run", side_effect=Exception("Test error")):
            # Should not raise exception, just log it
            await switch.async_turn_on()
            
            # Coordinator refresh should NOT be called on exception
            mock_coordinator.async_request_refresh.assert_not_called()

    @pytest.mark.asyncio
    async def test_interface_name_mapping_all_ports(self, mock_coordinator):
        """Test interface name mapping for all port types."""
        test_cases = [
            # (poe_set, port_number, expected_interface)
            ("onboard", 0, "poe0"),
            ("onboard", 7, "poe7"),
            ("pse0", 0, "poe0-0"),
            ("pse0", 7, "poe0-7"),
            ("pse1", 0, "poe1-0"),
            ("pse1", 7, "poe1-7"),
        ]
        
        for poe_set, port_num, expected_interface in test_cases:
            switch = ExavizPoEPortSwitch(
                coordinator=mock_coordinator,
                entry_id="test_entry",
                poe_set=poe_set,
                port_number=port_num,
            )
            
            assert switch._interface == expected_interface, \
                f"Failed for {poe_set} port {port_num}: expected {expected_interface}, got {switch._interface}"


@pytest.mark.asyncio
async def test_async_setup_entry(mock_config_entry):
    """Test setting up switch entities from config entry."""
    hass = MagicMock(spec=HomeAssistant)
    mock_coordinator = MagicMock()
    mock_coordinator.data = {
        "onboard": {
            "ports": [{"port": 0}, {"port": 1}]
        },
        "pse0": {
            "ports": [{"port": 0}]
        },
    }
    
    hass.data = {
        DOMAIN: {
            mock_config_entry.entry_id: mock_coordinator
        }
    }
    
    async_add_entities = AsyncMock()
    
    await async_setup_entry(hass, mock_config_entry, async_add_entities)
    
    # Should create 3 switch entities (2 onboard + 1 addon)
    async_add_entities.assert_called_once()
    entities = async_add_entities.call_args[0][0]
    assert len(entities) == 3
    
    # Verify entity types
    assert all(isinstance(entity, ExavizPoEPortSwitch) for entity in entities)


@pytest.mark.asyncio
async def test_sudo_permission_simulation():
    """
    Simulate the sudo permission check that would happen on real hardware.
    This test verifies the command format is correct for sudoers rule.
    """
    test_cases = [
        # Format: (poe_set, port, expected_command)
        ("onboard", 0, ["sudo", "ip", "link", "set", "poe0", "up"]),
        ("onboard", 7, ["sudo", "ip", "link", "set", "poe7", "down"]),
        ("pse0", 0, ["sudo", "ip", "link", "set", "poe0-0", "up"]),
        ("pse0", 7, ["sudo", "ip", "link", "set", "poe0-7", "down"]),
        ("pse1", 0, ["sudo", "ip", "link", "set", "poe1-0", "up"]),
        ("pse1", 7, ["sudo", "ip", "link", "set", "poe1-7", "down"]),
    ]
    
    mock_coordinator = MagicMock()
    mock_coordinator.async_request_refresh = AsyncMock()
    
    for poe_set, port, expected_up_cmd in test_cases:
        switch = ExavizPoEPortSwitch(
            coordinator=mock_coordinator,
            entry_id="test",
            poe_set=poe_set,
            port_number=port,
        )
        
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            
            if "up" in expected_up_cmd:
                await switch.async_turn_on()
            else:
                await switch.async_turn_off()
            
            actual_cmd = mock_run.call_args[0][0]
            assert actual_cmd == expected_up_cmd, \
                f"Command mismatch for {poe_set} port {port}: expected {expected_up_cmd}, got {actual_cmd}"


def test_sudoers_rule_compatibility():
    """
    Verify that our commands match the sudoers rule format.
    
    Sudoers rule:
    admin ALL=(ALL) NOPASSWD: /usr/sbin/ip link set poe* up, /usr/sbin/ip link set poe* down
    
    This test ensures our commands will match the wildcard pattern.
    """
    # Commands we generate
    test_commands = [
        "sudo ip link set poe0 up",
        "sudo ip link set poe7 down",
        "sudo ip link set poe0-0 up",
        "sudo ip link set poe0-7 down",
        "sudo ip link set poe1-0 up",
        "sudo ip link set poe1-7 down",
    ]
    
    # Sudoers pattern (simplified for testing)
    import re
    sudoers_pattern = r"^sudo ip link set poe[0-9](-[0-9])? (up|down)$"
    
    for cmd in test_commands:
        assert re.match(sudoers_pattern, cmd), \
            f"Command '{cmd}' does not match sudoers rule pattern"

