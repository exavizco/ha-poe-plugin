"""Zigbee coordinator status next to the PoE ports (os-support #175).

The ESP32 `info` command prints "firmware variant: <name>". Only the "zigbee",
"zigbee-rcp" and "all-unsupported" images carry the Zigbee NCP; "stock" and "poe-only" do not.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.exaviz.binary_sensor import ExavizZigbeeCoordinatorSensor
from custom_components.exaviz.board_detector import BoardType
from custom_components.exaviz.const import ZIGBEE_MISSING_MESSAGE
from custom_components.exaviz.coordinator import parse_esp32_info

INFO = (
    "Exaviz PoE monitor version 1.1.2+abc1234\n"
    "firmware variant: {variant}\n"
    "board model: cruiser\n"
    "board serial: CRU-000011\n"
)


@pytest.mark.parametrize("variant", ["zigbee", "zigbee-rcp", "stock", "poe-only", "all-unsupported"])
def test_parse_reads_variant(variant):
    info = parse_esp32_info(INFO.format(variant=variant))
    assert info["esp32_firmware_variant"] == variant
    assert info["esp32_firmware_version"] == "1.1.2+abc1234"


def test_parse_old_firmware_has_no_variant():
    info = parse_esp32_info("Exaviz PoE monitor version 1.0.0\nboard model: cruiser\n")
    assert "esp32_firmware_variant" not in info


def _sensor(system_info):
    coordinator = MagicMock()
    coordinator.system_info = system_info
    coordinator.last_update_success = True
    coordinator.data = {"poe": {}}
    coordinator.board_type = BoardType.CRUISER
    return ExavizZigbeeCoordinatorSensor(coordinator, "entry")


@pytest.mark.parametrize("variant", ["zigbee", "zigbee-rcp", "all-unsupported"])
def test_on_when_firmware_has_zigbee(variant):
    s = _sensor({"esp32_firmware_variant": variant})
    assert s.is_on is True
    assert "message" not in (s.extra_state_attributes or {})


@pytest.mark.parametrize("variant", ["stock", "poe-only"])
def test_off_with_helper_message_when_firmware_lacks_zigbee(variant):
    s = _sensor({"esp32_firmware_variant": variant})
    assert s.is_on is False
    assert s.extra_state_attributes["message"] == ZIGBEE_MISSING_MESSAGE
    assert s.extra_state_attributes["firmware_variant"] == variant


def test_unknown_when_firmware_does_not_report_variant():
    s = _sensor({"esp32_firmware_version": "1.0.0"})
    assert s.is_on is None
    assert "message" not in (s.extra_state_attributes or {})


def test_message_is_the_approved_wording():
    assert ZIGBEE_MISSING_MESSAGE == (
        "Zigbee firmware isn't installed on this Cruiser board. "
        "Install it with the Exaviz tools to use Zigbee."
    )


def test_sensor_ids():
    s = _sensor({})
    assert s.entity_id == "binary_sensor.zigbee_coordinator"
    assert s._attr_unique_id == "entry_zigbee_coordinator"


def test_sensor_stays_available_when_poll_fails():
    sensor = _sensor({"esp32_firmware_variant": "zigbee"})
    sensor.coordinator.last_update_success = False
    assert sensor.available is True
    assert sensor.is_on is True
