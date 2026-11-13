"""T-11..T-19: mapping contract v1 replies into the coordinator's data shape."""
from __future__ import annotations

import datetime as dt
import json
from unittest.mock import patch

import pytest

from custom_components.exaviz import remote
from custom_components.exaviz.coordinator import ExavizDataUpdateCoordinator
from custom_components.exaviz.remote import (
    map_board,
    map_health,
    map_ports,
    map_total_ports,
    map_zigbee,
)

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


def test_t17b_board_strings_are_capped_and_typed():
    """A board string longer than the cap is cut; a non-string value is left out."""
    cap = 256  # the documented limit; a change here is a visible change

    body = case("board_authed")["body"]
    body["os_version"] = "A" + "x" * (cap + 5000)
    body["kernel_version"] = "  6.18.34  "
    body["netplan_version"] = {"nested": "y" * 100_000}
    body["poe_controller"] = ["a"] * 1000
    body["serial"] = "S" * cap  # exactly the cap: kept whole
    info = map_board(body)[1]
    assert info["os_version"] == "A" + "x" * (cap - 1)  # the start is kept
    assert info["kernel_version"] == "6.18.34"
    assert "netplan_version" not in info
    assert "poe_controller" not in info
    assert info["board_serial"] == "S" * cap
    assert info["management_version"] == "1.0.8+test"


def test_t18_health():
    assert map_health({"cpu_temp_c": 52.3}) == 52.3
    assert map_health({"cpu_temp_c": 52}) == 52
    assert map_health({}) is None


@pytest.mark.parametrize(
    "value",
    ["n/a", "52.3", True, None, [52.3], {"c": 52.3}, float("nan"), float("inf"), float("-inf")],
)
def test_health_temperature_of_the_wrong_type_is_missing(value):
    assert map_health({"cpu_temp_c": value}) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [(8, 8), (4, 4), ("8", None), (8.0, None), (True, None), (0, None), (-1, None), (None, None)],
)
def test_board_port_count_must_be_a_positive_int(value, expected):
    assert map_total_ports({"total_poe_ports": value}) == expected
    assert map_total_ports({}) is None


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (case("zigbee")["body"], "on"),
        (dict(case("zigbee")["body"], state="off"), "off"),
        (dict(case("zigbee")["body"], state="starting"), "starting"),
        (dict(case("zigbee")["body"], state="failed"), "failed"),
        # The board could not read the unit: a value of unknown, not gone.
        (case("zigbee_unknown")["body"], "unknown"),
        # No radio to report: the unit is not installed, the reply is the
        # pre-#462 stub, the state is one this plugin does not know, or the
        # route is missing (the client passes None).
        (case("zigbee_not_available")["body"], None),
        (case("zigbee_stub")["body"], None),
        (dict(case("zigbee")["body"], stub=True), None),
        (dict(case("zigbee")["body"], state="sleeping"), None),
        (dict(case("zigbee")["body"], state=1), None),
        (dict(case("zigbee")["body"], state=["on"]), None),
        ({"stub": False}, None),
        (["on"], None),
        (None, None),
    ],
)
def test_zigbee_radio_state(body, expected):
    assert map_zigbee(body) == expected


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


def test_unknown_port_name_is_logged_once(caplog):
    body = poe()
    # A name no other test uses: each name is warned about once per process.
    body["ports"] = [dict(body["ports"][0], name="pse7-3", pse=7, index=3)]
    with caplog.at_level("WARNING"):
        map_ports(body, {"ports": []}, DATE, None)
        map_ports(body, {"ports": []}, DATE, None)
    assert sum("pse7-3" in r.getMessage() for r in caplog.records) == 1


def _device(**fields):
    body = poe()
    body["connected_devices"]["poe0"] = fields
    return by_port(map_ports(body, switch(), DATE, None))[0]["connected_device"]


def test_43_device_text_is_trimmed_and_capped():
    device = _device(
        ip="  192.0.2.10 ",
        mac="AA:BB:CC:DD:EE:01",
        manufacturer="M" * 500_000,
        hostname="h" * 300 + "TAIL",
    )
    assert device["ip_address"] == "192.0.2.10"
    assert device["manufacturer"] == "M" * 256
    assert device["hostname"] == "h" * 256


def test_43_device_text_that_is_not_text_falls_back():
    device = _device(
        ip=["z"], mac={"x": 1}, manufacturer=["y" * 100_000], hostname=12345
    )
    assert device["ip_address"] is None
    assert device["mac_address"] is None
    assert device["manufacturer"] == "Unknown"
    assert device["hostname"] is None


def test_43_blank_device_text_falls_back():
    device = _device(ip="192.0.2.10", mac="AA:BB:CC:DD:EE:01", manufacturer="  ", hostname="")
    assert device["manufacturer"] == "Unknown"
    assert device["hostname"] is None


@pytest.mark.parametrize("devices", [None, [], "text", 7, [{"ip": "192.0.2.10"}]])
def test_43_connected_devices_that_is_not_a_dict_means_no_devices(devices):
    body = poe()
    body["connected_devices"] = devices
    ports = by_port(map_ports(body, switch(), DATE, None))
    assert ports.keys() == by_port(map_ports(poe(), switch(), DATE, None)).keys()
    assert all("connected_device" not in p for p in ports.values())


def test_43_a_device_entry_that_is_not_a_dict_drops_only_that_device():
    body = poe()
    body["connected_devices"] = {
        "poe0": "not a dict",
        "poe1": ["x"],
        "poe3": {},
        "poe2": {"ip": "192.0.2.12", "mac": "AA:BB:CC:DD:EE:02"},
    }
    ports = by_port(map_ports(body, switch(), DATE, None))
    assert "connected_device" not in ports[0]
    assert "connected_device" not in ports[1]
    assert "connected_device" not in ports[3]
    assert ports[2]["connected_device"]["ip_address"] == "192.0.2.12"


# --- #43 round 8: a malformed reply degrades, it does not raise ---------------

GOOD_PORT = {"name": "poe0", "pse": 0, "index": 0, "state": "delivering"}


def _ports(poe_ports, switch_ports=None, date=DATE, previous=None):
    return by_port(
        map_ports(
            {"ports": poe_ports},
            {"ports": [] if switch_ports is None else switch_ports},
            date,
            previous,
        )
    )


@pytest.mark.parametrize("entry", [1, None, "poe1", ["poe1"], 2.5])
def test_43_a_port_entry_that_is_not_a_dict_drops_only_that_port(entry):
    ports = _ports([entry, GOOD_PORT, dict(GOOD_PORT, name="poe1", index=1)])
    assert sorted(ports) == [0, 1]


@pytest.mark.parametrize("name", [None, 5, ["poe1"], {"a": 1}, True])
def test_43_a_port_name_that_is_not_text_drops_only_that_port(name):
    ports = _ports([dict(GOOD_PORT, name=name, index=3), GOOD_PORT])
    assert sorted(ports) == [0]


@pytest.mark.parametrize("ports_value", [None, "poe0", 7, {"poe0": GOOD_PORT}])
def test_43_a_ports_field_that_is_not_a_list_means_no_ports(ports_value):
    kept = [{**by_port(map_ports(poe(), switch(), DATE, None))[0]}]
    assert map_ports({"ports": ports_value}, switch(), DATE, None) == []
    # With a good poll behind it the old port stays, marked stale.
    again = map_ports({"ports": ports_value}, switch(), DATE, kept)
    assert [(p["port"], p["stale"]) for p in again] == [(0, True)]


@pytest.mark.parametrize("body", [None, [], [GOOD_PORT], "text", 7])
def test_43_a_poe_reply_that_is_not_a_dict_means_no_ports(body):
    assert map_ports(body, switch(), DATE, None) == []


@pytest.mark.parametrize("body", [None, [], [{"name": "poe0"}], "text", 7])
def test_43_a_switch_reply_that_is_not_a_dict_means_no_link_data(body):
    port = map_ports({"ports": [GOOD_PORT]}, body, DATE, None)[0]
    assert port["link_state"] == "unknown"
    assert port["rx_bytes"] == 0


@pytest.mark.parametrize("switch_ports", [None, "x", 3, {"name": "poe0"}])
def test_43_a_switch_ports_field_that_is_not_a_list_means_no_link_data(switch_ports):
    port = _ports([GOOD_PORT], switch_ports)[0]
    assert port["link_state"] == "unknown"


def test_43_a_switch_entry_that_is_not_a_dict_or_has_no_text_name_is_skipped():
    link = {"name": "poe0", "oper_state": "up", "speed_mbps": 1000}
    bad = [7, None, ["poe0"], {"name": ["poe0"], "oper_state": "down"}, {"name": None}]
    port = _ports([GOOD_PORT], bad + [link])[0]
    assert port["link_state"] == "up"
    assert port["speed_mbps"] == 1000


@pytest.mark.parametrize("stats", [None, [], "x", 7, [1, 2]])
def test_43_link_stats_that_are_not_a_dict_count_as_zero(stats):
    link = {"name": "poe0", "oper_state": "up", "stats": stats}
    port = _ports([GOOD_PORT], [link])[0]
    assert port["link_state"] == "up"
    assert (port["rx_bytes"], port["tx_bytes"]) == (0, 0)


@pytest.mark.parametrize(
    "updated_at",
    [
        "not a date",
        "",
        5,
        ["2026-11-10T19:00:00Z"],
        {"t": 1},
        "2026-11-10T19:00:00",  # no timezone: cannot be compared with the board's Date
    ],
)
def test_43_a_bad_updated_at_means_not_stale_and_keeps_the_port(updated_at):
    ports = _ports([dict(GOOD_PORT, updated_at=updated_at)])
    assert ports[0]["stale"] is False


def test_43_a_good_updated_at_still_marks_stale():
    old = (UPDATED - dt.timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    assert _ports([dict(GOOD_PORT, updated_at=old)])[0]["stale"] is True


def test_43_a_naive_board_date_means_not_stale():
    naive = dt.datetime(2026, 11, 10, 19, 31, 0)
    old = (UPDATED - dt.timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    assert _ports([dict(GOOD_PORT, updated_at=old)], date=naive)[0]["stale"] is False


@pytest.mark.parametrize("body", [None, [], [1], "text", 7])
def test_43_a_health_reply_that_is_not_a_dict_means_no_temperature(body):
    assert map_health(body) is None


def test_43_a_port_name_that_is_not_text_is_logged_by_type_once(caplog, monkeypatch):
    monkeypatch.setattr(remote, "_WARNED_PORT_NAMES", set())
    huge = ["x" * 100_000]
    with caplog.at_level("WARNING"):
        for _ in range(2):
            _ports([dict(GOOD_PORT, name=huge), dict(GOOD_PORT, name=huge)])
    messages = [r.getMessage() for r in caplog.records]
    assert sum("<list>" in m for m in messages) == 1
    assert all(len(m) < 200 for m in messages)


def test_43_a_huge_integer_temperature_means_no_temperature():
    assert map_health(json.loads('{"cpu_temp_c": 1' + "0" * 400 + "}")) is None


@pytest.mark.parametrize("name", ["poe" + "1" * 5000, "pse" + "1" * 5000 + "-0"])
def test_43_a_port_name_with_a_huge_number_drops_only_that_port(name):
    ports = _ports([dict(GOOD_PORT, name=name, index=2), GOOD_PORT])
    assert sorted(ports) == [0]


# --- #43: a measurement of the wrong type counts as missing -------------------

BAD_MEASUREMENTS = [
    pytest.param(value, id=name)
    for name, value in [
        ("text", "x"), ("null", None), ("list", [1]), ("dict", {"a": 1}), ("bool", True),
        ("nan", float("nan")), ("inf", float("inf")), ("huge-int", 10**400),
    ]
]


@pytest.mark.parametrize("bad", BAD_MEASUREMENTS)
@pytest.mark.parametrize(
    ("wire", "key", "default"),
    [
        ("power_w", "power_consumption_watts", 0.0),
        ("voltage_v", "voltage_volts", 0.0),
        ("current_ma", "current_milliamps", 0),
    ],
)
def test_43_a_poe_measurement_of_the_wrong_type_counts_as_missing(wire, key, default, bad):
    port = _ports([dict(GOOD_PORT, **{wire: bad})])[0]
    assert port[key] == default
    assert type(port[key]) is type(default)


@pytest.mark.parametrize("bad", BAD_MEASUREMENTS)
@pytest.mark.parametrize("key", ["speed_mbps", "rx_bytes", "tx_bytes"])
def test_43_a_link_measurement_of_the_wrong_type_counts_as_missing(key, bad):
    link = {"name": "poe0", "speed_mbps": 1000, "stats": {"rx_bytes": 7, "tx_bytes": 9}}
    if key == "speed_mbps":
        link[key] = bad
    else:
        link["stats"][key] = bad
    port = _ports([GOOD_PORT], [link])[0]
    assert port[key] == 0


def test_43_good_measurements_pass_through_unchanged():
    wire = dict(GOOD_PORT, power_w=4.5, voltage_v=52, current_ma=94)
    link = {"name": "poe0", "speed_mbps": 1000, "stats": {"rx_bytes": 7, "tx_bytes": 9}}
    port = _ports([wire], [link])[0]
    assert (port["power_consumption_watts"], port["voltage_volts"]) == (4.5, 52)
    assert port["current_milliamps"] == 94 and type(port["voltage_volts"]) is int
    assert (port["speed_mbps"], port["rx_bytes"], port["tx_bytes"]) == (1000, 7, 9)


@pytest.mark.parametrize(
    ("stored_key", "exists", "written"),
    [
        ("k" * 64, True, True),
        # A reauth paired another key meanwhile: the old key's leaf stays out.
        ("n" * 64, True, False),
        # The entry was removed while the request was in flight.
        ("k" * 64, False, False),
    ],
)
def test_renewed_fingerprint_is_stored_only_for_the_same_pairing(
    stored_key, exists, written
):
    from unittest.mock import MagicMock

    from custom_components.exaviz.const import CONF_FINGERPRINT, CONF_SPKI

    coordinator = object.__new__(ExavizDataUpdateCoordinator)
    coordinator.hass = MagicMock()
    entry = MagicMock(
        data={CONF_FINGERPRINT: "a" * 64, CONF_SPKI: stored_key, "host": "h"}
    )
    coordinator.entry = entry
    coordinator.hass.config_entries.async_get_entry.return_value = (
        entry if exists else None
    )
    coordinator._store_renewed_fingerprint("k" * 64, "b" * 64)
    update = coordinator.hass.config_entries.async_update_entry
    if written:
        update.assert_called_once_with(
            entry,
            data={CONF_FINGERPRINT: "b" * 64, CONF_SPKI: stored_key, "host": "h"},
        )
    else:
        update.assert_not_called()
