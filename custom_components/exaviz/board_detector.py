"""Board detection for Axzez Interceptor and Cruiser carrier boards.

Detection uses a 3-tier fallback chain:
  1. /proc/device-tree/chosen/board (device tree property, if present)
  2. /boot/firmware/config.txt dtoverlay line (set by exaviz-dkms postinst)
  3. /dev/pse (Cruiser udev symlink) vs /proc/pse (Interceptor kernel driver)
"""
from __future__ import annotations

import asyncio
import logging
import re
from enum import Enum
from pathlib import Path
from typing import List, Optional

_LOGGER = logging.getLogger(__name__)


class BoardType(Enum):
    """Board type enumeration."""
    INTERCEPTOR = "interceptor"
    CRUISER = "cruiser"
    UNKNOWN = "unknown"


class PoESystemType(Enum):
    """PoE system type enumeration."""
    ADDON_IP808AR = "addon"      # /proc/pse* controllers (IP808ar PSE)
    ONBOARD_NETWORK = "onboard"  # Network interfaces (poe0-poe7)


async def _detect_from_device_tree() -> Optional[BoardType]:
    """Tier 1: Detect board type from device tree property.

    Some boards set /proc/device-tree/chosen/board via the DT overlay.
    This is the fastest and most direct method when available.
    """
    board_file = Path("/proc/device-tree/chosen/board")

    try:
        if not board_file.exists():
            return None

        board_name = await asyncio.to_thread(board_file.read_text)
        board_name = board_name.strip().lower()

        if not board_name:
            return None

        if board_name.startswith("interceptor"):
            _LOGGER.info("Detected Interceptor board via device tree: %s", board_name)
            return BoardType.INTERCEPTOR

        _LOGGER.info("Detected Cruiser board via device tree: %s", board_name)
        return BoardType.CRUISER

    except Exception as ex:
        _LOGGER.debug("Device tree board detection failed: %s", ex)
        return None


async def _detect_from_config_txt() -> Optional[BoardType]:
    """Tier 2: Detect board type from /boot/firmware/config.txt.

    The exaviz-dkms postinst script writes a dtoverlay line like:
        dtoverlay=cruiser-raspberrypi-cm5,...
    or:
        dtoverlay=interceptor-raspberrypi-cm5,...

    This file is world-readable and always present on Exaviz boards.
    """
    config_file = Path("/boot/firmware/config.txt")

    try:
        if not config_file.exists():
            return None

        content = await asyncio.to_thread(config_file.read_text)

        # Look for dtoverlay=cruiser- or dtoverlay=interceptor-
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue

            if re.match(r"dtoverlay=cruiser-", stripped):
                _LOGGER.info(
                    "Detected Cruiser board via config.txt: %s",
                    stripped.split(",")[0],
                )
                return BoardType.CRUISER

            if re.match(r"dtoverlay=interceptor-", stripped):
                _LOGGER.info(
                    "Detected Interceptor board via config.txt: %s",
                    stripped.split(",")[0],
                )
                return BoardType.INTERCEPTOR

        return None

    except Exception as ex:
        _LOGGER.debug("config.txt board detection failed: %s", ex)
        return None


async def _detect_from_pse_interface() -> Optional[BoardType]:
    """Tier 3: Detect board type from PoE interface presence.

    - Cruiser: /dev/pse exists (udev symlink to ttyAMA3, rule 60-pse.rules)
    - Interceptor: /proc/pse exists (ip808ar kernel driver procfs)

    These are mutually exclusive on current hardware.
    """
    dev_pse = Path("/dev/pse")
    proc_pse = Path("/proc/pse")

    if dev_pse.exists():
        _LOGGER.info("Detected Cruiser board via /dev/pse symlink")
        return BoardType.CRUISER

    if proc_pse.exists():
        _LOGGER.info("Detected Interceptor board via /proc/pse")
        return BoardType.INTERCEPTOR

    return None


async def detect_board_type() -> BoardType:
    """Detect board type using a 3-tier fallback chain.

    1. /proc/device-tree/chosen/board (DT property, backward compat)
    2. /boot/firmware/config.txt dtoverlay (set by exaviz-dkms)
    3. /dev/pse (Cruiser) vs /proc/pse (Interceptor)

    Returns:
        BoardType enum value
    """
    # Tier 1: Device tree property
    result = await _detect_from_device_tree()
    if result:
        return result

    # Tier 2: config.txt dtoverlay
    result = await _detect_from_config_txt()
    if result:
        return result

    # Tier 3: PoE interface presence
    result = await _detect_from_pse_interface()
    if result:
        return result

    _LOGGER.warning(
        "Board type could not be determined. Checked: "
        "/proc/device-tree/chosen/board, /boot/firmware/config.txt, "
        "/dev/pse and /proc/pse. Is exaviz-dkms installed?"
    )
    return BoardType.UNKNOWN


async def detect_addon_boards() -> List[str]:
    """Detect add-on PoE boards (IP808ar PSE controllers).

    Checks known /proc/pse{N} paths directly (max 2 PSE boards supported).
    Avoids scanning all of /proc which triggers a blocking I/O warning in HA.

    Returns:
        List of PSE identifiers (e.g., ["pse0", "pse1"])
    """
    addon_boards = []

    try:
        # Check specific paths directly instead of scanning /proc
        # Maximum of 2 add-on PSE boards supported (pse0, pse1)
        for pse_idx in range(2):
            pse_dir = Path(f"/proc/pse{pse_idx}")
            if not pse_dir.is_dir():
                continue

            pse_id = pse_dir.name

            # Verify it has port subdirectories by checking known paths
            # directly (max 8 ports per PSE board) to avoid iterdir()
            port_count = sum(
                1 for port_idx in range(8)
                if (pse_dir / f"port{port_idx}").is_dir()
            )
            if port_count > 0:
                addon_boards.append(pse_id)
                _LOGGER.info(
                    "Detected add-on PoE board: %s (%d ports)",
                    pse_id, port_count,
                )

        if not addon_boards:
            _LOGGER.debug("No add-on PoE boards detected")

        return sorted(addon_boards)

    except Exception as ex:
        _LOGGER.error("Failed to detect add-on boards: %s", ex)
        return []


async def detect_onboard_poe() -> List[str]:
    """Detect onboard PoE ports via network interfaces.

    Scans /proc/sys/net/ipv4/conf/poe* to find PoE network interfaces.
    On Cruiser boards these are real DSA ports created by the device tree
    overlay (cruiser-raspberrypi-cm5.dtbo) and managed by exaviz-dkms.

    Returns:
        List of interface names (e.g., ["poe0", "poe1", ..., "poe7"])
    """
    conf_path = Path("/proc/sys/net/ipv4/conf")
    onboard_ports = []

    try:
        if not conf_path.exists():
            _LOGGER.debug("Network config path not found: %s", conf_path)
            return []

        # Check specific poe interface paths directly instead of scanning
        # the directory (avoids blocking I/O warning in HA).
        # Maximum 16 onboard ports (poe0 through poe15).
        for i in range(16):
            poe_path = conf_path / f"poe{i}"
            if poe_path.is_dir():
                onboard_ports.append(f"poe{i}")

        if onboard_ports:
            _LOGGER.info(
                "Detected onboard PoE ports: %s (%d ports)",
                ", ".join(sorted(onboard_ports)), len(onboard_ports),
            )
        else:
            _LOGGER.warning(
                "No onboard PoE interfaces found. "
                "Verify exaviz-dkms is installed and the device tree "
                "overlay is loaded (check /boot/firmware/config.txt)."
            )

        return sorted(onboard_ports)

    except Exception as ex:
        _LOGGER.error("Failed to detect onboard PoE ports: %s", ex)
        return []


async def detect_all_poe_systems() -> dict:
    """Detect all PoE systems on the board.

    Returns:
        Dictionary with board type, add-on boards, and onboard ports
    """
    board_type = await detect_board_type()
    addon_boards = await detect_addon_boards()
    onboard_ports = await detect_onboard_poe()

    # Calculate total port count
    total_ports = 0

    # Add-on boards typically have 8 ports each
    total_ports += len(addon_boards) * 8

    # Onboard ports counted from actual interfaces detected
    onboard_port_count = len(onboard_ports)
    total_ports += onboard_port_count

    result = {
        "board_type": board_type,
        "addon_boards": addon_boards,
        "onboard_ports": onboard_ports,
        "total_poe_ports": total_ports,
    }

    _LOGGER.info(
        "PoE detection complete: %s board with %d total PoE ports "
        "(%d add-on, %d onboard)",
        board_type.value,
        total_ports,
        len(addon_boards) * 8,
        onboard_port_count,
    )

    return result
