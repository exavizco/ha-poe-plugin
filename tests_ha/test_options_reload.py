"""T-30b: an options change reloads through the config entry state machine."""

from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState

import custom_components.exaviz as exaviz
from custom_components.exaviz.const import CONF_UPDATE_INTERVAL, DOMAIN

from .local_board import patch_local_board
from .test_golden_local import setup_local_entry


async def test_local_options_change_reloads_once_via_state_machine(hass, freezer):
    entry = await setup_local_entry(hass)
    stack, _reader = patch_local_board()
    with (
        stack,
        patch.object(
            exaviz, "async_unload_entry", wraps=exaviz.async_unload_entry
        ) as unload,
        patch.object(
            exaviz, "async_setup_entry", wraps=exaviz.async_setup_entry
        ) as setup,
        patch.object(
            hass.config_entries,
            "async_schedule_reload",
            wraps=hass.config_entries.async_schedule_reload,
        ) as schedule,
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_UPDATE_INTERVAL: 45}
        )
        await hass.async_block_till_done()

        assert unload.call_count == 1
        assert setup.call_count == 1
        schedule.assert_called_once_with(entry.entry_id)
        assert entry.state is ConfigEntryState.LOADED
        coordinator = hass.data[DOMAIN][entry.entry_id]
        assert coordinator.update_interval.total_seconds() == 45

        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
