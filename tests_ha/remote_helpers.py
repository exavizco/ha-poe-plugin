"""Helpers for remote-host tests on a real Home Assistant."""
from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.exaviz.const import DOMAIN
from tests.fake_board import FakeBoard, case

TOKEN = case("pair_201")["body"]["token"]
SERIAL = "CRU-TEST-0001"


def remote_data(board: FakeBoard, **overrides: Any) -> dict[str, Any]:
    data = {
        "connection": "remote",
        "host": board.host,
        "port": board.port,
        "token": "exha_0000000000000001_" + "11" * 32,
        "token_id": "0000000000000001",
        "scope": "poe_control",
        "fingerprint": board.cert.sha256,
        "spki": board.cert.spki_sha256,
        "trust_mode": "pin",
        "serial": SERIAL,
        "board_type": "cruiser",
        "update_interval": 30,
    }
    data.update(overrides)
    return data


def remote_entry(board: FakeBoard, **overrides: Any) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        data=remote_data(board, **overrides),
        unique_id=SERIAL,
        title="Garage",
        entry_id="remote_entry",
    )


async def start_remote(hass, host: str, port: int | None = None) -> dict:
    """User menu -> remote step -> submit host. Returns the next result."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "remote"}
    )
    assert result["step_id"] == "remote"
    user_input: dict[str, Any] = {"host": host}
    if port is not None:
        user_input["port"] = port
    return await hass.config_entries.flow.async_configure(result["flow_id"], user_input)


def grouped(fingerprint: str) -> str:
    return " ".join(fingerprint[i : i + 4] for i in range(0, 64, 4))
