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

_LOGGER = logging.getLogger(__name__)

CONTRACT_VERSION = 1
DEFAULT_TIMEOUT = 10
PORT_ACTIONS = frozenset({"enable", "disable", "reset"})
_PIN_RE = re.compile(r"^[0-9a-f]{64}$")


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
