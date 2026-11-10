"""HTTPS client for an Exaviz board running Exaviz Management (HA contract v1).

Used when Home Assistant runs on a different host than the board. No Home
Assistant imports: the caller passes in the aiohttp session (HA's shared one)
and, in CA mode, an SSLContext built off the event loop.

Copyright (c) 2026 Axzez LLC.
Licensed under the MIT License. See LICENSE for details.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import os
import re
import ssl
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

import aiohttp
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from .const import PLUGIN_VERSION
from .poe_readers import get_allocated_power_watts

_LOGGER = logging.getLogger(__name__)

CONTRACT_VERSION = 1
DEFAULT_TIMEOUT = 10
PORT_ACTIONS = frozenset({"enable", "disable", "reset"})
# Contract rule: a port is unavailable when updated_at is more than 10 s older
# than the Date of the same response.
STALE_AFTER_SECONDS = 10
_PIN_RE = re.compile(r"^[0-9a-f]{64}$")
_POE_NAME_RE = re.compile(r"^poe(\d+)$")
_NEUTRAL_NAME_RE = re.compile(r"^pse(\d+)-(\d+)$")
# Cruiser wiring: PSE 1 feeds poe0-3, PSE 0 feeds poe4-7.
_CRUISER_PSE_OFFSET = {1: 0, 0: 4}

# /board key -> system_info key (the names the local path and Board Status use).
_BOARD_INFO_KEYS = {
    "compute_module": "compute_module",
    "os_version": "os_version",
    "kernel_version": "kernel_version",
    "dkms_version": "dkms_driver_version",
    "netplan_version": "netplan_version",
    "poe_controller": "poe_controller",
    "firmware_version": "esp32_firmware_version",
    "firmware_variant": "esp32_firmware_variant",
    "board_revision": "board_hw_version",
    "serial": "board_serial",
    "management_version": "management_version",
}


class RemoteError(Exception):
    """Base for every error the remote client raises."""


class CannotConnect(RemoteError):
    """Connection refused, timed out or dropped."""


class CertificateChanged(RemoteError):
    """The board's certificate does not match the stored pin or CA trust."""


class ProtocolError(RemoteError):
    """A reply the contract does not allow (redirect, bad JSON, odd status)."""


class BadRequest(RemoteError):
    """HTTP 400: the board rejected the request body (a plugin bug)."""


class AuthFailed(RemoteError):
    """HTTP 401: the token is revoked or the pairing code is wrong."""


class Forbidden(RemoteError):
    """HTTP 403: the token's scope does not allow this, or plain HTTP."""


class NotFound(RemoteError):
    """HTTP 404: unknown route or port (also the board's startup window)."""


class Conflict(RemoteError):
    """HTTP 409: the board holds the maximum number of HA tokens."""


class TooManyAttempts(RemoteError):
    """HTTP 429, with the Retry-After seconds when the board sent them."""

    def __init__(self, retry_after: int | None) -> None:
        super().__init__(f"retry after {retry_after}s")
        self.retry_after = retry_after


class BoardError(RemoteError):
    """HTTP 5xx: the board could not complete the request."""


class NoManagement(RemoteError):
    """GET /board answered 404: Exaviz Management is not installed."""


class ManagementTooOld(RemoteError):
    """GET /board has no ha_contract_version."""


class UnsupportedContract(RemoteError):
    """GET /board reports a contract version this plugin does not speak."""


_STATUS_ERRORS: dict[int, type[RemoteError]] = {
    400: BadRequest,
    401: AuthFailed,
    403: Forbidden,
    404: NotFound,
    409: Conflict,
}


def check_contract(board: dict[str, Any]) -> None:
    """Raise unless the board speaks this plugin's contract version."""
    version = board.get("ha_contract_version")
    if version is None:
        raise ManagementTooOld("board has no ha_contract_version")
    if version != CONTRACT_VERSION:
        raise UnsupportedContract(f"board speaks contract {version}")


def fingerprint_of(der: bytes) -> str:
    """SHA-256 of the certificate's DER bytes, lower-case hex."""
    return hashlib.sha256(der).hexdigest()


def spki_of(der: bytes) -> str:
    """SHA-256 of the certificate's SubjectPublicKeyInfo, lower-case hex."""
    spki = (
        x509.load_der_x509_certificate(der)
        .public_key()
        .public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return hashlib.sha256(spki).hexdigest()


def ca_bundle_path() -> str:
    """The CA bundle Home Assistant itself trusts."""
    bundle = os.environ.get("REQUESTS_CA_BUNDLE")
    if bundle:
        return bundle
    import certifi  # pylint: disable=import-outside-toplevel

    return certifi.where()


def build_ca_context(cafile: str) -> ssl.SSLContext:
    """Verifying context for CA mode. Blocking: run it in the executor."""
    return ssl.create_default_context(cafile=cafile)


def _no_verify_context() -> ssl.SSLContext:
    # A bare context loads no certificates, so it is safe on the event loop.
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


async def _tls_connect(
    host: str, port: int, ctx: ssl.SSLContext, timeout: float
) -> bytes:
    """Complete a TLS handshake, return the leaf DER, send no HTTP bytes."""
    _reader, writer = await asyncio.wait_for(
        asyncio.open_connection(host, port, ssl=ctx, server_hostname=host),
        timeout,
    )
    try:
        return writer.get_extra_info("ssl_object").getpeercert(binary_form=True)
    finally:
        writer.close()
        with contextlib.suppress(OSError, ssl.SSLError):
            await writer.wait_closed()


async def fetch_leaf_certificate(
    host: str, port: int, timeout: float = DEFAULT_TIMEOUT
) -> bytes:
    """Read the board's leaf certificate without verifying it."""
    try:
        return await _tls_connect(host, port, _no_verify_context(), timeout)
    except (OSError, asyncio.TimeoutError, ssl.SSLError) as err:
        raise CannotConnect(f"cannot reach {host}:{port}") from err


async def tls_verifies(
    host: str, port: int, ctx: ssl.SSLContext, timeout: float = DEFAULT_TIMEOUT
) -> bool:
    """True when the board's certificate verifies for host under ctx."""
    try:
        await _tls_connect(host, port, ctx, timeout)
    except ssl.SSLCertVerificationError:
        return False
    except (OSError, asyncio.TimeoutError, ssl.SSLError) as err:
        raise CannotConnect(f"cannot reach {host}:{port}") from err
    return True


class RemoteClient:
    """Contract v1 client. Every request goes through `_request`."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        *,
        pin: str | None = None,
        ssl_context: ssl.SSLContext | None = None,
        token: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        if not base_url.startswith("https://"):
            raise ValueError("the board URL must use https")
        if (pin is None) == (ssl_context is None):
            raise ValueError("give exactly one of pin or ssl_context")
        if pin is not None and not _PIN_RE.match(pin):
            raise ValueError("pin must be 64 lower-case hex characters")
        self._session = session
        self._base = base_url.rstrip("/") + "/api/v1"
        # Built once: a new object per request is a new pool key and a new
        # TCP connection every time.
        self._ssl: aiohttp.Fingerprint | ssl.SSLContext = (
            aiohttp.Fingerprint(bytes.fromhex(pin)) if pin else ssl_context
        )
        self._token = token
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def _request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> tuple[Any, datetime | None]:
        """Send one request; return the JSON body and the board's Date."""
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        try:
            async with self._session.request(
                method,
                self._base + path,
                json=body,
                headers=headers,
                ssl=self._ssl,
                allow_redirects=False,
                timeout=self._timeout,
            ) as resp:
                status = resp.status
                if 300 <= status < 400:
                    raise ProtocolError(f"{method} {path}: redirect {status}")
                if status == 429:
                    retry = resp.headers.get("Retry-After", "")
                    raise TooManyAttempts(int(retry) if retry.isdigit() else None)
                if status in _STATUS_ERRORS:
                    raise _STATUS_ERRORS[status](f"{method} {path}: {status}")
                if status >= 500:
                    raise BoardError(f"{method} {path}: {status}")
                if not 200 <= status < 300:
                    raise ProtocolError(f"{method} {path}: status {status}")
                try:
                    data = await resp.json(content_type=None)
                except ValueError as err:
                    raise ProtocolError(f"{method} {path}: body is not JSON") from err
                date = resp.headers.get("Date")
                return data, parsedate_to_datetime(date) if date else None
        except (aiohttp.ServerFingerprintMismatch, aiohttp.ClientConnectorCertificateError) as err:
            raise CertificateChanged("the board's certificate changed") from err
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as err:
            raise CannotConnect(f"{method} {path}: {type(err).__name__}") from err

    async def get_board(self) -> dict[str, Any]:
        return (await self._request("GET", "/board"))[0]

    async def probe(self) -> dict[str, Any]:
        """GET /board and check the contract version."""
        try:
            board = await self.get_board()
        except NotFound as err:
            raise NoManagement("GET /board answered 404") from err
        check_contract(board)
        return board

    async def get_poe_ports(self) -> tuple[dict[str, Any], datetime | None]:
        """Port list plus the response Date, the clock for port staleness."""
        return await self._request("GET", "/poe/ports")

    async def get_switch_ports(self) -> dict[str, Any]:
        return (await self._request("GET", "/switch/ports"))[0]

    async def get_health(self) -> dict[str, Any]:
        return (await self._request("GET", "/system/health"))[0]

    async def pair(self, code: str, name: str = "Home Assistant") -> dict[str, Any]:
        return (
            await self._request("POST", "/ha/pair", {"code": code, "name": name})
        )[0]

    async def port_action(self, pse: int, index: int, action: str) -> None:
        if action not in PORT_ACTIONS:
            raise ValueError(f"unknown port action {action!r}")
        await self._request("POST", f"/poe/ports/{pse}/{index}/{action}")


def map_board(board: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """GET /board -> (board_type, system_info). Empty values are left out."""
    info: dict[str, Any] = {
        ours: board[theirs]
        for theirs, ours in _BOARD_INFO_KEYS.items()
        if board.get(theirs) not in (None, "")
    }
    info["plugin_version"] = PLUGIN_VERSION
    return board.get("board_type", "unknown"), info


def map_health(health: dict[str, Any]) -> float | None:
    """GET /system/health -> board temperature in degrees C."""
    return health.get("cpu_temp_c")


def _port_number(name: str) -> int | None:
    if match := _POE_NAME_RE.match(name):
        return int(match.group(1))
    if match := _NEUTRAL_NAME_RE.match(name):
        pse, index = int(match.group(1)), int(match.group(2))
        if pse in _CRUISER_PSE_OFFSET:
            return _CRUISER_PSE_OFFSET[pse] + index
    return None


def _is_stale(updated_at: str | None, server_date: datetime | None) -> bool:
    if server_date is None or not updated_at:
        return False
    updated = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    return (server_date - updated).total_seconds() > STALE_AFTER_SECONDS


def map_ports(
    poe_body: dict[str, Any],
    switch_body: dict[str, Any],
    server_date: datetime | None,
    previous: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """GET /poe/ports + GET /switch/ports -> onboard port dicts, by port number.

    A port seen before but missing now (startup window, or one controller not
    parsed yet) keeps its last values and is marked stale.
    """
    links = {p.get("name"): p for p in switch_body.get("ports", [])}
    devices = poe_body.get("connected_devices", {})
    ports: dict[int, dict[str, Any]] = {}
    for wire in poe_body.get("ports", []):
        name = wire.get("name", "")
        number = _port_number(name)
        if number is None:
            _LOGGER.warning("Skipping board port with unknown name %r", name)
            continue
        interface = f"poe{number}"
        link = links.get(name) or links.get(interface) or {}
        stats = link.get("stats", {})
        poe_class = str(wire.get("class", "?"))
        state = wire.get("state", "unknown")
        port: dict[str, Any] = {
            "port": number,
            "interface": interface,
            "pse": wire["pse"],
            "index": wire["index"],
            "enabled": state != "disabled",
            "status": "power on" if state == "delivering" else state,
            "power_consumption_watts": wire.get("power_w", 0.0),
            "allocated_power_watts": get_allocated_power_watts(poe_class),
            "power_mocked": False,
            "poe_class": poe_class,
            "voltage_volts": wire.get("voltage_v", 0.0),
            "current_milliamps": wire.get("current_ma", 0),
            "link_state": link.get("oper_state", "unknown"),
            "speed_mbps": link.get("speed_mbps", 0),
            "rx_bytes": stats.get("rx_bytes", 0),
            "tx_bytes": stats.get("tx_bytes", 0),
            "poe_system": "onboard",
            "stale": _is_stale(wire.get("updated_at"), server_date),
        }
        if device := devices.get(interface):
            port["connected_device"] = {
                "ip_address": device.get("ip"),
                "mac_address": device.get("mac"),
                "manufacturer": device.get("manufacturer", "Unknown"),
                "hostname": device.get("hostname"),
            }
        ports[number] = port
    for old in previous or []:
        if old["port"] not in ports:
            ports[old["port"]] = {**old, "stale": True}
    return [ports[n] for n in sorted(ports)]
