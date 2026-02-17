"""PoE Sensor Platform for Exaviz Integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .base_entity import ExavizPoEBaseEntity
from .const import DOMAIN
from .coordinator import ExavizDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PoE sensor entities from a config entry."""
    coordinator: ExavizDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    
    entities: list[SensorEntity] = []
    if coordinator.data and "poe" in coordinator.data:
        poe_data = coordinator.data["poe"]
        
        for poe_set_name, poe_set_data in poe_data.items():
            if isinstance(poe_set_data, dict) and "ports" in poe_set_data:
                for port in poe_set_data["ports"]:
                    port_num = port.get("port", 0)
                    entities.append(
                        ExavizPoECurrentSensor(
                            coordinator,
                            poe_set_name,
                            port_num,
                            config_entry.entry_id
                        )
                    )
    
    # Always add the board-level sensors
    entities.append(ExavizServerStatusSensor(coordinator, config_entry.entry_id))
    entities.append(ExavizBoardTemperatureSensor(coordinator, config_entry.entry_id))

    async_add_entities(entities)


class ExavizPoECurrentSensor(ExavizPoEBaseEntity, SensorEntity):
    """Sensor for monitoring PoE port current consumption."""

    def __init__(
        self,
        coordinator: ExavizDataUpdateCoordinator,
        poe_set: str,
        port_number: int,
        entry_id: str,
    ) -> None:
        """Initialize the PoE current sensor."""
        super().__init__(
            coordinator=coordinator,
            poe_set=poe_set,
            port_number=port_number,
            entry_id=entry_id,
            entity_type="sensor",
            entity_suffix="current",
            entity_name_suffix="Current"
        )

    @property
    def device_class(self) -> SensorDeviceClass:
        """Return the device class."""
        return SensorDeviceClass.POWER

    @property
    def state_class(self) -> SensorStateClass:
        """Return the state class."""
        return SensorStateClass.MEASUREMENT

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the unit of measurement."""
        return UnitOfPower.WATT

    @property
    def native_value(self) -> float | None:
        """Return the current power consumption in watts."""
        if not self.coordinator.data:
            return None
        return self._get_port_attribute("power_consumption_watts", 0.0)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes."""
        base_attrs = super().extra_state_attributes
        if not base_attrs:
            return None
            
        port_data = self._get_port_data()
        if port_data:
            base_attrs.update({
                "voltage_volts": port_data.get("voltage_volts", 0),
                "current_milliamps": port_data.get("current_milliamps", 0),
                "allocated_power_watts": port_data.get("allocated_power_watts", 15.4),
                "poe_class": port_data.get("poe_class", "?"),
                "poe_system": port_data.get("poe_system", "unknown"),
            })
            
            if port_data.get("power_mocked"):
                base_attrs["power_note"] = "Power metrics estimated (TPS23861 driver not available)"
                base_attrs["power_mocked"] = True
            
            if self.coordinator.board_type:
                base_attrs["board_type"] = self.coordinator.board_type.value
        
        return base_attrs


class ExavizServerStatusSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Exaviz local board status."""

    def __init__(self, coordinator: ExavizDataUpdateCoordinator, entry_id: str) -> None:
        """Initialize the board status sensor."""
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_name = "Board Status"
        self._attr_unique_id = f"{entry_id}_board_status"
        self._attr_icon = "mdi:chip"
        self.entity_id = "sensor.board_status"

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information."""
        board_type = self.coordinator.board_type
        board_name = board_type.value.title() if board_type else "Unknown"
        
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": f"Exaviz {board_name}",
            "manufacturer": "Exaviz (by Axzez LLC)",
            "model": f"{board_name} Carrier Board",
            "sw_version": "1.0.0",
        }

    @property
    def native_value(self) -> str:
        """Return the state of the sensor."""
        if not self.coordinator.last_update_success:
            return "Error"
        if self.coordinator.total_poe_ports > 0:
            return "Operational"
        return "No PoE Detected"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes."""
        board_info = self.coordinator.board_info

        attrs: dict[str, Any] = {
            "board_type": board_info.get("board_type", "unknown"),
            "total_poe_ports": board_info.get("total_poe_ports", 0),
            "onboard_ports": board_info.get("onboard_ports", 0),
            "addon_boards": board_info.get("addon_boards", 0),
        }

        # System info (gathered once at startup)
        for key in (
            "compute_module",
            "cm_model",
            "total_ram_gb",
            "has_wifi",
            "emmc_storage",
            "os_version",
            "kernel_version",
            "dkms_driver_version",
            "netplan_version",
            "poe_controller",
            "esp32_firmware_version",
            "board_model_esp32",
            "board_hw_version",
            "board_serial",
            "board_identifier",
            "poe_driver_version",
            "plugin_version",
        ):
            if key in board_info:
                attrs[key] = board_info[key]

        # Live PoE stats (updated each poll cycle)
        if self.coordinator.data:
            data = self.coordinator.data
            attrs["total_enabled_ports"] = data.get("total_enabled_ports", 0)
            attrs["total_power_watts"] = data.get("total_power_watts", 0)

        attrs["update_interval"] = (
            self.coordinator.update_interval.total_seconds()
            if self.coordinator.update_interval
            else 30
        )

        return attrs

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return True  # Always available to show connection status


class ExavizBoardTemperatureSensor(CoordinatorEntity, SensorEntity):
    """Sensor for CM5 SoC temperature.

    Reads /sys/class/thermal/thermal_zone0/temp which reports the
    Broadcom BCM2712 SoC temperature in millidegrees Celsius.
    Updated every coordinator poll cycle alongside PoE data.
    """

    _THERMAL_PATH = "/sys/class/thermal/thermal_zone0/temp"

    def __init__(self, coordinator: ExavizDataUpdateCoordinator, entry_id: str) -> None:
        """Initialize the board temperature sensor."""
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_name = "Board Temperature"
        self._attr_unique_id = f"{entry_id}_board_temperature"
        self._attr_icon = "mdi:thermometer"
        self.entity_id = "sensor.board_temperature"

    @property
    def device_class(self) -> SensorDeviceClass:
        """Return the device class."""
        return SensorDeviceClass.TEMPERATURE

    @property
    def state_class(self) -> SensorStateClass:
        """Return the state class."""
        return SensorStateClass.MEASUREMENT

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the unit of measurement."""
        return UnitOfTemperature.CELSIUS

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information (same parent device as board status)."""
        board_type = self.coordinator.board_type
        board_name = board_type.value.title() if board_type else "Unknown"
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": f"Exaviz {board_name}",
            "manufacturer": "Exaviz (by Axzez LLC)",
            "model": f"{board_name} Carrier Board",
            "sw_version": "1.0.0",
        }

    @property
    def native_value(self) -> float | None:
        """Return the SoC temperature in degrees Celsius."""
        if self.coordinator.data:
            temp = self.coordinator.data.get("board_temperature_celsius")
            if temp is not None:
                return temp
        return None

    @property
    def available(self) -> bool:
        """Return True if thermal zone is readable."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
            and self.coordinator.data.get("board_temperature_celsius") is not None
        )
