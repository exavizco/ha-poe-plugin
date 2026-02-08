"""Config flow for Exaviz local board PoE management."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from .board_detector import detect_all_poe_systems
from .const import CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def validate_board_detection(hass: HomeAssistant) -> dict[str, Any]:
    """Detect board type and PoE systems."""
    try:
        detection = await detect_all_poe_systems()
        
        if detection["total_poe_ports"] == 0:
            raise NoPoEDetected("No PoE systems detected on this board")
        
        return {
            "title": f"Exaviz {detection['board_type'].value.title()}",
            "board_info": {
                "board_type": detection["board_type"].value,
                "addon_boards": len(detection["addon_boards"]),
                "onboard_ports": len(detection["onboard_ports"]),
                "total_poe_ports": detection["total_poe_ports"],
            },
        }
    except Exception as ex:
        _LOGGER.error("Board detection failed: %s", ex)
        raise CannotConnect from ex


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Exaviz local board PoE management."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step - auto-detect board."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_board_detection(self.hass)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except NoPoEDetected:
                errors["base"] = "no_poe_detected"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception during board detection")
                errors["base"] = "unknown"
            else:
                # Create unique ID based on board type
                await self.async_set_unique_id(f"exaviz_{info['board_info']['board_type']}")
                self._abort_if_unique_id_configured()
                
                return self.async_create_entry(
                    title=info["title"],
                    data={
                        "board_type": info["board_info"]["board_type"],
                        "addon_boards": info["board_info"]["addon_boards"],
                        "onboard_ports": info["board_info"]["onboard_ports"],
                        "total_poe_ports": info["board_info"]["total_poe_ports"],
                        CONF_UPDATE_INTERVAL: user_input.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
                    },
                )

        # Auto-detect on first show
        if user_input is None:
            try:
                info = await validate_board_detection(self.hass)
                # Show confirmation with detected info
                return self.async_show_form(
                    step_id="user",
                    data_schema=vol.Schema(
                        {
                            vol.Optional(
                                CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL
                            ): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
                        }
                    ),
                    description_placeholders={
                        "board_type": info["board_info"]["board_type"].title(),
                        "total_ports": str(info["board_info"]["total_poe_ports"]),
                        "addon_boards": str(info["board_info"]["addon_boards"]),
                        "onboard_ports": str(info["board_info"]["onboard_ports"]),
                    },
                    errors=errors,
                )
            except (CannotConnect, NoPoEDetected):
                errors["base"] = "no_poe_detected"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception during initial detection")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL
                    ): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
                }
            ),
            errors=errors,
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect to the board."""


class NoPoEDetected(HomeAssistantError):
    """Error to indicate no PoE systems were detected."""
