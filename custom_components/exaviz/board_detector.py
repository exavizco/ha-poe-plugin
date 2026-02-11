"""Board detection for Axzez Interceptor and Cruiser carrier boards.

Prerequisites:
  This integration requires the following Exaviz packages from
  apt.exaviz.com to be installed on the host OS:

    - exaviz-dkms    (kernel modules, device tree overlays, udev rules)
    - exaviz-netplan  (per-port network configuration with DHCP servers)

  These packages are required on BOTH Cruiser and Interceptor boards,
  regardless of the base OS.  The deprecated pre-built Exaviz OS images
  are not supported.

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
from typing import Any, List, Optional

_LOGGER = logging.getLogger(__name__)

# Required Exaviz host packages.  Both are needed on Cruiser and
# Interceptor — exaviz-dkms provides kernel modules (ip179h DSA switch,
# ip808ar PSE controller, ESP32 SDIO) and device tree overlays;
# exaviz-netplan provides per-port network configuration (subnets,
# DHCP servers for connected devices).
REQUIRED_PACKAGES = ("exaviz-dkms", "exaviz-netplan")


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

    Docker note: Docker's device passthrough resolves symlinks, so
    /dev/pse (a symlink to ttyAMA3) appears as /dev/ttyAMA3 inside the
    container.  We check both paths for Cruiser detection.
    """
    dev_pse = Path("/dev/pse")
    dev_ttyama3 = Path("/dev/ttyAMA3")
    proc_pse = Path("/proc/pse")

    if dev_pse.exists():
        _LOGGER.info("Detected Cruiser board via /dev/pse symlink")
        return BoardType.CRUISER

    if dev_ttyama3.exists():
        _LOGGER.info(
            "Detected Cruiser board via /dev/ttyAMA3 "
            "(Docker resolves /dev/pse symlink to the real device)"
        )
        return BoardType.CRUISER

    if proc_pse.exists():
        _LOGGER.info("Detected Interceptor board via /proc/pse")
        return BoardType.INTERCEPTOR

    return None


async def check_prerequisites() -> dict[str, Any]:
    """Verify that required Exaviz host packages are installed.

    Returns a dict with:
      packages:  {pkg_name: version_str | None}
      missing:   list of package names that are not installed
      all_ok:    True if every required package is present

    This check runs ``dpkg-query`` which is available on all Debian-based
    systems.  Inside a Docker container the host packages are invisible,
    so a missing result there is expected — the check is a best-effort
    hint, not a hard gate.
    """
    result: dict[str, Any] = {"packages": {}, "missing": [], "all_ok": True}

    for pkg in REQUIRED_PACKAGES:
        try:
            proc = await asyncio.create_subprocess_exec(
                "dpkg-query", "-W", "-f", "${Version}", pkg,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0 and stdout:
                result["packages"][pkg] = stdout.decode().strip()
            else:
                result["packages"][pkg] = None
                result["missing"].append(pkg)
                result["all_ok"] = False
        except OSError:
            # dpkg-query not available (unlikely on Debian, possible in
            # minimal containers).  Don't block setup.
            result["packages"][pkg] = None
            result["missing"].append(pkg)
            result["all_ok"] = False

    if result["all_ok"]:
        _LOGGER.info(
            "Exaviz prerequisites OK: %s",
            ", ".join(f"{k} {v}" for k, v in result["packages"].items()),
        )
    else:
        _LOGGER.warning(
            "Missing required Exaviz packages: %s. "
            "Install them from apt.exaviz.com — see "
            "https://exa-pedia.com/docs/software/apt-repository/ "
            "for instructions. If running Home Assistant in Docker, "
            "the packages must be installed on the HOST OS, not "
            "inside the container.",
            ", ".join(result["missing"]),
        )

    return result


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

    The IP808AR kernel driver (v2.0) exposes a single streaming file at
    /proc/pse — NOT per-PSE directories like /proc/pse0/port0/.  Each PSE
    controller is identified by the prefix in the data lines (e.g., "0-3:"
    for PSE 0 port 3, "1-0:" for PSE 1 port 0).

    Detection strategy:
      1. Check if /proc/pse exists (streaming file from ip808ar driver)
      2. Read the header + first batch of port lines
      3. Determine which PSE controllers are present from the port prefixes

    Returns:
        List of PSE identifiers (e.g., ["pse0"] or ["pse0", "pse1"])
    """
    addon_boards = []

    try:
        pse_file = Path("/proc/pse")

        if not pse_file.exists():
            _LOGGER.debug("No add-on PoE boards detected (/proc/pse not found)")
            return []

        # /proc/pse is a streaming file — read a limited number of lines
        # to avoid blocking.  30 lines is enough for 2 full PSE cycles
        # (header + 8 ports + summary per PSE × 2).
        import subprocess
        result = await asyncio.to_thread(
            subprocess.run,
            ["head", "-30", str(pse_file)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        pse_text = result.stdout

        if not pse_text:
            _LOGGER.debug("/proc/pse exists but returned no data")
            return []

        # Scan port lines to discover which PSE controllers are present.
        # Port lines match: "0-3: power-on 0 15.50 ..."  (PSE 0, port 3)
        pse_ids_found: set[int] = set()
        for line in pse_text.splitlines():
            match = re.match(r"^(\d+)-\d+:", line.strip())
            if match:
                pse_ids_found.add(int(match.group(1)))

        for pse_num in sorted(pse_ids_found):
            pse_id = f"pse{pse_num}"
            addon_boards.append(pse_id)
            _LOGGER.info(
                "Detected add-on PoE board: %s (via /proc/pse streaming file)",
                pse_id,
            )

        if not addon_boards:
            _LOGGER.debug(
                "/proc/pse exists but no port lines found — "
                "driver may still be initialising"
            )

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

    On an Interceptor, the poe0-poe7 network interfaces are created by
    the IP179H DSA switch on the add-on PSE board.  Their power data comes
    from /proc/pse (IP808AR), so they must be handled via the addon path.
    We detect them as network interfaces (for ARP / link state) but do NOT
    count them as separate onboard ports.

    On a Cruiser, the poe0-poe7 interfaces are true onboard DSA ports and
    power data comes from the ESP32 (/dev/pse).  No addon boards exist.

    Returns:
        Dictionary with board type, add-on boards, and onboard ports
    """
    board_type = await detect_board_type()
    addon_boards = await detect_addon_boards()
    onboard_ports = await detect_onboard_poe()

    # On Interceptor, the poe network interfaces are created by the
    # add-on PSE board's IP179H DSA switch — they are NOT onboard ports.
    # On Cruiser, the poe interfaces are true onboard DSA ports even
    # when an add-on board is also present, so we must keep them.
    if addon_boards and board_type != BoardType.CRUISER:
        if onboard_ports:
            _LOGGER.info(
                "Add-on PoE boards detected on %s — poe interfaces (%s) "
                "are addon ports, not onboard. Clearing onboard list.",
                board_type.value,
                ", ".join(onboard_ports),
            )
        onboard_ports = []

    # Calculate total port count
    total_ports = 0
    total_ports += len(addon_boards) * 8
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
