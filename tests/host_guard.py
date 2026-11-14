"""Keep tests from changing the machine that runs them.

The integration runs `sudo ip link set ...` and `sudo arp-scan`, writes to
the PoE controller's serial port (`bash -c "echo ... > /dev/pse"`) and sets
that port up with `stty`. A test that lets port code outlive its patches (a
reset cycle still running after its `with` block, say) would run those on
the developer's machine or the CI runner, even after the test ends: the
event loop's close cancels leftover tasks, and a cancelled reset turns its
port back on. So the guard stays in place for the whole session.

It sits on `subprocess.Popen`, which asyncio's `create_subprocess_exec` and
`create_subprocess_shell` and `subprocess.run` all start their child with.
"""
from __future__ import annotations

import shlex
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import PurePath
from unittest.mock import patch

import pytest

# Commands that change the host. `ip` and `timeout` are what `sudo_argv`
# runs without sudo when the tests run as root; `stty` changes a terminal.
_REFUSED = frozenset({"sudo", "ip", "timeout", "arp-scan", "tcpdump", "stty"})
# The PoE controller's serial port, under either of its names.
_REFUSED_PATHS = ("/dev/pse", "/dev/ttyAMA")

refused: list[tuple[str, ...]] = []


def changes_host(args) -> bool:
    """True for a command line (argv or shell string) the guard refuses."""
    words = shlex.split(args) if isinstance(args, str) else [str(a) for a in args]
    if not words:
        return False
    if any(path in word for word in words for path in _REFUSED_PATHS):
        return True
    if PurePath(words[0]).name in {"bash", "sh"} and "-c" in words:
        # The script's commands: any word a refused program counts.
        script = " ".join(words[words.index("-c") + 1:])
        words = script.replace(";", " ").replace("&", " ").replace("|", " ").split()
        return any(PurePath(word).name in _REFUSED for word in words)
    return PurePath(words[0]).name in _REFUSED


@contextmanager
def refuse_host_commands() -> Iterator[None]:
    """Refuse host-changing subprocesses; fail on exit if any were tried."""

    class GuardedPopen(subprocess.Popen):
        def __init__(self, args, *rest, **kwargs):
            if changes_host(args):
                words = (args,) if isinstance(args, str) else tuple(map(str, args))
                refused.append(words)
                # An OSError, which the port code handles like a missing binary.
                raise PermissionError(f"test tried to run {' '.join(words)}")
            super().__init__(args, *rest, **kwargs)

    with patch("subprocess.Popen", GuardedPopen):
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

    A try after its test ended is blamed on the test running then, or fails
    the session at its end after the last test.
    """
    yield
    tried = refused.copy()
    refused.clear()
    assert not tried, f"this test tried to run host commands: {tried}"
