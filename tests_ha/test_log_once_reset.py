"""#43: warn-once log state goes with the entry that recorded it.

Home Assistant calls async_unload_entry only for a loaded entry. An entry
removed while its setup is still retrying skips it, so removal has to forget
the warnings too, or the next entry stays silent about the same fault.
"""
from __future__ import annotations

import logging

import pytest
from homeassistant.config_entries import ConfigEntryState

from custom_components.exaviz import poe_readers, remote
from tests.fake_board import case

from .remote_helpers import remote_entry

SKIPPED = "Skipping board port 'uplink': unknown name or address"


@pytest.fixture(autouse=True)
def _clean_log_once_state(monkeypatch):
    poe_readers._unavailable.clear()
    monkeypatch.setattr(remote, "_WARNED_PORT_NAMES", set())
    yield
    poe_readers._unavailable.clear()


async def test_removing_an_entry_still_retrying_setup_forgets_its_warnings(
    hass, board, caplog
):
    # Startup window: no port count yet, so setup retries, and one port has a
    # name the plugin does not know, which is warned about once.
    startup = case("board")
    del startup["body"]["total_poe_ports"]
    board.reply("GET", "/board", startup)
    ports = case("poe_ports")
    ports["body"]["ports"].append(dict(ports["body"]["ports"][0], name="uplink"))
    board.reply("GET", "/poe/ports", ports)
    entry = remote_entry(board)
    entry.add_to_hass(hass)
    with caplog.at_level(logging.WARNING, logger=remote._LOGGER.name):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert [r.getMessage() for r in caplog.records].count(SKIPPED) == 1
    poe_readers._log_unavailable("/proc/pse", "Failed to read /proc/pse: %s", "x")

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert remote._WARNED_PORT_NAMES == set()
    assert poe_readers._unavailable == set()
