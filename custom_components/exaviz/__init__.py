from __future__ import annotations

"""Exaviz PoE Management Integration for Home Assistant."""

import json
import logging
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr

from .board_detector import check_prerequisites
from .const import DOMAIN
from .coordinator import ExavizDataUpdateCoordinator
from .services import async_setup_services, async_unload_services

# URL prefix for the bundled Lovelace frontend cards.
# Users add this as a Lovelace resource: /exaviz_static/exaviz-cards.js
FRONTEND_URL_BASE = "/exaviz_static"

_LOGGER = logging.getLogger(__name__)

# Read integration version from manifest.json once at import time.
# Used to cache-bust the Lovelace JS resource URL on upgrades.
_manifest_path = Path(__file__).parent / "manifest.json"
try:
    _INTEGRATION_VERSION: str = json.loads(_manifest_path.read_text()).get("version", "0")
except Exception:  # pragma: no cover
    _INTEGRATION_VERSION = "0"

# PoE-only platforms: sensor, switch, binary_sensor, button
PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.SWITCH, 
    Platform.BINARY_SENSOR,
    Platform.BUTTON
]


async def _register_frontend(hass: HomeAssistant) -> None:
    """Register bundled Lovelace frontend cards (once per HA session).

    1. Register a static HTTP path so the JS file is accessible.
    2. Create a Lovelace resource entry so HA loads the module in the browser.
    """
    if "frontend_registered" in hass.data.get(DOMAIN, {}):
        return

    www_path = Path(__file__).parent / "www"
    if not www_path.is_dir():
        return

    # Versioned URL — the ?v= parameter changes each release so browsers
    # always fetch the new JS instead of serving a stale cached copy.
    resource_url = f"{FRONTEND_URL_BASE}/exaviz-cards.js?v={_INTEGRATION_VERSION}"
    resource_url_base = f"{FRONTEND_URL_BASE}/exaviz-cards.js"

    # Step 1: static HTTP path (cache_headers=False → no Expires/Cache-Control)
    try:
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(FRONTEND_URL_BASE, str(www_path), False)]
        )
    except (ImportError, AttributeError) as exc:
        _LOGGER.warning(
            "Could not register static path for frontend cards: %s. "
            "Manually copy www/ contents to /config/www/community/exaviz/",
            exc,
        )
        hass.data[DOMAIN]["frontend_registered"] = True
        return

    # Step 2: Lovelace resource (storage mode only)
    # Replace any stale entry (unversioned URL or an older ?v= tag) with the
    # current versioned URL so the browser always fetches the latest JS.
    try:
        from homeassistant.components.lovelace import LOVELACE_DATA
        from homeassistant.components.lovelace.resources import ResourceStorageCollection

        lovelace_data = hass.data.get(LOVELACE_DATA)
        resources = getattr(lovelace_data, "resources", None) if lovelace_data else None

        if isinstance(resources, ResourceStorageCollection):
            all_items = resources.async_items()
            # Any entry pointing at our JS file, regardless of version param
            stale = [
                r for r in all_items
                if r.get("url", "").split("?")[0] == resource_url_base
                and r.get("url") != resource_url
            ]
            exact = [r for r in all_items if r.get("url") == resource_url]

            # Remove stale entries (old version or unversioned)
            for item in stale:
                await resources.async_delete_item(item["id"])
                _LOGGER.info(
                    "Removed stale Exaviz Lovelace resource: %s", item.get("url")
                )

            if not exact:
                await resources.async_create_item({"res_type": "module", "url": resource_url})
                _LOGGER.info("Exaviz frontend resource registered: %s", resource_url)
            else:
                _LOGGER.debug("Exaviz frontend resource up to date: %s", resource_url)
        else:
            _LOGGER.info(
                "Lovelace not using storage mode — add %s as a resource (type: module) manually",
                resource_url,
            )
    except (ImportError, AttributeError, KeyError) as exc:
        _LOGGER.warning(
            "Could not auto-register Lovelace resource: %s. "
            "Add %s as a resource (type: module) manually in Settings > Dashboards > Resources",
            exc,
            resource_url,
        )

    hass.data[DOMAIN]["frontend_registered"] = True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Exaviz PoE Management from a config entry."""
    _LOGGER.debug("Setting up Exaviz PoE integration for entry: %s", entry.entry_id)

    # Check that required Exaviz host packages are installed.
    # Inside Docker, dpkg-query sees the container's packages (not the
    # host's), so a failure here is only a warning — board detection
    # itself is the real gate.
    prereqs = await check_prerequisites()
    if not prereqs["all_ok"]:
        _LOGGER.warning(
            "Exaviz prerequisites not met — missing: %s. "
            "The integration requires exaviz-dkms and exaviz-netplan "
            "on the host OS.  See https://exa-pedia.com/docs/software/apt-repository/",
            ", ".join(prereqs["missing"]),
        )

    coordinator = ExavizDataUpdateCoordinator(hass, entry)

    if not await coordinator.async_setup():
        _LOGGER.error("Could not detect PoE systems on local board")
        raise ConfigEntryNotReady("Board detection failed")

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as ex:
        _LOGGER.error("Unable to read PoE data from local board: %s", ex)
        raise ConfigEntryNotReady from ex

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await _register_frontend(hass)

    # Register the parent board device BEFORE forwarding platforms.
    # Child entities reference this device via via_device=(DOMAIN, entry.entry_id).
    # Creating it here avoids a race condition where child platforms load before
    # the sensor platform creates the ExavizServerStatusSensor device.
    board_type = coordinator.board_type
    board_name = board_type.value.title() if board_type else "Unknown"

    # Update the config entry title if board detection now succeeds but the
    # title was created with "Unknown" (e.g., Docker first-boot before all
    # volume mounts were in place, or Tier 2/3 detection improved).
    entry_title = getattr(entry, "title", "") or ""
    if board_name != "Unknown" and isinstance(entry_title, str) and "Unknown" in entry_title:
        new_title = f"Exaviz {board_name}"
        _LOGGER.info(
            "Updating integration title from '%s' to '%s' "
            "(board type resolved after initial setup)",
            entry.title, new_title,
        )
        hass.config_entries.async_update_entry(entry, title=new_title)
    device_reg = dr.async_get(hass)
    device_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"Exaviz {board_name}",
        manufacturer="Exaviz (by Axzez LLC)",
        model=f"{board_name} Carrier Board",
        sw_version=_INTEGRATION_VERSION,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if not hass.services.has_service(DOMAIN, "refresh_data"):
        await async_setup_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading Exaviz PoE integration for entry: %s", entry.entry_id)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)

        # Clean up coordinator resources
        if hasattr(coordinator, "async_shutdown"):
            await coordinator.async_shutdown()

        # Remove services if this was the last entry
        if not hass.data[DOMAIN]:
            await async_unload_services(hass)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
