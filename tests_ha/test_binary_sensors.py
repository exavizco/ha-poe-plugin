"""Powered and Plugged thresholds, and which boards get the Zigbee sensor."""

from unittest.mock import AsyncMock, patch

import pytest

from custom_components.exaviz.board_detector import BoardType
from tests.fake_board import case

from .local_board import ONBOARD, patch_local_board
from .test_golden_local import local_entry
from .test_remote_runtime import setup_remote



def set_port(board, index, **fields):
    reply = case("poe_ports")
    reply["body"]["ports"][index].update(fields)
    board.reply("GET", "/poe/ports", reply)


@pytest.mark.parametrize(("watts", "shown"), [(0.3, "off"), (0.5, "off"), (0.6, "on")])
async def test_powered_needs_more_than_half_a_watt(hass, board, watts, shown):
    """A port's idle reading at or under 0.5 W is not a powered device."""
    set_port(board, 0, power_w=watts)
    await setup_remote(hass, board)
    assert hass.states.get("binary_sensor.onboard_port0_powered").state == shown


@pytest.mark.parametrize(("milliamps", "shown"), [(0, "off"), (10, "off"), (11, "on")])
async def test_plugged_by_current_alone(hass, board, milliamps, shown):
    """With no power drawn and no device seen (port 1 in the fixture), a
    current over 10 mA still means something is plugged in."""
    set_port(board, 1, power_w=0, current_ma=milliamps)
    await setup_remote(hass, board)
    assert hass.states.get("binary_sensor.onboard_port1_powered").state == "off"
    plugged = hass.states.get("binary_sensor.onboard_port1_plug")
    assert "device_name" not in plugged.attributes
    assert plugged.state == shown


@pytest.mark.parametrize(
    ("board_type", "has_zigbee"),
    [(BoardType.CRUISER, True), (BoardType.INTERCEPTOR, False)],
)
async def test_zigbee_coordinator_sensor_only_on_a_cruiser(hass, board_type, has_zigbee):
    """The Zigbee radio is on the Cruiser's ESP32-C6; an Interceptor has none."""
    entry = local_entry()
    entry.add_to_hass(hass)
    stack, _reader = patch_local_board()
    with stack, patch(
        "custom_components.exaviz.coordinator.detect_all_poe_systems",
        AsyncMock(
            return_value={
                "board_type": board_type,
                "addon_boards": [],
                "onboard_ports": ONBOARD,
                "total_poe_ports": 8,
            }
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert hass.states.get("switch.onboard_port0") is not None
    assert (hass.states.get("binary_sensor.zigbee_coordinator") is not None) is has_zigbee
