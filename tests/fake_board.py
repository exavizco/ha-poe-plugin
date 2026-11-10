"""Fake Exaviz board for remote-host tests: HTTPS on 127.0.0.1, fixture replies.

No Home Assistant imports, so both test suites can use it.
"""
from __future__ import annotations

import asyncio
import copy
import datetime as dt
import hashlib
import ipaddress
import json
import ssl
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aiohttp import web
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "board_contract_v1.json").read_text()
)["cases"]


def case(name: str) -> dict[str, Any]:
    """A deep copy of one fixture case."""
    return copy.deepcopy(FIXTURE[name])


@dataclass
class Cert:
    """A certificate, its key and the files an SSLContext loads."""

    cert: x509.Certificate
    key: ec.EllipticCurvePrivateKey
    cert_path: str
    key_path: str

    @property
    def der(self) -> bytes:
        return self.cert.public_bytes(serialization.Encoding.DER)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.der).hexdigest()

    @property
    def spki_sha256(self) -> str:
        spki = self.cert.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return hashlib.sha256(spki).hexdigest()

    @property
    def pem(self) -> bytes:
        return self.cert.public_bytes(serialization.Encoding.PEM)


def make_cert(
    names: tuple[str, ...] = ("127.0.0.1",),
    issuer: Cert | None = None,
    is_ca: bool = False,
    key: ec.EllipticCurvePrivateKey | None = None,
) -> Cert:
    """Self-signed (issuer None) or CA-signed certificate for the given SANs."""
    key = key or ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0])])
    sans: list[x509.GeneralName] = []
    for name in names:
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(name)))
        except ValueError:
            sans.append(x509.DNSName(name))
    now = dt.datetime.now(dt.timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer.cert.subject if issuer else subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=is_ca, path_length=None), critical=True)
    )
    if not is_ca:
        builder = builder.add_extension(x509.SubjectAlternativeName(sans), critical=False)
    cert = builder.sign(issuer.key if issuer else key, hashes.SHA256())
    tmp = Path(tempfile.mkdtemp(prefix="exaviz-cert-"))
    cert_path, key_path = tmp / "cert.pem", tmp / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return Cert(cert, key, str(cert_path), str(key_path))


@dataclass
class Seen:
    """One request the fake board received."""

    method: str
    path: str
    headers: dict[str, str]
    body: Any


@dataclass
class FakeBoard:
    """HTTPS server replaying fixture cases. Override a route with `reply`."""

    cert: Cert = field(default_factory=make_cert)
    host: str = "127.0.0.1"
    port: int = 0
    connections: int = 0
    requests: list[Seen] = field(default_factory=list)
    replies: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    _server: asyncio.AbstractServer | None = None
    _runner: web.AppRunner | None = None

    def __post_init__(self) -> None:
        self.replies.update(
            {
                ("GET", "/api/v1/board"): case("board"),
                ("GET", "/api/v1/poe/ports"): case("poe_ports"),
                ("GET", "/api/v1/switch/ports"): case("switch_ports"),
                ("GET", "/api/v1/system/health"): case("health"),
                ("POST", "/api/v1/ha/pair"): case("pair_201"),
            }
        )
        for pse in (0, 1):
            for index in range(4):
                for action in ("enable", "disable", "reset"):
                    self.replies[
                        ("POST", f"/api/v1/poe/ports/{pse}/{index}/{action}")
                    ] = case(f"control_{action}_200")

    def reply(self, method: str, path: str, reply: dict[str, Any]) -> None:
        self.replies[(method, f"/api/v1{path}")] = reply

    def seen(self, method: str | None = None, path: str | None = None) -> list[Seen]:
        return [
            r
            for r in self.requests
            if (method is None or r.method == method)
            and (path is None or r.path == f"/api/v1{path}")
        ]

    @property
    def url(self) -> str:
        return f"https://{self.host}:{self.port}"

    async def _handle(self, request: web.Request) -> web.StreamResponse:
        raw = await request.read()
        self.requests.append(
            Seen(
                request.method,
                request.path_qs,
                dict(request.headers),
                json.loads(raw) if raw else None,
            )
        )
        reply = self.replies.get((request.method, request.path))
        if reply is None:
            return web.json_response(
                {"error": "not found", "code": "NOT_FOUND"}, status=404
            )
        headers = dict(reply.get("headers", {}))
        if "body" not in reply:
            return web.Response(status=reply["status"], headers=headers)
        return web.json_response(reply["body"], status=reply["status"], headers=headers)

    def ssl_context(self) -> ssl.SSLContext:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(self.cert.cert_path, self.cert.key_path)
        return ctx

    async def start(self) -> FakeBoard:
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", self._handle)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        server_factory = self._runner.server

        def counting_factory():
            self.connections += 1
            return server_factory()

        self._server = await asyncio.get_running_loop().create_server(
            counting_factory, self.host, self.port, ssl=self.ssl_context()
        )
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def restart(self, cert: Cert | None = None) -> None:
        """Serve again on the same port, optionally with a new certificate."""
        await self.stop()
        if cert:
            self.cert = cert
        await self.start()

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
