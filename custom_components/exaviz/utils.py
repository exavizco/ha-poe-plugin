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
        poe_set: PoE set name (e.g., 'onboard', 'addon_0', 'addon_1',
                 or legacy 'poe0', 'poe1', 'pse0', 'pse1')
        port_number: Port number (0-7)
        
    Returns:
        Exaviz entity ID following the pattern:
        - onboard / addon_0 / poe0 / pse0: 1000-1007
        - addon_1 / poe1 / pse1:           2000-2007
    """
    if poe_set in ("onboard", "addon_0", "poe0", "pse0"):
        return 1000 + port_number
    elif poe_set in ("addon_1", "poe1", "pse1"):
        return 2000 + port_number
    else:
        _LOGGER.warning("Unknown PoE set: %s, using fallback mapping", poe_set)
        return 1000 + port_number


def parse_entity_prefix(entity_id: str) -> tuple[str | None, int | None]:
    """Parse entity ID to extract PoE set and port number.
    
    Handles entity IDs like:
        switch.onboard_port0
        switch.addon_0_port3
        switch.pse0_port3  (legacy)
    
    Args:
        entity_id: HA entity ID
        
    Returns:
        Tuple of (poe_set, port_number) or (None, None) if parsing fails
    """
    import re

    try:
        if "." in entity_id:
            _, suffix = entity_id.split(".", 1)
        else:
            suffix = entity_id

        # Match: {poe_set}_port{N}[_suffix]
        # poe_set may contain underscores (e.g. addon_0)
        m = re.match(r"^(.+?)_port(\d+)(?:_|$)", suffix)
        if m:
            return m.group(1), int(m.group(2))

        return None, None

    except (ValueError, IndexError):
        return None, None


def build_entity_id(domain: str, poe_set: str, port_number: int, suffix: str = "") -> str:
    """Build standardized entity ID.
    
    Args:
        domain: HA domain (sensor, switch, binary_sensor, button)
        poe_set: PoE set name (onboard, addon_0, addon_1)
        port_number: Port number
        suffix: Optional suffix (current, powered, reset, etc.)
        
    Returns:
        Formatted entity ID
    """
    if suffix:
        return f"{domain}.{poe_set}_port{port_number}_{suffix}"
    return f"{domain}.{poe_set}_port{port_number}"
