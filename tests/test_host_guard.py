"""The session guard refuses every host-changing command the integration runs,
through each way the integration starts a process."""
from __future__ import annotations

import asyncio
import subprocess
import sys

import pytest

from tests import host_guard

# The integration's own command lines (switch.py, coordinator.py, poe_readers.py).
HOST_CHANGING = [
    ("sudo", "ip", "link", "set", "poe3", "down"),
    ("ip", "link", "set", "poe3", "up"),  # as root, without sudo
    ("bash", "-c", "echo 'disable-port 1 0' > /dev/pse"),
    ("bash", "-c", "echo 'enable-port 1 0' > /dev/ttyAMA3"),
    ("bash", "-c", "echo 'info' > /dev/pse && timeout 3 cat /dev/pse"),
    ("stty", "-F", "/dev/pse", "115200", "raw", "-echo"),
    ("timeout", "3", "cat", "/dev/ttyAMA3"),
    ("/usr/sbin/arp-scan", "--interface", "br0", "--localnet", "--plain"),
    ("sudo", "timeout", "10", "tcpdump", "-i", "poe0", "-c", "20"),
    ("bash", "-c", "ip link set poe0 down"),  # through a shell
    ("sh", "-c", "cd /; sudo ip link set poe0 up"),
]


@pytest.mark.parametrize("argv", HOST_CHANGING, ids=" ".join)
def test_host_changing_commands_are_recognised(argv):
    assert host_guard.changes_host(argv)
    assert host_guard.changes_host(" ".join(f"'{a}'" if " " in a else a for a in argv))


@pytest.mark.parametrize("argv", [
    (sys.executable, "-c", "pass"),
    ("bash", "-c", "echo 'disable-port 1 0' > /tmp/pse"),  # a test's own device file
    ("head", "-30", "/proc/pse0"),
    ("dpkg-query", "-W", "-f", "${Version}", "exaviz-dkms"),
])
def test_other_commands_are_allowed(argv):
    assert not host_guard.changes_host(argv)


def _starts():
    """Each way the integration (or a test) can start a process."""
    async def exec_():
        return await asyncio.create_subprocess_exec(
            "bash", "-c", "echo 'enable-port 1 0' > /dev/pse",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )

    async def shell():
        return await asyncio.create_subprocess_shell("sudo ip link set poe0 up")

    async def run():
        return await asyncio.to_thread(
            subprocess.run, ["stty", "-F", "/dev/pse", "115200"], capture_output=True
        )

    return {"create_subprocess_exec": exec_, "create_subprocess_shell": shell,
            "subprocess.run": run}


@pytest.mark.asyncio
@pytest.mark.parametrize("how", list(_starts()))
async def test_refused_through_each_way_to_start_a_process(how):
    """Refused as an OSError (what the port code handles), and recorded so
    the test that tried fails."""
    # Without the session guard these would really run; stop first.
    assert subprocess.Popen.__name__ == "GuardedPopen"
    try:
        with pytest.raises(PermissionError, match="test tried to run"):
            await _starts()[how]()
        assert len(host_guard.refused) == 1
    finally:
        host_guard.refused.clear()  # this test tried on purpose
