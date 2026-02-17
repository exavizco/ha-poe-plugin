"""Shared test configuration and fixtures.

Home Assistant is not installed in the test venv, so we mock its modules
at the sys.modules level before any custom_components imports occur.
"""
import sys
from unittest.mock import MagicMock, AsyncMock

import pytest

# ---------------------------------------------------------------------------
# Mock Home Assistant modules (required — HA is not installed in test venv)
# ---------------------------------------------------------------------------

_HA_MODULES = [
    "homeassistant",
    "homeassistant.config_entries",
    "homeassistant.components",
    "homeassistant.components.binary_sensor",
    "homeassistant.components.button",
    "homeassistant.components.camera",
    "homeassistant.components.frontend",
    "homeassistant.components.http",
    "homeassistant.components.lovelace",
    "homeassistant.components.lovelace.resources",
    "homeassistant.components.persistent_notification",
    "homeassistant.components.sensor",
    "homeassistant.components.switch",
    "homeassistant.components.websocket_api",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.data_entry_flow",
    "homeassistant.exceptions",
    "homeassistant.helpers",
    "homeassistant.helpers.aiohttp_client",
    "homeassistant.helpers.config_validation",
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.entity",
    "homeassistant.helpers.entity_component",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.entity_registry",
    "homeassistant.helpers.event",
    "homeassistant.helpers.service",
    "homeassistant.helpers.storage",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.loader",
    "voluptuous",
    "async_timeout",
]

for _mod in _HA_MODULES:
    sys.modules.setdefault(_mod, MagicMock())

# Stub base classes that source code inherits from — must be real classes,
# not MagicMock, to avoid metaclass conflicts in multiple-inheritance.
class _StubEntity:
    """Base for all mocked HA entity classes."""
    def __init__(self, *args, **kwargs):
        pass

class _StubCoordinatorEntity(_StubEntity):
    def __init__(self, coordinator, *args, **kwargs):
        self.coordinator = coordinator

class _StubDataUpdateCoordinator:
    """Minimal DataUpdateCoordinator stub."""
    def __init__(self, hass, logger, *, name="", update_interval=None, **kwargs):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.data = None
        self.last_update_success = True

    async def async_config_entry_first_refresh(self):
        self.data = await self._async_update_data()

    async def _async_update_data(self):
        raise NotImplementedError

sys.modules["homeassistant.helpers.update_coordinator"].CoordinatorEntity = _StubCoordinatorEntity
sys.modules["homeassistant.helpers.update_coordinator"].DataUpdateCoordinator = _StubDataUpdateCoordinator
sys.modules["homeassistant.helpers.update_coordinator"].UpdateFailed = Exception
sys.modules["homeassistant.components.sensor"].SensorEntity = _StubEntity
sys.modules["homeassistant.components.sensor"].SensorDeviceClass = MagicMock()
sys.modules["homeassistant.components.sensor"].SensorStateClass = MagicMock()
sys.modules["homeassistant.components.switch"].SwitchEntity = _StubEntity
sys.modules["homeassistant.components.switch"].SwitchDeviceClass = MagicMock()
sys.modules["homeassistant.components.binary_sensor"].BinarySensorEntity = _StubEntity
sys.modules["homeassistant.components.binary_sensor"].BinarySensorDeviceClass = MagicMock()
sys.modules["homeassistant.components.button"].ButtonEntity = _StubEntity
sys.modules["homeassistant.components.button"].ButtonDeviceClass = MagicMock()
sys.modules["homeassistant.components.camera"].Camera = _StubEntity
sys.modules["homeassistant.exceptions"].HomeAssistantError = Exception
sys.modules["homeassistant.exceptions"].ConfigEntryNotReady = Exception
sys.modules["homeassistant.exceptions"].ServiceValidationError = Exception

# Constants — Platform values must be real strings so `'sensor' in PLATFORMS` works
class _Platform:
    SENSOR = "sensor"
    SWITCH = "switch"
    BINARY_SENSOR = "binary_sensor"
    BUTTON = "button"

sys.modules["homeassistant.const"].Platform = _Platform
sys.modules["homeassistant.const"].UnitOfPower = MagicMock()
sys.modules["homeassistant.const"].UnitOfTemperature = MagicMock()
sys.modules["homeassistant.const"].UnitOfElectricPotential = MagicMock()
sys.modules["homeassistant.const"].UnitOfElectricCurrent = MagicMock()
sys.modules["homeassistant.const"].PERCENTAGE = "%"

# Lovelace resource type must be a real class for isinstance() checks
class _ResourceStorageCollection:
    pass

sys.modules["homeassistant.components.lovelace.resources"].ResourceStorageCollection = _ResourceStorageCollection

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_hass():
    """Minimal mock Home Assistant instance."""
    hass = MagicMock()
    hass.data = {}
    hass.bus = MagicMock()
    hass.services = MagicMock()
    hass.config_entries = MagicMock()
    return hass


@pytest.fixture
def mock_config_entry():
    """Mock config entry."""
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.data = {}
    entry.options = {}
    entry.title = "Exaviz PoE Test"
    return entry


@pytest.fixture
def mock_coordinator():
    """Mock data update coordinator."""
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.data = None
    coordinator.async_request_refresh = AsyncMock()
    coordinator.async_setup = AsyncMock(return_value=True)
    coordinator.async_config_entry_first_refresh = AsyncMock()
    coordinator.async_shutdown = AsyncMock()
    return coordinator


@pytest.fixture
def sample_poe_data():
    """Realistic PoE data matching coordinator output format."""
    return {
        "poe": {
            "onboard": {
                "total_ports": 8,
                "active_ports": 2,
                "used_power_watts": 20.7,
                "total_power_budget": 240.0,
                "ports": [
                    {
                        "port": 0,
                        "interface": "poe0",
                        "enabled": True,
                        "status": "power on",
                        "power_consumption_watts": 12.5,
                        "voltage_volts": 48.2,
                        "current_milliamps": 260,
                        "poe_system": "onboard",
                        "connected_device": {
                            "name": "Device on poe0",
                            "device_type": "Network Device",
                            "ip_address": "192.168.1.201",
                            "mac_address": "00:11:22:33:44:55",
                            "manufacturer": "GeoVision",
                            "hostname": "camera-1",
                        },
                    },
                    {
                        "port": 1,
                        "interface": "poe1",
                        "enabled": True,
                        "status": "power on",
                        "power_consumption_watts": 8.2,
                        "voltage_volts": 48.1,
                        "current_milliamps": 171,
                        "poe_system": "onboard",
                        "connected_device": None,
                    },
                    {
                        "port": 2,
                        "interface": "poe2",
                        "enabled": False,
                        "status": "disabled",
                        "power_consumption_watts": 0.0,
                        "voltage_volts": 0.0,
                        "current_milliamps": 0,
                        "poe_system": "onboard",
                    },
                ],
            },
        },
    }
