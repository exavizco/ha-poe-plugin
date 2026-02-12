from __future__ import annotations

"""Exaviz PoE Management Integration for Home Assistant."""

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

# PoE-only platforms: sensor, switch, binary_sensor, button
PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.SWITCH, 
    Platform.BINARY_SENSOR,
    Platform.BUTTON
]


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

    # Set up the coordinator (detects local board and PoE systems)
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

    # Register static path AND Lovelace resource for the bundled frontend
    # cards (once per HA session).  Two steps are needed:
    #   1. async_register_static_paths  → makes the JS file accessible via HTTP
    #   2. Lovelace resource creation   → tells HA to load the JS module in the
    #      browser, so the card appears in the card picker automatically.
    if "frontend_registered" not in hass.data[DOMAIN]:
        www_path = Path(__file__).parent / "www"
        if www_path.is_dir():
            resource_url = f"{FRONTEND_URL_BASE}/exaviz-cards.js"
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
                resource_url = None  # Skip Lovelace registration too

            # Register as a Lovelace resource so the browser loads the JS
            # module automatically — no manual resource URL step for users.
            if resource_url is not None:
                try:
                    from homeassistant.components.lovelace import (  # noqa: E402
                        ResourceStorageCollection,
                    )

                    resources = hass.data.get("lovelace", {}).get("resources")
                    if isinstance(resources, ResourceStorageCollection):
                        existing = [
                            r
                            for r in resources.async_items()
                            if r.get("url") == resource_url
                        ]
                        if not existing:
                            await resources.async_create_item(
                                {"res_type": "module", "url": resource_url}
                            )
                            _LOGGER.info(
                                "Exaviz frontend resource auto-registered: %s",
                                resource_url,
                            )
                        else:
                            _LOGGER.debug(
                                "Exaviz frontend resource already registered: %s",
                                resource_url,
                            )
                    else:
                        _LOGGER.info(
                            "Lovelace resources not using storage mode — "
                            "add %s as a Lovelace resource (type: module) manually",
                            resource_url,
                        )
                except (ImportError, AttributeError, KeyError) as exc:
                    _LOGGER.warning(
                        "Could not auto-register Lovelace resource: %s. "
                        "Add %s as a resource (type: module) manually in "
                        "Settings > Dashboards > Resources",
                        exc,
                        resource_url,
                    )

            hass.data[DOMAIN]["frontend_registered"] = True

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
        sw_version="1.0.0",
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Set up PoE management services (only once)
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
