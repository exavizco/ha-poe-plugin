"""Constants for the Exaviz PoE Management integration.

Copyright (c) 2026 Axzez LLC.
Licensed under the MIT License. See LICENSE for details.
"""
from __future__ import annotations

from typing import Final

# Integration domain
DOMAIN: Final = "exaviz"

# Plugin version (semver + git hash for build metadata)
# Format: MAJOR.MINOR.PATCH+<git-short-hash>
# Update MAJOR.MINOR.PATCH here; the hash is appended at build/tag time.
PLUGIN_VERSION: Final = "1.0.0"

# Configuration keys
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_UPDATE_INTERVAL: Final = "update_interval"
CONF_SWITCH_MODE_DISCOVERY: Final = "switch_mode_discovery"

# Default values
DEFAULT_SCAN_INTERVAL: Final = 30
DEFAULT_UPDATE_INTERVAL: Final = 30
# Opt-in: switch-mode discovery runs an active arp-scan of the bridge subnet, so
# it stays off until the operator enables it in the integration options.
DEFAULT_SWITCH_MODE_DISCOVERY: Final = False

# Network and device detection constants
MIN_TRAFFIC_BYTES: Final = 1000  # Minimum bytes to consider port active
TCPDUMP_TIMEOUT: Final = 10  # Seconds to wait for packet capture
BOSCH_PACKET_COUNT: Final = 20  # Number of packets to capture for Bosch detection

# Switch/bridge-mode device discovery (issue #10)
# When a poeN interface is enslaved to a bridge (e.g. br0), per-port ARP is
# empty because neighbours attach to the bridge, not to poeN. We resolve the
# device via the bridge FDB (MAC learned on the port) + arp-scan (MAC->IP+OUI).
# Enable/disable per integration via CONF_SWITCH_MODE_DISCOVERY (options flow).
# arp-scan is run directly under sudo (NOT wrapped in `timeout`): modern sudo
# rejects wildcards in command arguments, so the only valid NOPASSWD rule for a
# variable-arg command is the bare binary path -- and whitelisting `arp-scan`
# (which cannot exec anything else) is far tighter than whitelisting `timeout`
# (which can run anything as root). We bound the run with asyncio.wait_for.
ARP_SCAN_BIN: Final = "/usr/sbin/arp-scan"
ARP_SCAN_TIMEOUT: Final = 5  # Seconds to wait for an arp-scan sweep before giving up
ARP_SCAN_CACHE_TTL: Final = 25  # Seconds a bridge sweep is reused across ports
# arp-scan on Ubuntu 26.04 cannot open its default OUI database (the sweep still
# maps MAC->IP, but the vendor column comes back "(Unknown)"); pass this path
# explicitly so vendor enrichment works. Ignored if the file is absent.
ARP_SCAN_OUI_FILE: Final = "/usr/share/arp-scan/ieee-oui.txt"

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
