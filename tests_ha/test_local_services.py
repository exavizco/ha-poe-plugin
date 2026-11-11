"""exaviz.* actions and local port control on a real Home Assistant.

A patched local Cruiser (local_board.py) is set up; the ESP32 serial
command and `ip link` helpers are replaced by recorders, so each test
checks which hardware commands an action produced.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.exaviz.const import DOMAIN
from custom_components.exaviz.switch import ExavizPoEPortSwitch

from .local_board import patch_local_board


class Hardware:
    """Records ESP32 commands and ip link calls in order."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.esp32_error: Exception | None = None

    async def send(self, command: str) -> bool:
        if self.esp32_error:
            raise self.esp32_error
        self.calls.append(command)
        return True

    async def link(self, interface: str, action: str) -> bool:
        self.calls.append(f"{interface} {action}")
        return True


@pytest.fixture
async def local(hass) -> AsyncIterator[tuple[MockConfigEntry, AsyncMock, Hardware]]:
    """A loaded local Cruiser entry with recorded port hardware."""
    hardware = Hardware()
    real_sleep = asyncio.sleep

    async def no_reset_wait(delay, *args, **kwargs):
        # The reset button waits 3 s between power off and on.
        return await real_sleep(0 if delay == 3 else delay, *args, **kwargs)

    stack, reader = patch_local_board()
    with stack, \
         patch.object(ExavizPoEPortSwitch, "_send_esp32_command", side_effect=hardware.send), \
         patch.object(ExavizPoEPortSwitch, "_run_ip_link", side_effect=hardware.link), \
         patch("custom_components.exaviz.button.asyncio.sleep", no_reset_wait):
        entry = MockConfigEntry(
            domain=DOMAIN, data={}, unique_id="exaviz_cruiser", entry_id="local_entry"
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry, reader, hardware
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def action(hass, service: str, **data) -> None:
    await hass.services.async_call(DOMAIN, service, data, blocking=True)
    await hass.async_block_till_done()


# Port mapping on a Cruiser: poe0-3 are ESP32 PSE 1, poe4-7 are PSE 0.


async def test_turn_on_and_off_port_actions(hass, local):
    _entry, _reader, hw = local
    await action(hass, "turn_off_port", entity_id="switch.onboard_port1")
    await action(hass, "turn_on_port", entity_id="switch.onboard_port1")
    assert hw.calls == [
        "disable-port 1 1", "poe1 down",
        "poe1 up", "enable-port 1 1",
    ]


async def test_toggle_port_flips_the_current_state(hass, local):
    _entry, _reader, hw = local
    # In the fixture poe7 is disabled and poe0 is enabled.
    await action(hass, "toggle_port", entity_id="switch.onboard_port7")
    await action(hass, "toggle_port", entity_id="switch.onboard_port0")
    assert hw.calls == [
        "poe7 up", "enable-port 0 3",
        "disable-port 1 0", "poe0 down",
    ]


async def test_control_port_with_an_action_and_with_the_default(hass, local):
    _entry, _reader, hw = local
    await action(hass, "control_port", entity_id="switch.onboard_port4", action="turn_off")
    assert hw.calls == ["disable-port 0 0", "poe4 down"]
    hw.calls.clear()
    # No action given: toggle. poe7 starts disabled, so it is turned on.
    await action(hass, "control_port", entity_id="switch.onboard_port7")
    assert hw.calls == ["poe7 up", "enable-port 0 3"]


async def test_port_action_accepts_the_current_sensor_entity(hass, local):
    _entry, _reader, hw = local
    await action(hass, "turn_off_port", entity_id="sensor.onboard_port3_current")
    assert hw.calls == ["disable-port 1 3", "poe3 down"]


@pytest.mark.parametrize("sensor", ["onboard_port3_powered", "onboard_port3_plug"])
async def test_port_action_accepts_a_port_binary_sensor(hass, local, sensor):
    _entry, _reader, hw = local
    await action(hass, "turn_off_port", entity_id=f"binary_sensor.{sensor}")
    assert hw.calls == ["disable-port 1 3", "poe3 down"]


async def test_refresh_data_polls_loaded_entries_only(hass, local):
    _entry, reader, _hw = local
    # A second entry that never loaded has no coordinator to refresh.
    idle = MockConfigEntry(domain=DOMAIN, data={}, unique_id="idle", entry_id="idle")
    idle.add_to_hass(hass)
    polls = reader.await_count
    await action(hass, "refresh_data")
    assert reader.await_count == polls + 1


async def test_unexpected_switch_error_reaches_the_caller(hass, local):
    _entry, _reader, hw = local
    hw.esp32_error = RuntimeError("serial port vanished")
    with pytest.raises(
        HomeAssistantError,
        match="Could not enable PoE port onboard:7: serial port vanished",
    ):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": "switch.onboard_port7"}, blocking=True
        )
    with pytest.raises(
        HomeAssistantError,
        match="Could not disable PoE port onboard:0: serial port vanished",
    ):
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": "switch.onboard_port0"}, blocking=True
        )


async def test_unexpected_reset_error_reaches_the_caller(hass, local):
    _entry, reader, hw = local
    hw.esp32_error = RuntimeError("serial port vanished")
    polls = reader.await_count
    with pytest.raises(
        HomeAssistantError,
        match="Could not reset PoE port onboard:2: serial port vanished",
    ):
        await hass.services.async_call(
            "button", "press", {"entity_id": "button.onboard_port2_reset"}, blocking=True
        )
    await hass.async_block_till_done()
    # The state is refreshed even though the reset failed.
    assert reader.await_count == polls + 1


@pytest.mark.parametrize(
    "entity_id",
    [
        "switch.onboard_port5",
        "sensor.onboard_port5_current",
        "binary_sensor.onboard_port5_powered",
        "binary_sensor.onboard_port5_plug",
    ],
)
async def test_reset_port_action_power_cycles_through_the_button(hass, local, entity_id):
    _entry, _reader, hw = local
    await action(hass, "reset_port", entity_id=entity_id)
    assert hw.calls == ["disable-port 0 1", "poe5 down", "poe5 up", "enable-port 0 1"]
