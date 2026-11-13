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
    # The button starts its power cycle as a config entry task.
    coordinator.config_entry.async_create_task.side_effect = (
        lambda _hass, coro, _name: asyncio.ensure_future(coro)
    )
    return coordinator


def _switch() -> ExavizPoEPortSwitch:
    return ExavizPoEPortSwitch(_coordinator("onboard", "onboard"), "onboard", 0, "e")


def _button(poe_set: str = "onboard", poe_system: str = "onboard") -> ExavizPoEPortResetButton:
    button = ExavizPoEPortResetButton(_coordinator(poe_set, poe_system), poe_set, 0, "e")
    button.hass = MagicMock()
    return button


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
    assert calls[-1] == "enable-port 1 0"


@pytest.mark.asyncio
async def test_cycle_cancelled_while_the_write_will_not_stop_sends_nothing_after_it(caplog):
    """An unstoppable disable write may still land, so no enable-port follows
    it; the task still ends as cancelled and the failure is not hidden."""
    button = _button()
    calls: list[str] = []
    reached = asyncio.Event()

    async def send(command: str) -> bool:
        calls.append(command)
        if command.startswith("disable-port"):
            reached.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                raise HomeAssistantError("did not stop") from None
        raise HomeAssistantError("did not stop")

    with patch.object(ExavizPoEPortSwitch, "_send_esp32_command", side_effect=send):
        cycle = asyncio.create_task(button._power_cycle_onboard_port())
        await reached.wait()
        cycle.cancel()
        with pytest.raises(HomeAssistantError, match="did not stop"):
            await cycle
    assert calls == ["disable-port 1 0"]


@pytest.mark.parametrize("resend_result", ["ok", "raises", "false"])
@pytest.mark.asyncio
async def test_cancel_during_the_restore_write_resends_it(resend_result, caplog):
    """Shutdown cancels once. If that lands on the restore write itself (the
    write is killed), the restore is sent again; the cancel stays the outcome
    even when the second write will not stop (it is logged)."""
    button = _button()
    calls: list[str] = []
    in_restore = asyncio.Event()

    async def send(command: str) -> bool:
        calls.append(command)
        if command.startswith("enable-port") and calls.count(command) == 1:
            in_restore.set()
            await asyncio.Event().wait()  # cancelled here
        if command.startswith("enable-port") and resend_result == "raises":
            raise HomeAssistantError("did not stop")
        return resend_result != "false"

    async def link(interface: str, action: str) -> bool:
        return True

    async def settle(delay):
        return None

    with patch.object(ExavizPoEPortSwitch, "_send_esp32_command", side_effect=send), \
         patch.object(ExavizPoEPortSwitch, "_run_ip_link", side_effect=link), \
         patch("custom_components.exaviz.button.asyncio.sleep", side_effect=settle):
        cycle = asyncio.create_task(button._power_cycle_onboard_port())
        await in_restore.wait()
        cycle.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cycle
    assert calls == ["disable-port 1 0", "enable-port 1 0", "enable-port 1 0"]
    assert ("Could not turn port poe0 back on" in caplog.text) is (resend_result != "ok")


@pytest.mark.parametrize("cancel_at", ["disable-port", "settle"])
@pytest.mark.asyncio
async def test_cycle_cancelled_then_a_failed_turn_on_is_logged(cancel_at, caplog):
    """Shutdown cancels the cycle; if the turn-on that follows fails (a plain
    False, not another cancel), say so: the port may be left off."""
    button = _button()
    reached = asyncio.Event()

    async def send(command: str) -> bool:
        if command.startswith("disable-port"):
            if cancel_at == "disable-port":
                reached.set()
                await asyncio.Event().wait()
            return True
        return False  # enable-port fails

    async def link(interface: str, action: str) -> bool:
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
    assert "Could not turn port poe0 back on" in caplog.text


@pytest.mark.asyncio
async def test_cycle_cancelled_during_the_settle_leaves_the_link_up_too():
    button = _button()
    calls: list[str] = []
    in_settle = asyncio.Event()

    async def send(command: str) -> bool:
        calls.append(command)
        return True

    async def link(interface: str, action: str) -> bool:
        calls.append(f"link {action}")
        return True

    async def settle(delay):
        in_settle.set()
        await asyncio.Event().wait()

    with patch.object(ExavizPoEPortSwitch, "_send_esp32_command", side_effect=send), \
         patch.object(ExavizPoEPortSwitch, "_run_ip_link", side_effect=link), \
         patch("custom_components.exaviz.button.asyncio.sleep", side_effect=settle):
        cycle = asyncio.create_task(button._power_cycle_onboard_port())
        await in_settle.wait()
        cycle.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cycle
    assert calls == ["disable-port 1 0", "link down", "link up", "enable-port 1 0"]


@pytest.mark.asyncio
async def test_cancel_during_the_restore_write_with_the_real_write_path(tmp_path):
    """Same as above through the real _send_esp32_command and a real kill: the
    device must end up having received enable-port."""
    import custom_components.exaviz.switch as switch_module

    device = tmp_path / "pse"
    device.write_text("")
    button = _button()
    written: list[str] = []
    killed: list[str] = []
    in_restore = asyncio.Event()
    n_enable = 0

    class Proc:
        returncode = None

        def __init__(self, command, block):
            self.command, self.block = command, block

        async def communicate(self):
            if self.block:
                in_restore.set()
                await asyncio.Event().wait()
            written.append(self.command)
            self.returncode = 0
            return b"", b""

        async def wait(self):
            self.returncode = -9

        def kill(self):
            killed.append(self.command)

    async def exec_(*args, **kwargs):
        nonlocal n_enable
        command = args[2].split("'")[1]
        block = command.startswith("enable-port") and n_enable == 0
        n_enable += command.startswith("enable-port")
        return Proc(command, block)

    async def link(interface: str, action: str) -> bool:
        return True

    async def settle(delay):
        return None

    with patch.object(switch_module, "_PSE_DEVICE_PATHS", [device]), \
         patch("asyncio.create_subprocess_exec", side_effect=exec_), \
         patch.object(ExavizPoEPortSwitch, "_run_ip_link", side_effect=link), \
         patch("custom_components.exaviz.button.asyncio.sleep", side_effect=settle):
        cycle = asyncio.create_task(button._power_cycle_onboard_port())
        await in_restore.wait()
        cycle.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cycle
    assert written == ["disable-port 1 0", "enable-port 1 0"]
    assert killed == ["enable-port 1 0"]  # the cancelled restore write was killed


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
