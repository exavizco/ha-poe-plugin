"""Local port commands must surface a failed step, never report success.

A False from the ESP32 command or a failed `ip link` / `tee` used to be
logged and ignored, so the UI showed the action as done.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.exaviz.button import ExavizPoEPortResetButton
from custom_components.exaviz.switch import ExavizPoEPortSwitch

pytestmark = pytest.mark.asyncio


def _coordinator(poe_set: str, poe_system: str) -> MagicMock:
    coordinator = MagicMock()
    coordinator.remote = None
    coordinator.data = {
        "poe": {
            poe_set: {
                "pse_id": "pse0",
                "ports": [{"port": 0, "enabled": True, "poe_system": poe_system}],
            }
        }
    }
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


def _switch() -> ExavizPoEPortSwitch:
    return ExavizPoEPortSwitch(_coordinator("onboard", "onboard"), "onboard", 0, "e")


def _button(poe_set: str = "onboard", poe_system: str = "onboard") -> ExavizPoEPortResetButton:
    return ExavizPoEPortResetButton(_coordinator(poe_set, poe_system), poe_set, 0, "e")


def _patch_switch(esp32: dict[str, bool], link: dict[str, bool]):
    """Patch the two command helpers; record the calls in order."""
    calls: list[str] = []

    async def send(command: str) -> bool:
        calls.append(command)
        return esp32.get(command.split()[0], True)

    async def run_ip_link(self, interface: str, action: str) -> bool:
        calls.append(f"link {action}")
        return link.get(action, True)

    return calls, (
        patch.object(ExavizPoEPortSwitch, "_send_esp32_command", side_effect=send),
        patch.object(ExavizPoEPortSwitch, "_run_ip_link", run_ip_link),
    )


def _proc(returncode: int) -> MagicMock:
    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(b"", b"boom"))
    proc.returncode = returncode
    return proc


# --- switch -------------------------------------------------------------------


async def test_turn_off_fails_when_power_cut_fails():
    switch = _switch()
    calls, (p1, p2) = _patch_switch({"disable-port": False}, {})
    with p1, p2, pytest.raises(HomeAssistantError, match="disable"):
        await switch.async_turn_off()
    # Power is still on, so the link is left up.
    assert calls == ["disable-port 1 0"]
    switch.coordinator.async_request_refresh.assert_awaited_once()


async def test_turn_off_fails_when_link_down_fails():
    switch = _switch()
    calls, (p1, p2) = _patch_switch({}, {"down": False})
    with p1, p2, pytest.raises(HomeAssistantError):
        await switch.async_turn_off()
    assert calls == ["disable-port 1 0", "link down"]
    switch.coordinator.async_request_refresh.assert_awaited_once()


async def test_turn_on_fails_when_power_restore_fails():
    switch = _switch()
    calls, (p1, p2) = _patch_switch({"enable-port": False}, {})
    with p1, p2, pytest.raises(HomeAssistantError, match="enable"):
        await switch.async_turn_on()
    assert calls == ["link up", "enable-port 1 0"]
    switch.coordinator.async_request_refresh.assert_awaited_once()


async def test_turn_on_still_restores_power_when_link_up_fails():
    switch = _switch()
    calls, (p1, p2) = _patch_switch({}, {"up": False})
    with p1, p2, pytest.raises(HomeAssistantError):
        await switch.async_turn_on()
    assert calls == ["link up", "enable-port 1 0"]


async def test_turn_on_and_off_succeed_quietly():
    switch = _switch()
    calls, (p1, p2) = _patch_switch({}, {})
    with p1, p2:
        await switch.async_turn_off()
        await switch.async_turn_on()
    assert calls == ["disable-port 1 0", "link down", "link up", "enable-port 1 0"]


async def test_send_esp32_command_without_device_returns_false(tmp_path):
    missing = tmp_path / "pse"
    with patch("custom_components.exaviz.switch._PSE_DEVICE_PATHS", [missing]):
        assert await ExavizPoEPortSwitch._send_esp32_command("enable-port 1 0") is False


# --- onboard reset button -----------------------------------------------------


def _patch_button(esp32: dict[str, bool], link_rc: dict[str, int]):
    calls: list[str] = []

    async def send(command: str) -> bool:
        calls.append(command)
        return esp32.get(command.split()[0], True)

    async def exec_(*argv, **kwargs):
        action = argv[-1]
        calls.append(f"link {action}")
        return _proc(link_rc.get(action, 0))

    return calls, (
        patch.object(ExavizPoEPortSwitch, "_send_esp32_command", side_effect=send),
        patch("asyncio.create_subprocess_exec", side_effect=exec_),
        patch("asyncio.sleep", AsyncMock()),
    )


async def test_onboard_reset_fails_when_power_cut_fails():
    button = _button()
    calls, (p1, p2, p3) = _patch_button({"disable-port": False}, {})
    with p1, p2, p3, pytest.raises(HomeAssistantError):
        await button.async_press()
    # Nothing was cut, so nothing is touched.
    assert calls == ["disable-port 1 0"]


async def test_onboard_reset_restores_power_when_link_down_fails():
    button = _button()
    calls, (p1, p2, p3) = _patch_button({}, {"down": 1})
    with p1, p2, p3, pytest.raises(HomeAssistantError):
        await button.async_press()
    assert calls == ["disable-port 1 0", "link down", "link up", "enable-port 1 0"]


async def test_onboard_reset_fails_when_power_restore_fails():
    button = _button()
    calls, (p1, p2, p3) = _patch_button({"enable-port": False}, {})
    with p1, p2, p3, pytest.raises(HomeAssistantError):
        await button.async_press()
    assert calls == ["disable-port 1 0", "link down", "link up", "enable-port 1 0"]


async def test_onboard_reset_succeeds_quietly():
    button = _button()
    calls, (p1, p2, p3) = _patch_button({}, {})
    with p1, p2, p3:
        await button.async_press()
    assert calls == ["disable-port 1 0", "link down", "link up", "enable-port 1 0"]
    button.coordinator.async_request_refresh.assert_awaited_once()


# --- add-on reset button ------------------------------------------------------


@pytest.mark.parametrize("failing_write", [0, 1])
async def test_addon_reset_fails_when_a_write_fails(failing_write):
    button = _button("addon_0", "addon")
    writes: list[bytes] = []

    async def exec_(*argv, **kwargs):
        proc = MagicMock()
        proc.returncode = 0

        async def communicate(input=None):
            writes.append(input)
            if len(writes) - 1 == failing_write:
                proc.returncode = 1
            return b"", b""

        proc.communicate = communicate
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=exec_), \
         patch("asyncio.sleep", AsyncMock()), \
         pytest.raises(HomeAssistantError):
        await button.async_press()
    assert len(writes) == failing_write + 1


async def test_addon_reset_fails_when_tee_cannot_start():
    button = _button("addon_0", "addon")
    with patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=OSError("no sudo"))), \
         pytest.raises(HomeAssistantError, match="no sudo"):
        await button.async_press()
