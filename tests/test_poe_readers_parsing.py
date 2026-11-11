"""Parsing and error-path tests for custom_components.exaviz.poe_readers.

The readers touch fixed host paths (/proc/pse, /dev/pse, /dev/ttyAMA3,
/sys/class/net). These tests root those paths in tmp_path by patching the
module's ``Path`` name, then write files in the real kernel and firmware
formats:

- /proc/pse lines follow the ip808ar.c printf: state, class, requested power,
  voltage, current/limit, temp/limit, at|af mode, last event.
- ESP32 lines follow the poe-fw golden telemetry corpus (port.golden.txt,
  summary.golden.txt), including the NMEA-style ``*XX`` checksum suffix that
  current firmware appends to every line.

External commands (stty, cat, ip, bridge, arp-scan, tcpdump) are replaced at
``asyncio.create_subprocess_exec`` by a router that records each argv.

Copyright (c) 2026 Axzez LLC.
Licensed under the MIT License. See LICENSE for details.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from functools import reduce
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.exaviz import poe_readers
from custom_components.exaviz.poe_readers import (
    _bridge_has_ipv4,
    _collect_local_macs,
    _detect_bosch_camera,
    _get_bridge_master,
    _get_connected_device_from_arp,
    _parse_bridge_fdb,
    _parse_esp32_line,
    _parse_field,
    _read_all_esp32_data,
    _read_bridge_fdb,
    _read_link_state,
    _read_traffic_stats,
    _resolve_bridged_device,
    _run_arp_scan,
    _try_bosch_detection,
    read_all_addon_ports,
    read_all_onboard_ports,
    read_network_port_status,
    read_pse_port_status,
)


# ---------------------------------------------------------------------------
# Captured-format fixtures
# ---------------------------------------------------------------------------

# /proc/pse as printed by the ip808ar kernel module (two add-on boards).
PROC_PSE = """\
Exaviz Interceptor PoE driver version 2.0
0-0: power-on 0 15.50 48.2500 0.09700/0.80000 33.1250/150.0000 af
0-1: backoff ? 0.00 48.2500 0.00000/0.80000 34.6250/150.0000 af dc-disconnect
0-4: power-on 4 30.00 48.2500 0.52000/0.80000 41.5000/150.0000 at
0: 48.2500/40.0000-60.0000 0.61700/2.50000 45.50/120
1-2: detecting ? 0.00 48.1875 0.00000/0.80000 30.0000/150.0000 af
1: 48.1875/40.0000-60.0000 0.00000/2.50000 0.00/120
"""


def _nmea(body: str) -> str:
    """Append the poe-fw line checksum: ``*`` plus XOR of the body bytes."""
    return f"{body}*{reduce(lambda a, b: a ^ b, body.encode(), 0):02X}"


# poe-fw golden bodies (tests/fixtures/telemetry/port.golden.txt).
ESP32_PORT_0_0 = "0-0: power-on 3 15.0 48.126 0.143/0.374 50.0 at "
ESP32_PORT_0_1 = "0-1: backoff ? 0.0 0.000 0.000/0.000 50.0 at "
ESP32_PORT_1_1 = "1-1: backoff ? 0.0 0.000 0.000/0.000 47.9 at short-circuit"
ESP32_PORT_1_3 = "1-3: power-on 0 15.0 48.433 0.047/0.374 47.9 af "


def _esp32_stream() -> bytes:
    """Three seconds of /dev/pse: a torn first line, then two full cycles.

    The second cycle changes PSE 0 port 0 current from 0.143 A to 0.150 A, so
    a reader that keeps the newest sample reports 7.22 W, not 6.88 W.
    """
    cycle1 = [ESP32_PORT_0_0, ESP32_PORT_0_1, ESP32_PORT_1_1, ESP32_PORT_1_3,
              "0: 48.126 0.143", "1: 48.389 0.110"]
    cycle2 = [ESP32_PORT_0_0.replace("0.143/", "0.150/"), ESP32_PORT_0_1,
              ESP32_PORT_1_1, ESP32_PORT_1_3, "0: 48.126 0.150", "1: 48.389 0.110"]
    # `cat` on a live UART starts wherever the ESP32 happens to be mid-line.
    lines = ["374 50.0 at *5D"] + [_nmea(b) for b in cycle1 + cycle2]
    return ("\n".join(lines) + "\n").encode()


# `ip -4 -o addr show dev br0 scope global` on a bridge with a DHCP lease.
IP_ADDR_BR0 = (
    b"7: br0    inet 192.168.86.40/24 brd 192.168.86.255 scope global dynamic br0\\"
    b"       valid_lft 86213sec preferred_lft 86213sec\n"
)


# ---------------------------------------------------------------------------
# Harness: rooted filesystem and a recording subprocess router
# ---------------------------------------------------------------------------

@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Re-root every absolute Path the module builds under tmp_path."""
    monkeypatch.setattr(
        poe_readers, "Path", lambda p: tmp_path / str(p).lstrip("/")
    )
    return tmp_path


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _make_iface(
    root: Path,
    name: str,
    *,
    operstate: str = "up",
    flags: str = "0x1003",
    speed: str | None = "1000",
    rx: str = "123456",
    tx: str = "654321",
    address: str = "2c:cf:67:00:00:01",
) -> Path:
    """Create /sys/class/net/<name> as the kernel exposes it."""
    base = root / "sys/class/net" / name
    _write(root, f"sys/class/net/{name}/operstate", operstate + "\n")
    _write(root, f"sys/class/net/{name}/flags", flags + "\n")
    _write(root, f"sys/class/net/{name}/address", address + "\n")
    if speed is not None:
        _write(root, f"sys/class/net/{name}/speed", speed + "\n")
    _write(root, f"sys/class/net/{name}/statistics/rx_bytes", rx + "\n")
    _write(root, f"sys/class/net/{name}/statistics/tx_bytes", tx + "\n")
    return base


class FakeExec:
    """Stand-in for asyncio.create_subprocess_exec.

    ``routes`` maps an argv prefix to (stdout, returncode) or to an exception
    to raise at spawn time. The longest matching prefix wins. Any command with
    no route raises FileNotFoundError, as a missing binary would.
    """

    def __init__(self, routes: dict[tuple[str, ...], Any]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, ...]] = []

    async def __call__(self, *argv: str, **_kwargs: Any) -> MagicMock:
        self.calls.append(tuple(argv))
        for prefix in sorted(self.routes, key=len, reverse=True):
            if tuple(argv[: len(prefix)]) == prefix:
                result = self.routes[prefix]
                if isinstance(result, BaseException):
                    raise result
                stdout, returncode = result
                proc = MagicMock()
                proc.returncode = returncode
                proc.communicate = AsyncMock(return_value=(stdout, b""))
                return proc
        raise FileNotFoundError(argv[0])

    def ran(self, *prefix: str) -> list[tuple[str, ...]]:
        return [c for c in self.calls if c[: len(prefix)] == prefix]


@pytest.fixture
def no_dns():
    """Keep enrich_device_info off the network; return a fixed PTR name."""
    with patch(
        "custom_components.exaviz.device_identifier.get_hostname_from_ip",
        AsyncMock(return_value="cam.lan"),
    ) as mock:
        yield mock


@pytest.fixture(autouse=True)
def _clean_arp_cache():
    poe_readers._arp_scan_cache.clear()
    poe_readers._arp_scan_locks.clear()
    yield
    poe_readers._arp_scan_cache.clear()
    poe_readers._arp_scan_locks.clear()


# ---------------------------------------------------------------------------
# /proc/pse (Interceptor add-on, IP808AR)
# ---------------------------------------------------------------------------

class TestProcPse:
    @pytest.mark.asyncio
    async def test_power_is_volts_times_amps_not_budget(self, root):
        # The third field (15.50) is the class budget; real draw is V x I.
        _write(root, "proc/pse", PROC_PSE)
        result = await read_pse_port_status("pse0", 0)

        assert result == {
            "available": True,
            "poe_system": "addon",
            "state": "power-on",
            "class": "0",
            "power_watts": 4.68,  # 48.25 V x 0.097 A
            "allocated_power_watts": 15.4,
            "voltage_volts": 48.25,
            "current_milliamps": 97,
            "temperature_celsius": 33.1,
            "enabled": True,
        }

    @pytest.mark.asyncio
    async def test_class4_port_and_trailing_event_tokens(self, root):
        _write(root, "proc/pse", PROC_PSE)
        result = await read_pse_port_status("pse0", 4)

        assert result["class"] == "4"
        assert result["allocated_power_watts"] == 30.0
        assert result["power_watts"] == 25.09  # 48.25 x 0.52
        assert result["temperature_celsius"] == 41.5

    @pytest.mark.asyncio
    async def test_second_board_selected_by_pse_number(self, root):
        # pse1 reads "1-2:", never the "0-2" or the "1:" summary line.
        _write(root, "proc/pse", PROC_PSE)
        result = await read_pse_port_status("pse1", 2)

        assert result["state"] == "detecting"
        assert result["voltage_volts"] == 48.19
        assert result["power_watts"] == 0.0
        assert result["enabled"] is True

    @pytest.mark.asyncio
    async def test_port_missing_from_proc_pse(self, root, caplog):
        _write(root, "proc/pse", PROC_PSE)
        with caplog.at_level(logging.WARNING):
            result = await read_pse_port_status("pse0", 7)

        assert result["available"] is False
        assert result["state"] == "unavailable"
        assert "Port 0-7 not found in /proc/pse" in caplog.text

    @pytest.mark.asyncio
    async def test_proc_pse_read_timeout(self, root, caplog):
        # A wedged driver can block `head` on the streaming file.
        _write(root, "proc/pse", PROC_PSE)
        with patch.object(
            poe_readers.subprocess, "run",
            side_effect=subprocess.TimeoutExpired(["head"], 5),
        ), caplog.at_level(logging.ERROR):
            result = await read_pse_port_status("pse0", 0)

        assert result["available"] is False
        assert result["state"] == "error"
        assert "timed out" in result["error"]
        assert "Failed to read /proc/pse" in caplog.text

    @pytest.mark.asyncio
    async def test_reads_with_bounded_head(self, root):
        # The file streams forever; it must be read through `head -30`.
        _write(root, "proc/pse", PROC_PSE)
        real_run = subprocess.run
        with patch.object(poe_readers.subprocess, "run", side_effect=real_run) as run:
            await read_pse_port_status("pse0", 0)
        argv = run.call_args[0][0]
        assert argv[:2] == ["head", "-30"]
        assert argv[2].endswith("/proc/pse")
        assert run.call_args.kwargs["timeout"] == 5


class TestReadAllAddonPorts:
    @pytest.mark.asyncio
    async def test_arp_device_attached_on_second_board_interface(self, root, no_dns):
        # pse1 port 2 is the Interceptor netdev poe10 (pse_num * 8 + port).
        _write(root, "proc/pse", PROC_PSE)
        fake = FakeExec({
            ("ip", "neigh", "show", "dev", "poe10"):
                (b"192.168.86.77 lladdr b8:27:eb:11:22:33 REACHABLE\n", 0),
            ("ip", "neigh", "show"): (b"", 0),
        })
        with patch("asyncio.create_subprocess_exec", fake):
            ports = await read_all_addon_ports("pse1", port_count=3)

        # Ports 0 and 1 are absent on pse1, so ARP is only asked about poe10.
        assert ports[0]["available"] is False
        assert "connected_device" not in ports[0]
        assert fake.ran("ip", "neigh") == [("ip", "neigh", "show", "dev", "poe10")]
        device = ports[2]["connected_device"]
        assert device["ip_address"] == "192.168.86.77"
        assert device["manufacturer"] == "Raspberry Pi Foundation"
        assert device["hostname"] == "cam.lan"


# ---------------------------------------------------------------------------
# ESP32 telemetry (Cruiser onboard, /dev/pse)
# ---------------------------------------------------------------------------

class TestParseEsp32Line:
    def test_golden_power_on_line_with_checksum(self):
        parsed = _parse_esp32_line(_nmea(ESP32_PORT_0_0))

        assert parsed["pse_num"] == 0 and parsed["port_num"] == 0
        assert parsed["state"] == "power-on"
        assert parsed["class"] == "3"
        assert parsed["power_watts"] == 6.88  # 48.126 x 0.143, not the 15.0 budget
        assert parsed["allocated_power_watts"] == 15.4
        assert parsed["voltage_volts"] == 48.13
        assert parsed["current_milliamps"] == 143
        assert parsed["temperature_celsius"] == 50.0
        assert parsed["poe_system"] == "onboard"
        assert parsed["enabled"] is True

    def test_last_error_token_kept(self):
        parsed = _parse_esp32_line(_nmea(ESP32_PORT_1_1))

        assert (parsed["pse_num"], parsed["port_num"]) == (1, 1)
        assert parsed["state"] == "backoff"
        assert parsed["class"] == "?"
        assert parsed["power_watts"] == 0.0
        assert "short-circuit" in parsed["error"]

    def test_unchecksummed_legacy_line(self):
        # N-3 backward-compat corpus: older firmware sent no *XX suffix.
        parsed = _parse_esp32_line(ESP32_PORT_1_3)
        assert parsed["class"] == "0"
        assert parsed["power_watts"] == 2.28  # 48.433 x 0.047

    def test_disabled_port_not_enabled(self):
        parsed = _parse_esp32_line("1-0: disabled ? 0.0 0.000 0.000/0.000 31.2 af ")
        assert parsed["enabled"] is False

    @pytest.mark.parametrize("line", [
        "0: 48.126 0.143*35",  # per-PSE summary line
        "374 50.0 at *5D",  # torn line at the start of a read
        "",
    ])
    def test_non_port_lines_ignored(self, line):
        assert _parse_esp32_line(line) is None

    def test_corrupt_number_rejected(self, caplog):
        # UART noise inside a numeric field must drop the line, not raise.
        with caplog.at_level(logging.DEBUG):
            assert _parse_esp32_line("0-0: power-on 3 15.0 48.1#6 0.143/0.374 50.0 at ") is None
        assert "Failed to parse ESP32 line" in caplog.text


class TestEsp32SerialStream:
    """read_network_port_status(esp32_data_map=None) reads the UART itself."""

    @pytest.mark.asyncio
    async def test_reads_dev_pse_and_keeps_newest_sample(self, root):
        _write(root, "dev/pse", "")
        _make_iface(root, "poe4")
        fake = FakeExec({
            ("stty",): (b"", 0),
            ("timeout", "3", "cat"): (_esp32_stream(), 0),
            ("ip", "neigh"): (b"", 0),
        })
        with patch("asyncio.create_subprocess_exec", fake):
            result = await read_network_port_status("poe4")

        # Linux poe4 is the right-hand PSE 0, local port 0.
        assert result["power_watts"] == 7.22  # second cycle: 48.126 x 0.150
        assert result["current_milliamps"] == 150
        assert result["class"] == "3"
        assert "power_mocked" not in result
        dev = str(root / "dev/pse")
        assert fake.ran("stty") == [("stty", "-F", dev, "115200", "raw", "-echo")]
        assert fake.ran("timeout") == [("timeout", "3", "cat", dev)]

    @pytest.mark.asyncio
    async def test_left_ports_map_to_pse1(self, root):
        # Linux poe3 is the left-hand PSE 1, local port 3 (golden "1-3:").
        _write(root, "dev/pse", "")
        _make_iface(root, "poe3", speed="100")
        fake = FakeExec({
            ("stty",): (b"", 0),
            ("timeout", "3", "cat"): (_esp32_stream(), 0),
            ("ip", "neigh"): (b"", 0),
        })
        with patch("asyncio.create_subprocess_exec", fake):
            result = await read_network_port_status("poe3")

        assert result["power_watts"] == 2.28
        assert result["class"] == "0"

    @pytest.mark.asyncio
    async def test_falls_back_to_ttyama3_when_dev_pse_missing(self, root):
        _write(root, "dev/ttyAMA3", "")
        _make_iface(root, "poe5")
        fake = FakeExec({
            ("stty",): (b"", 0),
            ("timeout", "3", "cat"): (_esp32_stream(), 0),
            ("ip", "neigh"): (b"", 0),
        })
        with patch("asyncio.create_subprocess_exec", fake):
            result = await read_network_port_status("poe5")

        assert fake.ran("timeout") == [("timeout", "3", "cat", str(root / "dev/ttyAMA3"))]
        assert result["state"] == "backoff"  # golden "0-1:"
        assert "power_mocked" not in result

    @pytest.mark.asyncio
    async def test_tries_ttyama3_after_dev_pse_fails(self, root):
        # /dev/pse spawns fail (e.g. stty missing for it) and /dev/ttyAMA3 is silent.
        _write(root, "dev/pse", "")
        _write(root, "dev/ttyAMA3", "")
        _make_iface(root, "poe4", operstate="down", speed=None)
        pse = str(root / "dev/pse")
        fake = FakeExec({
            ("stty", "-F", pse): OSError("Device or resource busy"),
            ("stty",): (b"", 0),
            ("timeout", "3", "cat"): (b"0: 48.126 0.143*35\n", 0),
            ("ip", "neigh"): (b"", 0),
        })
        with patch("asyncio.create_subprocess_exec", fake):
            result = await read_network_port_status("poe4")

        assert fake.ran("timeout") == [("timeout", "3", "cat", str(root / "dev/ttyAMA3"))]
        # No sample for the port: mocked fallback, link down.
        assert result["power_mocked"] is True
        assert result["state"] == "searching"

    @pytest.mark.asyncio
    async def test_no_serial_device_spawns_nothing(self, root):
        _make_iface(root, "poe0", operstate="down", speed=None)
        fake = FakeExec({("ip", "neigh"): (b"", 0)})
        with patch("asyncio.create_subprocess_exec", fake):
            result = await read_network_port_status("poe0")

        assert fake.ran("stty") == [] and fake.ran("timeout") == []
        assert result["power_mocked"] is True


class TestReadAllEsp32Data:
    @pytest.mark.asyncio
    async def test_one_pass_keeps_newest_per_port(self, root):
        _write(root, "dev/pse", "")
        fake = FakeExec({
            ("stty",): (b"", 0),
            ("timeout", "3", "cat"): (_esp32_stream(), 0),
        })
        with patch("asyncio.create_subprocess_exec", fake):
            data = await _read_all_esp32_data()

        assert set(data) == {(0, 0), (0, 1), (1, 1), (1, 3)}
        assert data[(0, 0)]["current_milliamps"] == 150
        assert len(fake.ran("timeout")) == 1

    @pytest.mark.asyncio
    async def test_empty_dev_pse_then_ttyama3(self, root):
        _write(root, "dev/pse", "")
        _write(root, "dev/ttyAMA3", "")
        pse = str(root / "dev/pse")
        fake = FakeExec({
            ("stty",): (b"", 0),
            ("timeout", "3", "cat", pse): (b"", 124),
            ("timeout", "3", "cat"): (_esp32_stream(), 0),
        })
        with patch("asyncio.create_subprocess_exec", fake):
            data = await _read_all_esp32_data()

        assert [c[3] for c in fake.ran("timeout")] == [pse, str(root / "dev/ttyAMA3")]
        assert (1, 3) in data

    @pytest.mark.asyncio
    async def test_spawn_error_on_both_devices(self, root, caplog):
        _write(root, "dev/pse", "")
        _write(root, "dev/ttyAMA3", "")
        fake = FakeExec({})  # no stty binary
        with patch("asyncio.create_subprocess_exec", fake), caplog.at_level(logging.DEBUG):
            data = await _read_all_esp32_data()

        assert data == {}
        assert caplog.text.count("Failed to read ESP32 stream") == 2


class TestReadAllOnboardPorts:
    @pytest.mark.asyncio
    async def test_end_to_end_cruiser_poll(self, root, no_dns):
        # One serial read for all ports; poe4 has ESP32 power, poe0 is down.
        _write(root, "dev/pse", "")
        _make_iface(root, "poe4")
        _make_iface(root, "poe0", operstate="lowerlayerdown", speed=None)
        fake = FakeExec({
            ("stty",): (b"", 0),
            ("timeout", "3", "cat"): (_esp32_stream(), 0),
            ("ip", "neigh", "show", "dev", "poe4"):
                (b"192.168.86.93 lladdr b8:27:eb:11:22:33 used 0/0/0 probes 4 STALE\n", 0),
            ("ip", "neigh", "show", "dev", "poe0"): (b"", 0),
        })
        with patch("asyncio.create_subprocess_exec", fake):
            ports = await read_all_onboard_ports(["poe4", "poe0", "poe9"])

        assert len(fake.ran("timeout")) == 1
        assert ports["poe4"]["power_watts"] == 7.22
        assert ports["poe4"]["connected_device"]["ip_address"] == "192.168.86.93"
        assert ports["poe4"]["connected_device"]["arp_state"] == "STALE"
        assert ports["poe0"]["state"] == "searching"
        assert ports["poe0"]["enabled"] is True
        assert ports["poe9"] == {"available": False, "state": "unavailable", "link_state": "down"}

    @pytest.mark.asyncio
    async def test_exception_from_one_port_is_isolated(self, caplog):
        async def fake_read(interface, esp32_map, switch_mode):
            if interface == "poe1":
                raise RuntimeError("sysfs vanished")
            return {"available": True, "state": "power on"}

        with patch.object(poe_readers, "_read_all_esp32_data", AsyncMock(return_value={})), \
             patch.object(poe_readers, "read_network_port_status", side_effect=fake_read), \
             caplog.at_level(logging.ERROR):
            ports = await read_all_onboard_ports(["poe0", "poe1"])

        assert ports["poe0"]["state"] == "power on"
        assert ports["poe1"] == {"available": False, "state": "error", "error": "sysfs vanished"}
        assert "Failed to read interface poe1" in caplog.text


# ---------------------------------------------------------------------------
# sysfs link state and counters
# ---------------------------------------------------------------------------

class TestLinkState:
    @pytest.mark.asyncio
    async def test_up_with_speed(self, root):
        base = _make_iface(root, "poe2", flags="0x1003", speed="1000")
        assert await _read_link_state(base) == ("up", True, 1000)

    @pytest.mark.asyncio
    async def test_admin_down_flag(self, root):
        # `ip link set poe2 down` clears IFF_UP (bit 0): 0x1002.
        base = _make_iface(root, "poe2", operstate="down", flags="0x1002", speed=None)
        assert await _read_link_state(base) == ("down", False, 0)

    @pytest.mark.asyncio
    async def test_unreadable_flags_fall_back_to_operstate(self, root):
        base = _make_iface(root, "poe2", operstate="lowerlayerdown", flags="garbage")
        link, admin_up, speed = await _read_link_state(base)
        # No-carrier but configured up, so admin state is inferred as up.
        assert (link, admin_up, speed) == ("lowerlayerdown", True, 0)

    @pytest.mark.asyncio
    async def test_speed_read_error_reports_zero(self, root):
        # The kernel returns EINVAL reading speed on some PHY states; any
        # OSError leaves speed at 0 rather than failing the poll.
        base = _make_iface(root, "poe2", speed=None)
        (base / "speed").mkdir()
        assert await _read_link_state(base) == ("up", True, 0)

    @pytest.mark.asyncio
    async def test_missing_files(self, root):
        base = root / "sys/class/net/poe2"
        base.mkdir(parents=True)
        assert await _read_link_state(base) == ("unknown", False, 0)


class TestTrafficStats:
    @pytest.mark.asyncio
    async def test_counters(self, root):
        base = _make_iface(root, "poe1", rx="1500", tx="42")
        assert await _read_traffic_stats(base) == (1500, 42)

    @pytest.mark.asyncio
    async def test_no_statistics_dir(self, root):
        base = root / "sys/class/net/poe1"
        base.mkdir(parents=True)
        assert await _read_traffic_stats(base) == (0, 0)

    @pytest.mark.asyncio
    async def test_bad_counter_skipped(self, root):
        base = _make_iface(root, "poe1", rx="", tx="77")
        assert await _read_traffic_stats(base) == (0, 77)


# ---------------------------------------------------------------------------
# read_network_port_status result shapes
# ---------------------------------------------------------------------------

def _esp32_sample(state: str = "power-on") -> dict[str, Any]:
    parsed = _parse_esp32_line(_nmea(ESP32_PORT_0_0.replace("power-on", state)))
    assert parsed is not None
    return parsed


class TestOnboardResult:
    @pytest.mark.asyncio
    async def test_real_power_with_admin_up(self, root):
        _make_iface(root, "poe4")
        fake = FakeExec({("ip", "neigh"): (b"", 0)})
        with patch("asyncio.create_subprocess_exec", fake):
            result = await read_network_port_status("poe4", {(0, 0): _esp32_sample()})

        assert result["state"] == "power-on"
        assert result["enabled"] is True
        assert result["power_watts"] == 6.88
        assert result["allocated_power_watts"] == 15.4
        assert result["temperature_celsius"] == 50.0
        assert result["link_state"] == "up"
        assert result["speed_mbps"] == 1000
        assert (result["rx_bytes"], result["tx_bytes"]) == (123456, 654321)

    @pytest.mark.asyncio
    async def test_admin_down_overrides_hardware_state(self, root):
        # TPS23861 keeps reporting power-on after `ip link set down`.
        _make_iface(root, "poe4", operstate="down", flags="0x1002", speed=None)
        fake = FakeExec({("ip", "neigh"): (b"", 0)})
        with patch("asyncio.create_subprocess_exec", fake):
            result = await read_network_port_status("poe4", {(0, 0): _esp32_sample()})

        assert result["state"] == "disabled"
        assert result["enabled"] is False
        assert result["power_watts"] == 6.88

    @pytest.mark.asyncio
    @pytest.mark.parametrize("speed,watts,poe_class,milliamps", [
        ("1000", 12.5, "3", 260),
        ("100", 8.0, "2", 166),
    ])
    async def test_mocked_power_by_link_speed(self, root, speed, watts, poe_class, milliamps):
        # Port 6 has no ESP32 sample in the map, so power is estimated.
        _make_iface(root, "poe6", speed=speed, rx="10", tx="10")
        fake = FakeExec({("ip", "neigh"): (b"", 0)})
        with patch("asyncio.create_subprocess_exec", fake):
            result = await read_network_port_status("poe6", {})

        assert result["power_mocked"] is True
        assert result["state"] == "power on"
        assert result["power_watts"] == watts
        assert result["class"] == poe_class
        assert result["voltage_volts"] == 48.0
        assert result["current_milliamps"] == milliamps

    @pytest.mark.asyncio
    async def test_mocked_admin_down(self, root):
        _make_iface(root, "poe6", operstate="down", flags="0x1002", speed=None)
        fake = FakeExec({("ip", "neigh"): (b"", 0)})
        with patch("asyncio.create_subprocess_exec", fake):
            result = await read_network_port_status("poe6", {})

        assert result["state"] == "disabled"
        assert result["power_watts"] == 0.0
        assert result["voltage_volts"] == 0.0
        assert result["current_milliamps"] == 0
        assert result["class"] == "?"

    @pytest.mark.asyncio
    async def test_bad_interface_name_is_error(self, root, caplog):
        # A sysfs entry that is not poeN cannot be mapped to a port number.
        _make_iface(root, "poeX")
        with caplog.at_level(logging.ERROR):
            result = await read_network_port_status("poeX", {})
        assert result["available"] is False
        assert result["state"] == "error"
        assert "invalid literal" in result["error"]
        assert "Failed to read network port status poeX" in caplog.text

    @pytest.mark.asyncio
    async def test_bosch_found_on_silent_port(self, root):
        # No ARP, no bridge, but traffic: tcpdump identifies the camera.
        _make_iface(root, "poe6", rx="250000", tx="0")
        capture = (
            b"01:23:45.678901 00:07:5f:12:34:56 > ff:ff:ff:ff:ff:ff, ethertype 0x2070, length 128:\n"
            b"        0x0010:  426f 7363 6820 4449 4e49 4f4e 2e69 6e74  Bosch.DINION.inteox.7100i\n"
        )
        fake = FakeExec({
            ("ip", "neigh"): (b"", 0),
            ("timeout",): (capture, 124),  # running as root: no sudo prefix
        })
        with patch("custom_components.exaviz.utils.os.geteuid", return_value=0), \
             patch("asyncio.create_subprocess_exec", fake):
            result = await read_network_port_status("poe6", {})

        assert fake.ran("timeout")[0][:4] == ("timeout", "10", "tcpdump", "-i")
        device = result["connected_device"]
        assert device["name"] == "DINION.inteox.7100i on poe6"
        assert device["manufacturer"] == "Bosch Security Systems"
        assert device["ip_address"] == "N/A (Proprietary Protocol)"
        assert device["mac_address"] == "N/A (Proprietary Protocol)"


# ---------------------------------------------------------------------------
# Bosch fallback decision
# ---------------------------------------------------------------------------

BOSCH = {
    "manufacturer": "Bosch Security Systems",
    "model": "FLEXIDOME.IP.5000i",
    "device_type": "Camera",
    "detection_method": "Bosch proprietary protocol",
}


class TestTryBoschDetection:
    @pytest.mark.asyncio
    async def test_unknown_manufacturer_updated_in_place(self):
        device = {"ip_address": "10.0.0.9", "mac_address": "3e:ac:94:54:25:fa",
                  "manufacturer": "Unknown"}
        with patch.object(poe_readers, "_detect_bosch_camera", AsyncMock(return_value=BOSCH)):
            result = await _try_bosch_detection("poe1", "up", 0, 0, device)

        assert result is device
        assert result["manufacturer"] == "Bosch Security Systems"
        assert result["name"] == "FLEXIDOME.IP.5000i on poe1"
        assert result["ip_address"] == "10.0.0.9"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("link,rx,tx,device", [
        ("up", 1000, 1000, None),  # traffic at, not above, the threshold
        ("down", 50000, 0, None),
        ("up", 0, 0, {"manufacturer": "Axis Communications AB"}),
    ])
    async def test_capture_skipped(self, link, rx, tx, device):
        detect = AsyncMock(return_value=BOSCH)
        with patch.object(poe_readers, "_detect_bosch_camera", detect):
            result = await _try_bosch_detection("poe1", link, rx, tx, device)
        detect.assert_not_called()
        assert result is device

    @pytest.mark.asyncio
    async def test_not_bosch_keeps_device(self):
        device = {"manufacturer": "Unknown"}
        with patch.object(poe_readers, "_detect_bosch_camera", AsyncMock(return_value=None)):
            assert await _try_bosch_detection("poe1", "up", 0, 0, device) == {"manufacturer": "Unknown"}

    @pytest.mark.asyncio
    async def test_tcpdump_spawn_failure(self, caplog):
        fake = FakeExec({})  # neither sudo nor timeout installed
        with patch("asyncio.create_subprocess_exec", fake), caplog.at_level(logging.DEBUG):
            assert await _detect_bosch_camera("poe1") is None
        assert "Failed to detect Bosch camera on poe1" in caplog.text


# ---------------------------------------------------------------------------
# ARP table (ip neigh)
# ---------------------------------------------------------------------------

class TestArp:
    @pytest.mark.asyncio
    async def test_ipv6_only_neighbor(self, no_dns):
        out = b"fe80::ba27:ebff:fe11:2233 lladdr b8:27:eb:11:22:33 router REACHABLE\n"
        fake = FakeExec({("ip", "neigh"): (out, 0)})
        with patch("asyncio.create_subprocess_exec", fake):
            device = await _get_connected_device_from_arp("poe1")

        assert device["ip_address"] == "fe80::ba27:ebff:fe11:2233"
        assert device["mac_address"] == "b8:27:eb:11:22:33"
        assert device["arp_state"] == "REACHABLE"
        assert device["manufacturer"] == "Raspberry Pi Foundation"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("out", [
        b"192.168.86.50  FAILED\n",
        b"192.168.86.50 lladdr b8:27:eb:11:22:33 PERMANENT\n",
        b"192.168.86.50 INCOMPLETE\n",
    ])
    async def test_unusable_states_ignored(self, out):
        fake = FakeExec({("ip", "neigh"): (out, 0)})
        with patch("asyncio.create_subprocess_exec", fake):
            assert await _get_connected_device_from_arp("poe1") is None

    @pytest.mark.asyncio
    async def test_ip_binary_missing(self, caplog):
        with patch("asyncio.create_subprocess_exec", FakeExec({})), \
             caplog.at_level(logging.DEBUG):
            assert await _get_connected_device_from_arp("poe1") is None
        assert "Failed to get ARP info for poe1" in caplog.text


# ---------------------------------------------------------------------------
# Switch/bridge mode: sysfs master link, local MACs, FDB, arp-scan
# ---------------------------------------------------------------------------

class TestBridgeSysfs:
    @pytest.mark.asyncio
    async def test_bridge_master_from_symlink(self, root):
        _make_iface(root, "br0")
        poe3 = _make_iface(root, "poe3")
        (poe3 / "master").symlink_to(root / "sys/class/net/br0")
        assert await _get_bridge_master("poe3") == "br0"

    @pytest.mark.asyncio
    async def test_not_a_bridge_member(self, root):
        _make_iface(root, "poe3")
        assert await _get_bridge_master("poe3") is None

    @pytest.mark.asyncio
    async def test_local_macs(self, root):
        _make_iface(root, "end0", address="2C:CF:67:AA:BB:01")
        _make_iface(root, "br0", address="2c:cf:67:aa:bb:02")
        _make_iface(root, "sit0", address="")  # tunnel netdevs have no MAC
        (root / "sys/class/net/wg0").mkdir()  # no address file at all
        assert await _collect_local_macs() == {"2c:cf:67:aa:bb:01", "2c:cf:67:aa:bb:02"}

    @pytest.mark.asyncio
    async def test_local_macs_no_sysfs(self, root):
        assert await _collect_local_macs() == set()

    @pytest.mark.asyncio
    @pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
    async def test_local_macs_unreadable_sysfs(self, root):
        net = root / "sys/class/net"
        net.mkdir(parents=True)
        net.chmod(0)
        try:
            assert await _collect_local_macs() == set()
        finally:
            net.chmod(0o755)


class TestBridgeFdbParsing:
    def test_skips_blank_header_and_unmastered_lines(self):
        out = (
            "\n"
            "dev poe3 vlan 1\n"
            "24:52:6a:08:71:80 dev poe3 vlan 1\n"  # no `master`: not a learned entry
            "b8:27:eb:11:22:33 master br0\n"
            "b8:27:eb:11:22:33 vlan 1 master br0\n"  # same MAC, second VLAN
        )
        assert _parse_bridge_fdb(out, set()) == ["b8:27:eb:11:22:33"]


class TestBridgeCommands:
    @pytest.mark.asyncio
    async def test_fdb_show_argv_and_output(self):
        fake = FakeExec({("bridge",): (b"b8:27:eb:11:22:33 master br0\n", 0)})
        with patch("asyncio.create_subprocess_exec", fake):
            out = await _read_bridge_fdb("poe3")
        assert out == "b8:27:eb:11:22:33 master br0\n"
        assert fake.calls == [("bridge", "fdb", "show", "dev", "poe3")]

    @pytest.mark.asyncio
    async def test_fdb_show_failure(self):
        fake = FakeExec({("bridge",): (b"", 255)})
        with patch("asyncio.create_subprocess_exec", fake):
            assert await _read_bridge_fdb("poe3") == ""

    @pytest.mark.asyncio
    async def test_fdb_bridge_binary_missing(self):
        with patch("asyncio.create_subprocess_exec", FakeExec({})):
            assert await _read_bridge_fdb("poe3") == ""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("route,expected", [
        ((IP_ADDR_BR0, 0), True),
        ((b"", 0), False),  # bridge up but no lease yet
        ((b"", 1), False),  # Device "br0" does not exist.
    ])
    async def test_bridge_has_ipv4(self, route, expected):
        fake = FakeExec({("ip", "-4"): route})
        with patch("asyncio.create_subprocess_exec", fake):
            assert await _bridge_has_ipv4("br0") is expected
        assert fake.calls == [("ip", "-4", "-o", "addr", "show", "dev", "br0", "scope", "global")]

    @pytest.mark.asyncio
    async def test_bridge_has_ipv4_without_ip_binary(self):
        with patch("asyncio.create_subprocess_exec", FakeExec({})):
            assert await _bridge_has_ipv4("br0") is False


class TestArpScanErrors:
    @pytest.mark.asyncio
    async def test_arp_scan_binary_missing(self, root, caplog):
        fake = FakeExec({("ip", "-4"): (IP_ADDR_BR0, 0)})  # no arp-scan route
        with patch("custom_components.exaviz.utils.os.geteuid", return_value=0), \
             patch("asyncio.create_subprocess_exec", fake), caplog.at_level(logging.DEBUG):
            assert await _run_arp_scan("br0") == {}
        assert fake.calls[-1][:2] == ("/usr/sbin/arp-scan", "--interface")
        # The OUI file is absent from the fake root, so no --ouifile argument.
        assert not any(a.startswith("--ouifile") for a in fake.calls[-1])
        assert "arp-scan failed on br0" in caplog.text

    @pytest.mark.asyncio
    async def test_timeout_kill_of_root_child_is_tolerated(self):
        # sudo's child runs as root, so kill() can raise PermissionError.
        proc = MagicMock()
        proc.kill.side_effect = PermissionError
        proc.communicate = AsyncMock(return_value=(b"", b""))

        async def fake_wait_for(coro, timeout):
            coro.close()
            raise asyncio.TimeoutError

        with patch.object(poe_readers, "_bridge_has_ipv4", AsyncMock(return_value=True)), \
             patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)), \
             patch("asyncio.wait_for", fake_wait_for):
            assert await _run_arp_scan("br0") == {}
        proc.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_expires_after_ttl(self):
        scan = AsyncMock(return_value={})
        with patch.object(poe_readers, "_do_arp_scan", scan), \
             patch.object(poe_readers.time, "monotonic", side_effect=[100.0, 110.0, 200.0, 200.0]):
            await _run_arp_scan("br0")  # sweep, stamped t=100
            await _run_arp_scan("br0")  # t=110: 10 s old, served from cache
            assert scan.await_count == 1
            await _run_arp_scan("br0")  # t=200: 100 s old, past the 25 s TTL
        assert scan.await_count == 2


class TestResolveBridgedEndToEnd:
    @pytest.mark.asyncio
    async def test_first_of_several_macs_with_arp_scan_vendor(self, root, no_dns, caplog):
        # Full chain on a fake root: master symlink, local MAC filter, FDB,
        # `ip -4` check, and arp-scan naming a vendor our OUI table lacks.
        _make_iface(root, "br0", address="2c:cf:67:aa:bb:02")
        poe3 = _make_iface(root, "poe3", address="2c:cf:67:aa:bb:03")
        (poe3 / "master").symlink_to(root / "sys/class/net/br0")
        fdb = (
            b"2c:cf:67:aa:bb:03 master br0 permanent\n"
            b"2c:cf:67:aa:bb:02 master br0\n"  # our own bridge MAC, learned back
            b"3e:ac:94:54:25:fa master br0\n"
            b"24:52:6a:08:71:80 master br0\n"
        )
        arp_scan = (
            b"Interface: br0, type: EN10MB, MAC: 2c:cf:67:aa:bb:02, IPv4: 192.168.86.40\n"
            b"192.168.86.61\t3e:ac:94:54:25:fa\tUbiquiti Inc\n"
        )
        fake = FakeExec({
            ("bridge",): (fdb, 0),
            ("ip", "-4"): (IP_ADDR_BR0, 0),
            ("/usr/sbin/arp-scan",): (arp_scan, 0),
        })
        with patch("custom_components.exaviz.utils.os.geteuid", return_value=0), \
             patch("asyncio.create_subprocess_exec", fake), caplog.at_level(logging.DEBUG):
            device = await _resolve_bridged_device("poe3", "up", None, enabled=True)

        assert device["mac_address"] == "3e:ac:94:54:25:fa"
        assert device["ip_address"] == "192.168.86.61"
        assert device["manufacturer"] == "Ubiquiti Inc"
        assert device["detection_method"] == "bridge FDB (br0) + arp-scan"
        assert device["arp_state"] == "BRIDGE_FDB"
        assert "poe3 has 2 learned MACs, using first: 3e:ac:94:54:25:fa" in caplog.text


# ---------------------------------------------------------------------------
# _parse_field (no production caller; see report)
# ---------------------------------------------------------------------------

class TestParseField:
    def test_captures_and_strips(self):
        assert _parse_field("state: power-on \nclass: 3", r"state:([^\n]*)") == "power-on"

    def test_no_match(self):
        assert _parse_field("class: 3", r"state:(.*)") is None
