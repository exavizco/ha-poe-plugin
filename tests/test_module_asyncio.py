"""patch_module_asyncio changes asyncio for one module only (#43)."""
from __future__ import annotations

import asyncio

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
