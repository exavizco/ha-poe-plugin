"""PoE port switch and reset button: state, attributes and command paths.

Failed onboard commands are covered in test_port_command_failures.py; this
file covers what the switch reports and the commands it actually runs: the
ESP32 line written to the serial device, `ip link set` argv, and the
add-on board /proc/pse paths.
"""
from __future__ import annotations

import asyncio
import logging
import signal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.exaviz import switch as switch_module
from custom_components.exaviz.board_detector import BoardType
from custom_components.exaviz.button import ExavizPoEPortResetButton
from custom_components.exaviz.switch import ExavizPoEPortSwitch
from custom_components.exaviz.utils import sudo_argv
from tests.hung_ip_link import HungIpLink


def _coordinator(data: dict | None, *, can_control: bool = True) -> MagicMock:
    coordinator = MagicMock()
    coordinator.remote = None
    coordinator.data = data
    coordinator.can_control = can_control
    coordinator.last_update_success = True
    coordinator.board_type = BoardType.CRUISER
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


def _data(poe_set: str, port: dict, pse_id: str | None = None) -> dict:
    poe_set_data: dict = {"ports": [port]}
    if pse_id:
        poe_set_data["pse_id"] = pse_id
    return {"poe": {poe_set: poe_set_data}}


def _proc(returncode: int, stderr: bytes = b"") -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(b"", stderr))
    return proc


# --- state and attributes -----------------------------------------------------


def test_is_on_follows_the_enabled_flag():
    on = ExavizPoEPortSwitch(_coordinator(_data("onboard", {"port": 3, "enabled": True})), "onboard", 3, "e")
    off = ExavizPoEPortSwitch(_coordinator(_data("onboard", {"port": 3, "enabled": False})), "onboard", 3, "e")
    assert on.is_on is True
    assert off.is_on is False


def test_is_on_unknown_without_data_or_port():
    assert ExavizPoEPortSwitch(_coordinator(None), "onboard", 0, "e").is_on is None
    # Data present, but not for this port.
    other_port = _coordinator(_data("onboard", {"port": 1, "enabled": True}))
    assert ExavizPoEPortSwitch(other_port, "onboard", 0, "e").is_on is None


def test_available_only_for_controllable_onboard_ports():
    data = _data("onboard", {"port": 0, "enabled": True})
    assert ExavizPoEPortSwitch(_coordinator(data), "onboard", 0, "e").available is True
    # A read-only remote pairing cannot switch ports.
    assert ExavizPoEPortSwitch(_coordinator(data, can_control=False), "onboard", 0, "e").available is False
    # Add-on board ports have no write interface yet.
    addon = _data("addon_0", {"port": 0, "enabled": True}, "pse0")
    assert ExavizPoEPortSwitch(_coordinator(addon), "addon_0", 0, "e").available is False


def test_attributes_of_an_onboard_port_with_a_device():
    port = {
        "port": 2,
        "enabled": True,
        "status": "power on",
        "power_consumption_watts": 4.5,
        "voltage_volts": 48.1,
        "current_milliamps": 93,
        "poe_system": "onboard",
        "interface": "poe2",
        "link_state": "up",
        "speed_mbps": 1000,
        "power_mocked": True,
        "connected_device": {
            "name": "Camera",
            "device_type": "camera",
            "ip_address": "192.168.1.50",
            "mac_address": "aa:bb:cc:dd:ee:02",
            "manufacturer": "Acme",
            "hostname": "camera-2",
        },
    }
    attrs = ExavizPoEPortSwitch(_coordinator(_data("onboard", port)), "onboard", 2, "e").extra_state_attributes
    assert attrs == {
        "port_number": 2,
        "poe_set": "onboard",
        "status": "power on",
        "power_consumption_watts": 4.5,
        "voltage_volts": 48.1,
        "current_milliamps": 93,
        "poe_system": "onboard",
        "power_note": "Power metrics estimated (TPS23861 driver pending)",
        "power_mocked": True,
        "board_type": "cruiser",
        "interface": "poe2",
        "link_state": "up",
        "speed_mbps": 1000,
        "device_name": "Camera",
        "device_type": "camera",
        "device_ip": "192.168.1.50",
        "device_mac": "aa:bb:cc:dd:ee:02",
        "device_manufacturer": "Acme",
        "device_hostname": "camera-2",
    }


def test_attributes_of_an_addon_port_say_control_is_unavailable():
    coordinator = _coordinator(_data("addon_0", {"port": 1, "poe_system": "addon"}, "pse0"))
    coordinator.board_type = None
    attrs = ExavizPoEPortSwitch(coordinator, "addon_0", 1, "e").extra_state_attributes
    assert attrs["control_available"] is False
    assert "lacks /proc/pse write interface" in attrs["control_note"]
    # Defaults fill the fields the port does not report.
    assert attrs["status"] == "unknown"
    assert "board_type" not in attrs
    assert "interface" not in attrs
    assert "device_name" not in attrs


def test_attributes_absent_without_port_data():
    assert ExavizPoEPortSwitch(_coordinator(None), "onboard", 0, "e").extra_state_attributes is None


def test_button_attributes():
    port = {"port": 0, "status": "power on", "connected_device": {"name": "Cam", "device_type": "camera"}}
    button = ExavizPoEPortResetButton(_coordinator(_data("onboard", port)), "onboard", 0, "e")
    assert button.extra_state_attributes == {
        "port_number": 0,
        "poe_set": "onboard",
        "status": "power on",
        "device_name": "Cam",
        "device_type": "camera",
    }
    assert ExavizPoEPortResetButton(_coordinator(None), "onboard", 0, "e").extra_state_attributes is None


# --- ESP32 port mapping and serial commands -----------------------------------


@pytest.mark.parametrize(
    ("linux_port", "esp32"),
    [(0, (1, 0)), (3, (1, 3)), (4, (0, 0)), (7, (0, 3))],
)
def test_linux_port_maps_to_esp32_pse_and_port(linux_port, esp32):
    assert ExavizPoEPortSwitch._linux_port_to_esp32(linux_port) == esp32


@pytest.mark.asyncio
async def test_esp32_command_is_written_to_the_first_present_device(tmp_path):
    """The command line really lands in the device file (bash echo)."""
    missing = tmp_path / "pse"
    uart = tmp_path / "ttyAMA3"
    uart.write_text("")
    with patch.object(switch_module, "_PSE_DEVICE_PATHS", [missing, uart]):
        assert await ExavizPoEPortSwitch._send_esp32_command("disable-port 1 2") is True
    assert uart.read_text() == "disable-port 1 2\n"
    assert not missing.exists()


@pytest.mark.asyncio
async def test_esp32_command_failure_on_every_device_returns_false(tmp_path, caplog):
    # A directory cannot be written to, so bash exits non-zero.
    device = tmp_path / "pse"
    device.mkdir()
    with patch.object(switch_module, "_PSE_DEVICE_PATHS", [device]), \
         caplog.at_level(logging.WARNING, logger=switch_module.__name__):
        assert await ExavizPoEPortSwitch._send_esp32_command("enable-port 0 1") is False
    assert "ESP32 command 'enable-port 0 1' failed" in caplog.text
    assert "No ESP32 serial device found" in caplog.text


@pytest.mark.asyncio
async def test_esp32_command_tries_the_next_device_when_bash_cannot_start(tmp_path, caplog):
    first = tmp_path / "pse"
    second = tmp_path / "ttyAMA3"
    first.write_text("")
    second.write_text("")
    exec_ = AsyncMock(side_effect=[OSError("no bash"), _proc(0)])
    with patch.object(switch_module, "_PSE_DEVICE_PATHS", [first, second]), \
         patch("asyncio.create_subprocess_exec", exec_), \
         caplog.at_level(logging.WARNING, logger=switch_module.__name__):
        assert await ExavizPoEPortSwitch._send_esp32_command("enable-port 0 1") is True
    assert f"Could not write to {first}: no bash" in caplog.text
    assert exec_.await_args_list[1].args == ("bash", "-c", f"echo 'enable-port 0 1' > {second}")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("exited_meanwhile", "late_returncode"),
    [(False, -9), (True, -9), (True, 0)],
)
async def test_esp32_write_that_never_finishes_is_killed_and_fails(
    tmp_path, caplog, exited_meanwhile, late_returncode
):
    """A blocked serial device cannot hang the action (or a reset cycle), and
    the same command is not written again through the other path while the
    killed write may still be on the UART (/dev/pse links to /dev/ttyAMA3)."""

    first, second = tmp_path / "pse", tmp_path / "ttyAMA3"
    first.write_text("")
    second.write_text("")
    proc = MagicMock()
    proc.returncode = None
    if exited_meanwhile:
        # The write finished between the timeout and the kill.
        proc.kill.side_effect = ProcessLookupError

    async def never_returns():
        await asyncio.Event().wait()

    async def exits():
        proc.returncode = late_returncode

    proc.communicate = never_returns
    proc.wait = exits
    exec_ = AsyncMock(return_value=proc)
    with patch.object(switch_module, "_PSE_DEVICE_PATHS", [first, second]), \
         patch.object(switch_module, "ESP32_WRITE_TIMEOUT", 0.05), \
         patch("asyncio.create_subprocess_exec", exec_), \
         caplog.at_level(logging.INFO, logger=switch_module.__name__):
        result = await asyncio.wait_for(
            ExavizPoEPortSwitch._send_esp32_command("disable-port 1 2"), timeout=2
        )
    # A write that finished just before the kill counts as sent.
    assert result is (late_returncode == 0)
    proc.kill.assert_called_once_with()
    assert exec_.await_count == 1
    timed_out = f"ESP32 command 'disable-port 1 2' timed out on {first}" in caplog.text
    assert timed_out is (late_returncode != 0)
    assert "No ESP32 serial device found" not in caplog.text


@pytest.mark.asyncio
async def test_esp32_write_that_does_not_stop_after_the_kill_raises(tmp_path):
    """The write may still land, so the caller must not send anything after it."""

    device = tmp_path / "pse"
    device.write_text("")
    proc = MagicMock()
    proc.returncode = None

    async def never_returns():
        await asyncio.Event().wait()

    proc.communicate = never_returns
    proc.wait = never_returns
    with patch.object(switch_module, "_PSE_DEVICE_PATHS", [device]), \
         patch.object(switch_module, "ESP32_WRITE_TIMEOUT", 0.05), \
         patch.object(switch_module, "ESP32_KILL_WAIT", 0.05), \
         patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)), \
         pytest.raises(HomeAssistantError, match="did not stop"):
        await asyncio.wait_for(
            ExavizPoEPortSwitch._send_esp32_command("disable-port 1 2"), timeout=2
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("stops", [True, False])
async def test_cancelled_esp32_write_is_killed_before_the_caller_goes_on(tmp_path, stops):
    """A cancelled caller (shutdown) must not leave the write running behind
    it, where it could land after the caller's next command."""

    device = tmp_path / "pse"
    device.write_text("")
    proc = MagicMock()
    proc.returncode = None
    started = asyncio.Event()

    async def blocked():
        started.set()
        await asyncio.Event().wait()

    async def exits():
        proc.returncode = -9

    proc.communicate = blocked
    proc.wait = exits if stops else blocked
    with patch.object(switch_module, "_PSE_DEVICE_PATHS", [device]), \
         patch.object(switch_module, "ESP32_KILL_WAIT", 0.05), \
         patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        task = asyncio.create_task(
            ExavizPoEPortSwitch._send_esp32_command("disable-port 1 2")
        )
        await started.wait()
        task.cancel()
        if stops:
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(HomeAssistantError, match="did not stop"):
                await task
    proc.kill.assert_called_once_with()


@pytest.mark.asyncio
async def test_second_cancel_during_the_kill_wait_counts_as_not_stopped(tmp_path):
    """The write was not confirmed stopped, so the caller gets the error that
    tells it to send nothing after it (not a bare cancel)."""

    device = tmp_path / "pse"
    device.write_text("")
    proc = MagicMock()
    proc.returncode = None
    started, in_wait = asyncio.Event(), asyncio.Event()

    async def blocked():
        started.set()
        await asyncio.Event().wait()

    async def waits():
        in_wait.set()
        await asyncio.Event().wait()

    proc.communicate = blocked
    proc.wait = waits
    with patch.object(switch_module, "_PSE_DEVICE_PATHS", [device]), \
         patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        task = asyncio.create_task(
            ExavizPoEPortSwitch._send_esp32_command("disable-port 1 2")
        )
        await started.wait()
        task.cancel()
        await in_wait.wait()
        task.cancel()
        with pytest.raises(HomeAssistantError, match="did not stop"):
            await task


@pytest.mark.asyncio
async def test_esp32_kill_wait_is_a_couple_of_seconds():
    assert switch_module.ESP32_KILL_WAIT == 2


@pytest.mark.asyncio
async def test_esp32_write_timeout_is_a_few_seconds():
    assert switch_module.ESP32_WRITE_TIMEOUT == 5


@pytest.mark.asyncio
async def test_enable_and_disable_send_the_mapped_esp32_commands():
    switch = ExavizPoEPortSwitch(_coordinator(None), "onboard", 5, "e")
    with patch.object(ExavizPoEPortSwitch, "_send_esp32_command", AsyncMock(return_value=True)) as send:
        assert await switch._esp32_disable_port() is True
        assert await switch._esp32_enable_port() is True
    assert [c.args[0] for c in send.await_args_list] == ["disable-port 0 1", "enable-port 0 1"]


# --- ip link ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_ip_link_runs_ip_link_set():
    exec_ = AsyncMock(return_value=_proc(0))
    with patch("asyncio.create_subprocess_exec", exec_):
        assert await ExavizPoEPortSwitch._run_ip_link("poe3", "down") is True
    assert exec_.await_args.args == tuple(sudo_argv("ip", "link", "set", "poe3", "down"))


@pytest.mark.asyncio
async def test_run_ip_link_failure_logs_stderr(caplog):
    exec_ = AsyncMock(return_value=_proc(2, b"RTNETLINK answers: Operation not permitted\n"))
    with patch("asyncio.create_subprocess_exec", exec_), \
         caplog.at_level(logging.ERROR, logger=switch_module.__name__):
        assert await ExavizPoEPortSwitch._run_ip_link("poe3", "up") is False
    assert "Failed to up port poe3: RTNETLINK answers: Operation not permitted" in caplog.text


def _fast_stop():
    return (
        patch.object(switch_module, "IP_LINK_TIMEOUT", 2),
        patch.object(switch_module, "IP_LINK_STOP_WAIT", 0.5),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ignore_term", "returncode"), [(False, -signal.SIGTERM), (True, -signal.SIGKILL)]
)
async def test_ip_link_that_hangs_as_root_is_stopped_and_fails(
    tmp_path, caplog, ignore_term, returncode
):
    """A hung `ip link` cannot hold a switch action or a reset (and with it
    Home Assistant's stop). Run as root, SIGTERM first, then SIGKILL."""
    hung = HungIpLink(tmp_path, sudo=False, ignore_term=ignore_term)
    timeout, stop_wait = _fast_stop()
    try:
        with hung.patches(), timeout, stop_wait, \
             caplog.at_level(logging.ERROR, logger=switch_module.__name__):
            result = await asyncio.wait_for(
                ExavizPoEPortSwitch._run_ip_link("poe3", "up"), timeout=10
            )
        assert result is False
        assert "ip link to up port poe3 timed out" in caplog.text
        assert [p.returncode for p in hung.procs] == [returncode]
    finally:
        hung.cleanup()


@pytest.mark.asyncio
async def test_ip_link_that_hangs_under_sudo_gets_sigterm_through_sudo(tmp_path, caplog):
    hung = HungIpLink(tmp_path, sudo=True)
    timeout, stop_wait = _fast_stop()
    try:
        with hung.patches(), timeout, stop_wait, \
             caplog.at_level(logging.ERROR, logger=switch_module.__name__):
            result = await asyncio.wait_for(
                ExavizPoEPortSwitch._run_ip_link("poe3", "up"), timeout=10
            )
        assert result is False
        assert "ip link to up port poe3 timed out" in caplog.text
        assert [p.returncode for p in hung.procs] == [-signal.SIGTERM]
        assert hung.ip_alive() == [False]
    finally:
        hung.cleanup()


@pytest.mark.asyncio
async def test_ip_link_that_finishes_as_it_is_stopped_counts_as_done(tmp_path):
    """It ended with status 0 just as the timeout stopped it: the link did
    change, so the caller must not report that it did not."""
    hung = HungIpLink(tmp_path, sudo=True, term="exit0")
    timeout, stop_wait = _fast_stop()
    try:
        with hung.patches(), timeout, stop_wait:
            assert await asyncio.wait_for(
                ExavizPoEPortSwitch._run_ip_link("poe3", "down"), timeout=10
            ) is True
    finally:
        hung.cleanup()


@pytest.mark.asyncio
async def test_ip_link_under_sudo_that_ignores_sigterm_is_reported_not_stopped(
    tmp_path, caplog
):
    """A SIGKILL would end only sudo and leave `ip` (root) free to change the
    link later, unseen. So sudo is not killed, and the caller hears that
    `ip` did not stop, which tells it to run no other `ip link` after it."""
    hung = HungIpLink(tmp_path, sudo=True, ignore_term=True)
    timeout, stop_wait = _fast_stop()
    try:
        with hung.patches(), timeout, stop_wait, \
             caplog.at_level(logging.WARNING, logger=switch_module.__name__):
            with pytest.raises(HomeAssistantError, match="did not stop"):
                await asyncio.wait_for(
                    ExavizPoEPortSwitch._run_ip_link("poe3", "down"), timeout=10
                )
        assert "ip link to down port poe3 (pid" in caplog.text
        assert [p.returncode for p in hung.procs] == [None]  # sudo still waits for it
        assert hung.ip_alive() == [True]
    finally:
        hung.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize("sudo", [False, True])
async def test_ip_link_whose_caller_is_cancelled_is_stopped(tmp_path, sudo):
    """Cancelling a reset (an unload, Home Assistant's stop) does not leave
    `ip link` running behind it, where it could still take the link down
    after the cancel path has brought it back up."""
    hung = HungIpLink(tmp_path, sudo=sudo)
    try:
        with hung.patches():
            run = asyncio.ensure_future(ExavizPoEPortSwitch._run_ip_link("poe3", "down"))
            await asyncio.wait_for(_until(lambda: hung.ip_pids), timeout=10)
            run.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(run, timeout=10)
        assert [p.returncode for p in hung.procs] == [-signal.SIGTERM]
        assert hung.ip_alive() == [False]
    finally:
        hung.cleanup()


@pytest.mark.asyncio
@pytest.mark.parametrize("sudo", [False, True])
async def test_second_cancel_while_ip_link_is_stopped_counts_as_not_stopped(tmp_path, sudo):
    """Shutdown cancels twice: the stop wait is cut short, so `ip` may still
    be running and the caller must not follow it with another `ip link`.
    Run as root, it gets SIGKILL on the way out."""
    hung = HungIpLink(tmp_path, sudo=sudo, ignore_term=True)
    try:
        with hung.patches():
            run = asyncio.ensure_future(ExavizPoEPortSwitch._run_ip_link("poe3", "down"))
            await asyncio.wait_for(_until(lambda: hung.ip_pids), timeout=10)
            run.cancel()
            await asyncio.sleep(0.1)  # now in the stop wait (2 s)
            assert not run.done()
            run.cancel()
            with pytest.raises(HomeAssistantError, match="did not stop"):
                await asyncio.wait_for(run, timeout=10)
        if sudo:
            await asyncio.sleep(0.3)  # a kill would have been seen by now
            assert hung.ip_alive() == [True]
            assert hung.procs[0].returncode is None  # sudo was not killed
        else:
            await asyncio.wait_for(hung.procs[0].wait(), timeout=10)
            assert hung.procs[0].returncode == -signal.SIGKILL
    finally:
        hung.cleanup()


@pytest.mark.asyncio
async def test_cancel_just_as_ip_link_has_started_stops_it_and_cancels(tmp_path):
    """The start finished but the caller had not resumed: the process is
    known, so it is stopped like any cancelled run, and the cancel stands."""
    hung = HungIpLink(tmp_path, sudo=True)
    try:
        with hung.patches():
            run = asyncio.ensure_future(ExavizPoEPortSwitch._run_ip_link("poe3", "down"))
            hung.on_started = run.cancel
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(run, timeout=10)
        assert [p.returncode for p in hung.procs] == [-signal.SIGTERM]
        assert hung.ip_alive() == [False]
    finally:
        hung.cleanup()


async def _until(condition) -> None:
    while not condition():
        await asyncio.sleep(0.01)


# --- add-on board ports (/proc/pse) -------------------------------------------


def _addon_switch(port: int = 2, pse_id: str = "pse1") -> ExavizPoEPortSwitch:
    data = _data("addon_0", {"port": port, "poe_system": "addon"}, pse_id)
    return ExavizPoEPortSwitch(_coordinator(data), "addon_0", port, "e")


@pytest.mark.asyncio
@pytest.mark.parametrize(("turn", "link"), [("async_turn_on", "up"), ("async_turn_off", "down")])
async def test_addon_switch_drives_the_pse_interface(turn, link):
    switch = _addon_switch()
    with patch.object(ExavizPoEPortSwitch, "_run_ip_link", AsyncMock(return_value=True)) as run:
        await getattr(switch, turn)()
    # The hardware pse_id (pse1), not the poe_set key, names the interface.
    run.assert_awaited_once_with("poe1-2", link)
    switch.coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_addon_switch_link_failure_raises():
    switch = _addon_switch()
    with patch.object(ExavizPoEPortSwitch, "_run_ip_link", AsyncMock(return_value=False)), \
         pytest.raises(Exception, match="Failed to disable port via poe1-2"):
        await switch.async_turn_off()
    switch.coordinator.async_request_refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_addon_pse_reset_failed_write_raises(tmp_path):
    switch = _addon_switch(port=3, pse_id="pse0")
    reset = tmp_path / "proc/pse0/port3/reset"
    reset.parent.mkdir(parents=True)
    reset.write_text("")
    with patch.object(switch_module, "Path", side_effect=lambda p: tmp_path / p.lstrip("/")), \
         patch("asyncio.create_subprocess_exec", AsyncMock(return_value=_proc(1))), \
         pytest.raises(Exception, match="Failed to reset port"):
        await switch._control_pse_port("reset")


def test_pse_number_comes_from_the_coordinator_pse_id():
    assert _addon_switch(pse_id="pse1")._get_pse_num() == 1
    # Without a pse_id the poe_set key is used, which works for "pseN" keys.
    data = {"poe": {"pse3": {"ports": [{"port": 0}]}}}
    assert ExavizPoEPortSwitch(_coordinator(data), "pse3", 0, "e")._get_pse_num() == 3


@pytest.mark.xfail(
    strict=True,
    raises=ValueError,
    reason="bug: _get_pse_num falls back to the poe_set key ('addon_0'), "
    "which int() cannot parse when coordinator data is missing",
)
def test_pse_number_without_coordinator_data():
    switch = ExavizPoEPortSwitch(_coordinator(None), "addon_0", 0, "e")
    assert switch._get_pse_num() == 0


# --- which control path a port uses -------------------------------------------


@pytest.mark.parametrize(
    ("poe_set", "data", "onboard"),
    [
        ("onboard", _data("onboard", {"port": 0, "poe_system": "onboard"}), True),
        ("addon_0", _data("addon_0", {"port": 0, "poe_system": "addon"}), False),
        # No port data yet: the poe_set key decides.
        ("onboard", None, True),
        ("addon_0", None, False),
    ],
)
def test_onboard_control_path_detection(poe_set, data, onboard):
    switch = ExavizPoEPortSwitch(_coordinator(data), poe_set, 0, "e")
    assert switch._is_onboard_poe_system() is onboard


@pytest.mark.asyncio
async def test_start_cancelled_with_its_caller_at_loop_shutdown_reports_not_stopped(tmp_path):
    """Loop shutdown cancels every task, the start included. The caller
    still reports that the run was not known to stop (not a bare cancel)."""
    hung = HungIpLink(tmp_path, sudo=True)
    try:
        with hung.patches():
            hung.gate = asyncio.Event()
            run = asyncio.ensure_future(ExavizPoEPortSwitch._run_ip_link("poe3", "down"))
            await asyncio.sleep(0.05)  # the start now waits on the gate
            others = asyncio.all_tasks() - {run, asyncio.current_task()}
            (start,) = [t for t in others if "exec_" in repr(t.get_coro())]
            start.cancel()
            run.cancel()
            with pytest.raises(HomeAssistantError, match="cancelled while it started"):
                await asyncio.wait_for(run, timeout=10)
            # The start may have left `ip` running unseen, so no later
            # `ip link` runs on the port.
            hung.gate.set()
            with pytest.raises(HomeAssistantError, match="has not ended"):
                await ExavizPoEPortSwitch._run_ip_link("poe3", "up")
            assert hung.started == []
    finally:
        hung.cleanup()


def _fake_proc(root: Path, processes: dict[int, list[str]]) -> Path:
    for pid, argv in processes.items():
        (root / str(pid)).mkdir(parents=True)
        (root / str(pid) / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
    (root / "self").mkdir()  # not a process number
    return root


@pytest.mark.asyncio
async def test_ip_link_left_running_by_an_earlier_run_blocks_the_port(tmp_path):
    """Under sudo a stuck `ip link` outlives a Home Assistant restart, and
    the new process has no record of it: /proc still shows it, so no other
    `ip link` runs on that port (others still do)."""
    proc = _fake_proc(tmp_path / "proc", {
        41: ["sudo", "ip", "link", "set", "poe3", "down"],
        42: ["/usr/sbin/ip", "link", "set", "poe3", "down"],
        43: ["ip", "link", "set", "poe4", "down"],  # another port
    })
    hung = HungIpLink(tmp_path, sudo=True, hang=())
    try:
        with hung.patches(), patch.object(switch_module, "_PROC", proc):
            with pytest.raises(HomeAssistantError, match="has not ended"):
                await ExavizPoEPortSwitch._run_ip_link("poe3", "up")
            assert await ExavizPoEPortSwitch._run_ip_link("poe31", "up") is True
        assert [action for action, _ in hung.started] == ["up"]
    finally:
        hung.cleanup()


def test_proc_scan_ignores_sudo_and_other_commands(tmp_path):
    proc = _fake_proc(tmp_path / "proc", {
        41: ["sudo", "ip", "link", "set", "poe3", "down"],  # sudo's own entry
        44: ["ip", "neigh", "show", "dev", "poe3"],
        45: ["vip", "link", "set", "poe3", "down"],
        46: ["ip", "link", "set", "poe31", "down"],  # another port
    })
    with patch.object(switch_module, "_PROC", proc):
        assert not switch_module._ip_link_in_proc("poe3")
    with patch.object(switch_module, "_PROC", tmp_path / "missing"):
        assert not switch_module._ip_link_in_proc("poe3")


class _RefusingSudo:
    """A just-started sudo: it refuses the first `refusals` signals; its
    `ip` ends on the first SIGTERM that gets through (never, by default)."""

    pid = 4242
    returncode = None

    def __init__(self, refusals: int = 10**6) -> None:
        self.signals, self.refusals = 0, refusals
        self.ended = asyncio.Event()

    def terminate(self) -> None:
        self.signals += 1
        if self.signals <= self.refusals:
            raise PermissionError("Operation not permitted")
        self.returncode = -signal.SIGTERM
        self.ended.set()

    def kill(self) -> None:
        raise AssertionError("sudo must not get SIGKILL")

    async def communicate(self):
        await asyncio.Event().wait()

    async def wait(self):
        await self.ended.wait()


@pytest.mark.asyncio
async def test_a_refused_stop_signal_is_sent_again_until_sudo_takes_it():
    sudo = _RefusingSudo(refusals=3)
    with patch.object(switch_module, "IP_LINK_STOP_WAIT", 1):
        assert await switch_module._stop_ip_link(sudo, under_sudo=True) is True
    assert sudo.signals == 4


@pytest.mark.asyncio
async def test_sudo_refusing_the_stop_signal_counts_as_not_stopped():
    """Real sudo refuses signals for a few ms after it starts. That must not
    escape as a PermissionError with the run unrecorded: it is waited for,
    then reported as not stopped, and the port stays blocked."""
    sudo = _RefusingSudo()
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=sudo)), \
         patch.object(switch_module, "sudo_argv", lambda *a: ("sudo", *a)), \
         patch.object(switch_module, "IP_LINK_TIMEOUT", 0.2), \
         patch.object(switch_module, "IP_LINK_STOP_WAIT", 0.2), \
         patch.object(switch_module, "_PROC", Path("/nonexistent")), \
         patch.dict(switch_module._stuck_ip_link, clear=True):
        started = asyncio.get_running_loop().time()
        with pytest.raises(HomeAssistantError, match="did not stop"):
            # Bounded, so a resend loop with no end fails instead of hanging.
            await asyncio.wait_for(
                ExavizPoEPortSwitch._run_ip_link("poe3", "down"), timeout=10
            )
        # Timeout 0.2 s, resends for 0.2 s, then the 0.2 s wait.
        assert asyncio.get_running_loop().time() - started < 2
        assert sudo.signals >= 4  # sent again, every 50 ms, for the stop wait
        with pytest.raises(HomeAssistantError, match="has not ended"):
            await ExavizPoEPortSwitch._run_ip_link("poe3", "up")


@pytest.mark.asyncio
async def test_a_start_that_failed_after_its_cancel_does_not_block_the_port():
    """Cancelled while starting, and the start then failed (no sudo, say):
    nothing is running, so the next `ip link` on the port runs."""
    gate = asyncio.Event()
    starts: list[tuple] = []

    async def exec_(*argv, **kwargs):
        starts.append(argv)
        if len(starts) == 1:
            await gate.wait()
            raise FileNotFoundError("sudo")
        return _proc(0)

    with patch("asyncio.create_subprocess_exec", exec_), \
         patch.object(switch_module, "_PROC", Path("/nonexistent")), \
         patch.dict(switch_module._stuck_ip_link, clear=True):
        run = asyncio.ensure_future(ExavizPoEPortSwitch._run_ip_link("poe3", "down"))
        await asyncio.wait_for(_until(lambda: starts), timeout=10)
        run.cancel()
        with pytest.raises(HomeAssistantError, match="cancelled while it started"):
            await run
        gate.set()
        await asyncio.sleep(0.05)
        assert await ExavizPoEPortSwitch._run_ip_link("poe3", "up") is True
    assert len(starts) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("under_sudo", [True, False])
async def test_a_late_start_that_refuses_sigterm_gets_it_again(under_sudo):
    """Started after its caller was cancelled, a just-started sudo may
    refuse the SIGTERM; it is sent once more shortly after. SIGKILL after
    the stop wait only without sudo."""
    proc = MagicMock(returncode=None)
    proc.terminate.side_effect = [PermissionError("Operation not permitted"), None]
    spawn = asyncio.get_running_loop().create_future()
    spawn.set_result(proc)
    with patch.object(switch_module, "IP_LINK_STOP_WAIT", 0.2):
        switch_module._stop_when_started(under_sudo, spawn)
        assert proc.terminate.call_count == 1
        await asyncio.sleep(0.5)  # past the retry and the stop wait
    assert proc.terminate.call_count == 2
    assert proc.kill.called is not under_sudo


@pytest.mark.asyncio
@pytest.mark.parametrize("under_sudo", [True, False])
async def test_second_cancel_while_a_refused_signal_is_resent_counts_as_not_stopped(
    under_sudo,
):
    """Shutdown's second cancel can land while a refused SIGTERM waits to be
    sent again. It ends the stop as "not stopped", so the caller records the
    run, and SIGKILL follows only without sudo."""
    sudo = _RefusingSudo()
    killed: list[bool] = []
    sudo.kill = lambda: killed.append(True)
    with patch.object(switch_module, "IP_LINK_STOP_WAIT", 5):
        stop = asyncio.ensure_future(switch_module._stop_ip_link(sudo, under_sudo))
        await asyncio.sleep(0.12)  # a few refused sends in
        stop.cancel()
        cancelled = asyncio.get_running_loop().time()
        assert await asyncio.wait_for(stop, timeout=10) is False
        assert asyncio.get_running_loop().time() - cancelled < 1  # not the 5 s wait
    assert sudo.signals >= 2
    assert killed == ([] if under_sudo else [True])


@pytest.mark.asyncio
async def test_run_cancelled_twice_while_its_stop_signal_is_refused_is_recorded():
    """The run is cancelled, its SIGTERM is refused, and a second cancel
    lands during a resend: the run is recorded and the port stays blocked."""
    sudo = _RefusingSudo()
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=sudo)), \
         patch.object(switch_module, "sudo_argv", lambda *a: ("sudo", *a)), \
         patch.object(switch_module, "IP_LINK_STOP_WAIT", 5), \
         patch.object(switch_module, "_PROC", Path("/nonexistent")), \
         patch.dict(switch_module._stuck_ip_link, clear=True):
        run = asyncio.ensure_future(ExavizPoEPortSwitch._run_ip_link("poe3", "down"))
        await asyncio.sleep(0.05)
        run.cancel()
        await asyncio.wait_for(_until(lambda: sudo.signals >= 2), timeout=10)
        run.cancel()
        with pytest.raises(HomeAssistantError, match="did not stop"):
            await asyncio.wait_for(run, timeout=10)
        with pytest.raises(HomeAssistantError, match="has not ended"):
            await ExavizPoEPortSwitch._run_ip_link("poe3", "up")
