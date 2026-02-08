"""PoE Services for Exaviz Integration."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Service schemas
REFRESH_DATA_SCHEMA = vol.Schema({})

POE_PORT_CONTROL_SCHEMA = vol.Schema({
    vol.Required("entity_id"): cv.string,
})

POE_PORT_CONTROL_WITH_ACTION_SCHEMA = vol.Schema({
    vol.Required("entity_id"): cv.string,
    vol.Optional("action", default="toggle"): vol.In(
        ["turn_on", "turn_off", "toggle"]
    ),
})

RESET_PORT_SCHEMA = vol.Schema({
    vol.Required("entity_id"): cv.string,
})


async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up services for Exaviz integration."""

    async def refresh_data(call: ServiceCall) -> None:
        """Refresh integration data from all coordinators."""
        _LOGGER.info("Refreshing Exaviz integration data")
        for coordinator in hass.data.get(DOMAIN, {}).values():
            if hasattr(coordinator, "async_request_refresh"):
                await coordinator.async_request_refresh()

    async def turn_on_port(call: ServiceCall) -> None:
        """Turn on a PoE port."""
        entity_id = call.data["entity_id"]
        await _control_poe_port(hass, entity_id, "turn_on")

    async def turn_off_port(call: ServiceCall) -> None:
        """Turn off a PoE port."""
        entity_id = call.data["entity_id"]
        await _control_poe_port(hass, entity_id, "turn_off")

    async def toggle_port(call: ServiceCall) -> None:
        """Toggle a PoE port."""
        entity_id = call.data["entity_id"]
        await _control_poe_port(hass, entity_id, "toggle")

    async def control_port(call: ServiceCall) -> None:
        """Control a PoE port with specified action."""
        entity_id = call.data["entity_id"]
        action = call.data.get("action", "toggle")
        await _control_poe_port(hass, entity_id, action)

    async def reset_port(call: ServiceCall) -> None:
        """Reset a PoE port (power cycle) by pressing its reset button."""
        entity_id = call.data["entity_id"]
        _LOGGER.info("Resetting PoE port: %s", entity_id)

        # Derive the button entity_id from the switch entity_id.
        # switch.onboard_port0 -> button.onboard_port0_reset
        button_entity_id = entity_id.replace("switch.", "button.") + "_reset"

        await hass.services.async_call(
            "button", "press",
            {"entity_id": button_entity_id},
            blocking=True,
        )
        _LOGGER.info("Port reset completed for %s", entity_id)

    # Register services
    hass.services.async_register(
        DOMAIN, "refresh_data", refresh_data, schema=REFRESH_DATA_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "turn_on_port", turn_on_port, schema=POE_PORT_CONTROL_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "turn_off_port", turn_off_port, schema=POE_PORT_CONTROL_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "toggle_port", toggle_port, schema=POE_PORT_CONTROL_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "control_port", control_port,
        schema=POE_PORT_CONTROL_WITH_ACTION_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, "reset_port", reset_port, schema=RESET_PORT_SCHEMA
    )


async def _control_poe_port(
    hass: HomeAssistant, entity_id: str, action: str,
) -> None:
    """Control a PoE port by delegating to the HA switch service.

    This replaces the old VMS-client approach. The switch entities handle
    all hardware-specific logic (ip link set, /proc/pse, etc.) so services
    only need to call the standard HA switch domain.
    """
    _LOGGER.debug("PoE port control: %s -> %s", entity_id, action)

    # Ensure the entity_id is a switch
    if not entity_id.startswith("switch."):
        entity_id = entity_id.replace("sensor.", "switch.").split("_current")[0]
        entity_id = entity_id.replace("binary_sensor.", "switch.").split("_powered")[0]
        entity_id = entity_id.replace("binary_sensor.", "switch.").split("_plug")[0]

    service = action  # turn_on, turn_off, toggle are HA switch services
    await hass.services.async_call(
        "switch", service,
        {"entity_id": entity_id},
        blocking=True,
    )
    _LOGGER.info("PoE port %s: %s completed", entity_id, action)


async def async_unload_services(hass: HomeAssistant) -> None:
    """Unload services for Exaviz integration."""
    for service_name in (
        "refresh_data", "turn_on_port", "turn_off_port",
        "toggle_port", "control_port", "reset_port",
    ):
        hass.services.async_remove(DOMAIN, service_name)
