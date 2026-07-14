"""T-10/T-11/T-12: enable and reset-button must not send bare ESP32 reset.

os-support #57 / Joost HA PoE mass re-enable. Bare token 'reset' reboots the
chip and re-inits all ports. Fixed firmware re-arms DCE on enable-port alone.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.exaviz.button import ExavizPoEPortResetButton
from custom_components.exaviz.switch import ExavizPoEPortSwitch


def _is_bare_reset(command: str) -> bool:
    """Exact bare reset token only; reset-port is allowed."""
    return command.strip() == "reset"


def _make_switch(port_number: int = 0) -> ExavizPoEPortSwitch:
    coordinator = MagicMock()
    coordinator.data = {
        "poe": {
            "onboard": {
                "ports": [{"port": port_number, "enabled": False, "poe_system": "onboard"}],
            }
        }
    }
    coordinator.async_request_refresh = AsyncMock()
    coordinator.last_update_success = True
    coordinator.board_type = None
    return ExavizPoEPortSwitch(coordinator, "onboard", port_number, "entry")


def _make_reset_button(port_number: int = 0) -> ExavizPoEPortResetButton:
    coordinator = MagicMock()
    coordinator.data = {
        "poe": {
            "onboard": {
                "ports": [{"port": port_number, "enabled": True, "poe_system": "onboard"}],
            }
        }
    }
    coordinator.async_request_refresh = AsyncMock()
    coordinator.last_update_success = True
    coordinator.board_type = None
    return ExavizPoEPortResetButton(coordinator, "onboard", port_number, "entry")


@pytest.mark.asyncio
async def test_enable_port_no_esp32_reset():
    """T-10: public enable path sends enable-port; forbids bare reset."""
    switch = _make_switch(0)
    commands: list[str] = []

    async def capture(cmd: str) -> bool:
        commands.append(cmd)
        return True

    with patch.object(ExavizPoEPortSwitch, "_send_esp32_command", side_effect=capture):
        ok = await switch._esp32_enable_port()

    assert ok is True
    assert any(c.startswith("enable-port ") for c in commands)
    assert "enable-port 1 0" in commands  # linux poe0 → PSE1 port0
    assert not any(_is_bare_reset(c) for c in commands)


@pytest.mark.asyncio
async def test_reset_button_no_esp32_reset():
    """T-11: reset button path: no bare reset; still sends enable-port or reset-port."""
    button = _make_reset_button(4)  # linux poe4 → PSE0 port0
    commands: list[str] = []

    async def capture(cmd: str) -> bool:
        commands.append(cmd)
        return True

    fake_proc = MagicMock()
    fake_proc.communicate = AsyncMock(return_value=(b"", b""))
    fake_proc.returncode = 0

    with patch.object(ExavizPoEPortSwitch, "_send_esp32_command", side_effect=capture), \
         patch("asyncio.create_subprocess_exec", AsyncMock(return_value=fake_proc)), \
         patch("asyncio.sleep", AsyncMock()):
        await button._reset_onboard_port()

    assert not any(_is_bare_reset(c) for c in commands)
    assert any(
        c.startswith("enable-port ") or c.startswith("reset-port ")
        for c in commands
    ), f"expected enable-port or reset-port, got {commands}"


@pytest.mark.asyncio
async def test_enable_returns_enable_result():
    """T-12: enable returns success/failure of enable-port, not of reset."""
    switch = _make_switch(5)  # PSE0 port1

    async def enable_only(cmd: str) -> bool:
        if cmd.strip() == "reset":
            return True
        if cmd.startswith("enable-port"):
            return False
        return True

    with patch.object(ExavizPoEPortSwitch, "_send_esp32_command", side_effect=enable_only), \
         patch("asyncio.sleep", AsyncMock()):
        ok = await switch._esp32_enable_port()

    assert ok is False
