"""Replace asyncio functions as one module sees them, and nowhere else.

`patch("pkg.mod.asyncio.sleep")` looks up `pkg.mod.asyncio`, which is the
asyncio module itself, so it replaces asyncio.sleep for every caller in
the process: the test body, the code under test in other modules and the
event loop. Patching the module's `asyncio` name keeps the change local.
"""
from __future__ import annotations

import asyncio
from types import ModuleType
from typing import Any
from unittest.mock import patch


class _ModuleAsyncio:
    """asyncio with some names replaced; every other name is the real one."""

    def __init__(self, **overrides: Any) -> None:
        self.__dict__.update(overrides)

    def __getattr__(self, name: str) -> Any:
        return getattr(asyncio, name)


def patch_module_asyncio(module: ModuleType, **overrides: Any):
    """Patch `module.asyncio` so only `module` sees `overrides`."""
    return patch.object(module, "asyncio", _ModuleAsyncio(**overrides))
