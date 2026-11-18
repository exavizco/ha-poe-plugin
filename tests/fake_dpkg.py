"""Fake `dpkg-query -W -f FORMAT PKG...` that renders FORMAT like dpkg does.

A package maps to (status_abbrev, version). Status abbreviations are the
three-character `${db:Status-Abbrev}` values, trailing space included:
want, current state, error flag. "ii " installed, "hi " installed and held
(apt-mark hold), "rc " removed with config files left. Checked against
dpkg-query in a Debian trixie container: a removed (not purged) package
still prints its version with exit 0; a purged or unknown package prints
nothing to stdout and exits 1.
"""
from __future__ import annotations

INSTALLED = "ii "
HELD = "hi "
REMOVED_CONFIG_LEFT = "rc "


def render(argv: tuple[str, ...], states: dict[str, tuple[str, str]]) -> tuple[int, str]:
    """Return (exit code, stdout) for a dpkg-query -W -f argv."""
    assert argv[:3] == ("dpkg-query", "-W", "-f"), argv
    fmt, packages = argv[3], argv[4:]
    out = ""
    for pkg in packages:
        if pkg in states:
            status, version = states[pkg]
            out += (
                fmt.replace("${db:Status-Abbrev}", status)
                .replace("${Package}", pkg)
                .replace("${Version}", version)
            )
    known = all(pkg in states for pkg in packages)
    return (0 if known else 1), out
