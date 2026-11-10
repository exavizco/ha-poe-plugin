"""T-11..T-19: mapping contract v1 replies into the coordinator's data shape."""
from __future__ import annotations

import datetime as dt
from unittest.mock import patch

import pytest

from custom_components.exaviz import remote
from custom_components.exaviz.coordinator import ExavizDataUpdateCoordinator
from custom_components.exaviz.remote import map_board, map_health, map_ports

from .fake_board import case

UTC = dt.timezone.utc
UPDATED = dt.datetime(2026, 11, 10, 19, 30, 0, tzinfo=UTC)
DATE = UPDATED + dt.timedelta(seconds=1)


def poe():
    return case("poe_ports")["body"]


def switch():
    return case("switch_ports")["body"]


def by_port(ports):
    return {p["port"]: p for p in ports}


def test_t11_ports_map_by_name_and_use_measured_power():
    ports = by_port(map_ports(poe(), switch(), DATE, None))
    assert sorted(ports) == list(range(8))
    p0 = ports[0]
    assert p0["interface"] == "poe0"
    assert (p0["pse"], p0["index"]) == (1, 0)
    assert (ports[5]["pse"], ports[5]["index"]) == (0, 1)
    assert p0["power_consumption_watts"] == 4.897  # power_w, not power_alloc_w (30)
    assert p0["voltage_volts"] == 52.1
    assert p0["current_milliamps"] == 94
    assert p0["poe_class"] == "4"
    assert p0["allocated_power_watts"] == 30.0
    assert p0["poe_system"] == "onboard"
    assert p0["power_mocked"] is False


def test_t12_neutral_names_and_skips():
    body = poe()
    body["ports"] = [
        dict(body["ports"][0], name="pse1-2", pse=1, index=2),
        dict(body["ports"][0], name="pse0-1", pse=0, index=1),
        dict(body["ports"][0], name="pse2-0", pse=2, index=0),
        dict(body["ports"][0], name="eth9", pse=0, index=0),
    ]
    ports = by_port(map_ports(body, {"ports": []}, DATE, None))
    assert sorted(ports) == [2, 5]
    assert ports[2]["interface"] == "poe2"
    assert (ports[5]["pse"], ports[5]["index"]) == (0, 1)


@pytest.mark.parametrize(
    ("wire", "status", "enabled"),
    [
        ("delivering", "power on", True),
        ("searching", "searching", True),
        ("disabled", "disabled", False),
        ("fault", "fault", True),
        ("unknown", "unknown", True),
    ],
)
def test_t13_state_map(wire, status, enabled):
    body = poe()
    body["ports"] = [dict(body["ports"][0], state=wire)]
    (port,) = map_ports(body, {"ports": []}, DATE, None)
    assert port["status"] == status
    assert port["enabled"] is enabled


def test_t14_connected_device_matches_local_shape():
    ports = by_port(map_ports(poe(), switch(), DATE, None))
    device = ExavizDataUpdateCoordinator._build_device_info(
        ports[0], "poe0", True, "Onboard PoE"
    )
    local = ExavizDataUpdateCoordinator._build_device_info(
        {"connected_device": {"ip_address": "x", "mac_address": "y"}},
        "poe0",
        True,
        "Onboard PoE",
    )
    assert set(device) == set(local)
    assert device["ip_address"] == "192.0.2.10"
    assert device["mac_address"] == "AA:BB:CC:DD:EE:01"
    assert device["manufacturer"] == "Axis"
    assert device["hostname"] == "camera-1"
    assert "connected_device" not in ports[1]


def test_t15_switch_ports_copied_or_defaulted():
    ports = by_port(map_ports(poe(), switch(), DATE, None))
    assert ports[0]["link_state"] == "up"
    assert ports[0]["speed_mbps"] == 100
    assert (ports[0]["rx_bytes"], ports[0]["tx_bytes"]) == (123456, 654321)
    assert ports[1]["link_state"] == "unknown"
    assert ports[1]["speed_mbps"] == 0
    assert (ports[1]["rx_bytes"], ports[1]["tx_bytes"]) == (0, 0)


class _ClockAhead(dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return dt.datetime.now(tz) + dt.timedelta(hours=1)


class _ClockBehind(dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return dt.datetime.now(tz) - dt.timedelta(hours=1)


@pytest.mark.parametrize("clock", [None, _ClockAhead, _ClockBehind])
def test_t16_stale_uses_the_board_date_only(clock):
    def stale_at(date):
        (port,) = map_ports(
            {"ports": [poe()["ports"][0]]}, {"ports": []}, date, None
        )
        return port["stale"]

    def run():
        assert stale_at(UPDATED + dt.timedelta(seconds=1)) is False
        assert stale_at(UPDATED + dt.timedelta(seconds=11)) is True
        assert stale_at(None) is False

    if clock is None:
        run()
    else:
        with patch.object(remote, "datetime", clock):
            run()


def test_t17_board_to_system_info():
    board_type, info = map_board(case("board_authed")["body"])
    assert board_type == "cruiser"
    assert info["esp32_firmware_variant"] == "zigbee"
    assert info["management_version"] == "1.0.8+test"
    assert info["esp32_firmware_version"] == "1.0.2+test"
    assert info["dkms_driver_version"] == "1.1.2+test"
    assert info["board_hw_version"] == "1.0"
    assert info["board_serial"] == "CRU-TEST-0001"
    assert info["compute_module"] == "Raspberry Pi CM5"
    assert "plugin_version" in info

    empty = case("board_authed")["body"]
    empty["firmware_variant"] = ""
    assert "esp32_firmware_variant" not in map_board(empty)[1]

    absent = case("board_authed")["body"]
    del absent["firmware_variant"]
    del absent["management_version"]
    info = map_board(absent)[1]
    assert "esp32_firmware_variant" not in info
    assert "management_version" not in info


def test_t18_health():
    assert map_health({"cpu_temp_c": 52.3}) == 52.3
    assert map_health({}) is None


def test_t19_startup_window_keeps_previous_ports_stale():
    first = map_ports(poe(), switch(), DATE, None)
    assert not any(p["stale"] for p in first)

    kept = map_ports(case("poe_ports_empty")["body"], switch(), DATE, first)
    assert [p["port"] for p in kept] == list(range(8))
    assert all(p["stale"] for p in kept)
    assert by_port(kept)[0]["power_consumption_watts"] == 4.897

    body = poe()
    body["ports"] = [p for p in body["ports"] if p["name"] != "poe3"]
    partial = by_port(map_ports(body, switch(), DATE, first))
    assert sorted(partial) == list(range(8))
    assert partial[3]["stale"] is True
    assert partial[2]["stale"] is False
