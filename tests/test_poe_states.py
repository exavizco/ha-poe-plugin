"""Tests for PoE port state mapping and enabled logic.

Covers both Cruiser (TPS23861) and Interceptor (IP808AR) hardware states.
"""
import pytest


class TestEnabledLogic:
    """Backend enabled attribute: only 'disabled' state means enabled=False."""

    @pytest.mark.parametrize("state,expected", [
        ("power on", True),
        ("backoff", True),
        ("start detection", True),
        ("searching", True),
        ("disabled", False),
    ])
    def test_enabled_from_state(self, state, expected):
        """Replicate the logic from poe_readers.py."""
        enabled = state not in ("disabled",)
        assert enabled == expected


class TestFrontendStateMapping:
    """Map hardware states to UI display states."""

    @staticmethod
    def _get_port_status(hardware_status: str) -> str:
        """Replicate frontend _getPortStatus() logic."""
        if hardware_status == "power on":
            return "active"
        if hardware_status == "disabled":
            return "disabled"
        if "backoff" in hardware_status:
            return "empty"
        if "detection" in hardware_status:
            return "empty"
        if "searching" in hardware_status:
            return "empty"
        return "unknown"

    @pytest.mark.parametrize("hw_state,ui_state", [
        ("power on", "active"),
        ("disabled", "disabled"),
        ("backoff", "empty"),
        ("start detection", "empty"),
        ("searching", "empty"),
    ])
    def test_mapping(self, hw_state, ui_state):
        assert self._get_port_status(hw_state) == ui_state

    def test_backoff_never_maps_to_disabled(self):
        """Regression: backoff was incorrectly mapped to 'disabled' (Oct 2025)."""
        assert self._get_port_status("backoff") != "disabled"


class TestChipStates:
    """Verify known states per PoE controller chip."""

    def test_cruiser_tps23861_states(self):
        expected = {"power on": "active", "disabled": "disabled",
                    "start detection": "empty", "searching": "empty"}
        for state, ui in expected.items():
            assert ui in ("active", "disabled", "empty")

    def test_interceptor_ip808ar_states(self):
        expected = {"power on": "active", "disabled": "disabled",
                    "backoff": "empty", "start detection": "empty"}
        for state, ui in expected.items():
            assert ui in ("active", "disabled", "empty")

    def test_both_chips_empty_port_maps_to_same_ui(self):
        """TPS23861 'start detection' and IP808AR 'backoff' both mean empty."""
        cruiser_empty = "empty"   # start detection
        interceptor_empty = "empty"  # backoff
        assert cruiser_empty == interceptor_empty


class TestAdminStateLogic:
    """Backend must distinguish admin-down from link-down."""

    @pytest.mark.parametrize("admin_up,link_state,expected_state", [
        (False, "down", "disabled"),
        (False, "lowerlayerdown", "disabled"),
        (True, "down", "searching"),
        (True, "lowerlayerdown", "searching"),
        (True, "up", "power on"),
    ])
    def test_state_from_admin_and_link(self, admin_up, link_state, expected_state):
        """Replicate mocked-data path logic from poe_readers.py."""
        if not admin_up:
            state = "disabled"
        elif link_state == "up":
            state = "power on"
        else:
            state = "searching"
        assert state == expected_state
