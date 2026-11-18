"""Local port entities when a port is missing from a poll.

A local port whose read fails comes back as `available: False` and the
coordinator skips it, so that poll has no data for the port.
"""
from __future__ import annotations

from homeassistant.helpers import entity_registry as er

from .local_board import PORT_STATUS, patch_local_board
from .test_golden_local import local_entry, setup_local_entry

POWERED = "binary_sensor.onboard_port2_powered"
PLUGGED = "binary_sensor.onboard_port2_plug"
CURRENT = "sensor.onboard_port2_current"
SWITCH = "switch.onboard_port2"
RESET = "button.onboard_port2_reset"
PORT2 = (POWERED, PLUGGED, CURRENT, SWITCH, RESET)
GONE = {**PORT_STATUS, "poe2": {**PORT_STATUS["poe2"], "available": False}}


async def _poll(hass, entry, port_status) -> None:
    stack, reader = patch_local_board()
    reader.return_value = port_status
    with stack:
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()


async def test_port_that_stops_reading_goes_unavailable(hass):
    entry = await setup_local_entry(hass)
    # Positive control: port 2 has a powered camera on it.
    assert hass.states.get(POWERED).state == "on"
    assert hass.states.get(PLUGGED).state == "on"
    assert hass.states.get(CURRENT).state == "4.5"
    assert hass.states.get(CURRENT).attributes["device_ip"] == "192.168.1.50"

    await _poll(hass, entry, GONE)

    assert entry.runtime_data.last_update_success
    for entity_id in PORT2:
        state = hass.states.get(entity_id)
        assert state.state == "unavailable", entity_id
        assert "port_number" not in state.attributes
        assert "device_ip" not in state.attributes
    # The other ports are untouched.
    assert hass.states.get("binary_sensor.onboard_port3_powered").state == "off"
    assert hass.states.get("sensor.onboard_port3_current").state == "0.0"

    await _poll(hass, entry, PORT_STATUS)
    assert hass.states.get(POWERED).state == "on"
    assert hass.states.get(CURRENT).state == "4.5"
    assert hass.states.get(CURRENT).attributes["port_number"] == 2
    assert hass.states.get(SWITCH).state == "on"
    assert hass.states.get(RESET).state != "unavailable"

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_port_unreadable_at_setup_gets_entities_when_it_reads(hass, caplog):
    entry = local_entry()
    entry.add_to_hass(hass)
    stack, reader = patch_local_board()
    reader.return_value = GONE
    with stack:
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    registry = er.async_get(hass)
    # Positive control: port 3 read and has its entities; port 2 has none.
    assert hass.states.get("sensor.onboard_port3_current") is not None
    for entity_id in PORT2:
        assert registry.async_get(entity_id) is None, entity_id

    await _poll(hass, entry, PORT_STATUS)

    assert hass.states.get(POWERED).state == "on"
    assert hass.states.get(CURRENT).state == "4.5"
    assert hass.states.get(SWITCH).state == "on"
    for entity_id in PORT2:
        assert registry.async_get(entity_id).unique_id.startswith(
            f"{entry.entry_id}_onboard_port2"
        ), entity_id
    # Each port's entities are added once: HA logs a second add of the same
    # unique id as an error and drops it.
    await _poll(hass, entry, PORT_STATUS)
    assert "does not generate unique IDs" not in caplog.text

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
