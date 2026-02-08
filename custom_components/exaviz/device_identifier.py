"""Device identification utilities for PoE ports."""
from __future__ import annotations

import asyncio
import logging
import socket
from typing import Any, Dict, Optional

_LOGGER = logging.getLogger(__name__)

# MAC vendor OUI database (first 3 bytes of MAC address)
# This is a subset of common manufacturers - can be expanded
MAC_VENDOR_DB = {
    "00:1D:0F": "Ubiquiti Networks",
    "00:27:22": "Ubiquiti Networks",
    "24:5A:4C": "Ubiquiti Networks",
    "74:83:C2": "Ubiquiti Networks",
    "F0:9F:C2": "Ubiquiti Networks",
    "00:04:20": "Axis Communications (Camera)",
    "00:40:8C": "Axis Communications (Camera)",
    "AC:CC:8E": "Axis Communications (Camera)",
    "00:50:C2": "Axis Communications (Camera)",
    "B8:A4:4F": "Axis Communications (Camera)",
    "00:13:E2": "GeoVision (Camera)",
    "E4:30:22": "Hanwha Vision (Wisenet Camera)",
    "00:09:57": "Hanwha Vision (Wisenet Camera)",
    "00:D0:3E": "Hanwha Techwin (Wisenet Camera)",
    "00:07:5F": "VCS Video Communication Systems (Camera)",
    "5C:F2:07": "Speco Technologies (Camera)",
    "00:01:31": "Bosch Security Systems (Camera)",
    "00:04:63": "Bosch Security Systems (Camera)",
    "00:10:17": "Bosch Security Systems (Camera)",
    "00:1B:86": "Bosch Security Systems (Camera)",
    "00:1C:44": "Bosch Security Systems (Camera)",
    "00:0C:29": "VMware Virtual",
    "00:50:56": "VMware Virtual",
    "08:00:27": "VirtualBox Virtual",
    "00:15:5D": "Microsoft Hyper-V",
    "00:1B:21": "Intel Corporate",
    "00:1E:67": "Intel Corporate",
    "00:25:90": "Intel Corporate",
    "00:0D:B9": "Raspberry Pi Trading",
    "B8:27:EB": "Raspberry Pi Foundation",
    "DC:A6:32": "Raspberry Pi Trading",
    "E4:5F:01": "Raspberry Pi Trading",
    "00:1C:42": "Parallels Virtual",
    "00:11:32": "Synology",
    "00:D0:41": "TP-Link Technologies",
    "50:C7:BF": "TP-Link Technologies",
    "A0:F3:C1": "TP-Link Technologies",
    "00:03:7F": "Atheros Communications",
    "00:1B:63": "Apple",
    "00:26:B0": "Apple",
    "00:3E:E1": "Apple",
    "04:26:65": "Apple",
    "D4:61:9D": "Apple",
    "00:1C:B3": "Netgear",
    "00:26:F2": "Netgear",
    "28:C6:8E": "Netgear",
    "00:14:6C": "Cisco Systems",
    "00:18:B9": "Cisco Systems",
    "00:1D:70": "Cisco Systems",
    "00:50:56": "Cisco Systems",
    "00:22:90": "Cisco Systems",
}


def get_mac_vendor(mac_address: str) -> str:
    """Look up vendor/manufacturer from MAC address OUI.
    
    Args:
        mac_address: MAC address in format "XX:XX:XX:XX:XX:XX"
    
    Returns:
        Manufacturer name or "Unknown" if not found
    """
    if not mac_address or len(mac_address) < 8:
        return "Unknown"
    
    # Extract OUI (first 3 bytes)
    oui = mac_address[:8].upper()
    
    # Look up in database
    vendor = MAC_VENDOR_DB.get(oui)
    if vendor:
        return vendor
    
    # Try to match partial OUI patterns
    for known_oui, manufacturer in MAC_VENDOR_DB.items():
        if oui.startswith(known_oui[:5]):  # Match first 2 bytes if exact match fails
            return f"{manufacturer} (partial match)"
    
    return "Unknown"


async def get_hostname_from_ip(ip_address: str, timeout: float = 2.0) -> Optional[str]:
    """Perform reverse DNS lookup to get hostname from IP address.
    
    Args:
        ip_address: IP address to look up
        timeout: Timeout in seconds (default 2.0)
    
    Returns:
        Hostname if found, None otherwise
    """
    try:
        # Run getnameinfo in thread pool to avoid blocking
        hostname, _ = await asyncio.wait_for(
            asyncio.to_thread(
                socket.getnameinfo, (ip_address, 0), socket.NI_NAMEREQD,
            ),
            timeout=timeout,
        )
        return hostname if hostname and hostname != ip_address else None
    except (socket.herror, socket.gaierror, asyncio.TimeoutError, OSError) as ex:
        _LOGGER.debug("Failed to resolve hostname for %s: %s", ip_address, ex)
        return None


async def enrich_device_info(device_info: Dict[str, Any]) -> Dict[str, Any]:
    """Enrich device information with vendor and hostname lookups.
    
    Args:
        device_info: Dictionary containing at least 'mac_address' and optionally 'ip_address'
    
    Returns:
        Enriched device info with 'manufacturer' and 'hostname' fields (always present)
    """
    enriched = device_info.copy() if device_info else {}
    
    # Add manufacturer from MAC address (always add, even if Unknown)
    mac_address = device_info.get("mac_address") if device_info else None
    enriched["manufacturer"] = get_mac_vendor(mac_address) if mac_address else "Unknown"
    
    # Add hostname from IP address (always add, may be None)
    ip_address = device_info.get("ip_address") if device_info else None
    enriched["hostname"] = await get_hostname_from_ip(ip_address) if ip_address else None
    
    return enriched

