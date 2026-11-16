"""patch_module_asyncio changes asyncio for one module only (#43)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from custom_components.exaviz import board_detector, coordinator, poe_readers
from custom_components.exaviz import button as button_module
from custom_components.exaviz import switch as switch_module
from tests.module_asyncio import patch_module_asyncio


async def _settle(delay: float) -> None:
    return None


def test_only_the_patched_module_sees_the_override():
    real_sleep = asyncio.sleep
    with patch_module_asyncio(button_module, sleep=_settle):
        assert button_module.asyncio.sleep is _settle
        assert asyncio.sleep is real_sleep
        assert switch_module.asyncio.sleep is real_sleep
        # Every other name is the real asyncio one.
        assert button_module.asyncio.shield is asyncio.shield
        assert button_module.asyncio.CancelledError is asyncio.CancelledError
        assert button_module.asyncio.TimeoutError is asyncio.TimeoutError
        assert button_module.asyncio.subprocess.PIPE is asyncio.subprocess.PIPE
    assert button_module.asyncio is asyncio


def test_an_unknown_name_is_refused():
    with pytest.raises(AttributeError, match="sleeep"):
        patch_module_asyncio(button_module, sleeep=_settle)


def test_a_faked_spawn_in_one_module_does_not_answer_in_another():
    """Faking poe_readers' subprocesses must not fake the coordinator's or
    the board detector's, which a process-wide patch did (#43)."""
    real_spawn = asyncio.create_subprocess_exec
    fake = AsyncMock()
    with patch_module_asyncio(poe_readers, create_subprocess_exec=fake):
        assert poe_readers.asyncio.create_subprocess_exec is fake
        assert coordinator.asyncio.create_subprocess_exec is real_spawn
        assert board_detector.asyncio.create_subprocess_exec is real_spawn
        assert asyncio.create_subprocess_exec is real_spawn
