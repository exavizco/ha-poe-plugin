"""PoE port status readers for add-on and onboard systems.

CRITICAL ARCHITECTURE NOTES:
==========================
Cruiser (Carrier Board):
  - Architecture: TPS23861 → ESP32-C6 (I2C) → CM5 (UART3) → /dev/ttyAMA3
  - Interface: /dev/pse → /dev/ttyAMA3 (udev symlink from 60-pse.rules)
  - Format: Text lines with port status from ESP32 firmware
  - Protocol: "{pse}-{port}: {state} {class} {power} {voltage} {current}/{limit} {temp}"
  
Interceptor (Add-on Board):
  - Architecture: IP808AR → Kernel driver (I2C) → /proc/pse
  - Interface: /proc/pse (procfs streaming file from ip808ar kernel module)
  - Format: Space-delimited lines

ESP32 Serial Reader:
  - Implemented: read_cruiser_pse_data() parses ESP32 UART stream
  - Fallback chain: /dev/pse → /dev/ttyAMA3 → network-only
  - Works when ESP32 firmware is running and outputting data
"""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any, Dict, Optional

from .const import MIN_TRAFFIC_BYTES, TCPDUMP_TIMEOUT, BOSCH_PACKET_COUNT, POE_CLASS_POWER_ALLOCATION
from .device_identifier import enrich_device_info

_LOGGER = logging.getLogger(__name__)


def get_allocated_power_watts(poe_class: str) -> float:
    """Get allocated power in watts based on PoE class.
    
    Args:
        poe_class: PoE class string ("0", "1", "2", "3", "4", or "?")
    
    Returns:
        Allocated power in watts
    """
    return POE_CLASS_POWER_ALLOCATION.get(str(poe_class), 15.4)


async def read_pse_port_status(pse_id: str, port_num: int) -> Dict[str, Any]:
    """Read add-on board PoE port status from /proc/pse.
    
    CRITICAL: /proc/pse is a STREAMING format (not /proc/pse0/port0/status subdirectories)!
    
    Format: Space-delimited fields per line:
        PSE-PORT: STATE CLASS POWER VOLTAGE CURRENT/LIMIT TEMP/MAX
    
    Example /proc/pse content:
        Axzez Interceptor PoE driver version 2.0
        0-0: power-on 0 15.50 47.9375 0.05950/0.80000 33.1250/150.0000
        0-1: backoff ? 0.00 47.9375 0.00000/0.80000 34.6250/150.0000
        0: 47.9375/40.0000-60.0000 0.05950/2.50000 15.50/120
    
    Args:
        pse_id: PSE controller ID (e.g., "pse0" -> extract "0")
        port_num: Port number (0-7)
    
    Returns:
        Dictionary with port status information
    """
    pse_file = Path("/proc/pse")
    
    try:
        if not pse_file.exists():
            _LOGGER.debug("/proc/pse not found")
            return {
                "available": False,
                "state": "unavailable",
                "class": "?",
                "power_watts": 0.0,
                "allocated_power_watts": 15.4,  # Default to Class 0/3
                "voltage_volts": 0.0,
                "current_milliamps": 0,
                "temperature_celsius": 0.0,
            }
        
        # Extract PSE number from pse_id (e.g., "pse0" -> 0)
        pse_num_match = re.search(r'\d+', pse_id)
        pse_num = int(pse_num_match.group()) if pse_num_match else 0
        
        # Read /proc/pse streaming output
        # CRITICAL: /proc/pse is a STREAMING file - must read limited lines to avoid hang!
        # Use subprocess to run 'head -30' to read only first batch
        import subprocess
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ['head', '-30', str(pse_file)],
                capture_output=True,
                text=True,
                timeout=5
            )
            pse_text = result.stdout
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
            _LOGGER.error("Failed to read /proc/pse: %s", e)
            return {
                "available": False,
                "state": "error",
                "error": str(e),
            }
        
        # Parse space-delimited format: "0-0: power-on 0 15.50 47.9375 0.05950/0.80000 33.1250/150.0000"
        # Look for line matching our PSE-PORT
        port_pattern = rf'^{pse_num}-{port_num}:\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)'
        
        for line in pse_text.split('\n'):
            match = re.match(port_pattern, line.strip())
            if match:
                state, poe_class, power_str, voltage_str, current_str, temp_str = match.groups()
                
                # Parse values
                power_watts = float(power_str) if power_str != '?' else 0.0
                voltage_volts = float(voltage_str) if voltage_str != '?' else 0.0
                
                # Parse "current/limit" format
                current_parts = current_str.split('/')
                current_amps = float(current_parts[0]) if current_parts else 0.0
                current_milliamps = int(current_amps * 1000)
                
                # Parse "temp/max" format
                temp_parts = temp_str.split('/')
                temperature_celsius = float(temp_parts[0]) if temp_parts else 0.0
                
                # Get allocated power based on class
                allocated_power = get_allocated_power_watts(poe_class)
                
                return {
                    "available": True,
                    "poe_system": "addon",
                    "state": state,
                    "class": poe_class,
                    "power_watts": round(power_watts, 2),
                    "allocated_power_watts": allocated_power,
                    "voltage_volts": round(voltage_volts, 2),
                    "current_milliamps": current_milliamps,
                    "temperature_celsius": round(temperature_celsius, 1),
                    "enabled": state not in ("disabled",),  # backoff/detecting are ENABLED states
                }
        
        # Port not found in output
        _LOGGER.warning("Port %d-%d not found in /proc/pse", pse_num, port_num)
        return {
            "available": False,
            "state": "unavailable",
            "class": "?",
            "power_watts": 0.0,
            "allocated_power_watts": 15.4,
            "voltage_volts": 0.0,
            "current_milliamps": 0,
            "temperature_celsius": 0.0,
        }
        
    except Exception as ex:
        _LOGGER.error("Failed to read PSE port status %s/port%d: %s", pse_id, port_num, ex)
        return {
            "available": False,
            "state": "error",
            "error": str(ex),
        }


def _parse_esp32_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse a single line from ESP32 PoE monitor output.
    
    ESP32 Protocol Format:
      Per-port: "{pse}-{port}: {state} {class} {power} {voltage} {current}/{limit} {temp} {error}"
      Per-PSE:  "{pse}: {voltage} {current}"
    
    Examples:
      "0-0: power-on 3 15 48.500 325/800 35.2 "
      "0: 48.250 1250"
    
    Args:
        line: Single line from ESP32 output
        
    Returns:
        Dictionary with parsed data or None if not a port line
    """
    # Match port line: "0-0: power-on 3 15 48.500 325/800 35.2 error_msg"
    port_pattern = r'^(\d+)-(\d+):\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)/(\S+)\s+(\S+)\s*(.*)$'
    match = re.match(port_pattern, line.strip())
    
    if not match:
        return None
    
    pse_num, port_num, state, poe_class, power_str, voltage_str, current_str, limit_str, temp_str, error = match.groups()
    
    try:
        # Parse values
        power_watts = float(power_str) if power_str != '?' else 0.0
        voltage_volts = float(voltage_str) if voltage_str != '?' else 0.0
        current_milliamps = int(float(current_str)) if current_str != '?' else 0
        temperature_celsius = float(temp_str) if temp_str != '?' else 0.0
        
        # Get allocated power based on class
        allocated_power = get_allocated_power_watts(poe_class)
        
        # Return RAW ESP32 coordinates (pse_num, port_num from ESP32)
        # Conversion to Linux port numbers happens at lookup time
        pse_num_int = int(pse_num)
        port_num_int = int(port_num)
        
        return {
            "pse_num": pse_num_int,  # ESP32 PSE number (0 or 1)
            "port_num": port_num_int,  # ESP32 port number (0-3)
            "available": True,
            "poe_system": "onboard",
            "state": state,
            "class": poe_class,
            "power_watts": round(power_watts, 2),
            "allocated_power_watts": allocated_power,
            "voltage_volts": round(voltage_volts, 2),
            "current_milliamps": current_milliamps,
            "temperature_celsius": round(temperature_celsius, 1),
            "enabled": state not in ("disabled",),
            "error": error.strip() if error else "",
        }
    except (ValueError, IndexError) as ex:
        _LOGGER.debug("Failed to parse ESP32 line '%s': %s", line, ex)
        return None


async def _read_esp32_serial_stream(pse_num: int, port_num: int) -> Optional[Dict[str, Any]]:
    """Read ESP32 PoE monitor serial stream from /dev/pse or /dev/ttyAMA3.
    
    Reads the serial stream for ~3 seconds to capture multiple update cycles.
    The ESP32 outputs port data approximately once per second, so we need
    to read long enough to catch at least one full cycle.
    
    Args:
        pse_num: PSE controller number (0 or 1)
        port_num: Port number (0-7)
        
    Returns:
        Dictionary with PoE metrics or None if not found
    """
    # Try both /dev/pse (udev symlink) and /dev/ttyAMA3 (direct UART)
    for device_path in [Path("/dev/pse"), Path("/dev/ttyAMA3")]:
        if not device_path.exists():
            continue
        
        try:
            _LOGGER.debug("Reading ESP32 stream from %s for PSE %d port %d", device_path, pse_num, port_num)
            
            # CRITICAL: ESP32 outputs at 115200 baud, must set before reading
            # Note: udev rule 60-pse.rules also sets this, but be explicit
            stty_proc = await asyncio.create_subprocess_exec(
                "stty", "-F", str(device_path), "115200", "raw", "-echo",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await stty_proc.communicate()
            
            # Read serial stream for 3 seconds to capture multiple update cycles
            # ESP32 outputs all ports once per second, so 3 seconds ensures we catch data
            proc = await asyncio.create_subprocess_exec(
                "timeout", "3", "cat", str(device_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL
            )
            
            stdout, _ = await proc.communicate()
            
            # Parse lines looking for our specific port
            # Take the most recent occurrence (last one in the stream)
            target_port_id = f"{pse_num}-{port_num}:"
            last_match = None
            for line in stdout.decode('utf-8', errors='ignore').split('\n'):
                if target_port_id in line:
                    parsed = _parse_esp32_line(line)
                    if parsed and parsed["pse_num"] == pse_num and parsed["port_num"] == port_num:
                        last_match = parsed  # Keep the most recent match
            
            if last_match:
                _LOGGER.debug("Found ESP32 data for port %s: %s", target_port_id, last_match)
                return last_match
            
            _LOGGER.debug("No ESP32 data found for %s in stream from %s", target_port_id, device_path)
            
        except Exception as ex:
            _LOGGER.debug("Failed to read ESP32 stream from %s: %s", device_path, ex)
            continue
    
    return None


async def _try_read_cruiser_pse_data(port_num: int) -> Optional[Dict[str, Any]]:
    """Try to read power data from Cruiser's ESP32 serial stream.
    
    CRITICAL ARCHITECTURE:
    - Cruiser: TPS23861 → ESP32-C6 (I2C) → CM5 (UART3) → /dev/ttyAMA3
    - Data format: Text lines from ESP32 firmware
    - ESP32 firmware reads TPS23861 and streams formatted data over UART
    
    ESP32 Protocol Format:
      "{pse}-{port}: {state} {class} {power} {voltage} {current}/{limit} {temp} {error}"
      Example: "0-0: power-on 3 15 48.500 325/800 35.2 "
    
    Args:
        port_num: Port number (0-7)
    
    Returns:
        Dictionary with power data if available, None if ESP32 not running
    """
    # CRITICAL: Hardware PSE-to-Port Mapping
    # Physical layout (looking at back of board):
    #   P1  P3  P5  P7
    #   P2  P4  P6  P8
    #
    # PSE Mapping:
    #   PSE 1 (left side)  → P1-P4 → Linux poe0-3
    #   PSE 0 (right side) → P5-P8 → Linux poe4-7
    #
    # Conversion: Linux port 0-7 → ESP32 PSE-port
    pse_num = 1 if port_num < 4 else 0  # Ports 0-3 use PSE1, ports 4-7 use PSE0
    pse_port_num = port_num % 4  # Local port number on PSE controller
    
    # Try to read from ESP32 serial stream
    esp32_data = await _read_esp32_serial_stream(pse_num, pse_port_num)
    if esp32_data:
        return esp32_data
    
    # ESP32 not running or no data - return None
    # The caller will fall back to network-only data
    _LOGGER.debug("ESP32 data not available for port %d (PSE %d, local port %d)", 
                  port_num, pse_num, pse_port_num)
    return None


async def read_network_port_status(interface: str, esp32_data_map: Optional[Dict[tuple[int, int], Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Read onboard PoE network interface status (Cruiser Carrier Board).
    
    Tries to read real power data from Cruiser's /dev/pse* interface (when available).
    Falls back to network-only data if power interface not ready.
    
    CRITICAL: Cruiser uses /dev/pse* (NOT /proc/pse*)!
    
    Args:
        interface: Network interface name (e.g., "poe0")
    
    Returns:
        Dictionary with port status information
    """
    try:
        # Check if interface exists
        sys_net_path = Path(f"/sys/class/net/{interface}")
        if not sys_net_path.exists():
            return {
                "available": False,
                "state": "unavailable",
                "link_state": "down",
            }
        
        # Extract port number from interface name (e.g., "poe0" -> 0)
        port_num = int(interface.replace("poe", ""))
        
        # Try to get ESP32 data from the shared map (if provided)
        # Otherwise, try reading directly (fallback for backward compatibility)
        real_power_data = None
        if esp32_data_map is not None:
            # Use pre-read ESP32 data to avoid serial port conflicts
            # PSE mapping: PSE 1 (left) = ports 0-3, PSE 0 (right) = ports 4-7
            pse_num = 1 if port_num < 4 else 0  # CORRECT: PSE1 for ports 0-3, PSE0 for ports 4-7
            pse_port_num = port_num % 4
            real_power_data = esp32_data_map.get((pse_num, pse_port_num))
        else:
            # Fallback: read directly (may conflict with parallel reads)
            real_power_data = await _try_read_cruiser_pse_data(port_num)
        
        # Read link state (operational state)
        operstate_file = sys_net_path / "operstate"
        link_state = "unknown"
        if operstate_file.exists():
            link_state = (await asyncio.to_thread(operstate_file.read_text)).strip()
        
        # Read administrative state (is interface enabled?)
        flags_file = sys_net_path / "flags"
        admin_up = False
        if flags_file.exists():
            try:
                flags_hex = (await asyncio.to_thread(flags_file.read_text)).strip()
                flags = int(flags_hex, 16)
                # IFF_UP flag is 0x1
                admin_up = bool(flags & 0x1)
            except (ValueError, OSError):
                # Fallback: if operstate is 'up' or 'lowerlayerdown', interface is admin up
                admin_up = link_state in ("up", "lowerlayerdown")
        
        # Read speed (if link is up)
        speed_mbps = 0
        if link_state == "up":
            speed_file = sys_net_path / "speed"
            if speed_file.exists():
                try:
                    speed_text = (await asyncio.to_thread(speed_file.read_text)).strip()
                    speed_mbps = int(speed_text)
                except (ValueError, OSError):
                    pass
        
        # Read statistics
        stats_path = sys_net_path / "statistics"
        rx_bytes = 0
        tx_bytes = 0
        if stats_path.exists():
            rx_file = stats_path / "rx_bytes"
            tx_file = stats_path / "tx_bytes"
            if rx_file.exists():
                try:
                    rx_bytes = int((await asyncio.to_thread(rx_file.read_text)).strip())
                except (ValueError, OSError):
                    pass
            if tx_file.exists():
                try:
                    tx_bytes = int((await asyncio.to_thread(tx_file.read_text)).strip())
                except (ValueError, OSError):
                    pass
        
        # Try to get connected device from ARP table
        connected_device = await _get_connected_device_from_arp(interface)
        
        # Try Bosch camera detection if:
        # 1. No ARP entry but traffic exists (camera uses non-IP protocol only)
        # 2. OR ARP entry exists but manufacturer is Unknown (camera might use dual-mode)
        should_try_bosch = False
        if not connected_device and link_state == "up" and (rx_bytes > MIN_TRAFFIC_BYTES or tx_bytes > MIN_TRAFFIC_BYTES):
            _LOGGER.debug("No ARP entry for %s but traffic detected (%d RX, %d TX bytes), trying Bosch detection", 
                         interface, rx_bytes, tx_bytes)
            should_try_bosch = True
        elif connected_device and connected_device.get("manufacturer") == "Unknown" and link_state == "up":
            _LOGGER.debug("Unknown manufacturer for %s (MAC: %s), trying Bosch detection", 
                         interface, connected_device.get("mac_address", "N/A"))
            should_try_bosch = True
        
        if should_try_bosch:
            bosch_info = await _detect_bosch_camera(interface)
            if bosch_info:
                # Merge Bosch info with existing device info (if any)
                if connected_device:
                    # Keep IP and MAC from ARP, update manufacturer/model from Bosch
                    connected_device.update({
                        "name": f"{bosch_info['model']} on {interface}",
                        "device_type": bosch_info['device_type'],
                        "manufacturer": bosch_info['manufacturer'],
                        "model": bosch_info['model'],
                        "detection_method": bosch_info['detection_method'],
                    })
                else:
                    # Create new device info from Bosch detection
                    connected_device = {
                        "name": f"{bosch_info['model']} on {interface}",
                        "device_type": bosch_info['device_type'],
                        "manufacturer": bosch_info['manufacturer'],
                        "model": bosch_info['model'],
                        "detection_method": bosch_info['detection_method'],
                        "ip_address": "N/A (Proprietary Protocol)",  # Bosch uses non-IP protocol (ethertype 0x2070)
                        "mac_address": "N/A (Proprietary Protocol)",  # Not available from L2 broadcast
                    }
        
        # Use real power data if available, otherwise mock it
        if real_power_data:
            # Real power data from ESP32/TPS23861
            _LOGGER.debug("Using real power data for %s", interface)
            poe_class = real_power_data.get("class", "?")
            allocated_power = get_allocated_power_watts(poe_class)
            
            # CRITICAL: Admin state overrides hardware state.
            # When the user disables a port via `ip link set down`, the
            # TPS23861 PSE chip continues delivering power (no software
            # path to cut it yet), so the ESP32 still reports "power on".
            # We override to "disabled" so the UI reflects the user's intent.
            hw_state = real_power_data["state"]
            state = "disabled" if not admin_up else hw_state
            
            return {
                "available": True,
                "poe_system": "onboard",
                "state": state,
                "link_state": link_state,
                "speed_mbps": speed_mbps,
                "rx_bytes": rx_bytes,
                "tx_bytes": tx_bytes,
                "connected_device": connected_device,
                "power_watts": real_power_data["power_watts"],
                "allocated_power_watts": allocated_power,
                "voltage_volts": real_power_data["voltage_volts"],
                "current_milliamps": real_power_data["current_milliamps"],
                "temperature_celsius": real_power_data.get("temperature_celsius", 0.0),
                "class": poe_class,
                "enabled": admin_up,
            }
        else:
            # Fallback: Mock power metrics (ESP32 data not available)
            _LOGGER.debug("Using mocked power data for %s (ESP32 data not available)", interface)
            power_watts_mocked = 0.0
            poe_class_mocked = "?"  # Unknown class when mocking
            
            if link_state == "up":
                # Estimate based on speed
                if speed_mbps >= 1000:
                    power_watts_mocked = 12.5  # Typical PoE camera at 1Gbps
                    poe_class_mocked = "3"  # Assume Class 3 for high-power devices
                elif speed_mbps > 0:
                    power_watts_mocked = 8.0   # Lower speed device
                    poe_class_mocked = "2"  # Assume Class 2 for medium-power devices
            
            allocated_power_mocked = get_allocated_power_watts(poe_class_mocked)
            
            # Determine state based on admin state first, then link state
            # This fixes the issue where disabled ports showed "empty" instead of "disabled"
            if not admin_up:
                state = "disabled"  # Administratively disabled
            elif link_state == "up":
                state = "power on"  # Device connected and powered
            else:
                state = "searching"  # Enabled but no device connected
            
            return {
                "available": True,
                "poe_system": "onboard",
                "state": state,
                "link_state": link_state,
                "speed_mbps": speed_mbps,
                "rx_bytes": rx_bytes,
                "tx_bytes": tx_bytes,
                "connected_device": connected_device,
                "power_watts": round(power_watts_mocked, 2),
                "allocated_power_watts": allocated_power_mocked,
                "power_mocked": True,  # Flag to indicate mocked power
                "voltage_volts": 48.0 if link_state == "up" else 0.0,  # Mocked
                "current_milliamps": int((power_watts_mocked / 48.0) * 1000) if link_state == "up" else 0,  # Mocked
                "class": poe_class_mocked,
                "enabled": admin_up,
            }
        
    except Exception as ex:
        _LOGGER.error("Failed to read network port status %s: %s", interface, ex)
        return {
            "available": False,
            "state": "error",
            "error": str(ex),
        }


async def _get_connected_device_from_arp(interface: str) -> Optional[Dict[str, str]]:
    """Get connected device information from ARP table with enrichment.
    
    Args:
        interface: Network interface name
    
    Returns:
        Dictionary with device IP, MAC, manufacturer, and hostname (if available)
    """
    try:
        # Run: ip neigh show dev poe0
        proc = await asyncio.create_subprocess_exec(
            "ip", "neigh", "show", "dev", interface,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        
        if proc.returncode != 0:
            return None
        
        output = stdout.decode().strip()
        if not output:
            return None
        
        # Parse ARP/NDP entry - supports both IPv4 and IPv6
        # IPv4 example: 192.168.1.100 lladdr 00:13:e2:1f:bc:b9 REACHABLE
        # IPv6 example: fe80::2652:6aff:fe08:7180 lladdr 24:52:6a:08:71:80 STALE
        
        # Try IPv4 first
        ipv4_match = re.search(r"(\d+\.\d+\.\d+\.\d+)\s+lladdr\s+([\da-f:]+)\s+(REACHABLE|STALE|DELAY)", output, re.IGNORECASE)
        if ipv4_match:
            device_info = {
                "ip_address": ipv4_match.group(1),
                "mac_address": ipv4_match.group(2),
                "arp_state": ipv4_match.group(3).upper(),
            }
            
            # Enrich with manufacturer and hostname
            enriched_info = await enrich_device_info(device_info)
            
            # VCS Video Communication Systems is used by Bosch cameras
            # Verify if this VCS device is actually a Bosch camera via tcpdump
            manufacturer = enriched_info.get("manufacturer", "") if enriched_info else ""
            if manufacturer.startswith("VCS Video Communication Systems"):
                _LOGGER.debug("VCS device detected on %s, checking if it's a Bosch camera", interface)
                bosch_info = await _detect_bosch_camera(interface)
                if bosch_info:
                    _LOGGER.info("Confirmed VCS device on %s is a Bosch camera: %s", interface, bosch_info.get("model", "Unknown"))
                    # Replace VCS with Bosch in manufacturer field
                    enriched_info["manufacturer"] = "Bosch"
                    enriched_info["model"] = bosch_info.get("model", "Camera")
            
            return enriched_info
        
        # Try IPv6 (neighbor discovery)
        ipv6_match = re.search(r"([\da-f:]+)\s+lladdr\s+([\da-f:]+)\s+(REACHABLE|STALE|DELAY|PROBE|INCOMPLETE|FAILED)", output, re.IGNORECASE)
        if ipv6_match:
            ipv6_addr = ipv6_match.group(1)
            mac_addr = ipv6_match.group(2)
            
            # Validate it's actually IPv6 (contains multiple colons, not a MAC)
            if ipv6_addr.count(':') >= 2:
                device_info = {
                    "ip_address": ipv6_addr,
                    "mac_address": mac_addr,
                    "arp_state": ipv6_match.group(3).upper(),
                }
                
                # Enrich with manufacturer and hostname
                enriched_info = await enrich_device_info(device_info)
                
                # VCS Video Communication Systems is used by Bosch cameras
                # Verify if this VCS device is actually a Bosch camera via tcpdump
                manufacturer = enriched_info.get("manufacturer", "") if enriched_info else ""
                if manufacturer.startswith("VCS Video Communication Systems"):
                    _LOGGER.debug("VCS device detected on %s, checking if it's a Bosch camera", interface)
                    bosch_info = await _detect_bosch_camera(interface)
                    if bosch_info:
                        _LOGGER.info("Confirmed VCS device on %s is a Bosch camera: %s", interface, bosch_info.get("model", "Unknown"))
                        # Replace VCS with Bosch in manufacturer field
                        enriched_info["manufacturer"] = "Bosch"
                        enriched_info["model"] = bosch_info.get("model", "Camera")
                
                return enriched_info
        
        return None
        
    except Exception as ex:
        _LOGGER.debug("Failed to get ARP info for %s: %s", interface, ex)
        return None


async def _detect_bosch_camera(interface: str) -> Optional[Dict[str, str]]:
    """Detect Bosch camera via proprietary protocol packet capture.
    
    Bosch cameras use ethertype 0x2070 and broadcast discovery packets
    containing manufacturer and model information in plaintext.
    
    Args:
        interface: Network interface name
    
    Returns:
        Dictionary with manufacturer and model info, or None if not Bosch
    """
    try:
        # Capture a few packets to look for Bosch protocol
        # Note: tcpdump requires root privileges, so we use sudo
        proc = await asyncio.create_subprocess_exec(
            "sudo", "timeout", str(TCPDUMP_TIMEOUT),
            "tcpdump", "-i", interface,
            "-c", str(BOSCH_PACKET_COUNT),  # Capture packets for detection
            "-XX",  # Hex dump with ASCII
            "-n",  # Don't resolve names
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        
        # timeout returns 124 if it timed out, 0 if tcpdump finished naturally
        if proc.returncode not in (0, 124):
            return None
        
        output = stdout.decode(errors='ignore')
        
        # Look for Bosch signatures in the capture
        if 'Bosch' in output or 'FLEXIDOME' in output or 'DINION' in output or 'AUTODOME' in output:
            # Try to extract model name
            model = "Unknown Model"
            manufacturer = "Bosch Security Systems"
            device_type = "Camera"
            
            # Common Bosch camera model patterns
            patterns = [
                r'(FLEXIDOME[^\\n]*)',
                r'(DINION[^\\n]*)',
                r'(AUTODOME[^\\n]*)',
                r'(MIC[^\\n]*)',  # Bosch MIC series
                r'(NBN[^\\n]*)',  # Bosch NBN series
            ]
            
            for pattern in patterns:
                match = re.search(pattern, output, re.IGNORECASE)
                if match:
                    model = match.group(1).strip()
                    # Clean up common artifacts
                    model = re.sub(r'[^\x20-\x7E]+', ' ', model)  # Remove non-printable
                    model = model.strip()
                    break
            
            _LOGGER.info("Detected Bosch camera on %s: %s", interface, model)
            
            return {
                "manufacturer": manufacturer,
                "model": model,
                "device_type": device_type,
                "detection_method": "Bosch proprietary protocol",
            }
        
        return None
        
    except Exception as ex:
        _LOGGER.debug("Failed to detect Bosch camera on %s: %s", interface, ex)
        return None


def _parse_field(text: str, pattern: str) -> Optional[str]:
    """Parse a field from status text using regex.
    
    Args:
        text: Text to parse
        pattern: Regex pattern with one capture group
    
    Returns:
        Captured value or None if not found
    """
    match = re.search(pattern, text)
    return match.group(1).strip() if match else None


async def read_all_addon_ports(pse_id: str, port_count: int = 8) -> Dict[int, Dict[str, Any]]:
    """Read all ports for an add-on PoE board.
    
    Args:
        pse_id: PSE controller ID (e.g., "pse0")
        port_count: Number of ports to read (default 8)
    
    Returns:
        Dictionary mapping port number to port status
    """
    tasks = [
        read_pse_port_status(pse_id, port_num)
        for port_num in range(port_count)
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    port_data = {}
    for port_num, result in enumerate(results):
        if isinstance(result, Exception):
            _LOGGER.error("Failed to read port %s/%d: %s", pse_id, port_num, result)
            port_data[port_num] = {
                "available": False,
                "state": "error",
                "error": str(result),
            }
        else:
            # Add-on boards have network interfaces: pse0 -> poe0-X, pse1 -> poe1-X
            pse_num = pse_id.replace("pse", "")
            interface = f"poe{pse_num}-{port_num}"
            
            # Check for connected device via ARP (same as onboard ports)
            port_status = result.copy()
            if port_status.get("available", False):
                device_info = await _get_connected_device_from_arp(interface)
                if device_info:
                    port_status["connected_device"] = device_info
            
            port_data[port_num] = port_status
    
    return port_data


async def _read_all_esp32_data() -> Dict[tuple[int, int], Dict[str, Any]]:
    """Read all ESP32 data in one pass to avoid serial port conflicts.
    
    Returns:
        Dictionary mapping (pse_num, port_num) to port data
    """
    esp32_data = {}
    
    # Try both /dev/pse (udev symlink) and /dev/ttyAMA3 (direct UART)
    for device_path in [Path("/dev/pse"), Path("/dev/ttyAMA3")]:
        if not device_path.exists():
            continue
        
        try:
            _LOGGER.debug("Reading ESP32 stream from %s for all ports", device_path)
            
            # Configure serial port for ESP32 (115200 baud, raw mode, no echo)
            stty_proc = await asyncio.create_subprocess_exec(
                "stty", "-F", str(device_path), "115200", "raw", "-echo",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await stty_proc.communicate()
            
            # Read serial stream for 3 seconds to capture multiple update cycles
            proc = await asyncio.create_subprocess_exec(
                "timeout", "3", "cat", str(device_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL
            )
            
            stdout, _ = await proc.communicate()
            
            # Parse all port lines from the stream
            # Keep the most recent data for each port
            for line in stdout.decode('utf-8', errors='ignore').split('\n'):
                parsed = _parse_esp32_line(line)
                if parsed:
                    key = (parsed["pse_num"], parsed["port_num"])
                    esp32_data[key] = parsed  # Keep most recent
            
            if esp32_data:
                _LOGGER.debug("Found ESP32 data for %d ports", len(esp32_data))
                break  # Successfully read data, no need to try other device
            
        except Exception as ex:
            _LOGGER.debug("Failed to read ESP32 stream from %s: %s", device_path, ex)
            continue
    
    return esp32_data


async def read_all_onboard_ports(interfaces: list[str]) -> Dict[str, Dict[str, Any]]:
    """Read all onboard PoE network interfaces.
    
    Reads ESP32 data once for all ports to avoid serial port conflicts,
    then reads network status for each interface.
    
    Args:
        interfaces: List of interface names (e.g., ["poe0", "poe1", ...])
    
    Returns:
        Dictionary mapping interface name to port status
    """
    # Read all ESP32 data in one pass
    esp32_data_map = await _read_all_esp32_data()
    
    # Now read network status for each interface (can be parallel)
    tasks = [
        read_network_port_status(interface, esp32_data_map)
        for interface in interfaces
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    port_data = {}
    for interface, result in zip(interfaces, results):
        if isinstance(result, Exception):
            _LOGGER.error("Failed to read interface %s: %s", interface, result)
            port_data[interface] = {
                "available": False,
                "state": "error",
                "error": str(result),
            }
        else:
            port_data[interface] = result
    
    return port_data

