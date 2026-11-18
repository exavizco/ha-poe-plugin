"""Board detection against a fake filesystem under tmp_path.

Every absolute path that board_detector builds with Path("/...") is
redirected to the same path under a temporary root, so the real detection
code reads real files: device tree board name, config.txt, the /proc/pse
streaming text and the /proc/sys/net/ipv4/conf/poeN directories.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.exaviz import board_detector
from custom_components.exaviz.board_detector import (
    BoardType,
    check_prerequisites,
    detect_addon_boards,
    detect_all_poe_systems,
    detect_board_type,
    detect_onboard_poe,
)
from tests import fake_dpkg
from tests.module_asyncio import patch_module_asyncio

pytestmark = pytest.mark.asyncio

# Two PSE controllers as the ip808ar driver streams them (header, port
# lines prefixed "<pse>-<port>:", summary).
PROC_PSE_TWO_CONTROLLERS = """\
IP808AR PSE status v2.0
0-0: power-on 0 15.50 48.10 120
0-1: searching 0 0.00 0.00 0
0-2: searching 0 0.00 0.00 0
0-3: power-on 3 6.20 48.00 130
total: 21.70
1-0: searching 0 0.00 0.00 0
1-1: power-on 2 4.10 48.20 85
total: 4.10
"""


@pytest.fixture
def fake_root(tmp_path: Path):
    """Redirect board_detector's absolute paths into tmp_path."""

    def rooted(path: str) -> Path:
        return tmp_path / path.lstrip("/")

    with patch.object(board_detector, "Path", side_effect=rooted):
        yield tmp_path


def write(root: Path, path: str, text: str) -> Path:
    target = root / path.lstrip("/")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    return target


# --- tier 1: device tree ------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        # Device tree string properties are NUL terminated.
        ("interceptor\x00", BoardType.INTERCEPTOR),
        ("Interceptor-CM5\n", BoardType.INTERCEPTOR),
        ("cruiser\x00", BoardType.CRUISER),
        # Any other non-empty name is treated as a Cruiser.
        ("exaviz-board\n", BoardType.CRUISER),
    ],
)
async def test_device_tree_names_the_board(fake_root, content, expected):
    write(fake_root, "/proc/device-tree/chosen/board", content)
    # config.txt and /proc/pse say the opposite, so a pass proves tier 1 won.
    write(fake_root, "/boot/firmware/config.txt", "dtoverlay=cruiser-raspberrypi-cm5\n")
    write(fake_root, "/proc/pse", "")
    assert await board_detector._detect_from_device_tree() is expected
    assert await detect_board_type() is expected


async def test_empty_device_tree_name_falls_through_to_config_txt(fake_root):
    write(fake_root, "/proc/device-tree/chosen/board", "  \n")
    write(fake_root, "/boot/firmware/config.txt", "dtoverlay=interceptor-raspberrypi-cm5\n")
    assert await board_detector._detect_from_device_tree() is None
    assert await detect_board_type() is BoardType.INTERCEPTOR


async def test_unreadable_device_tree_entry_is_skipped(fake_root, caplog):
    # A directory where the file should be: read_text raises, not FileNotFound.
    (fake_root / "proc/device-tree/chosen/board").mkdir(parents=True)
    with caplog.at_level(logging.DEBUG, logger=board_detector.__name__):
        assert await board_detector._detect_from_device_tree() is None
    assert "Device tree board detection failed" in caplog.text


# --- tier 2: config.txt -------------------------------------------------------


async def test_config_txt_skips_commented_overlays(fake_root):
    write(
        fake_root,
        "/boot/firmware/config.txt",
        "[all]\n"
        "  # dtoverlay=interceptor-raspberrypi-cm5\n"
        "dtparam=audio=on\n"
        "  dtoverlay=cruiser-raspberrypi-cm5,pse=on\n",
    )
    assert await board_detector._detect_from_config_txt() is BoardType.CRUISER


async def test_config_txt_interceptor_overlay(fake_root, caplog):
    write(fake_root, "/boot/firmware/config.txt", "dtoverlay=interceptor-raspberrypi-cm5,a=1\n")
    with caplog.at_level(logging.INFO, logger=board_detector.__name__):
        assert await board_detector._detect_from_config_txt() is BoardType.INTERCEPTOR
    # Only the overlay name is logged, not its parameters.
    assert "dtoverlay=interceptor-raspberrypi-cm5" in caplog.text
    assert "a=1" not in caplog.text


async def test_config_txt_without_exaviz_overlay(fake_root):
    write(fake_root, "/boot/firmware/config.txt", "dtoverlay=vc4-kms-v3d\n")
    assert await board_detector._detect_from_config_txt() is None


async def test_config_txt_missing(fake_root):
    assert await board_detector._detect_from_config_txt() is None


async def test_unreadable_config_txt_is_skipped(fake_root, caplog):
    (fake_root / "boot/firmware/config.txt").mkdir(parents=True)
    with caplog.at_level(logging.DEBUG, logger=board_detector.__name__):
        assert await board_detector._detect_from_config_txt() is None
    assert "config.txt board detection failed" in caplog.text


# --- tier 3: PSE interface ----------------------------------------------------


@pytest.mark.parametrize(
    ("present", "expected"),
    [
        (["/dev/pse", "/proc/pse"], BoardType.CRUISER),
        # Docker resolves the /dev/pse symlink to the real UART.
        (["/dev/ttyAMA3"], BoardType.CRUISER),
        (["/proc/pse"], BoardType.INTERCEPTOR),
    ],
)
async def test_pse_interface_decides_the_board(fake_root, present, expected):
    for path in present:
        write(fake_root, path, "")
    assert await board_detector._detect_from_pse_interface() is expected
    assert await detect_board_type() is expected


async def test_nothing_found_is_unknown_with_a_warning(fake_root, caplog):
    assert await board_detector._detect_from_pse_interface() is None
    with caplog.at_level(logging.WARNING, logger=board_detector.__name__):
        assert await detect_board_type() is BoardType.UNKNOWN
    assert "Board type could not be determined" in caplog.text


async def test_config_txt_wins_over_a_uart3_on_an_interceptor(fake_root):
    """An Interceptor with UART3 enabled for another use stays an Interceptor.

    The Interceptor overlay never enables UART3, but a user can, and then
    /dev/ttyAMA3 exists just as it does on a Cruiser in Docker. config.txt is
    checked first, so the board is not taken for a Cruiser and its poe
    interfaces are not counted a second time next to the add-on ports.
    """
    write(fake_root, "/boot/firmware/config.txt", "dtoverlay=interceptor-raspberrypi-cm5\n")
    write(fake_root, "/dev/ttyAMA3", "")
    write(fake_root, "/proc/pse", PROC_PSE_TWO_CONTROLLERS)
    for i in range(16):
        (fake_root / f"proc/sys/net/ipv4/conf/poe{i}").mkdir(parents=True)
    result = await detect_all_poe_systems()
    assert result["board_type"] is BoardType.INTERCEPTOR
    assert result["onboard_ports"] == []
    assert result["total_poe_ports"] == 16


# --- prerequisites (dpkg-query) -----------------------------------------------


def _dpkg(states: dict[str, tuple[str, str] | None | Exception]):
    """Fake create_subprocess_exec answering dpkg-query per package.

    A package maps to (status, version) rendered like dpkg-query, None when
    dpkg does not know it, or an exception to raise.
    """
    argvs: list[tuple] = []

    async def exec_(*argv, **kwargs):
        argvs.append(argv)
        answer = states[argv[-1]]
        if isinstance(answer, Exception):
            raise answer
        known = {argv[-1]: answer} if answer else {}
        proc = MagicMock()
        proc.returncode, stdout = fake_dpkg.render(argv, known)
        proc.communicate = AsyncMock(return_value=(stdout.encode(), None))
        return proc

    return argvs, patch_module_asyncio(board_detector, create_subprocess_exec=AsyncMock(side_effect=exec_))


@pytest.mark.parametrize("dkms_status", [fake_dpkg.INSTALLED, fake_dpkg.HELD], ids=["installed", "held"])
async def test_prerequisites_all_installed(caplog, dkms_status):
    argvs, p = _dpkg({
        "exaviz-dkms": (dkms_status, "2.1.0"),
        "exaviz-netplan": (fake_dpkg.INSTALLED, "1.4.2"),
    })
    with p, caplog.at_level(logging.INFO, logger=board_detector.__name__):
        result = await check_prerequisites()
    assert result == {
        "packages": {"exaviz-dkms": "2.1.0", "exaviz-netplan": "1.4.2"},
        "missing": [],
        "all_ok": True,
    }
    assert [argv[-1] for argv in argvs] == ["exaviz-dkms", "exaviz-netplan"]
    assert "exaviz-dkms 2.1.0, exaviz-netplan 1.4.2" in caplog.text


@pytest.mark.parametrize(
    "netplan_answer",
    [
        None,  # dpkg-query: no packages found (never installed, or purged)
        (fake_dpkg.REMOVED_CONFIG_LEFT, "1.4.2"),  # apt remove: version still printed, exit 0
        OSError("dpkg-query not found"),
    ],
    ids=["unknown", "removed-config-left", "no-dpkg-query"],
)
async def test_prerequisites_report_a_missing_package(caplog, netplan_answer):
    _argvs, p = _dpkg({"exaviz-dkms": (fake_dpkg.INSTALLED, "2.1.0"), "exaviz-netplan": netplan_answer})
    with p, caplog.at_level(logging.WARNING, logger=board_detector.__name__):
        result = await check_prerequisites()
    assert result["all_ok"] is False
    assert result["missing"] == ["exaviz-netplan"]
    assert result["packages"] == {"exaviz-dkms": "2.1.0", "exaviz-netplan": None}
    assert "Missing required Exaviz packages: exaviz-netplan" in caplog.text


# --- add-on boards (/proc/pse streaming file) ---------------------------------


async def test_addon_boards_found_from_port_line_prefixes(fake_root):
    write(fake_root, "/proc/pse", PROC_PSE_TWO_CONTROLLERS)
    assert await detect_addon_boards() == ["pse0", "pse1"]


async def test_addon_boards_read_only_the_first_lines(fake_root):
    """A streaming file never ends, so only `head -30` of it is read."""
    pse = write(fake_root, "/proc/pse", PROC_PSE_TWO_CONTROLLERS)
    runs: list[tuple] = []
    real_to_thread = asyncio.to_thread

    async def to_thread(func, *args, **kwargs):
        runs.append((func, args, kwargs))
        return await real_to_thread(func, *args, **kwargs)

    with patch_module_asyncio(board_detector, to_thread=to_thread):
        assert await detect_addon_boards() == ["pse0", "pse1"]
    import subprocess

    (func, args, kwargs), = [r for r in runs if r[0] is subprocess.run]
    assert args == (["head", "-30", str(pse)],)
    assert kwargs["timeout"] == 5


async def test_addon_board_on_a_single_controller(fake_root):
    write(fake_root, "/proc/pse", "IP808AR PSE status v2.0\n0-0: searching 0 0.00 0.00 0\n")
    assert await detect_addon_boards() == ["pse0"]


async def test_addon_boards_header_only_while_driver_starts(fake_root, caplog):
    write(fake_root, "/proc/pse", "IP808AR PSE status v2.0\n")
    with caplog.at_level(logging.DEBUG, logger=board_detector.__name__):
        assert await detect_addon_boards() == []
    assert "no port lines found" in caplog.text


async def test_addon_boards_empty_file(fake_root, caplog):
    write(fake_root, "/proc/pse", "")
    with caplog.at_level(logging.DEBUG, logger=board_detector.__name__):
        assert await detect_addon_boards() == []
    assert "returned no data" in caplog.text


async def test_addon_boards_read_failure_is_logged(fake_root, caplog):
    import subprocess

    write(fake_root, "/proc/pse", PROC_PSE_TWO_CONTROLLERS)
    with patch.object(
        subprocess, "run", side_effect=subprocess.TimeoutExpired("head", 5)
    ), caplog.at_level(logging.ERROR, logger=board_detector.__name__):
        assert await detect_addon_boards() == []
    assert "Failed to detect add-on boards" in caplog.text


# --- onboard ports (/proc/sys/net/ipv4/conf/poeN) -----------------------------


async def test_onboard_ports_are_the_poe_directories(fake_root, caplog):
    conf = fake_root / "proc/sys/net/ipv4/conf"
    for name in ("eth0", "lo", "poe0", "poe1", "poe3", "poe7"):
        (conf / name).mkdir(parents=True)
    # A plain file named like a port is not an interface.
    (conf / "poe2").write_text("")
    with caplog.at_level(logging.INFO, logger=board_detector.__name__):
        assert await detect_onboard_poe() == ["poe0", "poe1", "poe3", "poe7"]
    assert "(4 ports)" in caplog.text


async def test_onboard_ports_none_found_warns(fake_root, caplog):
    (fake_root / "proc/sys/net/ipv4/conf/eth0").mkdir(parents=True)
    with caplog.at_level(logging.WARNING, logger=board_detector.__name__):
        assert await detect_onboard_poe() == []
    assert "No onboard PoE interfaces found" in caplog.text


async def test_onboard_ports_without_net_conf(fake_root, caplog):
    with caplog.at_level(logging.WARNING, logger=board_detector.__name__):
        assert await detect_onboard_poe() == []
    # Missing /proc/sys/net is not the "no ports" warning.
    assert "No onboard PoE interfaces found" not in caplog.text


async def test_onboard_ports_scan_failure_is_logged(fake_root, caplog):
    (fake_root / "proc/sys/net/ipv4/conf").mkdir(parents=True)
    with patch.object(Path, "is_dir", side_effect=PermissionError("denied")), \
         caplog.at_level(logging.ERROR, logger=board_detector.__name__):
        assert await detect_onboard_poe() == []
    assert "Failed to detect onboard PoE ports: denied" in caplog.text


# --- whole chain --------------------------------------------------------------


async def test_full_detection_on_a_fake_cruiser(fake_root):
    write(fake_root, "/boot/firmware/config.txt", "dtoverlay=cruiser-raspberrypi-cm5\n")
    write(fake_root, "/dev/pse", "")
    for i in range(8):
        (fake_root / f"proc/sys/net/ipv4/conf/poe{i}").mkdir(parents=True)
    result = await detect_all_poe_systems()
    assert result == {
        "board_type": BoardType.CRUISER,
        "addon_boards": [],
        "onboard_ports": [f"poe{i}" for i in range(8)],
        "total_poe_ports": 8,
    }


async def test_full_detection_on_a_fake_interceptor(fake_root, caplog):
    write(fake_root, "/boot/firmware/config.txt", "dtoverlay=interceptor-raspberrypi-cm5\n")
    write(fake_root, "/proc/pse", PROC_PSE_TWO_CONTROLLERS)
    for i in range(8):
        (fake_root / f"proc/sys/net/ipv4/conf/poe{i}").mkdir(parents=True)
    with caplog.at_level(logging.INFO, logger=board_detector.__name__):
        result = await detect_all_poe_systems()
    # The poe interfaces belong to the add-on boards, not the carrier.
    assert result == {
        "board_type": BoardType.INTERCEPTOR,
        "addon_boards": ["pse0", "pse1"],
        "onboard_ports": [],
        "total_poe_ports": 16,
    }
    assert "Clearing onboard list" in caplog.text


async def test_unknown_board_keeps_its_poe_interfaces(fake_root):
    """HA in Docker on a Cruiser with no device passed through still gets its ports.

    The container sees no device tree name, config.txt, /dev/pse,
    /dev/ttyAMA3 or /proc/pse, so the board type is unknown, but host
    networking shows poe0-poe7. With no add-on board those
    are the board's own ports and must not be cleared (setup would otherwise
    fail with no PoE detected).
    """
    for i in range(8):
        (fake_root / f"proc/sys/net/ipv4/conf/poe{i}").mkdir(parents=True)
    result = await detect_all_poe_systems()
    assert result == {
        "board_type": BoardType.UNKNOWN,
        "addon_boards": [],
        "onboard_ports": [f"poe{i}" for i in range(8)],
        "total_poe_ports": 8,
    }
