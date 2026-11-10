"""T-01..T-10: the remote-host HTTPS client against a fake TLS board."""
from __future__ import annotations

import asyncio
import datetime as dt
from unittest.mock import patch

import aiohttp
import pytest
import pytest_asyncio

from custom_components.exaviz import remote
from custom_components.exaviz.remote import (
    AuthFailed,
    BadRequest,
    BoardError,
    CannotConnect,
    CertificateChanged,
    Conflict,
    Forbidden,
    ManagementTooOld,
    NoManagement,
    NotFound,
    ProtocolError,
    RemoteClient,
    TooManyAttempts,
    UnsupportedContract,
)

from .fake_board import FakeBoard, case, make_cert

TOKEN = "exha_4c74bb9a093ab30e_" + "ab" * 32


@pytest_asyncio.fixture
async def board():
    fake = await FakeBoard().start()
    yield fake
    await fake.stop()


@pytest_asyncio.fixture
async def session():
    async with aiohttp.ClientSession() as s:
        yield s


def client(session, board, **kwargs) -> RemoteClient:
    kwargs.setdefault("pin", board.cert.sha256)
    return RemoteClient(session, board.url, **kwargs)


@pytest.mark.asyncio
async def test_t01_https_with_right_pin_parses_and_reuses_connection(board, session):
    c = client(session, board)
    assert (await c.get_board())["serial"] == "CRU-TEST-0001"
    await c.get_health()
    assert board.connections == 1


@pytest.mark.asyncio
async def test_t02_http_base_refused_before_any_socket(board, session):
    with pytest.raises(ValueError):
        RemoteClient(session, f"http://127.0.0.1:{board.port}", pin=board.cert.sha256)
    assert board.connections == 0


@pytest.mark.asyncio
async def test_t03_pin_mismatch_sends_nothing(board, session):
    c = client(session, board, pin="0" * 64, token=TOKEN)
    with pytest.raises(CertificateChanged):
        await c.get_poe_ports()
    assert board.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [{}, {"pin": "abc"}, {"pin": "Z" * 64}, {"pin": "a" * 64, "ssl_context": object()}],
)
async def test_t04_bad_trust_policy_raises_before_socket(board, session, kwargs):
    with pytest.raises(ValueError):
        RemoteClient(session, board.url, **kwargs)
    assert board.connections == 0


@pytest.mark.asyncio
async def test_t05_redirect_is_protocol_error_and_not_followed(board, session):
    second = await FakeBoard().start()
    try:
        board.reply(
            "GET",
            "/poe/ports",
            {"status": 308, "headers": {"Location": f"{second.url}/api/v1/poe/ports"}},
        )
        with pytest.raises(ProtocolError):
            await client(session, board, token=TOKEN).get_poe_ports()
        assert second.requests == []
        assert second.connections == 0
    finally:
        await second.stop()


@pytest.mark.asyncio
async def test_t06_bearer_header_only(board, session):
    c = client(session, board, token=TOKEN)
    await c.get_board()
    await c.get_poe_ports()
    await c.get_switch_ports()
    await c.get_health()
    await c.port_action(1, 0, "disable")
    assert len(board.requests) == 5
    for seen in board.requests:
        assert seen.headers["Authorization"] == f"Bearer {TOKEN}"
        assert "token=" not in seen.path
        assert "Cookie" not in seen.headers


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reply", "error"),
    [
        ("unauth_401", AuthFailed),
        ("control_403", Forbidden),
        ("control_404", NotFound),
        ("pair_409", Conflict),
        ("pair_429", TooManyAttempts),
        ("control_500", BoardError),
        ("control_400", BadRequest),
    ],
)
async def test_t07_status_mapping(board, session, reply, error):
    board.reply("POST", "/poe/ports/1/0/disable", case(reply))
    with pytest.raises(error):
        await client(session, board, token=TOKEN).port_action(1, 0, "disable")


@pytest.mark.asyncio
async def test_t07_retry_after(board, session):
    board.reply("POST", "/ha/pair", case("pair_429"))
    with pytest.raises(TooManyAttempts) as err:
        await client(session, board).pair("ABCD-EFGH")
    assert err.value.retry_after == 60

    no_header = case("pair_429")
    del no_header["headers"]
    board.reply("POST", "/ha/pair", no_header)
    with pytest.raises(TooManyAttempts) as err:
        await client(session, board).pair("ABCD-EFGH")
    assert err.value.retry_after is None


@pytest.mark.asyncio
async def test_t07_refused_and_timeout(board, session):
    c = client(session, board)
    await board.stop()
    with pytest.raises(CannotConnect):
        await c.get_board()

    await board.start()

    async def hang(request):
        await asyncio.sleep(5)

    with patch.object(board, "_handle", hang):
        with pytest.raises(CannotConnect):
            await client(session, board, timeout=0.2).get_board()


@pytest.mark.asyncio
async def test_t08_leaf_fingerprint_without_http(board):
    der = await remote.fetch_leaf_certificate("127.0.0.1", board.port)
    assert der == board.cert.der
    assert remote.fingerprint_of(der) == board.cert.sha256
    assert remote.spki_of(der) == board.cert.spki_sha256
    assert board.connections == 1
    assert board.requests == []


@pytest.mark.asyncio
async def test_t09_probe_outcomes(board, session):
    c = client(session, board)
    assert (await c.probe())["serial"] == "CRU-TEST-0001"

    old = case("board")
    del old["body"]["ha_contract_version"]
    board.reply("GET", "/board", old)
    with pytest.raises(ManagementTooOld):
        await c.probe()

    newer = case("board")
    newer["body"]["ha_contract_version"] = 2
    board.reply("GET", "/board", newer)
    with pytest.raises(UnsupportedContract):
        await c.probe()

    board.reply("GET", "/board", case("control_404"))
    with pytest.raises(NoManagement):
        await c.probe()


@pytest.mark.asyncio
async def test_t10_one_door(board, session):
    c = client(session, board, token=TOKEN)

    class Sentinel(Exception):
        pass

    with patch.object(c, "_request", side_effect=Sentinel):
        for call in (
            c.get_board(),
            c.get_poe_ports(),
            c.get_switch_ports(),
            c.get_health(),
            c.pair("ABCD-EFGH"),
            c.port_action(1, 0, "reset"),
            c.probe(),
        ):
            with pytest.raises(Sentinel):
                await call
    assert board.requests == []


@pytest.mark.asyncio
async def test_poe_ports_returns_board_date(board, session):
    body, date = await client(session, board, token=TOKEN).get_poe_ports()
    assert len(body["ports"]) == 8
    assert date == dt.datetime(2026, 11, 10, 19, 30, 1, tzinfo=dt.timezone.utc)


@pytest.mark.asyncio
async def test_port_action_paths(board, session):
    c = client(session, board, token=TOKEN)
    await c.port_action(1, 0, "disable")
    await c.port_action(0, 1, "enable")
    await c.port_action(0, 3, "reset")
    assert [(r.method, r.path) for r in board.requests] == [
        ("POST", "/api/v1/poe/ports/1/0/disable"),
        ("POST", "/api/v1/poe/ports/0/1/enable"),
        ("POST", "/api/v1/poe/ports/0/3/reset"),
    ]
    with pytest.raises(ValueError):
        await c.port_action(0, 0, "explode")


@pytest.mark.asyncio
async def test_pair_body(board, session):
    reply = await client(session, board).pair("ABCD-EFGH")
    assert reply["token_id"] == "4c74bb9a093ab30e"
    (seen,) = board.requests
    assert seen.body == {"code": "ABCD-EFGH", "name": "Home Assistant"}
    assert "Authorization" not in seen.headers


@pytest.mark.asyncio
async def test_ca_mode_verifies_against_the_bundle(session, tmp_path):
    ca = make_cert(("Test CA",), is_ca=True)
    fake = await FakeBoard(cert=make_cert(("127.0.0.1",), issuer=ca)).start()
    try:
        bundle = tmp_path / "ca.pem"
        bundle.write_bytes(ca.pem)
        ctx = remote.build_ca_context(str(bundle))
        c = RemoteClient(session, fake.url, ssl_context=ctx)
        assert (await c.get_board())["serial"] == "CRU-TEST-0001"
        assert await remote.tls_verifies("127.0.0.1", fake.port, ctx)

        await fake.restart(make_cert(("127.0.0.1",)))
        with pytest.raises(CertificateChanged):
            await RemoteClient(session, fake.url, ssl_context=ctx).get_board()
        assert not await remote.tls_verifies("127.0.0.1", fake.port, ctx)
    finally:
        await fake.stop()
