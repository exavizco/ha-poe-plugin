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


@pytest.mark.parametrize(
    ("service", "link", "expected", "message"),
    [
        ("async_turn_off", "down", ["disable-port 1 0", "link down"], "power is off, but"),
        ("async_turn_on", "up", ["link up", "enable-port 1 0"], "power is on, but"),
    ],
)
@pytest.mark.asyncio
async def test_failed_link_step_is_reported_after_the_power_step(service, link, expected, message):
    """The switch shows the link state, so a failed link step is an error too."""
    switch = _switch()
    calls, (p1, p2) = _patch_switch({}, {link: False})
    with p1, p2, pytest.raises(HomeAssistantError, match=message):
        await getattr(switch, service)()
    assert calls == expected
    switch.coordinator.async_request_refresh.assert_awaited_once()


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
         patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=OSError("no sudo"))), \
         pytest.raises(HomeAssistantError, match="link did not come up"):
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
    # A timed-out disable may still have landed, so power is sent back on;
    # the link is not touched.
    assert calls == ["disable-port 1 0", "enable-port 1 0"]
    button.coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_reset_sends_nothing_after_a_write_that_did_not_stop():
    """A disable that may still land must not be followed by enable-port."""
    button = _button()
    sent: list[str] = []

    async def send(command: str) -> bool:
        sent.append(command)
        if command.startswith("disable-port"):
            raise HomeAssistantError("The write of 'disable-port 1 0' did not stop")
        return True

    with patch.object(ExavizPoEPortSwitch, "_send_esp32_command", side_effect=send), \
         pytest.raises(HomeAssistantError, match="did not stop"):
        await button.async_press()
    assert sent == ["disable-port 1 0"]


@pytest.mark.parametrize("link_rc", [{"down": 1}, {"down": "oserror"}])
@pytest.mark.asyncio
async def test_onboard_reset_ends_powered_and_up_after_a_failed_link_down(link_rc):
    button = _button()
    calls, (p1, p2, p3) = _patch_button({}, link_rc)
    with p1, p2, p3:
        await button.async_press()
    assert calls == FULL_RESET


@pytest.mark.parametrize("link_rc", [{"up": 1}, {"up": "oserror"}])
@pytest.mark.asyncio
async def test_onboard_reset_restores_power_and_reports_a_link_left_down(link_rc):
    button = _button()
    calls, (p1, p2, p3) = _patch_button({}, link_rc)
    with p1, p2, p3, pytest.raises(HomeAssistantError, match="did not come back up"):
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


@pytest.mark.parametrize(
    ("cancel_at", "restore_ok"),
    [("disable-port", True), ("settle", True), ("settle", False)],
)
@pytest.mark.asyncio
async def test_cancelled_reset_still_finishes_the_cycle(cancel_at, restore_ok, caplog):
    """A press cancelled mid-cycle (restarted script, shutdown) completes it,
    then logs a failed restore and refreshes the state itself."""
    button = _button()
    button.hass = MagicMock()
    calls: list[str] = []
    reached = asyncio.Event()
    go_on = asyncio.Event()

    async def send(command: str) -> bool:
        if command.startswith(cancel_at):
            reached.set()
            await go_on.wait()
        calls.append(command)
        return restore_ok or not command.startswith("enable-port")

    async def link(interface: str, action: str) -> bool:
        calls.append(f"link {action}")
        return True

    real_sleep = asyncio.sleep

    async def settle(delay):
        if cancel_at == "settle":
            reached.set()
            await go_on.wait()

    with patch.object(ExavizPoEPortSwitch, "_send_esp32_command", side_effect=send), \
         patch.object(ExavizPoEPortSwitch, "_run_ip_link", side_effect=link), \
         patch("custom_components.exaviz.button.asyncio.sleep", side_effect=settle):
        press = asyncio.create_task(button._reset_onboard_port())
        await reached.wait()
        press.cancel()
        with pytest.raises(asyncio.CancelledError):
            await press
        button.hass.async_create_task.assert_not_called()
        go_on.set()
        for _ in range(10):
            await real_sleep(0)
    assert calls == FULL_RESET
    # The refresh comes after the cycle, not when the press was cancelled.
    button.hass.async_create_task.assert_called_once()
    button.hass.async_create_task.call_args.args[0].close()
    failed = "Reset of PoE port onboard:0 (press cancelled) failed" in caplog.text
    assert failed is not restore_ok


@pytest.mark.parametrize("cancel_at", ["disable-port", "settle"])
@pytest.mark.asyncio
async def test_cycle_task_cancelled_at_shutdown_still_turns_the_port_on(cancel_at):
    """At final shutdown the runner cancels the cycle task itself (the shield
    only protects it from a cancelled press). The port must not stay off."""
    button = _button()
    button.hass = MagicMock()
    calls: list[str] = []
    reached = asyncio.Event()

    async def send(command: str) -> bool:
        calls.append(command)
        if command.startswith(cancel_at):
            reached.set()
            await asyncio.Event().wait()  # blocked until cancelled
        return True

    async def link(interface: str, action: str) -> bool:
        calls.append(f"link {action}")
        return True

    async def settle(delay):
        reached.set()
        await asyncio.Event().wait()

    with patch.object(ExavizPoEPortSwitch, "_send_esp32_command", side_effect=send), \
         patch.object(ExavizPoEPortSwitch, "_run_ip_link", side_effect=link), \
         patch("custom_components.exaviz.button.asyncio.sleep", side_effect=settle):
        cycle = asyncio.create_task(button._power_cycle_onboard_port())
        await reached.wait()
        cycle.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cycle
    assert calls[-1].startswith("enable-port")


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


@pytest.mark.asyncio
async def test_pressing_an_addon_reset_directly_is_refused():
    """Never runs the onboard cycle (it would cut onboard poe0)."""
    button = _button("addon_0", "addon")
    sent: list[str] = []

    async def send(command: str) -> bool:
        sent.append(command)
        return True

    with patch.object(ExavizPoEPortSwitch, "_send_esp32_command", side_effect=send), \
         pytest.raises(HomeAssistantError, match="not supported on add-on board port"):
        await button.async_press()
    assert sent == []
