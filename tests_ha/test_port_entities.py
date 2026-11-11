"""Port entities when a port drops out of the data after setup.

A local port whose sysfs read fails comes back as `available: False`; the
coordinator skips it, so its entities find no port data on the next poll.
"""
from __future__ import annotations

from .local_board import PORT_STATUS, patch_local_board
from .test_golden_local import setup_local_entry

POWERED = "binary_sensor.onboard_port2_powered"
PLUGGED = "binary_sensor.onboard_port2_plug"
CURRENT = "sensor.onboard_port2_current"


async def _poll(hass, entry, port_status) -> None:
    stack, reader = patch_local_board()
    reader.return_value = port_status
    with stack:
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()


async def test_port_that_stops_reading_loses_state_and_attributes(hass):
    entry = await setup_local_entry(hass)
    # Positive control: port 2 has a powered camera on it.
    assert hass.states.get(POWERED).state == "on"
    assert hass.states.get(PLUGGED).state == "on"
    assert hass.states.get(CURRENT).attributes["device_ip"] == "192.168.1.50"

    gone = {**PORT_STATUS, "poe2": {**PORT_STATUS["poe2"], "available": False}}
    await _poll(hass, entry, gone)

    assert entry.runtime_data.last_update_success
    assert hass.states.get(POWERED).state == "unknown"
    assert hass.states.get(PLUGGED).state == "unknown"
    for entity_id in (POWERED, PLUGGED, CURRENT):
        attrs = hass.states.get(entity_id).attributes
        assert "port_number" not in attrs
        assert "device_ip" not in attrs
    # The other ports are untouched.
    assert hass.states.get("binary_sensor.onboard_port3_powered").state == "off"

    await _poll(hass, entry, PORT_STATUS)
    assert hass.states.get(POWERED).state == "on"
    assert hass.states.get(CURRENT).attributes["port_number"] == 2

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
