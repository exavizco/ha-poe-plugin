"""Tests for custom_components.exaviz.utils.

Copyright (c) 2026 Axzez LLC.
Licensed under the MIT License. See LICENSE for details.
"""
from unittest.mock import patch

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
