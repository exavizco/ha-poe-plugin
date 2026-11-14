"""`ip link` stand-ins that are real processes, for the stop-and-kill tests.

The port code's handling of a stuck `ip link` is about real signals and
real process ends, so a mock would prove nothing. These stand in for what
`sudo ip link set ...` (or `ip link set ...`, as root) starts.
"""
from __future__ import annotations

import asyncio
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

# The stand-in `ip`: writes its pid once its SIGTERM handling is set, then
# hangs. argv: pid file, "ignore" or "obey" SIGTERM.
_IP = """
import os, signal, sys, time
if sys.argv[2] == "ignore":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
with open(sys.argv[1] + ".tmp", "w") as f:
    f.write(str(os.getpid()))
os.replace(sys.argv[1] + ".tmp", sys.argv[1])
time.sleep(60)
"""

# The stand-in sudo, which does what sudo(8) and sudo-rs do with signals
# (checked on sudo 1.9.16p2 and sudo-rs 0.2.13): it passes SIGTERM on to its
# command, ends when that ends with the same status, and a SIGKILL ends it
# alone, leaving the command running. argv: the command.
_SUDO = """
import os, signal, subprocess, sys
child = subprocess.Popen(sys.argv[1:])
signal.signal(signal.SIGTERM, lambda *_: child.send_signal(signal.SIGTERM))
rc = child.wait()
if rc < 0:
    signal.signal(-rc, signal.SIG_DFL)
    os.kill(os.getpid(), -rc)
sys.exit(rc)
"""


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class HungIpLink:
    """Patch `ip link set` to real processes; `hang` actions never end.

    `sudo` puts each one under the stand-in sudo. The patched exec returns
    once a hanging stand-in has set its SIGTERM handling, so a test's
    timeout starts after that. Other actions end at once with status 0.
    """

    def __init__(
        self, tmp_path: Path, *, sudo: bool, ignore_term: bool = False,
        hang: tuple[str, ...] = ("down", "up"),
    ) -> None:
        self.dir, self.sudo, self.hang = tmp_path, sudo, hang
        self.term = "ignore" if ignore_term else "obey"
        self.procs: list[asyncio.subprocess.Process] = []
        self.ip_pids: list[int] = []  # the stand-in `ip` of each hung run
        # For each run started: its action, and whether a hung `ip` from an
        # earlier run was still running at that moment.
        self.started: list[tuple[str, bool]] = []

    @contextmanager
    def patches(self):
        real_exec = asyncio.create_subprocess_exec
        sudo_argv = (lambda *a: ("sudo", *a)) if self.sudo else (lambda *a: a)

        async def exec_(*argv, **kwargs):
            action = argv[-1]
            self.started.append((action, any(map(alive, self.ip_pids))))
            if action in self.hang:
                pid_file = self.dir / f"ip-{len(self.started)}.pid"
                command = [sys.executable, "-c", _IP, str(pid_file), self.term]
            else:
                pid_file, command = None, [sys.executable, "-c", "pass"]
            if self.sudo:
                command = [sys.executable, "-c", _SUDO, *command]
            proc = await real_exec(*command, **kwargs)
            self.procs.append(proc)
            if pid_file is not None:
                while not pid_file.exists():
                    await asyncio.sleep(0.01)
                self.ip_pids.append(int(pid_file.read_text()))
            return proc

        with patch("asyncio.create_subprocess_exec", exec_), \
             patch("custom_components.exaviz.switch.sudo_argv", sudo_argv):
            yield

    def ip_alive(self) -> list[bool]:
        return [alive(pid) for pid in self.ip_pids]

    def cleanup(self) -> None:
        for pid in [p.pid for p in self.procs if p.returncode is None] + self.ip_pids:
            try:
                os.kill(pid, 9)
            except ProcessLookupError:
                pass
