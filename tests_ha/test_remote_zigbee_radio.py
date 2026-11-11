"""#36: the Zigbee radio state sensor on a remote board."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er

from tests.fake_board import case

from .test_remote_runtime import poll, reauth_flows, setup_remote, state

COMPONENT = Path(__file__).parents[1] / "custom_components" / "exaviz"
RADIO = "sensor.zigbee_radio"
OPTIONS = ["on", "off", "starting", "failed"]


def zigbee(**changes):
    reply = case("zigbee")
    reply["body"].update(changes)
    return reply


@pytest.mark.parametrize("radio", OPTIONS)
async def test_each_radio_state(hass, board, radio):
    board.reply("GET", "/zigbee", zigbee(state=radio))
    entry = await setup_remote(hass, board)
    sensor = state(hass, RADIO)
    assert sensor.state == radio
    assert sensor.attributes["device_class"] == "enum"
    assert sensor.attributes["options"] == OPTIONS
    registry = er.async_get(hass)
    reg = registry.async_get(RADIO)
    assert reg.unique_id == f"{entry.entry_id}_zigbee_radio"
    assert reg.translation_key == "zigbee_radio"
    assert reg.original_name == "Zigbee Radio"
    # Same device as the other board entities.
    assert reg.device_id == registry.async_get("sensor.board_temperature").device_id


async def test_state_change_seen_on_next_poll(hass, board):
    entry = await setup_remote(hass, board)
    assert state(hass, RADIO).state == "on"
    board.reply("GET", "/zigbee", zigbee(state="failed"))
    await poll(hass, entry)
    assert state(hass, RADIO).state == "failed"
    assert board.seen("GET", "/zigbee")[-1].headers["Authorization"].startswith("Bearer ")


async def test_board_could_not_read_the_unit_is_unknown(hass, board):
    board.reply("GET", "/zigbee", case("zigbee_unknown"))
    await setup_remote(hass, board)
    assert state(hass, RADIO).state == "unknown"


@pytest.mark.parametrize(
    "reply",
    [
        case("zigbee_not_available"),
        case("zigbee_stub"),
        zigbee(state="sleeping"),
        {"status": 200, "body": ["on"]},
    ],
    ids=["not_available", "stub", "unrecognised", "not_an_object"],
)
async def test_no_radio_reading_is_unavailable_and_the_rest_works(hass, board, reply):
    board.reply("GET", "/zigbee", reply)
    entry = await setup_remote(hass, board)
    assert entry.state is ConfigEntryState.LOADED
    assert state(hass, RADIO).state == "unavailable"
    assert state(hass, "sensor.board_status").state == "Operational"
    assert state(hass, "switch.onboard_port0").state == "on"
    assert state(hass, "binary_sensor.zigbee_coordinator").state == "on"


async def test_older_board_without_the_route(hass, board):
    del board.replies[("GET", "/api/v1/zigbee")]
    entry = await setup_remote(hass, board)
    assert entry.state is ConfigEntryState.LOADED
    assert state(hass, RADIO).state == "unavailable"
    assert state(hass, "sensor.board_status").state == "Operational"
    assert state(hass, "sensor.board_temperature").state == "52.3"
    assert state(hass, "switch.onboard_port0").state == "on"
    assert reauth_flows(hass) == []
    # After a management update the radio shows without a reload.
    board.reply("GET", "/zigbee", case("zigbee"))
    await poll(hass, entry)
    assert state(hass, RADIO).state == "on"


async def test_board_not_answering_then_back(hass, board):
    entry = await setup_remote(hass, board)
    port = board.port
    await board.stop()
    await poll(hass, entry)
    assert state(hass, RADIO).state == "unavailable"
    board.port = port
    await board.start()
    await poll(hass, entry)
    assert state(hass, RADIO).state == "on"


async def test_zigbee_error_fails_the_poll_like_the_other_reads(hass, board):
    entry = await setup_remote(hass, board)
    board.reply("GET", "/zigbee", case("control_500"))
    await poll(hass, entry)
    assert state(hass, RADIO).state == "unavailable"
    assert state(hass, "switch.onboard_port0").state == "unavailable"


async def test_read_only_pairing_reads_the_radio(hass, board):
    await setup_remote(hass, board, scope="read")
    assert state(hass, RADIO).state == "on"


async def test_name_matches_the_other_board_entities(hass, board):
    await setup_remote(hass, board)
    name = state(hass, RADIO).attributes["friendly_name"]
    temperature = state(hass, "sensor.board_temperature").attributes["friendly_name"]
    assert name.endswith("Zigbee Radio")
    # Both are built the same way: whatever HA prepends to one, it prepends
    # to the other.
    assert name.removesuffix("Zigbee Radio") == temperature.removesuffix(
        "Board Temperature"
    )


@pytest.mark.parametrize(
    "path",
    [COMPONENT / "strings.json", *sorted((COMPONENT / "translations").glob("*.json"))],
    ids=lambda p: p.name,
)
def test_every_language_names_every_state(path):
    radio = json.loads(path.read_text())["entity"]["sensor"]["zigbee_radio"]
    assert radio["name"]
    assert list(radio["state"]) == OPTIONS
    assert all(radio["state"].values())
