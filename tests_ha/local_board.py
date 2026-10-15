"""Patched local Cruiser: replaces every /proc, /sys, /dev and dpkg read."""

from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

from custom_components.exaviz.board_detector import BoardType

ONBOARD = [f"poe{i}" for i in range(8)]

PORT_STATUS = {
    f"poe{i}": {
        "available": True,
        "enabled": i != 7,
        "state": "active" if i == 2 else "disabled" if i == 7 else "detection",
        "power_watts": 4.5 if i == 2 else 0.0,
        "allocated_power_watts": 15.4,
        "class": "3" if i == 2 else "?",
        "voltage_volts": 0.0,
        "current_milliamps": 0,
        "link_state": "up" if i == 2 else "down",
        "speed_mbps": 1000 if i == 2 else 0,
        "rx_bytes": 90_000 if i == 2 else 0,
        "tx_bytes": 70_000 if i == 2 else 0,
        "connected_device": (
            {
                "ip_address": "192.168.1.50",
                "mac_address": "aa:bb:cc:dd:ee:02",
                "manufacturer": "Acme",
                "hostname": "camera-2",
            }
            if i == 2
            else None
        ),
    }
    for i in range(8)
}

SYSTEM_INFO = {
    "esp32_firmware_variant": "zigbee",
    "kernel_version": "6.12.0-test",
    "plugin_version": "fixed",
}


def patch_local_board() -> tuple[ExitStack, AsyncMock]:
    """Return an entered ExitStack of patches and the port reader mock."""
    stack = ExitStack()
    stack.enter_context(
        patch(
            "custom_components.exaviz.check_prerequisites",
            AsyncMock(return_value={"all_ok": True, "missing": []}),
        )
    )
    stack.enter_context(
        patch(
            "custom_components.exaviz.coordinator.detect_all_poe_systems",
            AsyncMock(
                return_value={
                    "board_type": BoardType.CRUISER,
                    "addon_boards": [],
                    "onboard_ports": ONBOARD,
                    "total_poe_ports": 8,
                }
            ),
        )
    )
    stack.enter_context(
        patch(
            "custom_components.exaviz.coordinator.ExavizDataUpdateCoordinator"
            "._gather_system_info",
            AsyncMock(return_value=dict(SYSTEM_INFO)),
        )
    )
    stack.enter_context(
        patch(
            "custom_components.exaviz.coordinator.ExavizDataUpdateCoordinator"
            "._read_board_temperature",
            AsyncMock(return_value=48.5),
        )
    )
    reader = AsyncMock(return_value=PORT_STATUS)
    stack.enter_context(
        patch(
            "custom_components.exaviz.coordinator.read_all_onboard_ports", reader
        )
    )
    return stack, reader
