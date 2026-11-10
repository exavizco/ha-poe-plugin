"""T-30: golden snapshot of every entity for a local Cruiser (1.3.1 behaviour).

Recorded against unchanged code. Later commits must leave it equal.
Set EXAVIZ_RECORD_GOLDEN=1 to re-record.
"""

import json
import os
from pathlib import Path

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.exaviz.const import DOMAIN

from .local_board import patch_local_board

GOLDEN = Path(__file__).parent / "golden"
VOLATILE = {"plugin_version", "last_updated"}
# HA composes friendly_name differently across versions (2026.x prepends the
# device name); original_name is what the plugin itself sets.
HA_COMPOSED = {"friendly_name"}


def snapshot(hass) -> list[dict]:
    registry = er.async_get(hass)
    rows = []
    for entry in sorted(registry.entities.values(), key=lambda e: e.entity_id):
        if entry.platform != DOMAIN:
            continue
        state = hass.states.get(entry.entity_id)
        attrs = {
            k: v
            for k, v in (state.attributes if state else {}).items()
            if k not in VOLATILE | HA_COMPOSED
        }
        rows.append(
            {
                "entity_id": entry.entity_id,
                "unique_id": entry.unique_id,
                "original_name": entry.original_name,
                "platform": entry.domain,
                "state": state.state if state else None,
                "available": bool(state) and state.state != "unavailable",
                "attributes": json.loads(json.dumps(attrs, default=str)),
            }
        )
    return rows


def local_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        data={},
        unique_id="exaviz_cruiser",
        title="Exaviz Cruiser",
        entry_id="golden_entry",
    )


async def setup_local_entry(hass) -> MockConfigEntry:
    """Set up a local entry. Callers patch the board for later polls."""
    entry = local_entry()
    entry.add_to_hass(hass)
    stack, _reader = patch_local_board()
    with stack:
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def setup_local(hass, after_setup=None):
    entry = local_entry()
    entry.add_to_hass(hass)
    stack, reader = patch_local_board()
    with stack:
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        if after_setup:
            await after_setup(hass, entry, reader)
        rows = snapshot(hass)
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
    return entry, rows


def check_golden(name: str, rows: list[dict]) -> None:
    path = GOLDEN / f"{name}.json"
    if os.environ.get("EXAVIZ_RECORD_GOLDEN"):
        GOLDEN.mkdir(exist_ok=True)
        path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n")
    assert rows == json.loads(path.read_text())


async def test_local_cruiser_golden(hass, freezer):
    entry, rows = await setup_local(hass)
    assert len(rows) > 8 * 4
    check_golden("local_cruiser", rows)


async def test_local_cruiser_poll_failure_golden(hass, freezer):
    """A good first poll, then the reader fails: records availability."""

    async def fail_poll(hass, entry, reader):
        reader.side_effect = OSError("serial gone")
        await hass.data[DOMAIN][entry.entry_id].async_refresh()
        await hass.async_block_till_done()

    entry, rows = await setup_local(hass, fail_poll)
    assert len(rows) > 8 * 4
    assert any(not r["available"] for r in rows)
    check_golden("local_cruiser_poll_failure", rows)


async def test_port_device_links_to_the_board_device(hass, freezer, caplog):
    """No deprecated via_device report, on the floor or on current HA."""
    entry, _rows = await setup_local(hass)
    devices = {
        identifier: device
        for device in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
        for identifier in device.identifiers
    }
    board = devices[(DOMAIN, entry.entry_id)]
    port = devices[(DOMAIN, f"{entry.entry_id}_onboard")]
    assert port.via_device_id == board.id
    assert "via_device" not in caplog.text
