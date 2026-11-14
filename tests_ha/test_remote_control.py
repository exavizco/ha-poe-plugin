"""T-40..T-45, T-40L, T-37 (control half): switching and resetting ports."""
from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from homeassistant import config_entries
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.exaviz.const import DOMAIN
from tests.fake_board import case

from .local_board import patch_local_board
from .remote_helpers import remote_entry

CARD_FIXTURE = (
    Path(__file__).parents[1]
    / "lovelace-cards"
    / "src"
    / "test"
    / "fixtures"
    / "read-scope-states.json"
)
READ_ONLY_NOTE = (
    "This pairing is read-only. To switch ports, revoke token `0000000000000001` "
    "on the board in More > Home Assistant, start a new pairing there with PoE "
    "control, and enter the code when Home Assistant asks."
)


async def setup_remote(hass, board, **overrides):
    entry = remote_entry(board, **overrides)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def advance(hass, freezer, seconds):
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass, dt_util.utcnow())
    # Interval polls run as background tasks; wait for them too.
    await hass.async_block_till_done(wait_background_tasks=True)


async def call(hass, domain, service, entity_id):
    await hass.services.async_call(
        domain, service, {"entity_id": entity_id}, blocking=True
    )
    await hass.async_block_till_done()


def posts(board):
    return [r.path for r in board.seen("POST")]


def polls(board):
    return len(board.seen("GET", "/poe/ports"))


@pytest.fixture
def no_subprocess():
    async def fail(*args, **kwargs):
        pytest.fail(f"remote control spawned {args}")

    with patch.object(asyncio, "create_subprocess_exec", fail):
        yield


def reauth_flows(hass):
    return [
        f
        for f in hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        if f["context"]["source"] == config_entries.SOURCE_REAUTH
    ]


# --- T-40..T-42 -----------------------------------------------------------------


async def test_t40_turn_off_one_post_and_two_polls(hass, board, freezer, no_subprocess):
    entry = await setup_remote(hass, board)
    before = polls(board)
    await call(hass, "switch", "turn_off", "switch.onboard_port0")
    assert posts(board) == ["/api/v1/poe/ports/1/0/disable"]
    (post,) = board.seen("POST")
    assert post.headers["Authorization"] == f"Bearer {entry.data['token']}"
    assert polls(board) == before + 1
    await advance(hass, freezer, 3)
    assert polls(board) == before + 2


async def test_t40_unload_inside_three_seconds_cancels_the_delayed_poll(
    hass, board, freezer
):
    entry = await setup_remote(hass, board)
    await call(hass, "switch", "turn_off", "switch.onboard_port0")
    count = polls(board)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await advance(hass, freezer, 5)
    assert polls(board) == count


async def test_t40_new_toggle_replaces_pending_delayed_poll(hass, board, freezer):
    await setup_remote(hass, board)
    await call(hass, "switch", "turn_off", "switch.onboard_port0")
    await advance(hass, freezer, 2)
    await call(hass, "switch", "turn_on", "switch.onboard_port0")
    count = polls(board)
    await advance(hass, freezer, 1)  # the first delayed poll would be due now
    assert polls(board) == count
    await advance(hass, freezer, 2)
    assert polls(board) == count + 1


async def test_t41_turn_on_port5(hass, board, no_subprocess):
    await setup_remote(hass, board)
    await call(hass, "switch", "turn_on", "switch.onboard_port5")
    assert posts(board) == ["/api/v1/poe/ports/0/1/enable"]


async def test_t42_reset_is_one_reset(hass, board, no_subprocess):
    await setup_remote(hass, board)
    await call(hass, "button", "press", "button.onboard_port6_reset")
    assert posts(board) == ["/api/v1/poe/ports/0/2/reset"]


# --- T-40L: a local entry never takes the remote path ----------------------------


async def test_t40l_local_entry_uses_local_control(hass):
    entry = MockConfigEntry(
        domain=DOMAIN, data={}, unique_id="exaviz_cruiser", entry_id="local_entry"
    )
    entry.add_to_hass(hass)

    async def no_http(*args, **kwargs):
        pytest.fail("a local entry made an HTTP request")

    stack, _reader = patch_local_board()
    control = AsyncMock()
    reset = AsyncMock()
    with (
        stack,
        patch.object(aiohttp.ClientSession, "_request", no_http),
        patch(
            "custom_components.exaviz.switch.ExavizPoEPortSwitch._control_onboard_port",
            control,
        ),
        patch(
            "custom_components.exaviz.button.ExavizPoEPortResetButton._reset_onboard_port",
            reset,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        await call(hass, "switch", "turn_off", "switch.onboard_port0")
        await call(hass, "button", "press", "button.onboard_port0_reset")
        control.assert_awaited_once_with("disable")
        reset.assert_awaited_once()
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_local_failed_power_cut_raises(hass):
    """A False from the ESP32 command reaches the service caller as an error."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={}, unique_id="exaviz_cruiser", entry_id="local_entry"
    )
    entry.add_to_hass(hass)

    stack, _reader = patch_local_board()
    send = AsyncMock(return_value=False)
    link = AsyncMock(return_value=True)
    with (
        stack,
        patch(
            "custom_components.exaviz.switch.ExavizPoEPortSwitch._send_esp32_command",
            send,
        ),
        patch("custom_components.exaviz.switch.ExavizPoEPortSwitch._run_ip_link", link),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert hass.states.get("switch.onboard_port0").state == "on"
        with pytest.raises(HomeAssistantError, match="did not disable port poe0"):
            await call(hass, "switch", "turn_off", "switch.onboard_port0")
        send.assert_awaited_once_with("disable-port 1 0")
        link.assert_not_awaited()
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


# --- T-37 control half, T-43: refusals without a request ----------------------------


async def test_t37_other_serial_refuses_control_without_request(hass, board):
    entry = await setup_remote(hass, board)
    other = case("board")
    other["body"]["serial"] = "CRU-OTHER-0002"
    board.reply("GET", "/board", other)
    coordinator = entry.runtime_data
    await coordinator.async_refresh()
    with pytest.raises(HomeAssistantError):
        await coordinator.async_port_action(0, "disable")
    assert posts(board) == []


def _normalised_states(hass) -> dict:
    registry = er.async_get(hass)
    view = {}
    for entity in sorted(registry.entities.values(), key=lambda e: e.entity_id):
        if entity.platform != DOMAIN:
            continue
        current = hass.states.get(entity.entity_id)
        # plugin_version moves with releases; friendly_name is composed by HA
        # and differs between HA versions (the card does not read it).
        attributes = {
            k: v
            for k, v in current.attributes.items()
            if k not in ("plugin_version", "friendly_name")
        }
        view[entity.entity_id] = {
            "state": current.state,
            "attributes": json.loads(json.dumps(attributes, default=str)),
        }
    return view


async def test_t43_read_scope(hass, board, request):
    entry = await setup_remote(hass, board, scope="read")
    for n in range(8):
        assert hass.states.get(f"switch.onboard_port{n}").state == "unavailable"
        assert hass.states.get(f"button.onboard_port{n}_reset").state == "unavailable"
        assert hass.states.get(f"sensor.onboard_port{n}_current").state != "unavailable"
    status = hass.states.get("sensor.board_status")
    assert status.attributes["pairing_scope"] == "read"
    assert status.attributes["control_note"] == READ_ONLY_NOTE
    assert status.attributes["management_version"] == "1.0.8+test"

    coordinator = entry.runtime_data
    with pytest.raises(HomeAssistantError):
        await coordinator.async_port_action(0, "disable")
    assert posts(board) == []

    view = _normalised_states(hass)
    if request.config.getoption("--update-card-fixture"):
        CARD_FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        CARD_FIXTURE.write_text(json.dumps(view, indent=2, sort_keys=True) + "\n")
    assert view == json.loads(CARD_FIXTURE.read_text())


async def test_poe_control_scope_has_no_read_only_note(hass, board):
    await setup_remote(hass, board)
    status = hass.states.get("sensor.board_status")
    assert status.attributes["pairing_scope"] == "poe_control"
    assert "control_note" not in status.attributes
    assert hass.states.get("switch.onboard_port0").state == "on"


# --- T-44: control errors -------------------------------------------------------------


@pytest.mark.parametrize(
    ("reply", "text"),
    [
        ("control_400", "rejected"),
        ("control_403", "pair again with PoE control"),
        ("control_404", "still starting"),
        ("control_500", "could not change the port"),
    ],
)
async def test_t44_control_errors_raise(hass, board, reply, text):
    await setup_remote(hass, board)
    board.reply("POST", "/poe/ports/1/0/disable", case(reply))
    with pytest.raises(HomeAssistantError, match=text):
        await call(hass, "switch", "turn_off", "switch.onboard_port0")
    assert reauth_flows(hass) == []
    assert hass.states.get("switch.onboard_port0").state == "on"


async def test_t44_control_401_starts_reauth(hass, board):
    await setup_remote(hass, board)
    # A revoked token: every token route answers 401.
    board.reply("POST", "/poe/ports/1/0/disable", case("unauth_401"))
    board.reply("GET", "/poe/ports", case("unauth_401"))
    with pytest.raises(HomeAssistantError, match="Pair Home Assistant"):
        await call(hass, "switch", "turn_off", "switch.onboard_port0")
    await hass.async_block_till_done()
    assert len(reauth_flows(hass)) == 1


async def test_t44_control_refused_raises(hass, board, short_remote_timeout):
    entry = await setup_remote(hass, board)
    await board.stop_holding_port()
    coordinator = entry.runtime_data
    with pytest.raises(HomeAssistantError, match="did not answer"):
        await coordinator.async_port_action(0, "disable")


# --- T-45: integration services reach the remote path ----------------------------------


async def test_t45_services_reach_remote(hass, board, no_subprocess):
    await setup_remote(hass, board)
    await hass.services.async_call(
        DOMAIN, "turn_off_port", {"entity_id": "switch.onboard_port0"}, blocking=True
    )
    await hass.services.async_call(
        DOMAIN, "reset_port", {"entity_id": "switch.onboard_port1"}, blocking=True
    )
    await hass.async_block_till_done()
    assert posts(board) == [
        "/api/v1/poe/ports/1/0/disable",
        "/api/v1/poe/ports/1/1/reset",
    ]


# --- Cross-vendor review findings -------------------------------------------------


async def test_control_401_stops_polling(hass, board, freezer):
    await setup_remote(hass, board)
    board.reply("POST", "/poe/ports/1/0/disable", case("unauth_401"))
    board.reply("GET", "/poe/ports", case("unauth_401"))
    with pytest.raises(HomeAssistantError):
        await call(hass, "switch", "turn_off", "switch.onboard_port0")
    await hass.async_block_till_done()
    count = len(board.requests)
    await advance(hass, freezer, 300)
    assert len(board.requests) == count
    assert len(reauth_flows(hass)) == 1


async def test_settle_poll_started_just_before_unload_sends_nothing(hass, board, freezer):
    entry = await setup_remote(hass, board)
    await call(hass, "switch", "turn_off", "switch.onboard_port0")
    count = polls(board)
    freezer.tick(timedelta(seconds=3))
    async_fire_time_changed(hass, dt_util.utcnow())  # the settle poll starts
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert polls(board) == count


@pytest.mark.parametrize("scope", ["", "admin", "Read"])
async def test_only_poe_control_scope_controls(hass, board, scope):
    """An unexpected stored scope is read-only, never control."""
    entry = await setup_remote(hass, board, scope=scope)
    assert hass.states.get("switch.onboard_port0").state == "unavailable"
    with pytest.raises(HomeAssistantError):
        await entry.runtime_data.async_port_action(0, "disable")
    assert posts(board) == []
