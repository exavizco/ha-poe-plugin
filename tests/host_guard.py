"""Keep tests from changing the machine that runs them.

The integration runs `sudo ip link set ...` and `sudo arp-scan` on a board.
A test that lets port code outlive its patches (a reset cycle still running
after its `with` block, say) would run those on the developer's machine or
the CI runner, even after the test ends: the event loop's close cancels
leftover tasks, and a cancelled reset turns its port back on. So the guard
stays in place for the whole session.
"""
from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

import pytest

# Commands that change the host. `ip` and `timeout` are what `sudo_argv`
# runs without sudo when the tests run as root.
_REFUSED = frozenset({"sudo", "ip", "timeout", "arp-scan", "tcpdump"})

refused: list[tuple[str, ...]] = []


@contextmanager
def refuse_host_commands() -> Iterator[None]:
    """Refuse privileged subprocesses; fail on exit if any were tried."""
    real_exec = asyncio.create_subprocess_exec

    async def guarded_exec(program, *args, **kwargs):
        if str(program).rsplit("/", 1)[-1] in _REFUSED:
            refused.append((program, *args))
            # An OSError, which the port code handles like a missing binary.
            raise PermissionError(f"test tried to run {program} {' '.join(args)}")
        return await real_exec(program, *args, **kwargs)

    with patch("asyncio.create_subprocess_exec", guarded_exec):
        yield
    assert not refused, f"a test tried to run host commands: {refused}"


@pytest.fixture(autouse=True, scope="session")
def no_host_commands() -> Iterator[None]:
    """No test may run `sudo ip link` and friends on this machine."""
    with refuse_host_commands():
        yield


@pytest.fixture(autouse=True)
def no_host_commands_in_test(no_host_commands) -> Iterator[None]:
    """Name the test that tried, when it tried while it ran.

    A try after its test ended fails the session at its end instead.
    """
    yield
    tried = refused.copy()
    refused.clear()
    assert not tried, f"this test tried to run host commands: {tried}"
