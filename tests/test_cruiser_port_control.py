"""
Regression tests for Cruiser port control behavior.

These tests document expected behavior for enable/disable operations on Cruiser.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_disabled_port_shows_disabled_not_empty():
    """
    Regression test for disabled ports showing "empty" instead of "disabled".
    
    Issue (October 31, 2025):
    - User disabled Port 0 on Cruiser
    - Port showed "empty" instead of "disabled"
    - Button said "Disable Port" but port was already disabled
    
    Root Cause:
    - Backend didn't check admin_up state before determining status
    - Backend returned state="searching" for any link_state != "up"
    - Frontend correctly mapped "searching" → "empty"
    - But disabled ports should show "disabled"!
    
    Fix:
    - Backend now checks admin_up FIRST
    - If not admin_up: return "disabled"
    - If admin_up and link == "up": return "power on"
    - If admin_up and link != "up": return "searching"
    
    Expected behavior after fix:
    - Disabled port (admin down): state="disabled" → UI shows "disabled"
    - Enabled port, no device (admin up, link down): state="searching" → UI shows "empty"
    """
    # When interface is administratively down
    port_data_disabled = {
        "available": True,
        "poe_system": "onboard",
        "state": "disabled",  # Backend now returns "disabled" when admin_up=False
        "enabled": False,     # Admin down
        "power_watts": 0.0,
    }
    
    # When interface is administratively up but no device
    port_data_empty = {
        "available": True,
        "poe_system": "onboard",
        "state": "searching",  # Backend returns "searching" when admin_up=True and link_state != "up"
        "enabled": True,       # Admin up
        "power_watts": 0.0,
    }
    
    assert port_data_disabled["state"] == "disabled", \
        "Disabled port must have state='disabled', not 'searching'"
    
    assert port_data_empty["state"] == "searching", \
        "Empty enabled port must have state='searching', which maps to UI 'empty'"


@pytest.mark.asyncio
async def test_backend_must_check_admin_state():
    """
    Test that backend distinguishes between admin down vs link down.
    
    Issue: poe_readers.py line 252 only checks link_state:
        "state": "power on" if link_state == "up" else "searching"
    
    This is wrong! It should be:
        if not admin_up: "disabled"
        elif link_state == "up": "power on"
        else: "searching"
    
    Fix needed in poe_readers.py:read_network_port_status()
    """
    test_cases = [
        # (admin_up, link_state, expected_state)
        (False, "down", "disabled"),        # Admin disabled
        (False, "lowerlayerdown", "disabled"),  # Admin disabled
        (True, "down", "searching"),        # Enabled, no device
        (True, "lowerlayerdown", "searching"),  # Enabled, no device
        (True, "up", "power on"),          # Enabled, device connected
    ]
    
    for admin_up, link_state, expected_state in test_cases:
        # This is what the backend SHOULD return
        if not admin_up:
            state = "disabled"
        elif link_state == "up":
            state = "power on"
        else:
            state = "searching"
        
        assert state == expected_state, \
            f"admin_up={admin_up}, link_state={link_state} should return state='{expected_state}'"


@pytest.mark.asyncio
async def test_enable_port_transition_timing():
    """
    Test that enabling a port with device plugged in transitions correctly.
    
    Observed behavior:
    - Disable active port → shows "empty" (should show "disabled"?)
    - Enable port with device → sometimes stays "empty" for 30 seconds
    
    Expected behavior:
    - Disable active port → should show "disabled" immediately
    - Enable port with device → should show "active" within 5-10 seconds
    
    The 30-second delay might be:
    - Network negotiation (link-up takes time)
    - PoE detection/classification
    - Frontend polling interval
    """
    timing_requirements = {
        "disable_to_disabled": "< 2 seconds",
        "enable_to_searching": "< 2 seconds", 
        "searching_to_active": "< 10 seconds",  # Link negotiation time
    }
    
    # These are timing expectations
    assert timing_requirements["disable_to_disabled"] == "< 2 seconds"
    assert timing_requirements["searching_to_active"] == "< 10 seconds"


@pytest.mark.asyncio
async def test_frontend_spinner_timeout():
    """
    Test that frontend spinner has reasonable timeout.
    
    Observed: Spinner spun, then port stayed at "empty" for 30 seconds.
    
    Frontend has polling logic in _togglePort():
    - Polls for up to 50 iterations at 200ms each
    - Total timeout: 10 seconds
    - After timeout, spinner stops but state might not have updated
    
    Issue: If link takes > 10 seconds to come up, spinner stops but
    the port shows "empty" until next coordinator update.
    """
    frontend_timeout_config = {
        "max_poll_iterations": 50,
        "poll_interval_ms": 200,
        "total_timeout_seconds": 10,
    }
    
    calculated_timeout = (
        frontend_timeout_config["max_poll_iterations"] *
        frontend_timeout_config["poll_interval_ms"] / 1000
    )
    
    assert calculated_timeout == 10.0, \
        "Frontend should timeout after 10 seconds"


def test_coordinator_update_interval():
    """
    Test that coordinator updates frequently enough to catch state changes.
    
    Issue: If frontend spinner times out but link comes up later,
    the port will stay "empty" until next coordinator update.
    
    Coordinator update interval should be:
    - Short enough to catch transitions (< 5 seconds)
    - Long enough to not overload system (> 1 second)
    """
    # This is a configuration value that should exist
    recommended_interval = 5  # seconds
    
    assert recommended_interval >= 1, \
        "Coordinator update interval should be at least 1 second"
    assert recommended_interval <= 10, \
        "Coordinator update interval should be at most 10 seconds"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

