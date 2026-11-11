"""PoE port switch and reset button: state, attributes and command paths.

Failed onboard commands are covered in test_port_command_failures.py; this
file covers what the switch reports and the commands it actually runs: the
ESP32 line written to the serial device, `ip link set` argv, and the
add-on board /proc/pse paths.
"""
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.exaviz import switch as switch_module
from custom_components.exaviz.board_detector import BoardType
from custom_components.exaviz.button import ExavizPoEPortResetButton
from custom_components.exaviz.switch import ExavizPoEPortSwitch
from custom_components.exaviz.utils import sudo_argv


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
    ("exited_meanwhile", "stops_after_kill"),
    [(False, True), (True, True), (False, False)],
)
async def test_esp32_write_that_never_finishes_is_killed_and_fails(
    tmp_path, caplog, exited_meanwhile, stops_after_kill
):
    """A blocked serial device cannot hang the action (or a reset cycle), and
    the same command is not written again through the other path while the
    killed write may still be on the UART (/dev/pse links to /dev/ttyAMA3)."""
    import asyncio

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

    proc.communicate = never_returns
    proc.wait = AsyncMock() if stops_after_kill else never_returns
    exec_ = AsyncMock(return_value=proc)
    with patch.object(switch_module, "_PSE_DEVICE_PATHS", [first, second]), \
         patch.object(switch_module, "ESP32_WRITE_TIMEOUT", 0.05), \
         patch.object(switch_module, "ESP32_KILL_WAIT", 0.05), \
         patch("asyncio.create_subprocess_exec", exec_), \
         caplog.at_level(logging.WARNING, logger=switch_module.__name__):
        result = await asyncio.wait_for(
            ExavizPoEPortSwitch._send_esp32_command("disable-port 1 2"), timeout=2
        )
    assert result is False
    proc.kill.assert_called_once_with()
    assert exec_.await_count == 1
    assert f"ESP32 command 'disable-port 1 2' timed out on {first}" in caplog.text
    assert ("did not stop" in caplog.text) is not stops_after_kill
    assert "No ESP32 serial device found" not in caplog.text


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
