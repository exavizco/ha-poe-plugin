"""
Copyright (c) 2025 Axzez LLC.
Licensed under MIT with Commons Clause. See LICENSE for details.
"""

"""Shared test configuration and fixtures."""

import sys
from unittest.mock import MagicMock, patch, AsyncMock
import pytest

# Mock additional third-party modules that might cause issues
sys.modules['voluptuous'] = MagicMock()
# Note: Don't mock aiohttp completely as it breaks real aiohttp imports in http_bridge
sys.modules['async_timeout'] = MagicMock()

# Mock Home Assistant modules before any imports
homeassistant_mock = MagicMock()
sys.modules['homeassistant'] = homeassistant_mock
sys.modules['homeassistant.core'] = MagicMock()
sys.modules['homeassistant.config_entries'] = MagicMock()
sys.modules['homeassistant.helpers'] = MagicMock()
sys.modules['homeassistant.helpers.entity'] = MagicMock()
sys.modules['homeassistant.helpers.entity_platform'] = MagicMock()
sys.modules['homeassistant.helpers.entity_component'] = MagicMock()
sys.modules['homeassistant.helpers.update_coordinator'] = MagicMock()
sys.modules['homeassistant.helpers.aiohttp_client'] = MagicMock()
sys.modules['homeassistant.helpers.service'] = MagicMock()
sys.modules['homeassistant.helpers.event'] = MagicMock()
sys.modules['homeassistant.helpers.device_registry'] = MagicMock()
sys.modules['homeassistant.helpers.entity_registry'] = MagicMock()
sys.modules['homeassistant.helpers.storage'] = MagicMock()
sys.modules['homeassistant.components'] = MagicMock()
sys.modules['homeassistant.components.sensor'] = MagicMock()
sys.modules['homeassistant.components.camera'] = MagicMock()
sys.modules['homeassistant.components.frontend'] = MagicMock()
sys.modules['homeassistant.components.websocket_api'] = MagicMock()
sys.modules['homeassistant.components.persistent_notification'] = MagicMock()
sys.modules['homeassistant.const'] = MagicMock()
sys.modules['homeassistant.exceptions'] = MagicMock()
sys.modules['homeassistant.loader'] = MagicMock()
sys.modules['homeassistant.data_entry_flow'] = MagicMock()

# Mock specific functions that are imported
sys.modules['homeassistant.helpers.aiohttp_client'].async_get_clientsession = MagicMock()
sys.modules['homeassistant.helpers.service'].async_extract_entity_ids = MagicMock()
sys.modules['homeassistant.helpers.event'].async_track_time_interval = MagicMock()
sys.modules['homeassistant.components.websocket_api'].websocket_command = MagicMock()
sys.modules['homeassistant.components.frontend'].add_extra_js_url = MagicMock()

# Create mock classes for commonly used HA classes
class MockConfigEntry:
    """Mock ConfigEntry class."""
    def __init__(self, version=1, domain="exaviz", title="Test VMS", 
                 data=None, source="test", entry_id="test_entry"):
        self.version = version
        self.domain = domain
        self.title = title
        self.data = data or {}
        self.source = source
        self.entry_id = entry_id

class MockHomeAssistant:
    """Mock HomeAssistant class."""
    def __init__(self):
        self.data = {}
        self.config_entries = MagicMock()
        self.services = MagicMock()

# Mock sensor classes
class MockSensorEntity:
    """Mock SensorEntity class."""
    def __init__(self, *args, **kwargs):
        pass

class MockCoordinatorEntity:
    """Mock CoordinatorEntity class."""
    def __init__(self, coordinator):
        self.coordinator = coordinator

class MockCamera:
    """Mock Camera class."""
    def __init__(self):
        pass

class MockCameraEntityFeature:
    """Mock CameraEntityFeature enum."""
    STREAM = 1
    ON_OFF = 2

class MockSensorDeviceClass:
    """Mock SensorDeviceClass enum."""
    TIMESTAMP = "timestamp"
    TEMPERATURE = "temperature"
    DATA_SIZE = "data_size"
    DURATION = "duration"
    POWER = "power"
    VOLTAGE = "voltage"
    CURRENT = "current"

class MockSensorStateClass:
    """Mock SensorStateClass enum."""
    MEASUREMENT = "measurement"
    TOTAL = "total"
    TOTAL_INCREASING = "total_increasing"

class MockSensorEntityDescription:
    """Mock SensorEntityDescription class."""
    def __init__(self, key, name=None, icon=None, **kwargs):
        self.key = key
        self.name = name
        self.icon = icon
        for k, v in kwargs.items():
            setattr(self, k, v)

class MockDeviceInfo(dict):
    """Mock DeviceInfo class that behaves like a dict."""
    def __init__(self, **kwargs):
        super().__init__(kwargs)
        for k, v in kwargs.items():
            setattr(self, k, v)

class MockPlatform:
    """Mock Platform enum for testing."""
    SENSOR = "sensor"
    SWITCH = "switch"
    BINARY_SENSOR = "binary_sensor"
    BUTTON = "button"

class MockUnitOfInformation:
    """Mock UnitOfInformation enum."""
    GIGABYTES = "GB"

class MockUnitOfTime:
    """Mock UnitOfTime enum."""
    SECONDS = "s"

class MockUnitOfPower:
    """Mock UnitOfPower enum."""
    WATT = "W"

class MockUnitOfElectricPotential:
    """Mock UnitOfElectricPotential enum."""
    VOLT = "V"

class MockUnitOfElectricCurrent:
    """Mock UnitOfElectricCurrent enum."""
    AMPERE = "A"
    MILLIAMPERE = "mA"

# Add mock classes to the mocked modules
sys.modules['homeassistant.config_entries'].ConfigEntry = MockConfigEntry
sys.modules['homeassistant.core'].HomeAssistant = MockHomeAssistant
sys.modules['homeassistant.components.sensor'].SensorEntity = MockSensorEntity
sys.modules['homeassistant.components.sensor'].SensorDeviceClass = MockSensorDeviceClass
sys.modules['homeassistant.components.sensor'].SensorStateClass = MockSensorStateClass
sys.modules['homeassistant.components.sensor'].SensorEntityDescription = MockSensorEntityDescription
sys.modules['homeassistant.helpers.update_coordinator'].CoordinatorEntity = MockCoordinatorEntity
sys.modules['homeassistant.helpers.entity'].DeviceInfo = MockDeviceInfo
sys.modules['homeassistant.components.camera'].Camera = MockCamera
sys.modules['homeassistant.components.camera'].CameraEntityFeature = MockCameraEntityFeature
sys.modules['homeassistant.const'].Platform = MockPlatform
sys.modules['homeassistant.const'].UnitOfInformation = MockUnitOfInformation
sys.modules['homeassistant.const'].UnitOfTime = MockUnitOfTime
sys.modules['homeassistant.const'].UnitOfPower = MockUnitOfPower
sys.modules['homeassistant.const'].UnitOfElectricPotential = MockUnitOfElectricPotential
sys.modules['homeassistant.const'].UnitOfElectricCurrent = MockUnitOfElectricCurrent
sys.modules['homeassistant.const'].PERCENTAGE = "%"

# ============================================================================
# ASYNC HANGING SOLUTION: aiosqlite daemon threads
# The hanging issue was caused by aiosqlite threads not being marked as daemon.
# Fixed in database_reader.py with: awaitable_db.daemon = True
# No custom event loop fixture needed.
# ============================================================================

@pytest.fixture
def mock_platform():
    """Provide mock Platform for tests."""
    return MockPlatform

# Mock HA components and dependencies
@pytest.fixture(autouse=True)
def mock_ha_dependencies():
    """Mock all Home Assistant dependencies."""
    mocks = {}
    
    # Mock homeassistant.const
    with patch("homeassistant.const.Platform", MockPlatform):
        # Mock other homeassistant modules that might be imported
        mock_modules = [
            "homeassistant.config_entries",
            "homeassistant.core", 
            "homeassistant.helpers.update_coordinator",
            "homeassistant.helpers.entity_platform",
            "homeassistant.components.sensor",
            "homeassistant.components.switch",
            "homeassistant.components.binary_sensor",
            "homeassistant.components.button",
            "homeassistant.exceptions",
            "homeassistant.helpers.entity",
            "homeassistant.helpers.service",
            "homeassistant.helpers",
        ]
        
        for module in mock_modules:
            mocks[module] = MagicMock()
        
        with patch.dict("sys.modules", mocks):
            yield mocks

@pytest.fixture 
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock()
    hass.data = {}
    hass.bus = MagicMock()
    hass.services = MagicMock()
    hass.config_entries = MagicMock()
    return hass

@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.data = {
        "host": "192.168.1.100",
        "port": 8080,
        "username": "test_user", 
        "password": "test_pass",
        "mock_mode": True
    }
    entry.options = {}
    entry.title = "Exaviz PoE Test"
    return entry

@pytest.fixture
def sample_poe_data():
    """Provide sample PoE data for testing."""
    return {
        "poe": {
            "poe0": {
                "switch_id": "poe0",
                "name": "Main PoE Switch",
                "model": "EX-POE24-PLUS",
                "total_ports": 8,
                "power_budget_watts": 240,
                "power_consumption_watts": 85.4,
                "ports": [
                    {
                        "port": 0,
                        "enabled": True,
                        "status": "active",
                        "power_consumption_watts": 12.5,
                        "voltage_volts": 48.2,
                        "current_milliamps": 260,
                        "connected_device": {
                            "name": "IP Camera 1",
                            "device_type": "ip_camera",
                            "power_class": "Class 3",
                            "ip_address": "192.168.1.201",
                            "mac_address": "00:11:22:33:44:55"
                        }
                    },
                    {
                        "port": 1,
                        "enabled": True,
                        "status": "active", 
                        "power_consumption_watts": 8.2,
                        "voltage_volts": 48.1,
                        "current_milliamps": 171,
                        "connected_device": {
                            "name": "Access Point 1",
                            "device_type": "wireless_ap",
                            "power_class": "Class 2",
                            "ip_address": "192.168.1.202",
                            "mac_address": "00:11:22:33:44:56"
                        }
                    },
                    {
                        "port": 2,
                        "enabled": False,
                        "status": "disabled",
                        "power_consumption_watts": 0.0,
                        "voltage_volts": 0.0,
                        "current_milliamps": 0
                    },
                    {
                        "port": 3,
                        "enabled": True,
                        "status": "fault",
                        "power_consumption_watts": 0.0,
                        "voltage_volts": 0.0,
                        "current_milliamps": 0
                    }
                ]
            }
        }
    }

@pytest.fixture
def mock_coordinator():
    """Create a mock data update coordinator."""
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.data = None
    coordinator.async_request_refresh = AsyncMock()
    coordinator.async_setup = AsyncMock(return_value=True)
    coordinator.async_config_entry_first_refresh = AsyncMock()
    coordinator.async_shutdown = AsyncMock()
    return coordinator

@pytest.fixture
def mock_coordinator_with_poe_data(mock_coordinator, sample_poe_data):
    """Create a coordinator with PoE data."""
    mock_coordinator.data = sample_poe_data
    return mock_coordinator

# Additional fixtures for PoE-specific testing
@pytest.fixture
def poe_port_entity_data():
    """Sample data for a PoE port entity."""
    return {
        "port": 0,
        "enabled": True,
        "status": "active",
        "power_consumption_watts": 12.5,
        "voltage_volts": 48.2,
        "current_milliamps": 260,
        "connected_device": {
            "name": "IP Camera 1",
            "device_type": "ip_camera", 
            "power_class": "Class 3",
            "ip_address": "192.168.1.201",
            "mac_address": "00:11:22:33:44:55"
        }
    }

@pytest.fixture
def mock_poe_entities():
    """Mock PoE entities for testing."""
    entities = {
        "sensor.poe0_port0_current": {
            "state": "12.5",
            "attributes": {
                "unit_of_measurement": "W",
                "device_class": "power",
                "port_number": 0,
                "poe_set": "poe0",
                "status": "active"
            }
        },
        "switch.poe0_port0": {
            "state": "on",
            "attributes": {
                "port_number": 0,
                "poe_set": "poe0"
            }
        },
        "binary_sensor.poe0_port0_powered": {
            "state": "on",
            "attributes": {
                "device_class": "power",
                "port_number": 0,
                "poe_set": "poe0"
            }
        },
        "binary_sensor.poe0_port0_plug": {
            "state": "on", 
            "attributes": {
                "device_class": "plug",
                "port_number": 0,
                "poe_set": "poe0"
            }
        },
        "button.poe0_port0_reset": {
            "state": "unknown",
            "attributes": {
                "port_number": 0,
                "poe_set": "poe0"
            }
        }
    }
    return entities 