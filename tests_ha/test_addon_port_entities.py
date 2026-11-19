"""Add-on board (Interceptor) port entities when a port is missing from a poll.

Same rules as onboard ports (test_port_entities.py): a port the coordinator
skips goes unavailable, and a port first read after setup gets its entities.
Two add-on boards both have ports 0-7, so these tests drop port 2 on the
second board and check port 2 on the first is untouched.
"""
from __future__ import annotations

from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.exaviz.const import DOMAIN

from .local_board import ADDON_STATUS, patch_local_board

BOARDS = ["pse0", "pse1"]
POWERED = "binary_sensor.addon_1_port2_powered"
PLUGGED = "binary_sensor.addon_1_port2_plug"
CURRENT = "sensor.addon_1_port2_current"
# The switch and button of an add-on port are always unavailable (no write
# interface), so only the readings are checked.
READINGS = (POWERED, PLUGGED, CURRENT)
# Port 2 on the second board draws a different power, so a reading taken from
# the wrong board shows.
SECOND = {**ADDON_STATUS, 2: {**ADDON_STATUS[2], "power_watts": 6.37}}
WATTS = {"addon_0_port2": "4.69", "addon_1_port2": "6.37"}


def _read(gone: bool):
    """read_all_addon_ports, with port 2 on pse1 unreadable when `gone`."""

    async def read(pse_id: str, port_count: int = 8):
        if pse_id == "pse0":
            return ADDON_STATUS
        if gone:
            return {**SECOND, 2: {"available": False, "state": "error"}}
        return SECOND

    return read


async def _setup(hass, gone: bool) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        unique_id="exaviz_interceptor",
        title="Exaviz Interceptor",
        entry_id="addon_entry",
    )
    entry.add_to_hass(hass)
    stack, reader = patch_local_board(BOARDS)
    reader.side_effect = _read(gone)
    with stack:
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def _poll(hass, entry, gone: bool) -> None:
    stack, reader = patch_local_board(BOARDS)
    reader.side_effect = _read(gone)
    with stack:
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()


def _assert_reading(hass, prefix: str) -> None:
    assert hass.states.get(f"binary_sensor.{prefix}_powered").state == "on"
    assert hass.states.get(f"binary_sensor.{prefix}_plug").state == "on"
    assert hass.states.get(f"sensor.{prefix}_current").state == WATTS[prefix]


async def test_addon_port_that_stops_reading_goes_unavailable(hass):
    entry = await _setup(hass, gone=False)
    # Positive control: port 2 on both boards has a powered camera.
    _assert_reading(hass, "addon_0_port2")
    _assert_reading(hass, "addon_1_port2")

    await _poll(hass, entry, gone=True)

    assert entry.runtime_data.last_update_success
    for entity_id in READINGS:
        state = hass.states.get(entity_id)
        assert state.state == "unavailable", entity_id
    # The same port number on the other board, and the other ports on this
    # board, still read.
    _assert_reading(hass, "addon_0_port2")
    assert hass.states.get("sensor.addon_1_port3_current").state == "0.0"

    await _poll(hass, entry, gone=False)
    _assert_reading(hass, "addon_1_port2")
    assert hass.states.get(CURRENT).attributes["port_number"] == 2

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_addon_port_unreadable_at_setup_gets_entities_when_it_reads(
    hass, caplog
):
    entry = await _setup(hass, gone=True)
    registry = er.async_get(hass)
    # Positive control: port 2 on the first board read and has its entities;
    # port 2 on the second board has none.
    _assert_reading(hass, "addon_0_port2")
    for entity_id in READINGS:
        assert registry.async_get(entity_id) is None, entity_id

    await _poll(hass, entry, gone=False)

    _assert_reading(hass, "addon_1_port2")
    for entity_id in READINGS:
        assert registry.async_get(entity_id).unique_id.startswith(
            f"{entry.entry_id}_addon_1_port2"
        ), entity_id
    # Each port's entities are added once: HA logs a second add of the same
    # unique id as an error and drops it.
    await _poll(hass, entry, gone=False)
    assert "does not generate unique IDs" not in caplog.text

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
