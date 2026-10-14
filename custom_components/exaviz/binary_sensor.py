"""PoE Binary Sensor Platform for Exaviz Integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .base_entity import ExavizPoEBaseEntity
from .board_detector import BoardType
from .const import (
    DOMAIN,
    PLUGGED_THRESHOLD_MILLIAMPS,
    POWER_ON_THRESHOLD_WATTS,
    ZIGBEE_FIRMWARE_VARIANTS,
    ZIGBEE_MISSING_MESSAGE,
)
from .coordinator import ExavizDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PoE binary sensor entities from a config entry."""
    coordinator: ExavizDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    
    entities: list[BinarySensorEntity] = []
    if coordinator.data and "poe" in coordinator.data:
        poe_data = coordinator.data["poe"]
        
        for poe_set_name, poe_set_data in poe_data.items():
            if isinstance(poe_set_data, dict) and "ports" in poe_set_data:
                for port in poe_set_data["ports"]:
                    port_num = port.get("port", 0)
                    entities.append(
                        ExavizPoEPortPoweredSensor(
                            coordinator, poe_set_name, port_num,
                            config_entry.entry_id,
                        )
                    )
                    entities.append(
                        ExavizPoEPortPluggedSensor(
                            coordinator, poe_set_name, port_num,
                            config_entry.entry_id,
                        )
                    )
    
    # Zigbee coordinator lives on the Cruiser's ESP32-C6
    if coordinator.board_type == BoardType.CRUISER:
        entities.append(ExavizZigbeeCoordinatorSensor(coordinator, config_entry.entry_id))

    async_add_entities(entities)


class ExavizPoEPortPoweredSensor(ExavizPoEBaseEntity, BinarySensorEntity):
    """Binary sensor for PoE port powered status."""

    def __init__(
        self,
        coordinator: ExavizDataUpdateCoordinator,
        poe_set: str,
        port_number: int,
        entry_id: str,
    ) -> None:
        """Initialize the PoE port powered sensor."""
        super().__init__(
            coordinator=coordinator,
            poe_set=poe_set,
            port_number=port_number,
            entry_id=entry_id,
            entity_type="binary_sensor",
            entity_suffix="powered",
            entity_name_suffix="Powered",
        )

    @property
    def device_class(self) -> BinarySensorDeviceClass:
        """Return the device class."""
        return BinarySensorDeviceClass.POWER

    @property
    def is_on(self) -> bool | None:
        """Return true if the PoE port is powered (device receiving power)."""
        if not self.coordinator.data:
            return None
        port_data = self._get_port_data()
        if port_data is None:
            return None
        power = port_data.get("power_consumption_watts", 0)
        return power > POWER_ON_THRESHOLD_WATTS

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.coordinator.data is not None


class ExavizPoEPortPluggedSensor(ExavizPoEBaseEntity, BinarySensorEntity):
    """Binary sensor for PoE port plugged status."""

    def __init__(
        self,
        coordinator: ExavizDataUpdateCoordinator,
        poe_set: str,
        port_number: int,
        entry_id: str,
    ) -> None:
        """Initialize the PoE port plugged sensor."""
        super().__init__(
            coordinator=coordinator,
            poe_set=poe_set,
            port_number=port_number,
            entry_id=entry_id,
            entity_type="binary_sensor",
            entity_suffix="plug",
            entity_name_suffix="Plugged",
        )

    @property
    def device_class(self) -> BinarySensorDeviceClass:
        """Return the device class."""
        return BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self) -> bool | None:
        """Return true if something is plugged into the PoE port."""
        if not self.coordinator.data:
            return None
        port_data = self._get_port_data()
        if port_data is None:
            return None
        connected_device = port_data.get("connected_device")
        current = port_data.get("current_milliamps", 0)
        return bool(connected_device) or current > PLUGGED_THRESHOLD_MILLIAMPS

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.coordinator.data is not None


class ExavizZigbeeCoordinatorSensor(CoordinatorEntity, BinarySensorEntity):
    """Whether the ESP32-C6 runs Zigbee coordinator firmware.

    On = Zigbee firmware installed, off = not installed (the attributes carry
    the helper message), unknown = firmware too old to report its variant.
    """

    def __init__(self, coordinator: ExavizDataUpdateCoordinator, entry_id: str) -> None:
        """Initialize the Zigbee coordinator sensor."""
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_name = "Zigbee Coordinator"
        self._attr_unique_id = f"{entry_id}_zigbee_coordinator"
        self._attr_icon = "mdi:zigbee"
        self.entity_id = "binary_sensor.zigbee_coordinator"

    @property
    def _variant(self) -> str | None:
        return self.coordinator.system_info.get("esp32_firmware_variant")

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information (same parent device as board status)."""
        return {"identifiers": {(DOMAIN, self._entry_id)}}

    @property
    def available(self) -> bool:
        """Firmware variant is static startup info, so a failed PoE poll does not hide it."""
        return True

    @property
    def is_on(self) -> bool | None:
        """Return true if the ESP32 firmware includes the Zigbee coordinator."""
        if self._variant is None:
            return None
        return self._variant in ZIGBEE_FIRMWARE_VARIANTS

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the firmware variant and, when Zigbee is missing, the helper message."""
        if self._variant is None:
            return None
        attrs: dict[str, Any] = {"firmware_variant": self._variant}
        if not self.is_on:
            attrs["message"] = ZIGBEE_MISSING_MESSAGE
        return attrs
