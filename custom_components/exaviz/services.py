"""PoE Services for Exaviz Integration."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
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
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.state is ConfigEntryState.LOADED:
                await entry.runtime_data.async_request_refresh()

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

        # switch.onboard_port0 (or one of its sensors) -> button.onboard_port0_reset
        button_entity_id = (
            _port_switch_id(entity_id).replace("switch.", "button.", 1) + "_reset"
        )

        _require_available(hass, button_entity_id)
        await hass.services.async_call(
            "button", "press",
            {"entity_id": button_entity_id},
            blocking=True,
        )
        _LOGGER.info("Port reset completed for %s", entity_id)

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


def _require_available(hass: HomeAssistant, entity_id: str) -> None:
    """Raise rather than let HA skip a missing or unavailable entity quietly."""
    state = hass.states.get(entity_id)
    if state is None:
        raise HomeAssistantError(f"{entity_id} does not exist")
    if state.state == STATE_UNAVAILABLE:
        raise HomeAssistantError(
            f"{entity_id} is unavailable (read-only pairing, add-on board port, "
            "or the board is not answering)"
        )


def _port_switch_id(entity_id: str) -> str:
    """Map a port's switch, current sensor or binary sensor to its switch."""
    if entity_id.startswith("switch."):
        return entity_id
    # binary_sensor. first: "sensor." is a substring of it.
    entity_id = entity_id.replace("binary_sensor.", "switch.").split("_powered")[0]
    entity_id = entity_id.split("_plug")[0]
    return entity_id.replace("sensor.", "switch.").split("_current")[0]


async def _control_poe_port(
    hass: HomeAssistant, entity_id: str, action: str,
) -> None:
    """Control a PoE port by delegating to the HA switch service.

    This replaces the old VMS-client approach. The switch entities handle
    all hardware-specific logic (ip link set, /proc/pse, etc.) so services
    only need to call the standard HA switch domain.
    """
    _LOGGER.debug("PoE port control: %s -> %s", entity_id, action)
    entity_id = _port_switch_id(entity_id)
    _require_available(hass, entity_id)

    service = action  # turn_on, turn_off, toggle are HA switch services
    await hass.services.async_call(
        "switch", service,
        {"entity_id": entity_id},
        blocking=True,
    )
    _LOGGER.info("PoE port %s: %s completed", entity_id, action)

