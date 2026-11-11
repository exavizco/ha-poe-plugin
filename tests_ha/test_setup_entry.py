"""Entry setup on a real Home Assistant: the Lovelace card, the board title.

These tests run the real `_register_frontend` against HA's own http and
lovelace components (the integration depends on both).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.exaviz as exaviz
from custom_components.exaviz.const import DOMAIN

from .local_board import patch_local_board

try:
    from homeassistant.components.lovelace import LOVELACE_DATA
except ImportError:  # HA 2024.12 keeps lovelace data in a plain dict
    LOVELACE_DATA = None

CARD_JS = Path(exaviz.__file__).parent / "www" / "exaviz-cards.js"
CARD_URL = f"/exaviz_static/exaviz-cards.js?v={exaviz._INTEGRATION_VERSION}"
OTHER = {"res_type": "module", "url": "/local/other-card.js"}

floor_has_no_lovelace_data = pytest.mark.xfail(
    LOVELACE_DATA is None,
    strict=True,
    reason="bug: HA 2024.12 has no LOVELACE_DATA, so the card resource is never "
    "registered on the declared floor (__init__.py:90)",
)


@pytest.fixture
def no_frontend_registration():
    """Override the conftest fixture: run the real frontend registration."""
    yield


def _resources(hass):
    """The Lovelace resource collection on either HA layout."""
    if LOVELACE_DATA is not None:
        return hass.data[LOVELACE_DATA].resources
    return hass.data["lovelace"]["resources"]


def _urls(hass) -> list[str]:
    return [item["url"] for item in _resources(hass).async_items()]


async def _setup(hass, title: str = "Exaviz Cruiser") -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, data={}, unique_id="exaviz_cruiser", title=title
    )
    entry.add_to_hass(hass)
    stack, _reader = patch_local_board()
    with stack:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


# --- The card's static path -------------------------------------------------


async def test_card_js_is_served_without_cache_headers(hass, hass_client_no_auth):
    await _setup(hass)
    client = await hass_client_no_auth()
    resp = await client.get("/exaviz_static/exaviz-cards.js")
    assert resp.status == 200
    assert await resp.read() == CARD_JS.read_bytes()
    # The ?v= tag busts the browser cache, so the file itself is not cached.
    assert "Cache-Control" not in resp.headers
    assert hass.data[DOMAIN]["frontend_registered"] is True


async def test_reload_registers_the_static_path_once(hass):
    assert await async_setup_component(hass, "http", {})
    with patch.object(
        hass.http,
        "async_register_static_paths",
        wraps=hass.http.async_register_static_paths,
    ) as register:
        entry = await _setup(hass)
        stack, _reader = patch_local_board()
        with stack:
            assert await hass.config_entries.async_reload(entry.entry_id)
            await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert register.call_count == 1


async def test_missing_www_dir_registers_nothing(hass, hass_client_no_auth, tmp_path):
    fake_init = tmp_path / "exaviz" / "__init__.py"
    with patch.object(exaviz, "Path", lambda _file: fake_init):
        await _setup(hass)
    client = await hass_client_no_auth()
    assert (await client.get("/exaviz_static/exaviz-cards.js")).status == 404
    # Not marked done: a later setup with the files in place may register.
    assert "frontend_registered" not in hass.data[DOMAIN]


async def test_no_static_path_api_warns_and_skips_the_resource(
    hass, hass_client_no_auth, monkeypatch, caplog
):
    import homeassistant.components.http as http

    monkeypatch.delattr(http, "StaticPathConfig")
    await _setup(hass)
    assert "Could not register static path for frontend cards" in caplog.text
    assert hass.data[DOMAIN]["frontend_registered"] is True
    client = await hass_client_no_auth()
    assert (await client.get("/exaviz_static/exaviz-cards.js")).status == 404
    assert CARD_URL not in _urls(hass)


async def test_no_lovelace_data_warns_with_the_manual_step(
    hass, hass_client_no_auth, monkeypatch, caplog
):
    """What every HA 2024.12 user sees; simulated on newer HA."""
    import homeassistant.components.lovelace as lovelace

    # Lovelace itself needs the name while it sets up; hide it afterwards.
    assert await async_setup_component(hass, "lovelace", {})
    monkeypatch.delattr(lovelace, "LOVELACE_DATA", raising=False)
    await _setup(hass)
    assert "Could not auto-register Lovelace resource" in caplog.text
    assert f"Add {CARD_URL} as a resource" in caplog.text
    assert hass.data[DOMAIN]["frontend_registered"] is True
    # The JS is still served; only the resource entry is left to the user.
    client = await hass_client_no_auth()
    assert (await client.get("/exaviz_static/exaviz-cards.js")).status == 200


# --- The Lovelace resource entry --------------------------------------------


@floor_has_no_lovelace_data
async def test_fresh_install_adds_one_versioned_module_resource(hass):
    await _setup(hass)
    items = _resources(hass).async_items()
    assert [(i["url"], i["type"]) for i in items] == [(CARD_URL, "module")]


@floor_has_no_lovelace_data
@pytest.mark.parametrize("current_present", [False, True])
async def test_loaded_resource_list_drops_stale_card_urls(hass, current_present):
    """Old /local/ path, unversioned and older ?v= entries go; others stay."""
    assert await async_setup_component(hass, "lovelace", {})
    resources = _resources(hass)
    stale = [
        "/local/custom_components/exaviz/exaviz-cards.js",
        "/exaviz_static/exaviz-cards.js",
        "/exaviz_static/exaviz-cards.js?v=1.0.0",
    ]
    for url in [OTHER["url"], *stale]:
        await resources.async_create_item({"res_type": "module", "url": url})
    if current_present:
        current = await resources.async_create_item(
            {"res_type": "module", "url": CARD_URL}
        )
    await _setup(hass)
    assert sorted(_urls(hass)) == sorted([OTHER["url"], CARD_URL])
    if current_present:
        # The existing entry is kept, not deleted and re-created.
        assert current["id"] in [i["id"] for i in resources.async_items()]


@floor_has_no_lovelace_data
async def test_restart_with_stored_resources_keeps_one_card_entry(hass, hass_storage):
    hass_storage["lovelace_resources"] = {
        "version": 1,
        "minor_version": 1,
        "key": "lovelace_resources",
        "data": {
            "items": [
                {"id": "current", "type": "module", "url": CARD_URL},
                # A repeat that 1.4.0 and earlier added on a restart.
                {"id": "repeat", "type": "module", "url": CARD_URL},
                {
                    "id": "old",
                    "type": "module",
                    "url": "/exaviz_static/exaviz-cards.js?v=1.0.0",
                },
                {"id": "other", "type": "module", "url": OTHER["url"]},
            ]
        },
    }
    await _setup(hass)
    assert sorted(_urls(hass)) == sorted([OTHER["url"], CARD_URL])
    # The first stored copy is the one kept.
    assert {item["id"] for item in _resources(hass).async_items()} == {"current", "other"}


# --- Board device and title -------------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected"),
    [("Exaviz Unknown", "Exaviz Cruiser"), ("Garage", "Garage")],
)
async def test_unknown_title_is_fixed_once_the_board_is_known(hass, title, expected):
    entry = await _setup(hass, title=title)
    assert entry.title == expected
    registry = dr.async_get(hass)
    (device,) = [
        d
        for d in dr.async_entries_for_config_entry(registry, entry.entry_id)
        if (DOMAIN, entry.entry_id) in d.identifiers
    ]
    assert device.name == "Exaviz Cruiser"
    assert device.model == "Cruiser Carrier Board"
    assert device.sw_version == exaviz._INTEGRATION_VERSION
