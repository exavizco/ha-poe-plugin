"""A port reset that is running when Home Assistant stops or the entry unloads.

The reset cuts power, waits, then turns the port back on. Home Assistant
must not finish stopping, or finish unloading the entry, while a reset still
has the port off: the port would stay off until someone turns it on.
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import CoreState
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.exaviz.const import DOMAIN
from custom_components.exaviz.switch import ExavizPoEPortSwitch

from .local_board import patch_local_board

# poe1 is ESP32 PSE 1, port 1 on a Cruiser.
FULL_RESET = ["disable-port 1 1", "poe1 down", "poe1 up", "enable-port 1 1"]


class SlowLinkHardware:
    """Records port commands; taking a link down takes a moment.

    The pause stands in for the reset's own wait with the power off, which
    the test cannot shorten without patching asyncio.sleep for everyone.
    """

    def __init__(self, hang_link: bool = False) -> None:
        self.calls: list[str] = []
        self.power_off = asyncio.Event()
        self.hang_link = hang_link

    async def send(self, command: str) -> bool:
        self.calls.append(command)
        # A real write runs a subprocess, so it always yields for a while.
        await asyncio.sleep(0.05)
        return True

    async def link(self, interface: str, action: str) -> bool:
        self.calls.append(f"{interface} {action}")
        if self.hang_link:
            self.power_off.set()
            await asyncio.Event().wait()
        if action == "down":
            self.power_off.set()
            await asyncio.sleep(0.3)
        return True


async def _setup(hass, hardware: SlowLinkHardware) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, data={}, unique_id="exaviz_cruiser", entry_id="local_entry"
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _patched(hardware: SlowLinkHardware):
    stack, _reader = patch_local_board()

    async def send(command: str) -> bool:
        # Looked up per call, so a test can swap hardware.send.
        return await hardware.send(command)

    stack.enter_context(
        patch.object(ExavizPoEPortSwitch, "_send_esp32_command", side_effect=send)
    )
    stack.enter_context(
        patch.object(ExavizPoEPortSwitch, "_run_ip_link", side_effect=hardware.link)
    )
    # The 3 s wait with the power off, kept short. Patched on the button
    # module's own name for the sleep, not on asyncio.
    stack.enter_context(
        patch("custom_components.exaviz.button.RESET_POWER_OFF_SECONDS", 0)
    )
    return stack


async def test_stop_waits_for_a_reset_started_by_a_script(hass, caplog):
    hardware = SlowLinkHardware()
    with _patched(hardware):
        await _setup(hass, hardware)
        assert await async_setup_component(
            hass,
            "script",
            {
                "script": {
                    "reset_camera": {
                        "sequence": [
                            {
                                "action": "button.press",
                                "target": {"entity_id": "button.onboard_port1_reset"},
                            }
                        ]
                    }
                }
            },
        )
        await hass.services.async_call("script", "turn_on", {"entity_id": "script.reset_camera"})
        await hardware.power_off.wait()

        # Stopping cancels the script, and with it the press.
        await hass.async_stop()

        assert hardware.calls == FULL_RESET
        # The reset ran to its end. Cancelling it at the last stop stage
        # also sends these commands, but with only 0.1 s to do it.
        assert "Successfully reset PoE port poe1" in caplog.text
        assert "still running after final writes" not in caplog.text


async def test_unload_waits_for_a_running_reset(hass, caplog):
    hardware = SlowLinkHardware()
    with _patched(hardware):
        entry = await _setup(hass, hardware)
        press = hass.async_create_task(
            hass.services.async_call(
                "button", "press", {"entity_id": "button.onboard_port1_reset"}, blocking=True
            )
        )
        await hardware.power_off.wait()

        assert await hass.config_entries.async_unload(entry.entry_id)

        assert entry.state is ConfigEntryState.NOT_LOADED
        assert hardware.calls == FULL_RESET
        assert "Successfully reset PoE port poe1" in caplog.text
        await press


async def test_stop_waits_for_an_older_reset_still_running(hass, caplog):
    """A cancelled press frees the button, so a second reset of the same
    port can start and end while the first still has the power off."""
    hardware = SlowLinkHardware()
    with _patched(hardware):
        await _setup(hass, hardware)
        first = hass.async_create_task(
            hass.services.async_call(
                "button", "press", {"entity_id": "button.onboard_port1_reset"}, blocking=True
            )
        )
        await hardware.power_off.wait()
        first.cancel()
        await asyncio.sleep(0)

        # The second reset fails at once: the controller does not take the
        # power cut. It ends while the first is still waiting.
        real_send = hardware.send

        async def refuse_disable(command: str) -> bool:
            if command.startswith("disable-port"):
                hardware.calls.append(command)
                return False
            return await real_send(command)

        hardware.send = refuse_disable
        with pytest.raises(HomeAssistantError, match="did not disable port poe1"):
            await hass.services.async_call(
                "button", "press", {"entity_id": "button.onboard_port1_reset"},
                blocking=True,
            )
        assert "Successfully reset PoE port poe1" not in caplog.text

        await hass.async_stop()

        assert "Successfully reset PoE port poe1" in caplog.text
        assert "still running after final writes" not in caplog.text


async def test_stop_turns_power_back_on_for_a_hung_reset(hass, caplog):
    """A reset stuck in `ip link` holds the stop only for the bounded wait.
    It is then cancelled while the stop still waits, and its cancel path
    turns the power on before it tries the (also stuck) link."""
    hardware = SlowLinkHardware(hang_link=True)
    with _patched(hardware), \
         patch("custom_components.exaviz.button.RESET_STOP_WAIT_SECONDS", 0.2):
        await _setup(hass, hardware)
        stage_at_power_on: list[CoreState] = []
        real_send = hardware.send

        async def send(command: str) -> bool:
            if command.startswith("enable-port"):
                stage_at_power_on.append(hass.state)
            return await real_send(command)

        hardware.send = send
        press = hass.async_create_task(
            hass.services.async_call(
                "button", "press", {"entity_id": "button.onboard_port1_reset"}, blocking=True
            )
        )
        await hardware.power_off.wait()
        press.cancel()

        started = time.monotonic()
        await hass.async_stop()

        # Without the bound, Home Assistant waits 100 s before moving on.
        assert time.monotonic() - started < 10
        assert hardware.calls == [
            "disable-port 1 1", "poe1 down", "enable-port 1 1", "poe1 up",
        ]
        # Turned on while the stop waited for the listener, not in the
        # last stage's 0.1 s.
        assert stage_at_power_on == [CoreState.stopping]
        assert "Reset of PoE port onboard:1 is stuck" in caplog.text

        # The cycle is still stuck in `ip link up`, with the power on. At
        # exit the asyncio runner cancels what is left; do that here.
        stuck = [t for t in asyncio.all_tasks() if t.get_name().startswith("reset PoE port")]
        assert len(stuck) == 1
        stuck[0].cancel()
        await asyncio.wait(stuck)


class HungLinkDownHardware(SlowLinkHardware):
    """Taking the link down never returns; bringing it up works."""

    async def link(self, interface: str, action: str) -> bool:
        self.calls.append(f"{interface} {action}")
        if action == "down":
            self.power_off.set()
            await asyncio.Event().wait()
        return True


async def test_unload_turns_power_back_on_for_a_hung_reset(hass, caplog):
    """Unload waits 10 s for the entry's tasks and then leaves them running.
    A reset stuck in `ip link down` would then never send enable-port, so
    the unload cancels it and waits for the power to come back."""
    hardware = HungLinkDownHardware()
    with _patched(hardware), \
         patch("custom_components.exaviz.button.RESET_STOP_WAIT_SECONDS", 0.2):
        entry = await _setup(hass, hardware)
        press = hass.async_create_task(
            hass.services.async_call(
                "button", "press", {"entity_id": "button.onboard_port1_reset"}, blocking=True
            )
        )
        await hardware.power_off.wait()

        assert await hass.config_entries.async_unload(entry.entry_id)

        assert entry.state is ConfigEntryState.NOT_LOADED
        assert hardware.calls == [
            "disable-port 1 1", "poe1 down", "enable-port 1 1", "poe1 up",
        ]
        assert "Reset of PoE port onboard:1 is stuck" in caplog.text
        assert "did not complete in time" not in caplog.text
        with pytest.raises(asyncio.CancelledError):
            await press


class SlowLinkDownHardware(SlowLinkHardware):
    """Taking the link down takes longer than the stop needs to reach its
    last stage."""

    async def link(self, interface: str, action: str) -> bool:
        result = await super().link(interface, action)
        if action == "down":
            await asyncio.sleep(1)
        return result


async def test_stop_during_an_unload_waits_for_the_reset(hass):
    """The stop listener stays until the unload's own wait is over, so a
    stop that starts while the unload waits still holds for the reset."""
    hardware = SlowLinkDownHardware()
    with _patched(hardware):
        entry = await _setup(hass, hardware)
        stage_at_power_on: list[CoreState] = []
        real_send = hardware.send

        async def send(command: str) -> bool:
            if command.startswith("enable-port"):
                stage_at_power_on.append(hass.state)
            return await real_send(command)

        hardware.send = send
        press = hass.async_create_task(
            hass.services.async_call(
                "button", "press", {"entity_id": "button.onboard_port1_reset"}, blocking=True
            )
        )
        await hardware.power_off.wait()
        unload = hass.async_create_task(hass.config_entries.async_unload(entry.entry_id))
        await asyncio.sleep(0.05)
        assert not unload.done()

        await hass.async_stop()

        assert hardware.calls == FULL_RESET
        # Not in the last stage's 0.1 s.
        assert stage_at_power_on == [CoreState.stopping]
        await asyncio.wait([press, unload])


async def test_stop_during_an_unload_cancels_a_hung_reset_once(hass, caplog):
    """The unload has already cancelled the stuck cycle, so the stop does
    not wait for it all over again or cancel it a second time."""
    hardware = SlowLinkHardware(hang_link=True)
    with _patched(hardware), \
         patch("custom_components.exaviz.button.RESET_STOP_WAIT_SECONDS", 0.2):
        entry = await _setup(hass, hardware)
        press = hass.async_create_task(
            hass.services.async_call(
                "button", "press", {"entity_id": "button.onboard_port1_reset"}, blocking=True
            )
        )
        await hardware.power_off.wait()
        unload = hass.async_create_task(hass.config_entries.async_unload(entry.entry_id))
        await asyncio.sleep(0.05)

        await hass.async_stop()

        assert hardware.calls == [
            "disable-port 1 1", "poe1 down", "enable-port 1 1", "poe1 up",
        ]
        assert caplog.text.count("Reset of PoE port onboard:1 is stuck") == 1

        # The cycle is still stuck in `ip link up`, with the power on.
        stuck = [t for t in asyncio.all_tasks() if t.get_name().startswith("reset PoE port")]
        assert len(stuck) == 1
        stuck[0].cancel()
        await asyncio.wait([*stuck, press, unload])
