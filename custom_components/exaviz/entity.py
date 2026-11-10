"""Base entity classes for Exaviz PoE integration."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ExavizDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Newer HA links a child device by the parent's registry id, looked up per
# config entry, and deprecates via_device (it stops working in 2027.8). The
# 2024.12 floor has neither, only via_device.
_VIA_DEVICE_ID = "via_device_id" in dr.DeviceInfo.__annotations__ and hasattr(
    dr.DeviceRegistry, "async_get_device_by_identifier"
)


def async_setup_port_entities(
    coordinator: ExavizDataUpdateCoordinator,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    build: Callable[[str, int], list[Entity]],
) -> None:
    """Add `build(poe_set, port)` entities for every port in the data.

    A remote board can report ports after setup (one controller parsed before
    the other), so remote entries also add entities for ports seen later,
    with the same ids the first refresh would have given them.
    """
    known: set[tuple[str, int]] = set()

    @callback
    def add_new_ports() -> None:
        entities: list[Entity] = []
        for poe_set_name, poe_set_data in (coordinator.data or {}).get("poe", {}).items():
            if isinstance(poe_set_data, dict) and "ports" in poe_set_data:
                for port in poe_set_data["ports"]:
                    key = (poe_set_name, port.get("port", 0))
                    if key not in known:
                        known.add(key)
                        entities.extend(build(*key))
        if entities:
            async_add_entities(entities)

    add_new_ports()
    if coordinator.remote is not None:
        config_entry.async_on_unload(coordinator.async_add_listener(add_new_ports))


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
        info: dict[str, Any] = {
            "identifiers": {(DOMAIN, f"{self._entry_id}_{self._poe_set}")},
            "name": f"Exaviz {self._poe_set.upper()} Switch",
            "model": "PoE Switch",
        }
        if _VIA_DEVICE_ID:
            # The board device is registered in async_setup_entry before
            # any platform loads.
            parent = dr.async_get(self.hass).async_get_device_by_identifier(
                (DOMAIN, self._entry_id), self._entry_id
            )
            if parent is not None:  # the user may have deleted it
                info["via_device_id"] = parent.id
        else:
            info["via_device"] = (DOMAIN, self._entry_id)
        return info

    @property
    def available(self) -> bool:
        """Return if entity is available (a remote port can be stale)."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
            and not self._get_port_attribute("stale", False)
        )

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
                "device_traffic_detected": connected_device.get("traffic_detected", False),
            })
        
        return attrs
