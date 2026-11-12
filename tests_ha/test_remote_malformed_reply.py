"""#43: a malformed port, link or health reply degrades; it does not fail the poll."""
from __future__ import annotations

from tests.fake_board import case

from .test_remote_runtime import setup_remote, state


async def test_malformed_port_and_link_fields_leave_ports_working(hass, board):
    poe = case("poe_ports")
    poe["body"]["ports"] = [
        "not a dict",
        {**poe["body"]["ports"][0], "name": ["poe9"]},
        {**poe["body"]["ports"][0], "updated_at": "junk"},
        *poe["body"]["ports"][1:],
    ]
    switch = case("switch_ports")
    switch["body"]["ports"] = [7, {"name": ["x"]}, *switch["body"]["ports"]]
    switch["body"]["ports"][2]["stats"] = None
    board.reply("GET", "/poe/ports", poe)
    board.reply("GET", "/switch/ports", switch)
    await setup_remote(hass, board)

    assert state(hass, "switch.onboard_port0").state in ("on", "off")
    assert state(hass, "switch.onboard_port1").state in ("on", "off")


async def test_health_reply_that_is_not_a_dict_leaves_ports_working(hass, board):
    health = case("health")
    health["body"] = ["not", "a", "dict"]
    board.reply("GET", "/system/health", health)
    await setup_remote(hass, board)

    assert state(hass, "switch.onboard_port0").state in ("on", "off")


async def test_wrong_type_measurements_leave_ports_working(hass, board):
    poe = case("poe_ports")
    poe["body"]["ports"][0].update(power_w="x", voltage_v=[1], current_ma={"a": 1})
    switch = case("switch_ports")
    switch["body"]["ports"][0].update(speed_mbps="fast", stats={"rx_bytes": "x", "tx_bytes": None})
    board.reply("GET", "/poe/ports", poe)
    board.reply("GET", "/switch/ports", switch)
    await setup_remote(hass, board)

    assert state(hass, "switch.onboard_port0").state in ("on", "off")
    assert state(hass, "switch.onboard_port1").state in ("on", "off")
