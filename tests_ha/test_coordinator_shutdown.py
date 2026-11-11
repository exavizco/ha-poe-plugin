"""Unloading an entry runs Home Assistant's own coordinator shutdown.

Removing the last entity already cancels a refresh waiting in the request
cooldown. What only the shutdown stops is a refresh requested after the
unload, such as a port action that finishes while its entry unloads (the
switch requests a refresh in a `finally`).
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from .remote_helpers import remote_entry


@pytest.mark.parametrize("unload", [False, True])
async def test_refresh_requested_after_unload_does_not_poll(
    hass, board, freezer, unload
):
    entry = remote_entry(board)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    # Past the 10 s request cooldown left by setup, short of the 30 s interval.
    freezer.tick(timedelta(seconds=15))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    if unload:
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.NOT_LOADED
    count = len(board.seen("GET", "/poe/ports"))

    await coordinator.async_request_refresh()
    await coordinator.async_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)

    # Positive control (loaded): both requests do poll the board.
    expected = count if unload else count + 2
    assert len(board.seen("GET", "/poe/ports")) == expected
