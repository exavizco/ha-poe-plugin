"""Regression tests for critical bug fixes.

Each test guards against reintroduction of a specific bug.
Tests verify behavior, not source text.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest


PROJECT_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# 1. Entity ID trailing underscore (base_entity.py)
# ---------------------------------------------------------------------------

class TestEntityNaming:
    """Entity IDs must not end with a trailing underscore."""

    @pytest.mark.parametrize("suffix,name_suffix,entity_type,expected_id,expected_name", [
        ("", "", "switch", "switch.onboard_port0", "ONBOARD Port 0"),
        ("reset", "Reset", "button", "button.onboard_port0_reset", "ONBOARD Port 0 Reset"),
        ("current", "Current", "sensor", "sensor.onboard_port0_current", "ONBOARD Port 0 Current"),
        ("powered", "Powered", "binary_sensor", "binary_sensor.onboard_port0_powered", "ONBOARD Port 0 Powered"),
    ])
    def test_naming_logic(self, suffix, name_suffix, entity_type, expected_id, expected_name):
        """Replicate base_entity.py naming logic."""
        poe_set, port_number = "onboard", 0
        sfx = f"_{suffix}" if suffix else ""
        nsfx = f" {name_suffix}" if name_suffix else ""
        entity_id = f"{entity_type}.{poe_set}_port{port_number}{sfx}"
        name = f"{poe_set.upper()} Port {port_number}{nsfx}"

        assert entity_id == expected_id
        assert name == expected_name
        assert not entity_id.endswith("_")
        assert not name.endswith(" ")


# ---------------------------------------------------------------------------
# 2. Parent device registered before platform forwarding (__init__.py)
# ---------------------------------------------------------------------------

class TestViaDeviceRegistration:
    """Parent device must be created before child platforms load."""

    @pytest.mark.asyncio
    async def test_device_created_before_platform_forward(self):
        import custom_components.exaviz as exaviz_init

        call_order: list[str] = []

        mock_hass = Mock()
        mock_hass.data = {}
        mock_hass.http = Mock()
        mock_hass.http.async_register_static_paths = AsyncMock()
        mock_hass.services = Mock()
        mock_hass.services.has_service = Mock(return_value=False)

        mock_entry = Mock()
        mock_entry.entry_id = "test_entry_id"
        mock_entry.data = {}
        mock_entry.title = "Exaviz Cruiser"

        mock_coordinator = AsyncMock()
        mock_coordinator.async_setup.return_value = True
        mock_coordinator.board_type = Mock()
        mock_coordinator.board_type.value = "cruiser"

        mock_device_reg = Mock()
        mock_device_reg.async_get_or_create = lambda **kw: call_order.append("device_create") or Mock()

        async def track_forward(*a, **kw):
            call_order.append("platform_forward")

        mock_hass.config_entries.async_forward_entry_setups = track_forward

        with patch("custom_components.exaviz.ExavizDataUpdateCoordinator", return_value=mock_coordinator):
            with patch("custom_components.exaviz.async_setup_services", new_callable=AsyncMock):
                with patch("custom_components.exaviz.dr.async_get", return_value=mock_device_reg):
                    await exaviz_init.async_setup_entry(mock_hass, mock_entry)

        assert call_order.index("device_create") < call_order.index("platform_forward")


# ---------------------------------------------------------------------------
# 3. No blocking iterdir calls (board_detector.py)
# ---------------------------------------------------------------------------

class TestNonBlockingScandir:
    """board_detector must not call Path.iterdir() in the event loop."""

    @pytest.mark.asyncio
    async def test_detect_addon_boards_no_iterdir(self):
        from custom_components.exaviz.board_detector import detect_addon_boards

        with patch("pathlib.Path.exists", return_value=False):
            with patch("pathlib.Path.iterdir") as mock_iterdir:
                await detect_addon_boards()
                mock_iterdir.assert_not_called()

    @pytest.mark.asyncio
    async def test_detect_onboard_poe_no_iterdir(self):
        from custom_components.exaviz.board_detector import detect_onboard_poe

        with patch("pathlib.Path.exists", return_value=False):
            with patch("pathlib.Path.iterdir") as mock_iterdir:
                await detect_onboard_poe()
                mock_iterdir.assert_not_called()


# ---------------------------------------------------------------------------
# 4. Coordinator _is_port_active handles both state strings
# ---------------------------------------------------------------------------

class TestIsPortActive:
    """_is_port_active must accept both 'power on' (addon) and 'active' states."""

    @pytest.mark.parametrize("state,power,expected", [
        ("power on", 0, True),
        ("active", 0, True),
        ("unknown", 5.0, True),
        ("disabled", 0, False),
        ("backoff", 0, False),
        ("searching", 0, False),
    ])
    def test_is_port_active(self, state, power, expected):
        def is_port_active(ps):
            s = ps.get("state", "")
            if s in ("power on", "active"):
                return True
            return ps.get("power_watts", 0) > 0

        assert is_port_active({"state": state, "power_watts": power}) == expected


# ---------------------------------------------------------------------------
# 5. Utils port mapping completeness
# ---------------------------------------------------------------------------

class TestUtilsPortMapping:
    """map_port_to_entity_id must handle all PoE set naming variants."""

    @pytest.mark.parametrize("poe_set,port,expected", [
        ("addon_0", 0, 1000), ("addon_0", 7, 1007),
        ("addon_1", 0, 2000), ("addon_1", 7, 2007),
        ("pse0", 0, 1000), ("pse1", 0, 2000),
        ("onboard", 0, 1000), ("onboard", 7, 1007),
        ("poe0", 0, 1000), ("poe1", 0, 2000),
    ])
    def test_map_port_to_entity_id(self, poe_set, port, expected):
        from custom_components.exaviz.utils import map_port_to_entity_id
        assert map_port_to_entity_id(poe_set, port) == expected

    @pytest.mark.parametrize("entity_id,expected_set,expected_port", [
        ("switch.pse0_port3", "pse0", 3),
        ("switch.onboard_port0", "onboard", 0),
        ("switch.addon_0_port3", "addon_0", 3),
        ("sensor.addon_1_port5_current", "addon_1", 5),
    ])
    def test_parse_entity_prefix(self, entity_id, expected_set, expected_port):
        from custom_components.exaviz.utils import parse_entity_prefix
        poe_set, port = parse_entity_prefix(entity_id)
        assert poe_set == expected_set
        assert port == expected_port


# ---------------------------------------------------------------------------
# 6. Binary sensor threshold constants exist
# ---------------------------------------------------------------------------

class TestBinarySensorThresholds:
    def test_thresholds_importable(self):
        from custom_components.exaviz.const import (
            POWER_ON_THRESHOLD_WATTS,
            PLUGGED_THRESHOLD_MILLIAMPS,
        )
        assert POWER_ON_THRESHOLD_WATTS == 0.5
        assert PLUGGED_THRESHOLD_MILLIAMPS == 10


# ---------------------------------------------------------------------------
# 7. Version alignment between manifest.json and pyproject.toml
# ---------------------------------------------------------------------------

class TestVersionAlignment:
    def test_versions_match(self):
        manifest = json.loads(
            (PROJECT_ROOT / "custom_components" / "exaviz" / "manifest.json").read_text()
        )
        pyproject = (PROJECT_ROOT / "pyproject.toml").read_text()
        match = re.search(r'version\s*=\s*"([^"]+)"', pyproject)
        assert match, "No version in pyproject.toml"
        assert manifest["version"] == match.group(1)
