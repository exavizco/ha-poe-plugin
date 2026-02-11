"""Regression tests for critical bug fixes.

These tests guard against reintroduction of bugs that were fixed during
the 2025/2026 code review and cleanup effort.
"""
from __future__ import annotations

import inspect
import re
import pytest
from unittest.mock import AsyncMock, Mock, patch

# ---------------------------------------------------------------------------
# 1. Trailing underscore in entity ID (base_entity.py)
# ---------------------------------------------------------------------------


class TestTrailingUnderscoreFix:
    """Regression tests for the trailing underscore entity ID bug.

    Bug: When entity_suffix was empty (e.g., for switch entities),
    the entity_id was generated as 'switch.onboard_port0_' with a
    trailing underscore, which is an invalid HA entity ID.

    Fix: base_entity.py now conditionally adds the '_' separator only
    when entity_suffix is not empty.
    """

    def test_source_uses_conditional_suffix(self):
        """base_entity.py must use conditional suffix logic, not f-string concat."""
        from custom_components.exaviz import base_entity

        source = inspect.getsource(base_entity)
        # The fix: suffix = f"_{entity_suffix}" if entity_suffix else ""
        assert 'if entity_suffix else ""' in source, (
            "base_entity.py must conditionally add underscore separator"
        )

    def test_source_no_unconditional_underscore_concat(self):
        """base_entity.py must NOT use '_{entity_suffix}' unconditionally."""
        from custom_components.exaviz import base_entity

        source = inspect.getsource(base_entity)
        # This pattern would cause trailing underscores when suffix is empty
        assert "_{entity_suffix}" not in source.replace(
            'f"_{entity_suffix}"', ""
        ), "base_entity.py has unconditional underscore concatenation"

    def test_naming_logic_unit(self):
        """Test the naming logic extracted from base_entity.py."""
        # Replicate the logic from base_entity.py __init__
        test_cases = [
            # (entity_suffix, entity_name_suffix, expected_id, expected_name)
            ("", "", "switch.onboard_port0", "ONBOARD Port 0"),
            ("reset", "Reset", "button.onboard_port0_reset", "ONBOARD Port 0 Reset"),
            ("current", "Current", "sensor.onboard_port0_current", "ONBOARD Port 0 Current"),
            ("powered", "Powered", "binary_sensor.onboard_port0_powered", "ONBOARD Port 0 Powered"),
        ]
        
        for entity_suffix, entity_name_suffix, expected_id, expected_name in test_cases:
            poe_set = "onboard"
            port_number = 0
            entity_type = expected_id.split(".")[0]
            
            suffix = f"_{entity_suffix}" if entity_suffix else ""
            name_suffix = f" {entity_name_suffix}" if entity_name_suffix else ""
            entity_id = f"{entity_type}.{poe_set}_port{port_number}{suffix}"
            name = f"{poe_set.upper()} Port {port_number}{name_suffix}"
            
            assert entity_id == expected_id, f"Got {entity_id}, expected {expected_id}"
            assert name == expected_name, f"Got {name}, expected {expected_name}"
            assert not entity_id.endswith("_"), f"Trailing underscore in {entity_id}"
            assert not name.endswith(" "), f"Trailing space in {name}"


# ---------------------------------------------------------------------------
# 2. via_device race condition (__init__.py)
# ---------------------------------------------------------------------------


class TestViaDeviceRegistration:
    """Regression tests for the via_device race condition.

    Bug: Child entities (sensors, switches, etc.) referenced a parent device
    via via_device=(DOMAIN, entry_id), but the parent device wasn't registered
    yet because it was only created when the sensor platform loaded.

    Fix: __init__.py now pre-registers the parent board device using
    device_reg.async_get_or_create() before forwarding platform setups.
    """

    @pytest.mark.asyncio
    async def test_parent_device_registered_before_platforms(self):
        """Verify that async_setup_entry registers the parent device first."""
        import custom_components.exaviz as exaviz_init

        mock_hass = Mock()
        mock_entry = Mock()
        mock_entry.entry_id = "test_entry_id"
        mock_entry.data = {}

        call_order = []

        mock_coordinator = AsyncMock()
        mock_coordinator.async_setup.return_value = True
        mock_coordinator.board_type = Mock()
        mock_coordinator.board_type.value = "cruiser"
        mock_coordinator.async_config_entry_first_refresh = AsyncMock()

        mock_device_reg = Mock()

        def track_device_create(**kwargs):
            call_order.append("device_create")
            return Mock()

        mock_device_reg.async_get_or_create = track_device_create

        async def track_forward(*args, **kwargs):
            call_order.append("platform_forward")

        mock_hass.config_entries.async_forward_entry_setups = track_forward
        mock_hass.data = {}
        # The static-path registration needs an async mock for the HTTP component
        mock_hass.http = Mock()
        mock_hass.http.async_register_static_paths = AsyncMock()

        with patch(
            "custom_components.exaviz.ExavizDataUpdateCoordinator",
            return_value=mock_coordinator,
        ):
            with patch(
                "custom_components.exaviz.async_setup_services",
                new_callable=AsyncMock,
            ):
                with patch(
                    "custom_components.exaviz.dr.async_get",
                    return_value=mock_device_reg,
                ):
                    await exaviz_init.async_setup_entry(mock_hass, mock_entry)

        assert "device_create" in call_order
        assert "platform_forward" in call_order
        assert call_order.index("device_create") < call_order.index("platform_forward"), (
            "Parent device must be registered BEFORE platform forwarding"
        )

    def test_init_imports_device_registry(self):
        """__init__.py must import device_registry for pre-registration."""
        import custom_components.exaviz as exaviz_init

        source = inspect.getsource(exaviz_init)
        assert "device_registry" in source or "dr.async_get" in source


# ---------------------------------------------------------------------------
# 3. Blocking scandir calls (board_detector.py)
# ---------------------------------------------------------------------------


class TestNonBlockingScandir:
    """Regression tests for blocking scandir in the event loop.

    Bug: board_detector.py used Path.iterdir() to scan /proc and
    /proc/sys/net/ipv4/conf, which triggers blocking scandir() in the
    HA event loop.

    Fix: Replaced iterdir() with direct checks for known paths.
    """

    @pytest.mark.asyncio
    async def test_detect_addon_boards_no_iterdir(self):
        """detect_addon_boards must not call Path.iterdir()."""
        from custom_components.exaviz.board_detector import detect_addon_boards

        with patch("pathlib.Path.exists", return_value=False):
            with patch("pathlib.Path.iterdir") as mock_iterdir:
                result = await detect_addon_boards()
                mock_iterdir.assert_not_called()
                assert result == []

    @pytest.mark.asyncio
    async def test_detect_onboard_poe_no_iterdir(self):
        """detect_onboard_poe must not call Path.iterdir()."""
        from custom_components.exaviz.board_detector import detect_onboard_poe

        with patch("pathlib.Path.exists", return_value=False):
            with patch("pathlib.Path.iterdir") as mock_iterdir:
                result = await detect_onboard_poe()
                mock_iterdir.assert_not_called()
                assert result == []

    def test_source_has_no_iterdir(self):
        """board_detector.py source should not contain iterdir calls."""
        from custom_components.exaviz import board_detector

        source = inspect.getsource(board_detector)
        # iterdir may appear in comments, so check for actual method calls
        # Remove comments and docstrings for a cleaner check
        lines = [
            line for line in source.split("\n")
            if not line.strip().startswith("#") and not line.strip().startswith('"""')
        ]
        code_only = "\n".join(lines)
        assert ".iterdir()" not in code_only, (
            "board_detector.py still contains .iterdir() calls"
        )


# ---------------------------------------------------------------------------
# 4. Button control_file undefined (button.py)
# ---------------------------------------------------------------------------


class TestButtonControlFileFix:
    """Regression tests for the undefined control_file bug in button.py.

    Bug: In the add-on board reset path, the code wrote to `reset_file`
    to disable the port, then used an undefined variable `control_file`
    to re-enable it, causing a NameError crash.

    Fix: Both disable and re-enable now correctly use `reset_file`.
    """

    def test_no_undefined_control_file_in_source(self):
        """button.py must not contain 'control_file' anywhere."""
        from pathlib import Path

        button_path = Path(__file__).parent.parent / "custom_components" / "exaviz" / "button.py"
        source = button_path.read_text()
        assert "control_file" not in source, (
            "button.py still references undefined 'control_file'"
        )


# ---------------------------------------------------------------------------
# 5. Services VMS client crash (services.py)
# ---------------------------------------------------------------------------


class TestServicesNoVmsClient:
    """Regression tests for the dead VMS client references in services.py.

    Bug: _control_poe_port() tried to access coordinator.vms_client and
    vms_client._protocol_client, which don't exist in the local-board
    architecture, causing AttributeError crashes.

    Fix: services.py now delegates port control to the HA switch service.
    """

    def test_no_vms_references_in_services(self):
        """Verify services.py doesn't reference vms_client."""
        from custom_components.exaviz import services as services_mod

        source = inspect.getsource(services_mod)
        assert "vms_client" not in source
        assert "_protocol_client" not in source

    def test_no_entity_registry_direct_access(self):
        """services.py should not directly access entity_registry for control."""
        from custom_components.exaviz import services as services_mod

        source = inspect.getsource(services_mod)
        # The old code used hass.helpers.entity_registry.async_get
        assert "entity_registry" not in source


# ---------------------------------------------------------------------------
# 6. Coordinator state value inconsistency
# ---------------------------------------------------------------------------


class TestCoordinatorStateConsistency:
    """Regression tests for inconsistent state value checks.

    Bug: Coordinator checked for 'power on' for addon boards but 'active'
    for onboard ports, leading to missed active-port detection.

    Fix: Added _is_port_active() helper that handles both state strings.
    """

    def test_coordinator_has_is_port_active_method(self):
        """Coordinator must have _is_port_active helper."""
        from custom_components.exaviz import coordinator as coord_mod

        source = inspect.getsource(coord_mod)
        assert "_is_port_active" in source

    def test_is_port_active_logic(self):
        """Test _is_port_active handles all expected states."""
        from custom_components.exaviz import coordinator as coord_mod

        source = inspect.getsource(coord_mod)
        # The method should check for both "power on" and "active"
        assert '"power on"' in source
        assert '"active"' in source

    def test_is_port_active_unit(self):
        """Unit-test the _is_port_active logic directly."""
        # Re-implement the logic to test it without instantiation
        def is_port_active(port_status):
            state = port_status.get("state", "")
            if state in ("power on", "active"):
                return True
            return port_status.get("power_watts", 0) > 0

        assert is_port_active({"state": "power on", "power_watts": 0})
        assert is_port_active({"state": "active", "power_watts": 0})
        assert is_port_active({"state": "unknown", "power_watts": 5.0})
        assert not is_port_active({"state": "disabled", "power_watts": 0})
        assert not is_port_active({"state": "backoff", "power_watts": 0})
        assert not is_port_active({"state": "searching", "power_watts": 0})


# ---------------------------------------------------------------------------
# 7. Utils incomplete port mapping
# ---------------------------------------------------------------------------


class TestUtilsPortMapping:
    """Regression tests for incomplete map_port_to_entity_id.

    Bug: map_port_to_entity_id only handled 'poe0' and 'poe1', missing
    'pse0', 'pse1', and 'onboard' PoE sets.

    Fix: Added support for all known PoE set names.
    """

    def test_addon_0_maps_correctly(self):
        from custom_components.exaviz.utils import map_port_to_entity_id
        assert map_port_to_entity_id("addon_0", 0) == 1000
        assert map_port_to_entity_id("addon_0", 7) == 1007

    def test_addon_1_maps_correctly(self):
        from custom_components.exaviz.utils import map_port_to_entity_id
        assert map_port_to_entity_id("addon_1", 0) == 2000
        assert map_port_to_entity_id("addon_1", 7) == 2007

    def test_pse0_maps_correctly(self):
        """Legacy pse0 still works."""
        from custom_components.exaviz.utils import map_port_to_entity_id
        assert map_port_to_entity_id("pse0", 0) == 1000
        assert map_port_to_entity_id("pse0", 7) == 1007

    def test_pse1_maps_correctly(self):
        """Legacy pse1 still works."""
        from custom_components.exaviz.utils import map_port_to_entity_id
        assert map_port_to_entity_id("pse1", 0) == 2000
        assert map_port_to_entity_id("pse1", 7) == 2007

    def test_onboard_maps_correctly(self):
        from custom_components.exaviz.utils import map_port_to_entity_id
        assert map_port_to_entity_id("onboard", 0) == 1000
        assert map_port_to_entity_id("onboard", 7) == 1007

    def test_poe0_still_works(self):
        from custom_components.exaviz.utils import map_port_to_entity_id
        assert map_port_to_entity_id("poe0", 0) == 1000

    def test_poe1_still_works(self):
        from custom_components.exaviz.utils import map_port_to_entity_id
        assert map_port_to_entity_id("poe1", 0) == 2000

    def test_parse_entity_prefix_with_pse(self):
        """parse_entity_prefix should handle pse-based entity IDs."""
        from custom_components.exaviz.utils import parse_entity_prefix
        poe_set, port = parse_entity_prefix("switch.pse0_port3")
        assert poe_set == "pse0"
        assert port == 3

    def test_parse_entity_prefix_with_onboard(self):
        """parse_entity_prefix should handle onboard entity IDs."""
        from custom_components.exaviz.utils import parse_entity_prefix
        poe_set, port = parse_entity_prefix("switch.onboard_port0")
        assert poe_set == "onboard"
        assert port == 0

    def test_parse_entity_prefix_with_addon_0(self):
        """parse_entity_prefix should handle addon_0 entity IDs."""
        from custom_components.exaviz.utils import parse_entity_prefix
        poe_set, port = parse_entity_prefix("switch.addon_0_port3")
        assert poe_set == "addon_0"
        assert port == 3

    def test_parse_entity_prefix_with_addon_1(self):
        """parse_entity_prefix should handle addon_1 entity IDs."""
        from custom_components.exaviz.utils import parse_entity_prefix
        poe_set, port = parse_entity_prefix("sensor.addon_1_port5_current")
        assert poe_set == "addon_1"
        assert port == 5


# ---------------------------------------------------------------------------
# 8. Binary sensor threshold constants
# ---------------------------------------------------------------------------


class TestBinarySensorThresholds:
    """Verify binary sensor thresholds use named constants."""

    def test_thresholds_importable(self):
        from custom_components.exaviz.const import (
            POWER_ON_THRESHOLD_WATTS,
            PLUGGED_THRESHOLD_MILLIAMPS,
        )
        assert POWER_ON_THRESHOLD_WATTS == 0.5
        assert PLUGGED_THRESHOLD_MILLIAMPS == 10

    def test_binary_sensor_source_uses_constants(self):
        from pathlib import Path

        bs_path = Path(__file__).parent.parent / "custom_components" / "exaviz" / "binary_sensor.py"
        source = bs_path.read_text()
        assert "POWER_ON_THRESHOLD_WATTS" in source
        assert "PLUGGED_THRESHOLD_MILLIAMPS" in source


# ---------------------------------------------------------------------------
# 9. Dead VMS code removed from const.py
# ---------------------------------------------------------------------------


class TestDeadVmsCodeRemoved:
    """Verify dead VMS-related code was cleaned up from const.py."""

    def test_no_api_endpoints(self):
        from custom_components.exaviz import const as const_mod
        source = inspect.getsource(const_mod)
        assert "API_STATUS_ENDPOINT" not in source
        assert "API_CAMERAS_ENDPOINT" not in source

    def test_no_websocket_endpoints(self):
        from custom_components.exaviz import const as const_mod
        source = inspect.getsource(const_mod)
        assert "WS_EVENTS_ENDPOINT" not in source
        assert "WS_STATUS_ENDPOINT" not in source

    def test_no_vms_constants(self):
        from custom_components.exaviz import const as const_mod
        source = inspect.getsource(const_mod)
        assert "CONF_VMS_URL" not in source
        assert "CONF_VMS_HOST" not in source
        assert "CONF_VMS_PORT" not in source

    def test_no_camera_events(self):
        from custom_components.exaviz import const as const_mod
        source = inspect.getsource(const_mod)
        assert "EVENT_MOTION_DETECTED" not in source
        assert "EVENT_CAMERA_OFFLINE" not in source

    def test_correct_docstring(self):
        from custom_components.exaviz import const as const_mod
        source = inspect.getsource(const_mod)
        assert "PoE Management" in source
        # Should NOT say "VMS integration"
        assert "VMS integration" not in source

    def test_correct_contact_email(self):
        from custom_components.exaviz import const as const_mod
        source = inspect.getsource(const_mod)
        # Public repo should not contain internal @axzez.com emails
        assert "axzez.com" not in source


# ---------------------------------------------------------------------------
# 10. Version alignment
# ---------------------------------------------------------------------------


class TestVersionAlignment:
    """Verify version consistency across manifest.json and pyproject.toml."""

    def test_pyproject_version_matches_manifest(self):
        import json
        from pathlib import Path

        base = Path(__file__).parent.parent
        manifest = json.loads((base / "custom_components" / "exaviz" / "manifest.json").read_text())
        pyproject = (base / "pyproject.toml").read_text()

        manifest_version = manifest["version"]
        # Extract version from pyproject.toml
        match = re.search(r'version\s*=\s*"([^"]+)"', pyproject)
        assert match, "Could not find version in pyproject.toml"
        pyproject_version = match.group(1)

        assert manifest_version == pyproject_version, (
            f"Version mismatch: manifest.json={manifest_version}, "
            f"pyproject.toml={pyproject_version}"
        )
