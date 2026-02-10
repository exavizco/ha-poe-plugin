from __future__ import annotations

"""Exaviz PoE Management Integration for Home Assistant."""

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .coordinator import ExavizDataUpdateCoordinator
from .services import async_setup_services, async_unload_services

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
