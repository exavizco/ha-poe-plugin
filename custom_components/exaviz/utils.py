"""Utility functions for Exaviz integration."""
from __future__ import annotations

import logging

from homeassistant.exceptions import ServiceValidationError

_LOGGER = logging.getLogger(__name__)


def extract_entity_id_from_ha_entity(entity_id: str) -> int:
    """Extract Exaviz entity ID from Home Assistant entity ID.
    
    Args:
        entity_id: HA entity ID (e.g., 'switch.exaviz_poe_port_1000')
        
    Returns:
        Exaviz entity ID (e.g., 1000)
        
    Raises:
        ServiceValidationError: If entity ID format is invalid
    """
    try:
        if "_port_" in entity_id and entity_id.count("_") >= 3:
            parts = entity_id.split("_")
            for i, part in enumerate(parts):
                if part == "port" and i + 1 < len(parts):
                    port_part = parts[i + 1].split("_")[0]
                    return int(port_part)
        
        # Fallback: look for the last number in the entity ID
        parts = entity_id.split("_")
        for part in reversed(parts):
            if part.isdigit():
                return int(part)
                
        raise ValueError("No numeric entity ID found")
        
    except (ValueError, IndexError) as ex:
        raise ServiceValidationError(
            f"Cannot extract Exaviz entity ID from {entity_id}: {ex}"
        ) from ex


def map_port_to_entity_id(poe_set: str, port_number: int) -> int:
    """Map PoE set and port number to Exaviz entity ID.
    
    Args:
        poe_set: PoE set name (e.g., 'poe0', 'poe1', 'pse0', 'pse1', 'onboard')
        port_number: Port number (0-7)
        
    Returns:
        Exaviz entity ID following the pattern:
        - poe0 / pse0 / onboard: 1000-1007
        - poe1 / pse1:           2000-2007
    """
    if poe_set in ("poe0", "pse0", "onboard"):
        return 1000 + port_number
    elif poe_set in ("poe1", "pse1"):
        return 2000 + port_number
    else:
        _LOGGER.warning("Unknown PoE set: %s, using fallback mapping", poe_set)
        return 1000 + port_number


def parse_entity_prefix(entity_id: str) -> tuple[str | None, int | None]:
    """Parse entity ID to extract PoE set and port number.
    
    Args:
        entity_id: HA entity ID (e.g., 'switch.poe0_port0')
        
    Returns:
        Tuple of (poe_set, port_number) or (None, None) if parsing fails
    """
    try:
        if "." in entity_id:
            _, suffix = entity_id.split(".", 1)
        else:
            suffix = entity_id
            
        parts = suffix.split("_")
        poe_set = None
        port_number = None
        
        for i, part in enumerate(parts):
            if part.startswith("poe") and part[3:].isdigit():
                poe_set = part
            elif part.startswith("pse") and part[3:].isdigit():
                poe_set = part
            elif part == "onboard":
                poe_set = "onboard"
            elif part == "port" and i + 1 < len(parts):
                next_part = parts[i + 1].split("_")[0]
                if next_part.isdigit():
                    port_number = int(next_part)

        # Also handle portN without underscore separator (e.g., "port0")
        if port_number is None:
            for part in parts:
                if part.startswith("port") and part[4:].isdigit():
                    port_number = int(part[4:])
                    break
                    
        return poe_set, port_number
        
    except (ValueError, IndexError):
        return None, None


def build_entity_id(domain: str, poe_set: str, port_number: int, suffix: str = "") -> str:
    """Build standardized entity ID.
    
    Args:
        domain: HA domain (sensor, switch, binary_sensor, button)
        poe_set: PoE set name (poe0, poe1, onboard, pse0, pse1)
        port_number: Port number
        suffix: Optional suffix (current, powered, reset, etc.)
        
    Returns:
        Formatted entity ID
    """
    if suffix:
        return f"{domain}.{poe_set}_port{port_number}_{suffix}"
    return f"{domain}.{poe_set}_port{port_number}"
