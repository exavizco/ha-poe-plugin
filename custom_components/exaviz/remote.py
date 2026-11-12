"""HTTPS client for an Exaviz board running Exaviz Management (HA contract v1).

Used when Home Assistant runs on a different host than the board. No Home
Assistant imports: the caller passes in the aiohttp session (HA's shared one).

Copyright (c) 2026 Axzez LLC.
Licensed under the MIT License. See LICENSE for details.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import math
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
# Largest reply body read; the contract's biggest reply is a few KiB.
MAX_BODY_BYTES = 1024 * 1024
# Longest board-supplied text kept for a Board Status or port device attribute.
MAX_BOARD_STRING_CHARS = 256
# A Cruiser has 8 onboard ports; higher numbers are not this board's.
MAX_REMOTE_PORTS = 8
# Unknown board port names already warned about, so each is logged once,
# capped so a board sending new names cannot grow it without bound.
_WARNED_PORT_NAMES: set[str] = set()
_MAX_WARNED_PORT_NAMES = 32
# GET /zigbee states the sensor shows. "unknown" (the board could not read the
# unit) is a reading too; anything else means no radio state to show.
ZIGBEE_RADIO_STATES = ("on", "off", "starting", "failed")
_ZIGBEE_READINGS = frozenset({*ZIGBEE_RADIO_STATES, "unknown"})
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


def board_url(host: str, port: int) -> str:
    """https URL for host and port; an IPv6 literal goes in brackets."""
    return f"https://[{host}]:{port}" if ":" in host else f"https://{host}:{port}"


def ca_bundle_path() -> str:
    """The CA bundle Home Assistant itself trusts."""
    bundle = os.environ.get("REQUESTS_CA_BUNDLE")
    if bundle:
        return bundle
    import certifi  # pylint: disable=import-outside-toplevel

    return certifi.where()


def build_ca_context(cafile: str | None = None) -> ssl.SSLContext:
    """Verifying context for CA mode (HA's bundle by default).

    Blocking (it loads the bundle): run it in the executor.
    """
    return ssl.create_default_context(cafile=cafile or ca_bundle_path())


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


async def ca_verified_leaf(
    host: str, port: int, ctx: ssl.SSLContext, timeout: float = DEFAULT_TIMEOUT
) -> bytes | None:
    """The leaf DER when it verifies for host under ctx, else None.

    Callers compare it with the leaf the user confirmed: a verifying
    certificate from some other server must not earn CA trust.
    """
    try:
        return await _tls_connect(host, port, ctx, timeout)
    except ssl.SSLCertVerificationError:
        return None
    except (OSError, asyncio.TimeoutError, ssl.SSLError) as err:
        raise CannotConnect(f"cannot reach {host}:{port}") from err


class _SpkiPin(aiohttp.Fingerprint):
    """Pin the leaf's public key, not the whole certificate (CA mode).

    aiohttp calls check() right after the handshake, before any HTTP byte,
    the same place it checks a certificate fingerprint. A renewed leaf with
    the same key passes; any other key closes the connection.
    """

    def check(self, transport: asyncio.Transport) -> None:
        sslobj = transport.get_extra_info("ssl_object")
        der = sslobj.getpeercert(binary_form=True) if sslobj else None
        try:
            got = bytes.fromhex(spki_of(der)) if der else b""
        except ValueError:  # a leaf cryptography cannot parse is a mismatch
            got = b""
        if got != self.fingerprint:
            host, port, *_ = transport.get_extra_info("peername")
            raise aiohttp.ServerFingerprintMismatch(self.fingerprint, got, host, port)


class RemoteClient:
    """Contract v1 client. Every request goes through `_request`."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        *,
        pin: str | None = None,
        spki_pin: str | None = None,
        token: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        if not base_url.startswith("https://"):
            raise ValueError("the board URL must use https")
        if (pin is None) == (spki_pin is None):
            raise ValueError("give exactly one of pin or spki_pin")
        if not _PIN_RE.match(pin or spki_pin or ""):
            raise ValueError("pin must be 64 lower-case hex characters")
        self._session = session
        self._base = base_url.rstrip("/") + "/api/v1"
        # Built once: a new object per request is a new pool key and a new
        # TCP connection every time.
        self._ssl: aiohttp.Fingerprint = (
            aiohttp.Fingerprint(bytes.fromhex(pin))
            if pin
            else _SpkiPin(bytes.fromhex(spki_pin or ""))
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
                raw = bytearray()
                async for chunk in resp.content.iter_chunked(65536):
                    raw += chunk
                    if len(raw) > MAX_BODY_BYTES:
                        raise ProtocolError(f"{method} {path}: body too large")
                try:
                    data = json.loads(raw) if raw.strip() else None
                    date = resp.headers.get("Date")
                    return data, parsedate_to_datetime(date) if date else None
                except (RecursionError, TypeError, ValueError) as err:
                    raise ProtocolError(f"{method} {path}: unreadable reply") from err
        except (aiohttp.ServerFingerprintMismatch, aiohttp.ClientConnectorCertificateError) as err:
            raise CertificateChanged("the board's certificate changed") from err
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as err:
            raise CannotConnect(f"{method} {path}: {type(err).__name__}") from err

    async def get_board(self) -> dict[str, Any]:
        board = (await self._request("GET", "/board"))[0]
        serial = board.get("serial") if isinstance(board, dict) else None
        # The serial becomes the entry's unique id, so it is refused, not cut.
        if not isinstance(serial, str) or not 0 < len(serial) <= MAX_BOARD_STRING_CHARS:
            raise ProtocolError("GET /board: no usable serial")
        return board

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

    async def get_zigbee(self) -> Any:
        """The radio status, or None when the board gives none.

        The radio is one optional reading, so a board without the route
        (404), a refusal (403), a board-side error (5xx) or an unreadable
        reply only leave its sensor unavailable. Auth, certificate and
        connection errors still fail the poll like every other read.
        """
        try:
            return (await self._request("GET", "/zigbee"))[0]
        except (NotFound, Forbidden, BoardError, ProtocolError) as err:
            _LOGGER.debug("No Zigbee radio state from the board: %s", err)
            return None

    async def pair(self, code: str, name: str = "Home Assistant") -> dict[str, Any]:
        reply = (
            await self._request("POST", "/ha/pair", {"code": code, "name": name})
        )[0]
        if not isinstance(reply, dict) or not all(
            isinstance(reply.get(key), str)
            for key in ("token", "token_id", "scope", "serial")
        ):
            raise ProtocolError("POST /ha/pair: incomplete reply")
        return reply

    async def port_action(self, pse: int, index: int, action: str) -> None:
        if action not in PORT_ACTIONS:
            raise ValueError(f"unknown port action {action!r}")
        await self._request("POST", f"/poe/ports/{pse}/{index}/{action}")


def board_text(value: Any) -> str | None:
    """Board-supplied text, trimmed and cut to MAX_BOARD_STRING_CHARS.

    None for a value that is not text or is blank.
    """
    if isinstance(value, str) and (value := value.strip()):
        return value[:MAX_BOARD_STRING_CHARS]
    return None


def map_board(board: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """GET /board -> (board_type, system_info).

    Empty values and values that are not text are left out; text is trimmed
    and cut to MAX_BOARD_STRING_CHARS.
    """
    info: dict[str, Any] = {}
    for theirs, ours in _BOARD_INFO_KEYS.items():
        if (value := board_text(board.get(theirs))) is not None:
            info[ours] = value
    info["plugin_version"] = PLUGIN_VERSION
    return board.get("board_type", "unknown"), info


def map_total_ports(board: dict[str, Any]) -> int | None:
    """GET /board -> the PoE port count, or None unless a positive int."""
    total = board.get("total_poe_ports")
    return total if type(total) is int and total > 0 else None


def map_health(health: dict[str, Any]) -> float | None:
    """GET /system/health -> board temperature in degrees C, or None.

    A value that is not a finite number (a bool is not one) counts as missing.
    """
    temp = health.get("cpu_temp_c")
    if isinstance(temp, (int, float)) and not isinstance(temp, bool) and math.isfinite(temp):
        return temp
    return None


def map_zigbee(body: Any) -> str | None:
    """GET /zigbee -> a ZIGBEE_RADIO_STATES value, "unknown", or None.

    None when there is no radio state: the unit is not installed
    (not_available), the reply is the stub of a board older than the radio
    service, the route is missing, or the state is one this plugin does not
    know (the contract says to treat that as unavailable).
    """
    if not isinstance(body, dict) or body.get("stub") is not False:
        return None
    state = body.get("state")
    return state if isinstance(state, str) and state in _ZIGBEE_READINGS else None


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
        pse, index = wire.get("pse"), wire.get("index")
        # pse and index go into the control URL, so they must be plain ints.
        if (
            number is None
            or number >= MAX_REMOTE_PORTS
            or type(pse) is not int
            or type(index) is not int
        ):
            if name not in _WARNED_PORT_NAMES and len(_WARNED_PORT_NAMES) < _MAX_WARNED_PORT_NAMES:
                _WARNED_PORT_NAMES.add(name)
                _LOGGER.warning("Skipping board port %r: unknown name or address", name)
            continue
        interface = f"poe{number}"
        link = links.get(name) or links.get(interface) or {}
        stats = link.get("stats", {})
        poe_class = str(wire.get("class", "?"))
        state = wire.get("state", "unknown")
        port: dict[str, Any] = {
            "port": number,
            "interface": interface,
            "pse": pse,
            "index": index,
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
                "ip_address": board_text(device.get("ip")),
                "mac_address": board_text(device.get("mac")),
                "manufacturer": board_text(device.get("manufacturer")) or "Unknown",
                "hostname": board_text(device.get("hostname")),
            }
        ports[number] = port
    for old in previous or []:
        if old["port"] not in ports:
            ports[old["port"]] = {**old, "stale": True}
    return [ports[n] for n in sorted(ports)]
