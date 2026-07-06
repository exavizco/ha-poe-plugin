"""Tests for switch/bridge-mode device discovery (issue #10).

Covers bridge-membership detection, bridge FDB parsing, arp-scan parsing, and
the end-to-end _resolve_bridged_device orchestration against captured-format
fixtures. Real bridge state must still be validated on hardware; these lock in
the parse + control-flow logic.

Copyright (c) 2026 Axzez LLC.
Licensed under the MIT License. See LICENSE for details.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.exaviz import poe_readers
from custom_components.exaviz.poe_readers import (
    _is_multicast_mac,
    _parse_bridge_fdb,
    _parse_arp_scan,
    _resolve_bridged_device,
    _run_arp_scan,
)


# ---------------------------------------------------------------------------
# Captured-format fixtures (real `bridge fdb show dev poeN` / `arp-scan` output)
# ---------------------------------------------------------------------------

# `bridge fdb show dev poe3` with one camera (24:52:6a:...) learned dynamically,
# plus the multicast/self/permanent noise the kernel always lists.
FDB_ONE_DEVICE = """\
33:33:00:00:00:01 self permanent
01:00:5e:00:00:01 self permanent
02:1a:2b:3c:4d:5e vlan 1 master br0 permanent
24:52:6a:08:71:80 master br0
"""

FDB_TWO_DEVICES = """\
33:33:00:00:00:01 self permanent
24:52:6a:08:71:80 master br0
b8:27:eb:11:22:33 master br0
"""

FDB_EMPTY = """\
33:33:00:00:00:01 self permanent
01:00:5e:00:00:01 self permanent
"""

# `arp-scan --interface br0 --localnet --plain --quiet`
ARP_SCAN_OUTPUT = """\
192.168.86.10\t24:52:6a:08:71:80\tHangzhou Hikvision Digital Technology
192.168.86.20\tb8:27:eb:11:22:33\tRaspberry Pi Foundation
"""


class TestMulticastMac:
    def test_multicast(self):
        assert _is_multicast_mac("01:00:5e:00:00:01")
        assert _is_multicast_mac("33:33:00:00:00:01")
        assert _is_multicast_mac("ff:ff:ff:ff:ff:ff")

    def test_unicast(self):
        assert not _is_multicast_mac("24:52:6a:08:71:80")
        assert not _is_multicast_mac("b8:27:eb:11:22:33")

    def test_garbage_is_not_multicast(self):
        assert not _is_multicast_mac("")
        assert not _is_multicast_mac("nope")


class TestParseBridgeFdb:
    def test_extracts_learned_device(self):
        assert _parse_bridge_fdb(FDB_ONE_DEVICE, set()) == ["24:52:6a:08:71:80"]

    def test_drops_self_permanent_and_multicast(self):
        # Only the dynamic unicast entry survives.
        macs = _parse_bridge_fdb(FDB_ONE_DEVICE, set())
        assert "33:33:00:00:00:01" not in macs
        assert "01:00:5e:00:00:01" not in macs
        assert "02:1a:2b:3c:4d:5e" not in macs  # vlan ... permanent

    def test_multiple_devices_preserve_order(self):
        assert _parse_bridge_fdb(FDB_TWO_DEVICES, set()) == [
            "24:52:6a:08:71:80",
            "b8:27:eb:11:22:33",
        ]

    def test_own_macs_excluded(self):
        own = {"24:52:6a:08:71:80"}
        assert _parse_bridge_fdb(FDB_ONE_DEVICE, own) == []

    def test_no_learned_devices(self):
        assert _parse_bridge_fdb(FDB_EMPTY, set()) == []

    def test_empty_input(self):
        assert _parse_bridge_fdb("", set()) == []


class TestParseArpScan:
    def test_maps_mac_to_ip_and_vendor(self):
        parsed = _parse_arp_scan(ARP_SCAN_OUTPUT)
        assert parsed["24:52:6a:08:71:80"]["ip_address"] == "192.168.86.10"
        assert "Hikvision" in parsed["24:52:6a:08:71:80"]["vendor"]
        assert parsed["b8:27:eb:11:22:33"]["ip_address"] == "192.168.86.20"

    def test_ignores_non_result_lines(self):
        noisy = "Interface: br0\n" + ARP_SCAN_OUTPUT + "\n2 packets received\n"
        assert len(_parse_arp_scan(noisy)) == 2

    def test_empty(self):
        assert _parse_arp_scan("") == {}

    def test_unknown_vendor_treated_as_empty(self):
        # Ubuntu 26.04 arp-scan without an OUI db prints "(Unknown)"; we must not
        # let that clobber our own OUI lookup downstream.
        out = (
            "192.168.86.10\t24:52:6a:08:71:80\t(Unknown)\n"
            "192.168.86.11\t3e:ac:94:54:25:fa\t(Unknown: locally administered)\n"
        )
        parsed = _parse_arp_scan(out)
        assert parsed["24:52:6a:08:71:80"]["vendor"] == ""
        assert parsed["3e:ac:94:54:25:fa"]["vendor"] == ""
        assert parsed["24:52:6a:08:71:80"]["ip_address"] == "192.168.86.10"

    def test_dup_marker_stripped(self):
        # Duplicate responses get a trailing "(DUP: N)" that must not leak into
        # the vendor string.
        out = "192.168.86.53\td8:3a:dd:95:21:ca\tRaspberry Pi Trading Ltd (DUP: 2)\n"
        parsed = _parse_arp_scan(out)
        assert parsed["d8:3a:dd:95:21:ca"]["vendor"] == "Raspberry Pi Trading Ltd"


class TestResolveBridgedDevice:
    @pytest.mark.asyncio
    async def test_noop_when_disabled(self):
        # Feature is opt-in: with enabled=False (the default) a bridge member
        # with a learned device is still ignored.
        with patch("custom_components.exaviz.poe_readers._get_bridge_master",
                   AsyncMock(return_value="br0")), \
             patch("custom_components.exaviz.poe_readers._read_bridge_fdb",
                   AsyncMock(return_value=FDB_ONE_DEVICE)):
            assert await _resolve_bridged_device("poe3", "up", None) is None

    @pytest.mark.asyncio
    async def test_noop_when_already_resolved(self):
        existing = {"ip_address": "10.0.0.5", "mac_address": "aa:bb:cc:dd:ee:ff"}
        result = await _resolve_bridged_device("poe3", "up", existing, enabled=True)
        assert result is existing

    @pytest.mark.asyncio
    async def test_noop_when_link_down(self):
        assert await _resolve_bridged_device("poe3", "down", None, enabled=True) is None

    @pytest.mark.asyncio
    async def test_noop_when_not_bridge_member(self):
        with patch("custom_components.exaviz.poe_readers._get_bridge_master",
                   AsyncMock(return_value=None)):
            assert await _resolve_bridged_device("poe3", "up", None, enabled=True) is None

    @pytest.mark.asyncio
    async def test_full_resolution_fdb_plus_arp_scan(self):
        with patch("custom_components.exaviz.poe_readers._get_bridge_master",
                   AsyncMock(return_value="br0")), \
             patch("custom_components.exaviz.poe_readers._collect_local_macs",
                   AsyncMock(return_value=set())), \
             patch("custom_components.exaviz.poe_readers._read_bridge_fdb",
                   AsyncMock(return_value=FDB_ONE_DEVICE)), \
             patch("custom_components.exaviz.poe_readers._run_arp_scan",
                   AsyncMock(return_value=_parse_arp_scan(ARP_SCAN_OUTPUT))):
            result = await _resolve_bridged_device("poe3", "up", None, enabled=True)

        assert result["mac_address"] == "24:52:6a:08:71:80"
        assert result["ip_address"] == "192.168.86.10"
        assert "Hikvision" in result["manufacturer"]
        assert "arp-scan" in result["detection_method"]

    @pytest.mark.asyncio
    async def test_fdb_only_when_arp_scan_empty(self):
        # Device on a foreign subnet: FDB has the MAC, arp-scan can't reach it.
        with patch("custom_components.exaviz.poe_readers._get_bridge_master",
                   AsyncMock(return_value="br0")), \
             patch("custom_components.exaviz.poe_readers._collect_local_macs",
                   AsyncMock(return_value=set())), \
             patch("custom_components.exaviz.poe_readers._read_bridge_fdb",
                   AsyncMock(return_value=FDB_ONE_DEVICE)), \
             patch("custom_components.exaviz.poe_readers._run_arp_scan",
                   AsyncMock(return_value={})):
            result = await _resolve_bridged_device("poe3", "up", None, enabled=True)

        assert result["mac_address"] == "24:52:6a:08:71:80"
        assert result.get("ip_address") is None
        assert result["detection_method"] == "bridge FDB (br0)"
        # OUI still resolves from the MAC even with no IP.
        assert "manufacturer" in result

    @pytest.mark.asyncio
    async def test_empty_fdb_returns_none(self):
        with patch("custom_components.exaviz.poe_readers._get_bridge_master",
                   AsyncMock(return_value="br0")), \
             patch("custom_components.exaviz.poe_readers._collect_local_macs",
                   AsyncMock(return_value=set())), \
             patch("custom_components.exaviz.poe_readers._read_bridge_fdb",
                   AsyncMock(return_value=FDB_EMPTY)):
            assert await _resolve_bridged_device("poe3", "up", None, enabled=True) is None


def _fake_proc(stdout: bytes, returncode: int = 0):
    """Build a mock asyncio subprocess with a canned communicate() result."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, b""))
    return proc


class TestRunArpScan:
    def setup_method(self):
        # Module-level cache/locks persist between tests; start each clean.
        poe_readers._arp_scan_cache.clear()
        poe_readers._arp_scan_locks.clear()

    @pytest.mark.asyncio
    async def test_skips_scan_when_bridge_has_no_ipv4(self):
        # No IPv4 -> --localnet has no subnet; never spawn arp-scan.
        with patch("custom_components.exaviz.poe_readers._bridge_has_ipv4",
                   AsyncMock(return_value=False)), \
             patch("asyncio.create_subprocess_exec") as spawn:
            result = await _run_arp_scan("br0")
        assert result == {}
        spawn.assert_not_called()

    @pytest.mark.asyncio
    async def test_concurrent_ports_share_one_sweep(self):
        # 8 ports polling the same bridge at once must collapse to ONE sweep.
        spawn = AsyncMock(return_value=_fake_proc(ARP_SCAN_OUTPUT.encode()))
        with patch("custom_components.exaviz.poe_readers._bridge_has_ipv4",
                   AsyncMock(return_value=True)), \
             patch("asyncio.create_subprocess_exec", spawn):
            import asyncio
            results = await asyncio.gather(*[_run_arp_scan("br0") for _ in range(8)])
        assert spawn.call_count == 1
        assert all("24:52:6a:08:71:80" in r for r in results)

    @pytest.mark.asyncio
    async def test_passes_ouifile_when_present(self):
        spawn = AsyncMock(return_value=_fake_proc(ARP_SCAN_OUTPUT.encode()))
        with patch("custom_components.exaviz.poe_readers._bridge_has_ipv4",
                   AsyncMock(return_value=True)), \
             patch("custom_components.exaviz.poe_readers.Path") as path_cls, \
             patch("asyncio.create_subprocess_exec", spawn):
            path_cls.return_value.exists.return_value = True
            await _run_arp_scan("br0")
        argv = spawn.call_args[0]
        assert any(str(a).startswith("--ouifile=") for a in argv)

    @pytest.mark.asyncio
    async def test_runs_arp_scan_directly_no_timeout_wrapper(self):
        # Must sudo the absolute arp-scan binary directly (no `timeout` wrapper),
        # so the NOPASSWD rule can whitelist just /usr/sbin/arp-scan.
        spawn = AsyncMock(return_value=_fake_proc(ARP_SCAN_OUTPUT.encode()))
        with patch("custom_components.exaviz.poe_readers._bridge_has_ipv4",
                   AsyncMock(return_value=True)), \
             patch("asyncio.create_subprocess_exec", spawn):
            await _run_arp_scan("br0")
        argv = list(spawn.call_args[0])
        assert argv[0] == "sudo"
        assert argv[1] == "/usr/sbin/arp-scan"
        assert "timeout" not in argv

    @pytest.mark.asyncio
    async def test_failure_is_cached_no_herd(self):
        # A failing sweep (rc!=0) must be cached so concurrent ports don't each
        # re-spawn arp-scan every poll cycle.
        spawn = AsyncMock(return_value=_fake_proc(b"", returncode=1))
        with patch("custom_components.exaviz.poe_readers._bridge_has_ipv4",
                   AsyncMock(return_value=True)), \
             patch("asyncio.create_subprocess_exec", spawn):
            import asyncio
            results = await asyncio.gather(*[_run_arp_scan("br0") for _ in range(8)])
        assert spawn.call_count == 1
        assert all(r == {} for r in results)

    @pytest.mark.asyncio
    async def test_timeout_returns_empty_and_caches(self):
        import asyncio
        proc = _fake_proc(ARP_SCAN_OUTPUT.encode())

        async def fake_wait_for(coro, timeout):
            coro.close()  # consume the communicate() coroutine, then time out
            raise asyncio.TimeoutError

        with patch("custom_components.exaviz.poe_readers._bridge_has_ipv4",
                   AsyncMock(return_value=True)), \
             patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)), \
             patch("asyncio.wait_for", fake_wait_for):
            result = await _run_arp_scan("br0")
        assert result == {}
        proc.kill.assert_called_once()
