"""Tests for custom_components.exaviz.utils.

Copyright (c) 2026 Axzez LLC.
Licensed under the MIT License. See LICENSE for details.
"""
import logging
from unittest.mock import patch

import pytest
from homeassistant.exceptions import ServiceValidationError

from custom_components.exaviz.utils import sudo_argv


class TestSudoArgv:
    """sudo_argv prefixes `sudo` only when the process is not already root."""

    def test_prefixes_sudo_when_not_root(self):
        with patch("custom_components.exaviz.utils.os.geteuid", return_value=1000):
            assert sudo_argv("ip", "link", "set", "poe0", "up") == (
                "sudo", "ip", "link", "set", "poe0", "up"
            )

    def test_drops_sudo_when_root(self):
        # HA Container/OS runs as root and often has no `sudo` binary; the
        # command must exec directly so it does not ENOENT on 'sudo'.
        with patch("custom_components.exaviz.utils.os.geteuid", return_value=0):
            assert sudo_argv("ip", "link", "set", "poe0", "up") == (
                "ip", "link", "set", "poe0", "up"
            )

    def test_single_arg_root(self):
        with patch("custom_components.exaviz.utils.os.geteuid", return_value=0):
            assert sudo_argv("/usr/sbin/arp-scan") == ("/usr/sbin/arp-scan",)

    def test_single_arg_non_root(self):
        with patch("custom_components.exaviz.utils.os.geteuid", return_value=1000):
            assert sudo_argv("/usr/sbin/arp-scan") == ("sudo", "/usr/sbin/arp-scan")


class TestExtractEntityId:
    """extract_entity_id_from_ha_entity reads the numeric Exaviz id."""

    def test_number_after_port(self):
        from custom_components.exaviz.utils import extract_entity_id_from_ha_entity

        assert extract_entity_id_from_ha_entity("switch.exaviz_poe_port_1000") == 1000
        # The token right after "port" wins over a later suffix.
        assert extract_entity_id_from_ha_entity("sensor.exaviz_poe_port_2003_power") == 2003

    def test_fallback_to_last_number(self):
        from custom_components.exaviz.utils import extract_entity_id_from_ha_entity

        # No "_port_" token, so the last all-digit part is used.
        assert extract_entity_id_from_ha_entity("switch.exaviz_poe_1005") == 1005

    def test_no_number_raises(self):
        from custom_components.exaviz.utils import extract_entity_id_from_ha_entity

        with pytest.raises(ServiceValidationError, match="switch.onboard_port0") as exc:
            extract_entity_id_from_ha_entity("switch.onboard_port0")
        assert "No numeric entity ID found" in str(exc.value)

    def test_non_numeric_after_port_raises(self):
        from custom_components.exaviz.utils import extract_entity_id_from_ha_entity

        # A non-number after "port" is an error, not a fallback to "7".
        with pytest.raises(ServiceValidationError, match="invalid literal"):
            extract_entity_id_from_ha_entity("switch.exaviz_poe_port_x_7")


class TestMapPortToEntityId:
    def test_unknown_set_logs_and_uses_first_range(self, caplog):
        from custom_components.exaviz.utils import map_port_to_entity_id

        with caplog.at_level(logging.WARNING):
            assert map_port_to_entity_id("addon_2", 3) == 1003
        assert "Unknown PoE set: addon_2" in caplog.text


class TestParseEntityPrefix:
    def test_bare_object_id(self):
        from custom_components.exaviz.utils import parse_entity_prefix

        assert parse_entity_prefix("addon_1_port6_current") == ("addon_1", 6)

    @pytest.mark.parametrize("entity_id", [
        "sensor.exaviz_board_temperature",
        "switch.onboard_portx",
        "binary_sensor.onboard_port12abc",
    ])
    def test_not_a_port_entity(self, entity_id):
        from custom_components.exaviz.utils import parse_entity_prefix

        assert parse_entity_prefix(entity_id) == (None, None)


class TestBuildEntityId:
    def test_with_and_without_suffix(self):
        from custom_components.exaviz.utils import build_entity_id, parse_entity_prefix

        assert build_entity_id("switch", "onboard", 3) == "switch.onboard_port3"
        built = build_entity_id("sensor", "addon_0", 5, "current")
        assert built == "sensor.addon_0_port5_current"
        # Round trip through the parser used by the service handlers' tests.
        assert parse_entity_prefix(built) == ("addon_0", 5)
