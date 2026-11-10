"""T-31..T-39, T-19b, T-33b, T-35a, T-30b remote twins: a remote entry at runtime."""
from __future__ import annotations

import asyncio
import logging
import subprocess
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.exaviz.const import DOMAIN
from tests.fake_board import case, make_cert

from .remote_helpers import TOKEN, remote_entry

LOCAL_ROOTS = ("/proc", "/sys", "/dev", "/boot", "/etc")
PORT_ENTITIES = (
    "switch.onboard_port{n}",
    "sensor.onboard_port{n}_current",
    "binary_sensor.onboard_port{n}_powered",
    "binary_sensor.onboard_port{n}_plug",
    "button.onboard_port{n}_reset",
)


async def setup_remote(hass, board, **overrides):
    entry = remote_entry(board, **overrides)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def poll(hass, entry):
    await hass.data[DOMAIN][entry.entry_id].async_refresh()
    await hass.async_block_till_done()


async def advance(hass, freezer, seconds):
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass, dt_util.utcnow())
    # Interval polls run as background tasks; wait for them too.
    await hass.async_block_till_done(wait_background_tasks=True)


def state(hass, entity_id):
    return hass.states.get(entity_id)


def reauth_flows(hass):
    return [
        f
        for f in hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        if f["context"]["source"] == config_entries.SOURCE_REAUTH
    ]


# --- T-31, T-32: setup and entities -----------------------------------------


async def test_t31_remote_setup_touches_nothing_local(hass, board):
    real_exists, real_read_text, real_read_bytes = (
        Path.exists,
        Path.read_text,
        Path.read_bytes,
    )

    def guard(real):
        def wrapper(self, *args, **kwargs):
            if str(self).startswith(LOCAL_ROOTS):
                pytest.fail(f"remote setup touched {self}")
            return real(self, *args, **kwargs)

        return wrapper

    async def no_subprocess(*args, **kwargs):
        pytest.fail(f"remote setup spawned {args}")

    def no_run(*args, **kwargs):
        pytest.fail(f"remote setup ran {args}")

    with (
        patch.object(asyncio, "create_subprocess_exec", no_subprocess),
        patch.object(subprocess, "run", no_run),
        patch.object(Path, "exists", guard(real_exists)),
        patch.object(Path, "read_text", guard(real_read_text)),
        patch.object(Path, "read_bytes", guard(real_read_bytes)),
    ):
        entry = await setup_remote(hass, board)
        await poll(hass, entry)
    assert entry.state is ConfigEntryState.LOADED


async def test_t32_remote_entities_match_local_ids_and_fixture(hass, board):
    entry = await setup_remote(hass, board)
    for n in range(8):
        for pattern in PORT_ENTITIES:
            assert state(hass, pattern.format(n=n)) is not None, pattern.format(n=n)
    assert state(hass, "switch.onboard_port0").state == "on"
    assert state(hass, "switch.onboard_port2").state == "off"
    assert state(hass, "switch.onboard_port0").attributes["power_consumption_watts"] == 4.897
    assert state(hass, "binary_sensor.onboard_port0_powered").state == "on"
    assert state(hass, "binary_sensor.onboard_port0_plug").state == "on"
    assert state(hass, "binary_sensor.onboard_port1_powered").state == "off"
    assert state(hass, "sensor.board_status").state == "Operational"
    assert state(hass, "sensor.board_temperature").state == "52.3"
    assert state(hass, "binary_sensor.zigbee_coordinator").state == "on"
    attrs = state(hass, "switch.onboard_port0").attributes
    assert attrs["device_ip"] == "192.0.2.10"
    assert attrs["link_state"] == "up"
    registry = er.async_get(hass)
    assert (
        registry.async_get("switch.onboard_port4").unique_id
        == f"{entry.entry_id}_onboard_port4"
    )
    # Every poll sends the bearer, /board included.
    assert {r.headers.get("Authorization") for r in board.requests} == {
        f"Bearer {entry.data['token']}"
    }


# --- T-19, T-19b: startup window and ports seen later -----------------------


async def test_t19_no_ports_at_first_read_is_not_ready(hass, board):
    board.reply("GET", "/poe/ports", case("poe_ports_empty"))
    startup = case("board")
    startup["body"]["total_poe_ports"] = 0
    board.reply("GET", "/board", startup)
    entry = await setup_remote(hass, board)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_t19_empty_after_good_poll_keeps_entities_and_count(hass, board):
    entry = await setup_remote(hass, board)
    board.reply("GET", "/poe/ports", case("poe_ports_empty"))
    startup = case("board")
    startup["body"]["total_poe_ports"] = 0
    board.reply("GET", "/board", startup)
    await poll(hass, entry)
    assert state(hass, "sensor.board_status").state == "Operational"
    assert state(hass, "switch.onboard_port0").state == "unavailable"


async def test_t19b_ports_seen_later_get_entities(hass, board):
    first = case("poe_ports")
    first["body"]["ports"] = first["body"]["ports"][:4]
    board.reply("GET", "/poe/ports", first)
    entry = await setup_remote(hass, board)
    assert state(hass, "switch.onboard_port3") is not None
    assert state(hass, "switch.onboard_port4") is None

    board.reply("GET", "/poe/ports", case("poe_ports"))
    await poll(hass, entry)
    registry = er.async_get(hass)
    for n in range(4, 8):
        for pattern in PORT_ENTITIES:
            entity_id = pattern.format(n=n)
            assert state(hass, entity_id) is not None, entity_id
    assert (
        registry.async_get("binary_sensor.onboard_port7_plug").unique_id
        == f"{entry.entry_id}_onboard_port7_plug"
    )


# --- T-33, T-33b: Zigbee -----------------------------------------------------


@pytest.mark.parametrize(
    ("variant", "expected"),
    [
        ("zigbee", "on"),
        ("zigbee-rcp", "on"),
        ("all-unsupported", "on"),
        ("stock", "off"),
        ("poe-only", "off"),
        ("", "unknown"),
    ],
)
async def test_t33_zigbee_variants(hass, board, variant, expected):
    reply = case("board")
    reply["body"]["firmware_variant"] = variant
    board.reply("GET", "/board", reply)
    await setup_remote(hass, board)
    zigbee = state(hass, "binary_sensor.zigbee_coordinator")
    assert zigbee.state == expected
    if expected == "off":
        assert zigbee.attributes["message"].startswith("You don't have Zigbee firmware")


async def test_t33b_zigbee_change_seen_without_reload(hass, board):
    stock = case("board")
    stock["body"]["firmware_variant"] = "stock"
    board.reply("GET", "/board", stock)
    entry = await setup_remote(hass, board)
    assert state(hass, "binary_sensor.zigbee_coordinator").state == "off"
    board.reply("GET", "/board", case("board"))
    await poll(hass, entry)
    assert state(hass, "binary_sensor.zigbee_coordinator").state == "on"


# --- T-34, T-35, T-35a: unreachable, 401, startup errors ---------------------


async def test_t34_unreachable_at_setup_retries(hass, board):
    await board.stop()
    entry = await setup_remote(hass, board)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_t34_unreachable_later_then_recovers(hass, board):
    entry = await setup_remote(hass, board)
    port = board.port
    await board.stop()
    await poll(hass, entry)
    assert state(hass, "switch.onboard_port0").state == "unavailable"
    assert state(hass, "sensor.board_status").state == "Error"
    board.port = port
    await board.start()
    await poll(hass, entry)
    assert state(hass, "switch.onboard_port0").state == "on"
    assert state(hass, "sensor.board_status").state == "Operational"


async def test_t35_401_on_poll_starts_reauth_and_stops_polling(hass, board, freezer):
    entry = await setup_remote(hass, board)
    board.reply("GET", "/poe/ports", case("unauth_401"))
    await poll(hass, entry)
    assert len(reauth_flows(hass)) == 1
    count = len(board.requests)
    await advance(hass, freezer, 300)
    assert len(board.requests) == count


@pytest.mark.parametrize("problem", ["401", "certificate", "contract"])
async def test_t35a_startup_errors_are_not_retried(hass, board, freezer, problem):
    paired = board.cert.sha256
    if problem == "401":
        # A revoked token: /board stays public, the token routes answer 401.
        board.reply("GET", "/poe/ports", case("unauth_401"))
    elif problem == "certificate":
        await board.restart(make_cert())
    else:
        old = case("board")
        del old["body"]["ha_contract_version"]
        board.reply("GET", "/board", old)
    entry = await setup_remote(hass, board, fingerprint=paired)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    if problem == "contract":
        assert "Update Exaviz Management" in entry.reason
        assert reauth_flows(hass) == []
    else:
        assert len(reauth_flows(hass)) == 1
    count = len(board.requests)
    await advance(hass, freezer, 300)
    assert len(board.requests) == count


async def test_t36_certificate_change_reauth_never_sends_bearer(hass, board):
    entry = await setup_remote(hass, board)
    old_token = entry.data["token"]
    new = make_cert()
    await board.restart(new)
    board.requests.clear()  # from here on the board holds the new certificate
    await poll(hass, entry)
    (flow,) = reauth_flows(hass)

    result = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    assert result["step_id"] == "fingerprint"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"confirm": True}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": "ABCD-EFGH"}
    )
    assert result["reason"] == "reauth_successful"
    await hass.async_block_till_done()
    assert entry.data["fingerprint"] == new.sha256
    assert entry.data["token"] == TOKEN
    assert entry.state is ConfigEntryState.LOADED
    assert all(
        r.headers.get("Authorization") != f"Bearer {old_token}" for r in board.requests
    )


# --- T-37, T-38, T-39 ----------------------------------------------------------


async def test_t37_other_serial_makes_entities_unavailable(hass, board):
    entry = await setup_remote(hass, board)
    other = case("board")
    other["body"]["serial"] = "CRU-OTHER-0002"
    board.reply("GET", "/board", other)
    await poll(hass, entry)
    assert state(hass, "switch.onboard_port0").state == "unavailable"
    assert state(hass, "sensor.board_status").state == "Error"
    assert hass.data[DOMAIN][entry.entry_id].serial_mismatch is True


@pytest.mark.parametrize("problem", ["no_contract", "404"])
async def test_t38_contract_lost_reloads_into_setup_error(hass, board, freezer, problem):
    entry = await setup_remote(hass, board)
    if problem == "404":
        board.reply("GET", "/board", case("control_404"))
        message = "Exaviz Management is not installed"
    else:
        old = case("board")
        del old["body"]["ha_contract_version"]
        board.reply("GET", "/board", old)
        message = "Update Exaviz Management"
    await poll(hass, entry)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert message in entry.reason
    count = len(board.seen("GET", "/board"))
    await advance(hass, freezer, 300)
    assert len(board.seen("GET", "/board")) == count


async def test_t39_stale_port_entities_unavailable_then_back(hass, board):
    entry = await setup_remote(hass, board)
    stale = case("poe_ports")
    stale["body"]["ports"][0]["updated_at"] = "2026-11-10T19:29:00Z"
    board.reply("GET", "/poe/ports", stale)
    await poll(hass, entry)
    for pattern in PORT_ENTITIES:
        assert state(hass, pattern.format(n=0)).state == "unavailable", pattern
    assert state(hass, "switch.onboard_port1").state != "unavailable"
    board.reply("GET", "/poe/ports", case("poe_ports"))
    await poll(hass, entry)
    for pattern in PORT_ENTITIES:
        assert state(hass, pattern.format(n=0)).state != "unavailable", pattern


# --- T-30b remote twins ---------------------------------------------------------


def _count_lifecycle():
    import custom_components.exaviz as integration

    counts = {"setup": 0, "unload": 0}
    real_setup, real_unload = integration.async_setup_entry, integration.async_unload_entry

    async def setup(hass, entry):
        counts["setup"] += 1
        return await real_setup(hass, entry)

    async def unload(hass, entry):
        counts["unload"] += 1
        return await real_unload(hass, entry)

    return counts, patch.multiple(integration, async_setup_entry=setup, async_unload_entry=unload)


async def test_ca_mode_sends_the_token_only_to_the_confirmed_key(hass, board):
    """CA mode accepts a renewed certificate with the same key. A CA-valid
    certificate with another key gets no bearer and starts reauth."""
    ca = make_cert(("Test CA",), is_ca=True)
    first = make_cert(("127.0.0.1",), issuer=ca)
    await board.restart(first)
    entry = await setup_remote(
        hass, board, trust_mode="ca", fingerprint=first.sha256, spki=first.spki_sha256
    )
    assert entry.state is ConfigEntryState.LOADED

    await board.restart(make_cert(("127.0.0.1",), issuer=ca, key=first.key))
    await poll(hass, entry)
    assert hass.data[DOMAIN][entry.entry_id].last_update_success
    assert reauth_flows(hass) == []

    await board.restart(make_cert(("127.0.0.1",), issuer=ca))
    board.requests.clear()
    await poll(hass, entry)
    assert board.requests == []
    assert len(reauth_flows(hass)) == 1


async def test_t30b_remote_reauth_success_reloads_once(hass, board, caplog):
    entry = await setup_remote(hass, board)
    counts, patcher = _count_lifecycle()
    with patcher:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
            data=dict(entry.data),
        )
        await hass.config_entries.flow.async_configure(result["flow_id"], {})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"code": "ABCD-EFGH"}
        )
        assert result["reason"] == "reauth_successful"
        await hass.async_block_till_done()
    assert counts == {"setup": 1, "unload": 1}
    assert entry.state is ConfigEntryState.LOADED
    assert "update listener" not in caplog.text.lower()


async def test_t30b_remote_options_change_with_401_goes_to_reauth(hass, board):
    entry = await setup_remote(hass, board)
    board.reply("GET", "/poe/ports", case("unauth_401"))
    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"], {"update_interval": 60}
    )
    await hass.async_block_till_done()
    assert entry.state is not ConfigEntryState.LOADED
    assert len(reauth_flows(hass)) == 1


async def test_reauth_after_startup_auth_failure_loads_the_entry(hass, board):
    """Review finding: no update listener exists yet when setup failed."""
    board.reply("GET", "/poe/ports", case("unauth_401"))
    entry = await setup_remote(hass, board)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    (flow,) = reauth_flows(hass)
    board.reply("GET", "/poe/ports", case("poe_ports"))
    await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"code": "ABCD-EFGH"}
    )
    assert result["reason"] == "reauth_successful"
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert entry.data["token"] == TOKEN


async def test_advance_helper_runs_interval_polls(hass, board, freezer):
    """Positive control: the "no more polls" checks above only mean
    something if advancing time does run the interval poll."""
    await setup_remote(hass, board)
    count = len(board.seen("GET", "/poe/ports"))
    for _ in range(3):
        await advance(hass, freezer, 31)
    assert len(board.seen("GET", "/poe/ports")) == count + 3


async def test_unreadable_port_data_marks_the_poll_failed(hass, board, caplog):
    """A malformed reply is a failed poll, not a traceback every interval."""
    entry = await setup_remote(hass, board)
    reply = case("poe_ports")
    reply["body"]["ports"][0]["power_w"] = "lots"
    board.reply("GET", "/poe/ports", reply)
    await poll(hass, entry)
    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert not coordinator.last_update_success
    assert hass.states.get("switch.onboard_port0").state == "unavailable"
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert [r.getMessage() for r in errors] == [
        "Error fetching exaviz data: the board sent data this integration cannot read"
    ]
    assert not any(r.exc_info for r in errors)
