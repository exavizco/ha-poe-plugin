"""Local port commands must surface a failed step, never report success.

A False from the ESP32 command or a failed `ip link` / `tee` used to be
logged and ignored, so the UI showed the action as done.
"""
from __future__ import annotations

import asyncio

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.exaviz.button import ExavizPoEPortResetButton
from custom_components.exaviz.switch import ExavizPoEPortSwitch



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


@pytest.mark.asyncio
async def test_turn_off_fails_when_power_cut_fails():
    switch = _switch()
    calls, (p1, p2) = _patch_switch({"disable-port": False}, {})
    with p1, p2, pytest.raises(HomeAssistantError, match="did not disable port poe0"):
        await switch.async_turn_off()
    # Power is still on, so the link is left up.
    assert calls == ["disable-port 1 0"]
    switch.coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_turn_on_fails_when_power_restore_fails():
    switch = _switch()
    calls, (p1, p2) = _patch_switch({"enable-port": False}, {})
    with p1, p2, pytest.raises(HomeAssistantError, match="did not enable port poe0"):
        await switch.async_turn_on()
    assert calls == ["link up", "enable-port 1 0"]
    switch.coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.parametrize(("service", "link"), [("async_turn_off", "down"), ("async_turn_on", "up")])
@pytest.mark.asyncio
async def test_failed_link_step_is_not_an_error_when_power_changed(service, link):
    """Power is the port's job; a failed link step is only logged."""
    switch = _switch()
    calls, (p1, p2) = _patch_switch({}, {link: False})
    with p1, p2:
        await getattr(switch, service)()
    assert f"link {link}" in calls
    assert any(c.endswith("able-port 1 0") for c in calls)


@pytest.mark.asyncio
async def test_turn_on_and_off_succeed_quietly():
    switch = _switch()
    calls, (p1, p2) = _patch_switch({}, {})
    with p1, p2:
        await switch.async_turn_off()
        await switch.async_turn_on()
    assert calls == ["disable-port 1 0", "link down", "link up", "enable-port 1 0"]


@pytest.mark.asyncio
async def test_run_ip_link_returns_false_when_it_cannot_start():
    with patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=OSError("no sudo"))):
        assert await ExavizPoEPortSwitch._run_ip_link("poe0", "up") is False


@pytest.mark.asyncio
async def test_turn_on_restores_power_when_ip_cannot_start():
    switch = _switch()
    sent: list[str] = []

    async def send(command: str) -> bool:
        sent.append(command)
        return True

    with patch.object(ExavizPoEPortSwitch, "_send_esp32_command", side_effect=send), \
         patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=OSError("no sudo"))):
        await switch.async_turn_on()
    assert sent == ["enable-port 1 0"]


# --- onboard reset button -----------------------------------------------------


def _patch_button(esp32: dict[str, bool], link_rc: dict[str, int]):
    calls: list[str] = []

    async def send(command: str) -> bool:
        calls.append(command)
        return esp32.get(command.split()[0], True)

    async def exec_(*argv, **kwargs):
        action = argv[-1]
        calls.append(f"link {action}")
        if link_rc.get(action) == "oserror":
            raise OSError("no sudo")
        return _proc(link_rc.get(action, 0))

    return calls, (
        patch.object(ExavizPoEPortSwitch, "_send_esp32_command", side_effect=send),
        patch("asyncio.create_subprocess_exec", side_effect=exec_),
        patch("asyncio.sleep", AsyncMock()),
    )


FULL_RESET = ["disable-port 1 0", "link down", "link up", "enable-port 1 0"]


@pytest.mark.asyncio
async def test_onboard_reset_fails_when_power_cut_fails():
    button = _button()
    calls, (p1, p2, p3) = _patch_button({"disable-port": False}, {})
    with p1, p2, p3, pytest.raises(HomeAssistantError, match="did not disable port poe0"):
        await button.async_press()
    # Nothing was cut, so nothing is touched.
    assert calls == ["disable-port 1 0"]
    button.coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.parametrize("link_rc", [{"down": 1}, {"up": 1}, {"down": "oserror"}])
@pytest.mark.asyncio
async def test_onboard_reset_restores_power_when_a_link_step_fails(link_rc):
    button = _button()
    calls, (p1, p2, p3) = _patch_button({}, link_rc)
    with p1, p2, p3:
        await button.async_press()
    assert calls == FULL_RESET


@pytest.mark.asyncio
async def test_onboard_reset_fails_when_power_restore_fails():
    button = _button()
    calls, (p1, p2, p3) = _patch_button({"enable-port": False}, {})
    with p1, p2, p3, pytest.raises(HomeAssistantError, match="back on after the reset"):
        await button.async_press()
    assert calls == FULL_RESET
    button.coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancelled_reset_still_restores_power():
    button = _button()
    sent: list[str] = []

    async def send(command: str) -> bool:
        sent.append(command)
        return True

    with patch.object(ExavizPoEPortSwitch, "_send_esp32_command", side_effect=send), \
         patch.object(ExavizPoEPortSwitch, "_run_ip_link", AsyncMock(return_value=True)), \
         patch("asyncio.sleep", AsyncMock(side_effect=asyncio.CancelledError)), \
         pytest.raises(asyncio.CancelledError):
        await button._reset_onboard_port()
    assert sent == ["disable-port 1 0", "enable-port 1 0"]


@pytest.mark.asyncio
async def test_onboard_reset_succeeds_quietly():
    button = _button()
    calls, (p1, p2, p3) = _patch_button({}, {})
    with p1, p2, p3:
        await button.async_press()
    assert calls == FULL_RESET
    button.coordinator.async_request_refresh.assert_awaited_once()


# --- add-on reset button ------------------------------------------------------


def test_addon_reset_button_is_unavailable_with_a_note():
    """Like the add-on switch: the driver has no /proc/pse write interface."""
    button = _button("addon_0", "addon")
    button.coordinator.can_control = True
    button.coordinator.last_update_success = True
    assert button.available is False
    assert button.extra_state_attributes["control_available"] is False
    onboard = _button()
    onboard.coordinator.can_control = True
    onboard.coordinator.last_update_success = True
    assert onboard.available is True
