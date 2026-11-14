"""Local port commands must surface a failed step, never report success.

A False from the ESP32 command or a failed `ip link` / `tee` used to be
logged and ignored, so the UI showed the action as done.
"""
from __future__ import annotations

import asyncio
import signal
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.exaviz.button import ExavizPoEPortResetButton
from custom_components.exaviz.switch import ExavizPoEPortSwitch
from tests.hung_ip_link import HungIpLink



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
        patch("custom_components.exaviz.button.RESET_POWER_OFF_SECONDS", 0),
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
    # Power comes back first; after a cancelled settle the link follows.
    tail = ["enable-port 1 0"] if cancel_at == "disable-port" else ["enable-port 1 0", "link up"]
    assert calls[-len(tail):] == tail


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
async def test_cycle_cancelled_during_the_settle_turns_power_on_then_the_link():
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
    # Power first, so a stuck `ip link` cannot keep the port off.
    assert calls == ["disable-port 1 0", "link down", "enable-port 1 0", "link up"]


@pytest.mark.asyncio
async def test_cycle_cancelled_during_the_settle_sends_nothing_after_a_stuck_restore():
    """The cancel path's restore write will not stop: it may still land, so
    neither a second enable-port nor the link step follows it."""
    button = _button()
    calls: list[str] = []
    in_settle = asyncio.Event()

    async def send(command: str) -> bool:
        calls.append(command)
        if command.startswith("enable-port"):
            raise HomeAssistantError("did not stop")
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
        with pytest.raises(HomeAssistantError, match="did not stop"):
            await cycle
    assert calls == ["disable-port 1 0", "link down", "enable-port 1 0"]


@pytest.mark.asyncio
async def test_finish_waits_for_a_cycle_that_reports_cancelling_for_its_own_reason():
    """A serial write that times out inside the cycle makes the cycle report
    cancelling() for a moment. The stop must still wait for that cycle."""
    button = _button()
    write_done = asyncio.Event()

    async def cycle_body() -> None:
        task = asyncio.current_task()
        task.cancel()  # what wait_for's timeout does to its own task
        try:
            await asyncio.sleep(0)
        except asyncio.CancelledError:
            pass  # caught inside the cycle; cancelling() stays above 0
        await write_done.wait()

    cycle = asyncio.create_task(cycle_body())
    button._cycles.add(cycle)
    cycle.add_done_callback(button._cycles.discard)
    await asyncio.sleep(0)
    assert cycle.cancelling()

    finish = asyncio.create_task(button._async_finish_cycles())
    await asyncio.sleep(0.05)
    assert not finish.done()
    write_done.set()
    await finish
    assert cycle.done() and not cycle.cancelled()


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


# --- a reset whose `ip link` hangs, with real processes -----------------------


@contextmanager
def _reset_with_hung_link(tmp_path, *, ignore_term: bool):
    """A button whose reset runs the real `_run_ip_link` under the stand-in
    sudo; `ip link down` hangs, `up` returns at once."""
    import custom_components.exaviz.switch as switch_module

    hung = HungIpLink(tmp_path, sudo=True, ignore_term=ignore_term, hang=("down",))
    sent: list[str] = []

    async def send(command: str) -> bool:
        sent.append(command)
        return True

    try:
        with hung.patches(), \
             patch.object(ExavizPoEPortSwitch, "_send_esp32_command", side_effect=send), \
             patch.object(switch_module, "IP_LINK_TIMEOUT", 2), \
             patch.object(switch_module, "IP_LINK_STOP_WAIT", 0.5), \
             patch("custom_components.exaviz.button.RESET_POWER_OFF_SECONDS", 0):
            yield _button(), hung, sent
    finally:
        hung.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True], ids=["timed-out", "cancelled"])
async def test_reset_runs_no_link_up_while_a_hung_link_down_still_runs(tmp_path, cancel):
    """`ip link down` hangs and will not stop (sudo cannot pass SIGKILL on).
    The reset turns the power back on but starts no `ip link up`, which the
    stuck `down` could land after."""
    with _reset_with_hung_link(tmp_path, ignore_term=True) as (button, hung, sent):
        cycle = asyncio.ensure_future(button._power_cycle_onboard_port())
        if cancel:
            await _within(lambda: hung.ip_pids)
            cycle.cancel()
        with pytest.raises(HomeAssistantError, match="did not stop"):
            await asyncio.wait_for(cycle, timeout=10)
        assert sent == ["disable-port 1 0", "enable-port 1 0"]
        assert [action for action, _ in hung.started] == ["down"]
        assert hung.ip_alive() == [True]


@pytest.mark.asyncio
async def test_reset_cancelled_in_a_hung_link_down_brings_the_link_up_after_it_ends(
    tmp_path,
):
    """When SIGTERM (through sudo) does end the stuck `down`, the cancel path
    turns the power on and then runs `ip link up`, after the `down` ended."""
    with _reset_with_hung_link(tmp_path, ignore_term=False) as (button, hung, sent):
        cycle = asyncio.ensure_future(button._power_cycle_onboard_port())
        await _within(lambda: hung.ip_pids)
        cycle.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(cycle, timeout=10)
        assert sent == ["disable-port 1 0", "enable-port 1 0"]
        assert hung.started == [("down", False), ("up", False)]


@pytest.mark.asyncio
async def test_turn_on_with_a_stuck_link_up_still_restores_power(tmp_path):
    """Power is what the user asked for: a stuck `ip link up` does not keep
    the serial enable-port from going out."""
    import custom_components.exaviz.switch as switch_module

    hung = HungIpLink(tmp_path, sudo=True, ignore_term=True, hang=("up",))
    switch = _switch()
    sent: list[str] = []

    async def send(command: str) -> bool:
        sent.append(command)
        return True

    try:
        with hung.patches(), \
             patch.object(ExavizPoEPortSwitch, "_send_esp32_command", side_effect=send), \
             patch.object(switch_module, "IP_LINK_TIMEOUT", 1), \
             patch.object(switch_module, "IP_LINK_STOP_WAIT", 0.5):
            with pytest.raises(HomeAssistantError, match="did not stop"):
                await asyncio.wait_for(switch.async_turn_on(), timeout=10)
        assert sent == ["enable-port 1 0"]
    finally:
        hung.cleanup()


@pytest.mark.asyncio
async def test_no_ip_link_runs_on_a_port_while_an_earlier_one_is_stuck(tmp_path):
    """A reset's `ip link down` will not stop. Turning the port on afterwards
    restores power but starts no `ip link up` until that `down` has ended,
    since the `down` could land after it. Once it ends, the link step runs."""
    with _reset_with_hung_link(tmp_path, ignore_term=True) as (button, hung, sent):
        with pytest.raises(HomeAssistantError, match="did not stop"):
            await asyncio.wait_for(button._power_cycle_onboard_port(), timeout=10)
        switch = _switch()
        with pytest.raises(HomeAssistantError, match="has not ended"):
            await switch.async_turn_on()
        assert [action for action, _ in hung.started] == ["down"]
        assert sent == ["disable-port 1 0", "enable-port 1 0", "enable-port 1 0"]

        hung.cleanup()  # the stuck `down` ends
        await asyncio.wait_for(_until_ended(hung.procs[0]), timeout=10)
        await switch.async_turn_on()
        assert hung.started[-1] == ("up", False)


async def _until_ended(proc) -> None:
    while proc.returncode is None:
        await asyncio.sleep(0.01)


async def _within(condition, timeout: float = 10) -> None:
    async def until() -> None:
        while not condition():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(until(), timeout)


@pytest.mark.asyncio
@pytest.mark.parametrize("ignore_term", [False, True], ids=["ends-on-sigterm", "ignores-sigterm"])
async def test_reset_cancelled_while_ip_link_down_starts_runs_no_link_up(tmp_path, ignore_term):
    """Cancelled half way through starting `sudo ip link down`, asyncio would
    SIGKILL sudo and leave `ip` running. The start is let finish and the run
    is asked to stop; until it has ended no other `ip link` runs."""
    with _reset_with_hung_link(tmp_path, ignore_term=ignore_term) as (button, hung, sent):
        hung.gate = asyncio.Event()
        cycle = asyncio.ensure_future(button._power_cycle_onboard_port())
        await _within(lambda: sent == ["disable-port 1 0"])
        await asyncio.sleep(0.05)  # the start now waits on the gate
        cycle.cancel()
        with pytest.raises(HomeAssistantError, match="cancelled while it started"):
            await asyncio.wait_for(cycle, timeout=10)
        assert sent == ["disable-port 1 0", "enable-port 1 0"]
        hung.gate.set()
        await _within(lambda: hung.ip_pids)
        switch = _switch()
        if ignore_term:
            await asyncio.sleep(0.8)  # past the stop wait (0.5 s)
            assert hung.ip_alive() == [True]
            assert hung.procs[0].returncode is None  # sudo was not killed
            with pytest.raises(HomeAssistantError, match="has not ended"):
                await switch.async_turn_on()
            assert [action for action, _ in hung.started] == ["down"]
        else:
            # Asked to stop once started; then the port's link can be used.
            await asyncio.wait_for(_until_ended(hung.procs[0]), timeout=10)
            assert hung.procs[0].returncode == -signal.SIGTERM
            await switch.async_turn_on()
            assert hung.started[-1] == ("up", False)


@pytest.mark.asyncio
async def test_ip_link_started_while_another_is_being_stopped_waits_then_refuses(tmp_path):
    """The reset button and the switch are separate platforms, so a turn-on
    can start while a reset's stuck `down` is still being stopped. It waits
    its turn, then sees the stuck `down` and runs no `up`."""
    with _reset_with_hung_link(tmp_path, ignore_term=True) as (button, hung, sent):
        cycle = asyncio.ensure_future(button._power_cycle_onboard_port())
        await _within(lambda: hung.ip_pids)
        turn_on = asyncio.ensure_future(_switch().async_turn_on())
        with pytest.raises(HomeAssistantError, match="did not stop"):
            await asyncio.wait_for(cycle, timeout=10)
        with pytest.raises(HomeAssistantError, match="has not ended"):
            await asyncio.wait_for(turn_on, timeout=10)
        assert [action for action, _ in hung.started] == ["down"]


@pytest.mark.asyncio
async def test_reset_with_a_stuck_ip_link_leaves_the_power_alone(tmp_path):
    """Its link steps would be refused, so a second reset does not cut the
    power for a moment and turn it straight back on."""
    with _reset_with_hung_link(tmp_path, ignore_term=True) as (button, hung, sent):
        with pytest.raises(HomeAssistantError, match="did not stop"):
            await asyncio.wait_for(button._power_cycle_onboard_port(), timeout=10)
        before = list(sent)
        with pytest.raises(HomeAssistantError, match="was not reset"):
            await button._power_cycle_onboard_port()
        assert sent == before


@pytest.mark.asyncio
async def test_turn_on_with_a_stuck_link_up_logs_a_failed_power_restore(tmp_path, caplog):
    import custom_components.exaviz.switch as switch_module

    hung = HungIpLink(tmp_path, sudo=True, ignore_term=True, hang=("up",))
    try:
        with hung.patches(), \
             patch.object(ExavizPoEPortSwitch, "_send_esp32_command", AsyncMock(return_value=False)), \
             patch.object(switch_module, "IP_LINK_TIMEOUT", 1), \
             patch.object(switch_module, "IP_LINK_STOP_WAIT", 0.5):
            with pytest.raises(HomeAssistantError, match="did not stop"):
                await asyncio.wait_for(_switch().async_turn_on(), timeout=10)
        assert "The PoE controller did not enable port poe0 either" in caplog.text
    finally:
        hung.cleanup()


@pytest.mark.asyncio
async def test_ip_link_cancelled_while_starting_as_root_gets_sigkill(tmp_path):
    """Run as root, a run that ignores SIGTERM is killed after the stop wait,
    as one cancelled after it started would be."""
    import custom_components.exaviz.switch as switch_module

    hung = HungIpLink(tmp_path, sudo=False, ignore_term=True)
    try:
        with hung.patches(), patch.object(switch_module, "IP_LINK_STOP_WAIT", 0.5):
            hung.gate = asyncio.Event()
            run = asyncio.ensure_future(ExavizPoEPortSwitch._run_ip_link("poe3", "down"))
            await asyncio.sleep(0.05)  # the start now waits on the gate
            run.cancel()
            with pytest.raises(HomeAssistantError, match="cancelled while it started"):
                await asyncio.wait_for(run, timeout=10)
            hung.gate.set()
            await _within(lambda: hung.procs)
            await asyncio.wait_for(_until_ended(hung.procs[0]), timeout=10)
        assert hung.procs[0].returncode == -signal.SIGKILL
    finally:
        hung.cleanup()


@pytest.mark.asyncio
async def test_reset_waits_for_a_stuck_ip_link_being_stopped_before_cutting_power(tmp_path):
    """A second reset of the port (the first one's press was cancelled)
    starts while the first one's `ip link down` is still being stopped. It
    waits its turn, sees the stuck run, and sends nothing."""
    with _reset_with_hung_link(tmp_path, ignore_term=True) as (button, hung, sent):
        first = asyncio.ensure_future(button._power_cycle_onboard_port())
        await _within(lambda: hung.ip_pids)
        second = asyncio.ensure_future(_button()._power_cycle_onboard_port())
        with pytest.raises(HomeAssistantError, match="did not stop"):
            await asyncio.wait_for(first, timeout=10)
        with pytest.raises(HomeAssistantError, match="was not reset"):
            await asyncio.wait_for(second, timeout=10)
        assert sent == ["disable-port 1 0", "enable-port 1 0"]
