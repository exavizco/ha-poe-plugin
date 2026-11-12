"""#43: a RAM or eMMC size that cannot be read is left out of the board status
sensor, not shown as a guess ("1 GB", "None (Lite)", or a made-up part number).

Runs the real _gather_system_info on a patched Cruiser whose filesystem reads
come from a fake root, through a real Home Assistant setup.
"""

from unittest.mock import AsyncMock, patch

from custom_components.exaviz.coordinator import ExavizDataUpdateCoordinator

from .local_board import patch_local_board
from .test_golden_local import local_entry

COORD = "custom_components.exaviz.coordinator"
COMPAT_CM5 = b"raspberrypi,5-compute-module\x00brcm,bcm2712\x00"
ATTRS = ("total_ram_gb", "emmc_storage", "cm_model")
# Captured at import, before patch_local_board replaces it with canned info.
REAL_GATHER = ExavizDataUpdateCoordinator._gather_system_info


async def _board_attrs(hass, tmp_path, files: dict[str, str | bytes]):
    for rel, content in files.items():
        target = tmp_path / rel.strip("/")
        if rel.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if isinstance(content, bytes) else content.encode())

    entry = local_entry()
    entry.add_to_hass(hass)
    stack, _reader = patch_local_board()
    with stack:
        # Undo the helper's canned system info so the real code runs.
        stack.enter_context(
            patch(f"{COORD}.Path", lambda p: tmp_path / str(p).lstrip("/"))
        )
        stack.enter_context(
            patch.object(
                ExavizDataUpdateCoordinator, "_gather_system_info", REAL_GATHER
            )
        )
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        attrs = dict(hass.states.get("sensor.board_status").attributes)
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
    return attrs


def _fake_exec():
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(b"", None))
    return AsyncMock(return_value=proc)


async def test_unreadable_ram_and_emmc_size_are_omitted(hass, tmp_path):
    with patch("asyncio.create_subprocess_exec", _fake_exec()):
        attrs = await _board_attrs(
            hass,
            tmp_path,
            {
                "/proc/device-tree/compatible": COMPAT_CM5,
                "/sys/block/mmcblk0boot0/": "",
                "/sys/block/mmcblk0/size": "not-a-number\n",
            },
        )
    assert attrs["compute_module"] == "Raspberry Pi CM5"
    for key in ATTRS:
        assert key not in attrs


async def test_readable_ram_and_emmc_are_shown(hass, tmp_path):
    with patch("asyncio.create_subprocess_exec", _fake_exec()):
        attrs = await _board_attrs(
            hass,
            tmp_path,
            {
                "/proc/device-tree/compatible": COMPAT_CM5,
                "/proc/meminfo": "MemTotal:        8245312 kB\n",
                "/sys/block/mmcblk0boot0/": "",
                "/sys/block/mmcblk0/size": "61071360\n",
            },
        )
    assert attrs["total_ram_gb"] == "8 GB"
    assert attrs["emmc_storage"] == "32 GB"
    assert attrs["cm_model"] == "CM5008032"
