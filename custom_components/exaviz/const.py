from __future__ import annotations

"""
Copyright (c) 2025 Axzez LLC.
Licensed under MIT with Commons Clause. See LICENSE for details.
"""

"""Constants for the Exaviz PoE Management integration."""

from typing import Final

# Integration domain
DOMAIN: Final = "exaviz"

# Plugin version (semver + git hash for build metadata)
# Format: MAJOR.MINOR.PATCH+<git-short-hash>
# Update MAJOR.MINOR.PATCH here; the hash is appended at build/tag time.
PLUGIN_VERSION: Final = "0.0.1"

# Configuration keys
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_UPDATE_INTERVAL: Final = "update_interval"

# Default values
DEFAULT_SCAN_INTERVAL: Final = 30
DEFAULT_UPDATE_INTERVAL: Final = 30

# Network and device detection constants
MIN_TRAFFIC_BYTES: Final = 1000  # Minimum bytes to consider port active
TCPDUMP_TIMEOUT: Final = 10  # Seconds to wait for packet capture
BOSCH_PACKET_COUNT: Final = 20  # Number of packets to capture for Bosch detection

# Binary sensor thresholds
POWER_ON_THRESHOLD_WATTS: Final = 0.5  # Minimum watts to consider port "powered"
PLUGGED_THRESHOLD_MILLIAMPS: Final = 10  # Minimum mA to consider port "plugged"

# PoE Class Power Allocations (IEEE 802.3 Standard)
# Maps PoE class number to allocated power in watts at PSE
POE_CLASS_POWER_ALLOCATION: Final = {
    "0": 15.4,  # Class 0: Legacy/Unknown (0.44-12.95W device, 15.4W PSE)
    "1": 4.0,   # Class 1: Low power (0.44-3.84W device, 4.0W PSE)
    "2": 7.0,   # Class 2: Medium power (3.84-6.49W device, 7.0W PSE)
    "3": 15.4,  # Class 3: High power (6.49-12.95W device, 15.4W PSE)
    "4": 30.0,  # Class 4: PoE+ (12.95-25.50W device, 30.0W PSE)
    "?": 15.4,  # Unknown class: Assume Class 0/3 allocation
}
