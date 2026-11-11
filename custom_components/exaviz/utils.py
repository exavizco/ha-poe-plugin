"""Utility functions for Exaviz integration."""
from __future__ import annotations

import os


def sudo_argv(*args: str) -> tuple[str, ...]:
    """Prefix a command with sudo only when not already running as root.

    Home Assistant Container/OS images run the integration as root (uid 0) and
    often ship without a `sudo` binary, so an unconditional `sudo` prefix fails
    with "No such file or directory: 'sudo'". When euid is 0 we already hold the
    privileges these commands need, so we exec them directly and skip sudo.
    """
    if os.geteuid() == 0:
        return args
    return ("sudo", *args)
