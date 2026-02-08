"""Base entity classes for Exaviz PoE integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ExavizDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class ExavizPoEBaseEntity(CoordinatorEntity):
    """Base class for all Exaviz PoE entities."""

    def __init__(
        self,
        coordinator: ExavizDataUpdateCoordinator,
        poe_set: str,
        port_number: int,
        entry_id: str,
        entity_type: str,
        entity_suffix: str,
        entity_name_suffix: str,
    ) -> None:
        """Initialize the base PoE entity."""
        super().__init__(coordinator)
        self._poe_set = poe_set
        self._port_number = port_number
        self._entry_id = entry_id
        self._entity_type = entity_type
        
        # Standardized entity naming pattern (handle empty suffix without trailing _)
        suffix = f"_{entity_suffix}" if entity_suffix else ""
        name_suffix = f" {entity_name_suffix}" if entity_name_suffix else ""
        self._attr_unique_id = f"{entry_id}_{poe_set}_port{port_number}{suffix}"
        self._attr_name = f"{poe_set.upper()} Port {port_number}{name_suffix}"
        self.entity_id = f"{entity_type}.{poe_set}_port{port_number}{suffix}"

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information about this PoE switch."""
        return {
            "identifiers": {(DOMAIN, f"{self._entry_id}_{self._poe_set}")},
            "name": f"Exaviz {self._poe_set.upper()} Switch",
            "model": "PoE Switch",
            "via_device": (DOMAIN, self._entry_id),
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.coordinator.data is not None

    def _get_port_data(self) -> dict[str, Any] | None:
        """Get port data from coordinator."""
        if not self.coordinator.data:
            return None
            
        poe_data = self.coordinator.data.get("poe", {})
        poe_set_data = poe_data.get(self._poe_set, {})
        ports = poe_set_data.get("ports", [])
        
        for port in ports:
            if port.get("port") == self._port_number:
                return port
        
        return None

    def _get_port_attribute(self, attribute: str, default: Any = None) -> Any:
        """Get a specific attribute from port data."""
        port_data = self._get_port_data()
        if port_data:
            return port_data.get(attribute, default)
        return default

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return common port attributes."""
        port_data = self._get_port_data()
        if not port_data:
            return None
            
        attrs: dict[str, Any] = {
            "port_number": self._port_number,
            "poe_set": self._poe_set,
            "status": port_data.get("status", "unknown"),
            "enabled": port_data.get("enabled", False),
        }
        
        connected_device = port_data.get("connected_device")
        if connected_device:
            attrs.update({
                "device_name": connected_device.get("name"),
                "device_type": connected_device.get("device_type"),
                "device_ip": connected_device.get("ip_address"),
                "device_mac": connected_device.get("mac_address"),
                "device_manufacturer": connected_device.get("manufacturer"),
                "device_hostname": connected_device.get("hostname"),
                "power_class": connected_device.get("power_class"),
            })
        
        return attrs
