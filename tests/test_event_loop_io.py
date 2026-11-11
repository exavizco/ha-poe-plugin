"""No filesystem stat or read on the event loop in the local paths.

The same guard as tests/test_board_detector.py::TestFilesystemOffTheEventLoop,
applied to the coordinator's local poll, its one-time system-info gathering
and the switch's ESP32 command. Every absolute path the code builds is
re-rooted under tmp_path (a fake board), so the code walks its "present"
branches and reads real files; subprocesses are faked.
"""
from __future__ import annotations

import asyncio
import pathlib
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from custom_components.exaviz import coordinator as coordinator_module
from custom_components.exaviz import poe_readers
from custom_components.exaviz import switch as switch_module
from custom_components.exaviz.board_detector import BoardType
from custom_components.exaviz.const import ARP_SCAN_OUI_FILE, CONF_SWITCH_MODE_DISCOVERY
from custom_components.exaviz.coordinator import ExavizDataUpdateCoordinator
from custom_components.exaviz.switch import ExavizPoEPortSwitch

from .test_poe_readers_parsing import (
    ESP32_PORT_0_0,
    IP_ADDR_BR0,
    PROC_PSE,
    FakeExec,
    _make_iface,
    _nmea,
    _write,
)

pytestmark = pytest.mark.asyncio

GUARDED = ("exists", "is_dir", "is_file", "read_text", "read_bytes", "resolve", "iterdir")


@contextmanager
def loop_io_recorder():
    """Record every guarded Path call made from the event loop thread."""
    on_loop: list[str] = []

    def guard(name):
        original = getattr(pathlib.Path, name)

        def wrapper(self, *args, **kwargs):
            try:
                asyncio.get_running_loop()
                on_loop.append(f"{name}({self})")
            except RuntimeError:
                pass  # a worker thread: fine
            return original(self, *args, **kwargs)

        return patch.object(pathlib.Path, name, wrapper)

    with ExitStack() as stack:
        for name in GUARDED:
            stack.enter_context(guard(name))
        yield on_loop


@pytest.fixture(autouse=True)
def _clean_reader_state():
    poe_readers._arp_scan_cache.clear()
    poe_readers._arp_scan_locks.clear()
    poe_readers._unavailable.clear()
    yield
    poe_readers._arp_scan_cache.clear()
    poe_readers._arp_scan_locks.clear()
    poe_readers._unavailable.clear()


@pytest.fixture
def board_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake Cruiser with an add-on board: every host path exists."""
    reroot = lambda p: tmp_path / str(p).lstrip("/")  # noqa: E731
    monkeypatch.setattr(coordinator_module, "Path", reroot)
    monkeypatch.setattr(poe_readers, "Path", reroot)
    monkeypatch.setattr(
        switch_module, "_PSE_DEVICE_PATHS", [reroot("/dev/pse"), reroot("/dev/ttyAMA3")]
    )
    _write(tmp_path, "proc/pse", PROC_PSE)
    _write(tmp_path, "dev/pse", "")
    _write(tmp_path, "dev/ttyAMA3", "")
    _write(tmp_path, "proc/device-tree/compatible", "raspberrypi,5-compute-module\x00")
    _write(tmp_path, "proc/device-tree/chosen/board", "cruiser-raspberrypi-cm5\x00")
    _write(tmp_path, "proc/meminfo", "MemTotal:        8245312 kB\n")
    _write(tmp_path, "etc/os-release", 'PRETTY_NAME="Debian GNU/Linux 12"\n')
    _write(tmp_path, "sys/class/thermal/thermal_zone0/temp", "55123\n")
    _write(tmp_path, "sys/block/mmcblk0/size", "61071360\n")
    (tmp_path / "sys/block/mmcblk0boot0").mkdir(parents=True)
    _write(tmp_path, ARP_SCAN_OUI_FILE.lstrip("/"), "")
    _make_iface(tmp_path, "wlan0")
    _make_iface(tmp_path, "br0", address="2c:cf:67:aa:bb:02")
    for n in range(2):
        poe = _make_iface(tmp_path, f"poe{n}", address=f"2c:cf:67:aa:bb:1{n}")
        (poe / "master").symlink_to(tmp_path / "sys/class/net/br0")
    return tmp_path


def _fake_exec() -> FakeExec:
    return FakeExec({
        ("stty",): (b"", 0),
        ("timeout",): ((_nmea(ESP32_PORT_0_0) + "\n").encode(), 0),
        ("bash",): (b"", 0),
        ("ip", "neigh"): (b"", 0),
        ("ip", "-4"): (IP_ADDR_BR0, 0),
        ("bridge",): (b"3e:ac:94:54:25:fa master br0\n", 0),
        ("/usr/sbin/arp-scan",): (b"192.168.86.61\t3e:ac:94:54:25:fa\tUbiquiti Inc\n", 0),
        ("sudo",): (b"", 1),
        ("uname",): (b"6.12.0\n", 0),
        ("dpkg-query",): (b"", 0),
    })


@pytest.fixture
def local_coordinator(mock_hass, mock_config_entry):
    mock_config_entry.options = {CONF_SWITCH_MODE_DISCOVERY: True}
    coordinator = ExavizDataUpdateCoordinator(mock_hass, mock_config_entry)
    coordinator.board_type = BoardType.CRUISER
    coordinator.addon_boards = ["pse0"]
    coordinator.onboard_ports = ["poe0", "poe1"]
    coordinator.total_poe_ports = 10
    return coordinator


async def test_local_poll_touches_the_filesystem_off_the_loop(board_root, local_coordinator):
    fake = _fake_exec()
    with patch("custom_components.exaviz.utils.os.geteuid", return_value=0), \
         patch("asyncio.create_subprocess_exec", fake), \
         patch.object(poe_readers, "_detect_bosch_camera", return_value=None), \
         loop_io_recorder() as on_loop:
        data = await local_coordinator._async_update_data()

    # The fake board was read for real (the guard is not vacuous).
    assert data["board_temperature_celsius"] == 55.1
    assert data["poe"]["addon_0"]["ports"][0]["status"] == "power-on"
    onboard = {p["interface"]: p for p in data["poe"]["onboard"]["ports"]}
    assert onboard["poe0"]["link_state"] == "up"
    assert onboard["poe0"]["connected_device"]["mac_address"] == "3e:ac:94:54:25:fa"
    assert fake.ran("/usr/sbin/arp-scan")[0][-1] == f"--ouifile={ARP_SCAN_OUI_FILE}"
    assert on_loop == []


async def test_system_info_touches_the_filesystem_off_the_loop(board_root, local_coordinator):
    fake = FakeExec({
        ("stty",): (b"", 0),
        ("bash",): (b"Exaviz PoE monitor version 1.1.2\n", 0),
        ("head",): (b"", 0),
        ("uname",): (b"6.12.0\n", 0),
        ("dpkg-query",): (b"", 0),
    })
    with patch("asyncio.create_subprocess_exec", fake), loop_io_recorder() as on_loop:
        info = await local_coordinator._gather_system_info()

    assert info["compute_module"] == "Raspberry Pi CM5"
    assert info["cm_model"] == "CM5108032"
    assert info["os_version"] == "Debian GNU/Linux 12"
    assert info["esp32_firmware_version"] == "1.1.2"
    assert info["board_identifier"] == "cruiser-raspberrypi-cm5"
    assert on_loop == []


async def test_proc_pse_header_touches_the_filesystem_off_the_loop(
    board_root, local_coordinator
):
    with loop_io_recorder() as on_loop:
        info = await local_coordinator._query_proc_pse_header()
    assert info["poe_driver_version"] == "2.0"
    assert on_loop == []


async def test_esp32_command_touches_the_filesystem_off_the_loop(board_root):
    fake = _fake_exec()
    with patch("asyncio.create_subprocess_exec", fake), loop_io_recorder() as on_loop:
        assert await ExavizPoEPortSwitch._send_esp32_command("enable-port 0 1") is True
    assert fake.ran("bash") == [
        ("bash", "-c", f"echo 'enable-port 0 1' > {board_root / 'dev/pse'}")
    ]
    assert on_loop == []


async def test_single_port_esp32_stream_touches_the_filesystem_off_the_loop(board_root):
    with patch("asyncio.create_subprocess_exec", _fake_exec()), \
         loop_io_recorder() as on_loop:
        data = await poe_readers._try_read_cruiser_pse_data(4)
    assert data["state"] == "power-on"
    assert on_loop == []
