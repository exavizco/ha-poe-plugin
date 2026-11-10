"""T-46..T-48: no secrets in logs, no host but the board, every text key present."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import pytest
from homeassistant import config_entries
from homeassistant.exceptions import HomeAssistantError

from custom_components.exaviz.const import DOMAIN
from tests.fake_board import case

from .remote_helpers import start_remote

COMPONENT = Path(__file__).parents[1] / "custom_components" / "exaviz"
CODE = "QWER-TYUP"


async def _walk_everything(hass, board) -> None:
    """Pair, set up, poll, switch a port, get a 401, re-pair."""
    result = await start_remote(hass, board.host, board.port)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"confirm": True}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": CODE}
    )
    entry = result["result"]
    await hass.async_block_till_done()
    coordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_refresh()
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.onboard_port0"}, blocking=True
    )
    await hass.async_block_till_done()

    board.reply("GET", "/poe/ports", case("unauth_401"))
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    (flow,) = [
        f
        for f in hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        if f["context"]["source"] == config_entries.SOURCE_REAUTH
    ]
    board.reply("GET", "/poe/ports", case("poe_ports"))
    await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {"code": CODE}
    )
    assert result["reason"] == "reauth_successful"
    await hass.async_block_till_done()


async def test_t46_logs_never_carry_token_or_code(hass, board, caplog):
    caplog.set_level(logging.DEBUG)
    token = case("pair_201")["body"]["token"]
    secret = token.rsplit("_", 1)[1]
    await _walk_everything(hass, board)
    assert caplog.records  # DEBUG logging was captured
    for record in caplog.records:
        text = record.getMessage()
        assert token not in text
        assert secret not in text
        assert CODE not in text


async def test_t47_only_the_board_is_contacted(hass, board):
    seen: set[tuple[str, int]] = set()
    loop = asyncio.get_running_loop()
    real_sock_connect = loop.sock_connect

    async def recording_sock_connect(sock, address):
        seen.add((address[0], address[1]))
        return await real_sock_connect(sock, address)

    loop.sock_connect = recording_sock_connect
    try:
        await _walk_everything(hass, board)
        entry = hass.config_entries.async_entries(DOMAIN)[0]
        board.reply(
            "POST",
            "/poe/ports/1/0/disable",
            {"status": 308, "headers": {"Location": f"https://127.0.0.2:{board.port}/"}},
        )
        with pytest.raises(HomeAssistantError):
            await hass.data[DOMAIN][entry.entry_id].async_port_action(0, "disable")
    finally:
        del loop.sock_connect
    assert seen == {("127.0.0.1", board.port)}


# --- T-48: text keys --------------------------------------------------------------

STEPS = ("user", "local", "remote", "fingerprint", "pair", "repair", "reconfigure")
ERRORS = (
    "cannot_connect",
    "no_poe_detected",
    "missing_packages",
    "unknown",
    "https_required",
    "invalid_host",
    "board_unreachable",
    "no_management",
    "management_too_old",
    "unsupported_contract",
    "unsupported_board",
    "invalid_code",
    "too_many_attempts",
    "token_limit",
)
ABORTS = (
    "single_instance_allowed",
    "fingerprint_rejected",
    "serial_mismatch",
    "board_unreachable",
    "reauth_successful",
    "reconfigure_successful",
    "reconfigure_local",
    # Reauth probes the stored address and can end on these.
    "no_management",
    "management_too_old",
    "unsupported_contract",
)


@pytest.mark.parametrize("name", ["strings.json", "translations/en.json"])
def test_t48_english_keys(name):
    config = json.loads((COMPONENT / name).read_text())["config"]
    for step in STEPS:
        assert config["step"][step]["title"], step
    assert set(config["step"]["user"]["menu_options"]) == {"local", "remote"}
    for key in ERRORS:
        assert config["error"][key], key
    for key in ABORTS:
        assert config["abort"][key], key
    assert "{fingerprint}" in config["step"]["fingerprint"]["description"]
    assert "{old_token_id}" in config["step"]["repair"]["description"]
    assert "{retry_after}" in config["error"]["too_many_attempts"]


@pytest.mark.parametrize(
    "locale", sorted((COMPONENT / "translations").glob("*.json")), ids=lambda p: p.stem
)
def test_t48_every_locale_loads_with_the_local_step(locale):
    config = json.loads(locale.read_text())["config"]
    assert "user" not in config["step"] or "menu_options" in config["step"]["user"]
    assert config["step"]["local"]["title"]
    assert config["error"]["missing_packages"]
