"""T-20..T-29: config flow, local and remote, plus reauth and reconfigure."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import aiohttp
import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.exaviz import remote
from custom_components.exaviz.board_detector import BoardType
from custom_components.exaviz.const import DOMAIN
from tests.fake_board import FakeBoard, case, make_cert

from .remote_helpers import (
    SERIAL,
    TOKEN,
    grouped,
    remote_data,
    remote_entry,
    start_remote,
)

COMPONENT = Path(__file__).parents[1] / "custom_components" / "exaviz"
LOCALES = sorted((COMPONENT / "translations").glob("*.json"))
CODE = "ABCD-EFGH"


@pytest.fixture(autouse=True)
async def no_entry_setup(hass):
    """Flows here only create entries; setup is covered by the runtime tests."""
    with (
        patch("custom_components.exaviz.async_setup_entry", return_value=True),
        patch("custom_components.exaviz.async_unload_entry", return_value=True),
    ):
        yield
        for entry in hass.config_entries.async_entries(DOMAIN):
            await hass.config_entries.async_unload(entry.entry_id)


@pytest.fixture(autouse=True)
def no_ca_bundle(monkeypatch, tmp_path):
    """An empty CA bundle unless a test sets its own: self-signed means pin."""
    empty = tmp_path / "empty-ca.pem"
    other = make_cert(("Unrelated CA",), is_ca=True)
    empty.write_bytes(other.pem)
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(empty))


def pair_calls(board: FakeBoard) -> list:
    return board.seen("POST", "/ha/pair")


async def to_pair(hass, board: FakeBoard) -> dict:
    result = await start_remote(hass, board.host, board.port)
    assert result["step_id"] == "fingerprint", result
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"confirm": True}
    )


# --- T-20, T-21: menu and the local step ------------------------------------


async def test_t20_user_shows_local_and_remote(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["local", "remote"]


def _detection(total=8):
    return {
        "board_type": BoardType.CRUISER,
        "addon_boards": [],
        "onboard_ports": [f"poe{i}" for i in range(total)],
        "total_poe_ports": total,
    }


async def _local(hass, prereqs_ok=True, detection=None, detect_error=None):
    detect = patch(
        "custom_components.exaviz.config_flow.detect_all_poe_systems",
        return_value=detection or _detection(),
        side_effect=detect_error,
    )
    prereqs = patch(
        "custom_components.exaviz.config_flow.check_prerequisites",
        return_value={"all_ok": prereqs_ok, "missing": [] if prereqs_ok else ["exaviz-dkms"]},
    )
    not_docker = patch("custom_components.exaviz.config_flow.Path")
    with detect, prereqs, not_docker as path:
        path.return_value.exists.return_value = False
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "local"}
        )
        if result["type"] is FlowResultType.FORM and not result["errors"]:
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {"update_interval": 30}
            )
    return result


async def test_t21_local_step_unchanged(hass):
    result = await _local(hass)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Exaviz Cruiser"
    assert result["data"] == {
        "board_type": "cruiser",
        "addon_boards": 0,
        "onboard_ports": 8,
        "total_poe_ports": 8,
        "update_interval": 30,
    }
    assert result["result"].unique_id == "exaviz_cruiser"


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"prereqs_ok": False}, "missing_packages"),
        ({"detection": _detection(0)}, "no_poe_detected"),
        ({"detect_error": OSError("no board")}, "no_poe_detected"),
        ({"detect_error": [_detection(), OSError("gone")]}, "cannot_connect"),
    ],
)
async def test_t21_local_errors_unchanged(hass, kwargs, error):
    result = await _local(hass, **kwargs)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "local"
    assert result["errors"] == {"base": error}


@pytest.mark.parametrize("locale", LOCALES, ids=lambda p: p.stem)
def test_t21_local_step_text_in_every_locale(locale):
    config = json.loads(locale.read_text())["config"]
    step = config["step"]["local"]
    assert step["title"] and step["description"]
    assert config["error"]["missing_packages"]


# --- T-22..T-26: remote happy path and errors -------------------------------


async def test_t22_remote_happy_path(hass, board):
    result = await start_remote(hass, board.host, board.port)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "fingerprint"
    assert result["description_placeholders"]["fingerprint"] == grouped(
        board.cert.sha256
    )
    strings = json.loads((COMPONENT / "strings.json").read_text())
    assert "Start pairing on the board now" in (
        strings["config"]["step"]["fingerprint"]["description"]
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"confirm": True}
    )
    assert result["step_id"] == "pair"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": CODE}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Garage"
    assert result["result"].unique_id == SERIAL
    assert result["data"] == {
        "connection": "remote",
        "host": "127.0.0.1",
        "port": board.port,
        "token": TOKEN,
        "token_id": "4c74bb9a093ab30e",
        "scope": "poe_control",
        "fingerprint": board.cert.sha256,
        "spki": board.cert.spki_sha256,
        "trust_mode": "pin",
        "serial": SERIAL,
        "board_type": "cruiser",
        "update_interval": 30,
    }
    (pair,) = pair_calls(board)
    assert pair.body == {"code": CODE, "name": "Home Assistant"}


async def test_t22_title_falls_back_to_serial(hass, board):
    unnamed = case("board")
    del unnamed["body"]["board_name"]
    board.reply("GET", "/board", unnamed)
    result = await to_pair(hass, board)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": CODE}
    )
    assert result["title"] == f"Exaviz Cruiser {SERIAL}"


async def test_43_long_board_name_is_trimmed_and_capped_in_the_title(hass, board):
    named = case("board")
    named["body"]["board_name"] = "  " + "N" * 500_000
    board.reply("GET", "/board", named)
    result = await to_pair(hass, board)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": CODE}
    )
    assert result["title"] == "N" * 256


async def test_43_blank_board_name_falls_back_to_serial(hass, board):
    named = case("board")
    named["body"]["board_name"] = "   "
    board.reply("GET", "/board", named)
    result = await to_pair(hass, board)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": CODE}
    )
    assert result["title"] == f"Exaviz Cruiser {SERIAL}"


async def test_43_overlong_serial_is_refused_at_setup(hass, board):
    bad = case("board")
    bad["body"]["serial"] = "S" * 5000
    board.reply("GET", "/board", bad)
    result = await start_remote(hass, board.host, board.port)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "remote"
    assert result["errors"] == {"base": "board_unreachable"}
    assert hass.config_entries.async_entries(DOMAIN) == []


async def test_t22a_pair_serial_mismatch_creates_nothing(hass, board):
    other = case("pair_201")
    other["body"]["serial"] = "CRU-OTHER-0002"
    board.reply("POST", "/ha/pair", other)
    result = await to_pair(hass, board)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": CODE}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "serial_mismatch"
    assert hass.config_entries.async_entries(DOMAIN) == []


@pytest.mark.parametrize(
    ("host", "error"),
    [
        ("http://127.0.0.1", "https_required"),
        ("HTTP://127.0.0.1", "https_required"),
        ("https://127.0.0.1/admin", "invalid_host"),
        ("https://127.0.0.1?x=1", "invalid_host"),
        ("https://user:pw@127.0.0.1", "invalid_host"),
        ("ftp://127.0.0.1", "invalid_host"),
        ("127.0.0.1/admin", "invalid_host"),
        ("", "invalid_host"),
        ("https://127.0.0.1:99999", "invalid_host"),
        ("127.0.0.1:notaport", "invalid_host"),
    ],
)
async def test_t23_host_input_refused_before_any_socket(hass, board, host, error):
    result = await start_remote(hass, host, board.port)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "remote"
    assert result["errors"] == {"base": error}
    assert board.connections == 0


async def test_t23_bare_host_uses_443_and_https_url_accepted(hass, board):
    seen = []

    async def fake_fetch(host, port, timeout=10):
        seen.append((host, port))
        raise remote.CannotConnect("test")

    with patch.object(remote, "fetch_leaf_certificate", fake_fetch):
        await start_remote(hass, "board.example")
        await start_remote(hass, "https://board.example:8443")
        await start_remote(hass, "https://board.example/")
    assert seen == [("board.example", 443), ("board.example", 8443), ("board.example", 443)]


async def test_t24_cannot_connect(hass, board):
    await board.stop()
    result = await start_remote(hass, board.host, board.port)
    assert result["errors"] == {"base": "board_unreachable"}


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ("404", "no_management"),
        ("no_contract", "management_too_old"),
        ("contract_2", "unsupported_contract"),
        ("interceptor", "unsupported_board"),
    ],
)
async def test_t24_probe_errors(hass, board, change, error):
    reply = case("board")
    if change == "404":
        reply = case("control_404")
    elif change == "no_contract":
        del reply["body"]["ha_contract_version"]
    elif change == "contract_2":
        reply["body"]["ha_contract_version"] = 2
    else:
        reply["body"]["board_type"] = "interceptor"
    board.reply("GET", "/board", reply)
    result = await start_remote(hass, board.host, board.port)
    assert result["errors"] == {"base": error}
    assert pair_calls(board) == []


async def test_t25_fingerprint_unticked_aborts(hass, board):
    result = await start_remote(hass, board.host, board.port)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"confirm": False}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "fingerprint_rejected"
    assert pair_calls(board) == []


@pytest.mark.parametrize(
    ("reply", "error"),
    [
        ("pair_401", "invalid_code"),
        ("pair_409", "token_limit"),
        ("pair_403", "https_required"),
        ("pair_500", "unknown"),
        ("pair_400", "unknown"),
    ],
)
async def test_t26_pair_errors_stay_on_step(hass, board, reply, error):
    board.reply("POST", "/ha/pair", case(reply))
    result = await to_pair(hass, board)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": CODE}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pair"
    assert result["errors"] == {"base": error}

    board.reply("POST", "/ha/pair", case("pair_201"))
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": CODE}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_t26_too_many_attempts_shows_retry_after(hass, board):
    board.reply("POST", "/ha/pair", case("pair_429"))
    result = await to_pair(hass, board)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": CODE}
    )
    assert result["errors"] == {"base": "too_many_attempts"}
    assert result["description_placeholders"]["retry_after"] == "60"


async def test_pair_certificate_change_returns_to_fingerprint(hass, board):
    result = await to_pair(hass, board)
    new = make_cert()
    await board.restart(new)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": CODE}
    )
    assert result["step_id"] == "fingerprint"
    assert result["description_placeholders"]["fingerprint"] == grouped(new.sha256)
    assert pair_calls(board) == []


# --- T-27: one board per Home Assistant -------------------------------------


@pytest.mark.parametrize("existing", ["local", "remote"])
async def test_t27_second_board_refused_before_any_request(hass, board, existing):
    if existing == "local":
        MockConfigEntry(domain=DOMAIN, data={}, unique_id="exaviz_cruiser").add_to_hass(hass)
    else:
        remote_entry(board).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"
    assert board.connections == 0


def test_t27_manifest_declares_single_config_entry():
    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    assert manifest["single_config_entry"] is True
    assert "zeroconf" not in manifest


# --- Reconfigure (T-27a, T-27b) ---------------------------------------------


async def _reconfigure(hass, entry, board: FakeBoard) -> dict:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    assert result["step_id"] == "reconfigure"
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": board.host, "port": board.port}
    )


async def test_t27a_reconfigure_same_certificate_moves_host_only(hass, board):
    old = await FakeBoard(cert=board.cert).start()
    try:
        entry = remote_entry(old)
        entry.add_to_hass(hass)
        before = dict(entry.data)
        result = await _reconfigure(hass, entry, board)
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        assert entry.data == {**before, "port": board.port}
        assert old.requests == []
        assert all("Authorization" not in r.headers for r in board.requests)
    finally:
        await old.stop()


async def test_t27a_reconfigure_ca_mode_same_key_new_certificate(hass, board, monkeypatch, tmp_path):
    ca = make_cert(("Test CA",), is_ca=True)
    bundle = tmp_path / "ca.pem"
    bundle.write_bytes(ca.pem)
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(bundle))
    first = make_cert(("127.0.0.1",), issuer=ca)
    renewed = make_cert(("127.0.0.1",), issuer=ca, key=first.key)
    await board.restart(renewed)
    entry = remote_entry(
        board,
        port=1,
        fingerprint=first.sha256,
        spki=first.spki_sha256,
        trust_mode="ca",
    )
    entry.add_to_hass(hass)
    before = dict(entry.data)
    result = await _reconfigure(hass, entry, board)
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {**before, "port": board.port}


async def test_t27b_reconfigure_new_certificate_repairs(hass, board):
    entry = remote_entry(board, port=1, fingerprint="0" * 64, spki="0" * 64)
    entry.add_to_hass(hass)
    old_token = entry.data["token"]
    result = await _reconfigure(hass, entry, board)
    assert result["step_id"] == "fingerprint"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"confirm": True}
    )
    assert result["step_id"] == "repair"
    assert result["description_placeholders"]["old_token_id"] == "0000000000000001"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": CODE}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.entry_id == "remote_entry"
    assert entry.data == remote_data(
        board,
        token=TOKEN,
        token_id="4c74bb9a093ab30e",
        scope="poe_control",
    )
    assert all(r.headers.get("Authorization") != f"Bearer {old_token}" for r in board.requests)


@pytest.mark.parametrize("where", ["probe", "pair"])
async def test_t27b_reconfigure_serial_mismatch_keeps_entry(hass, board, where):
    entry = remote_entry(board, port=1, fingerprint="0" * 64, spki="0" * 64)
    entry.add_to_hass(hass)
    before = dict(entry.data)
    if where == "probe":
        other = case("board")
        other["body"]["serial"] = "CRU-OTHER-0002"
        board.reply("GET", "/board", other)
        result = await _reconfigure(hass, entry, board)
    else:
        other = case("pair_201")
        other["body"]["serial"] = "CRU-OTHER-0002"
        board.reply("POST", "/ha/pair", other)
        result = await _reconfigure(hass, entry, board)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"confirm": True}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"code": CODE}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "serial_mismatch"
    assert entry.data == before
    assert all(
        r.headers.get("Authorization") != f"Bearer {before['token']}" for r in board.requests
    )


# --- Reauth ------------------------------------------------------------------


async def _reauth(hass, entry) -> dict:
    """Start reauth and submit its confirm form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=dict(entry.data),
    )
    assert result["step_id"] == "reauth_confirm"
    return await hass.config_entries.flow.async_configure(result["flow_id"], {})


async def test_reauth_asks_before_contacting_the_board(hass, board):
    """A reauth that probed and aborted in its first step would never be shown."""
    entry = remote_entry(board)
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=dict(entry.data),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["description_placeholders"]["host"] == entry.data["host"]
    assert board.connections == 0


async def test_reauth_same_certificate_updates_token_only(hass, board):
    entry = remote_entry(board)
    entry.add_to_hass(hass)
    before = dict(entry.data)
    result = await _reauth(hass, entry)
    assert result["step_id"] == "repair"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": CODE}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data == {
        **before,
        "token": TOKEN,
        "token_id": "4c74bb9a093ab30e",
        "scope": "poe_control",
    }


async def test_reauth_changed_certificate_shows_fingerprint_first(hass, board):
    entry = remote_entry(board, fingerprint="0" * 64, spki="0" * 64)
    entry.add_to_hass(hass)
    result = await _reauth(hass, entry)
    assert result["step_id"] == "fingerprint"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"confirm": True}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": CODE}
    )
    assert result["reason"] == "reauth_successful"
    assert entry.data["fingerprint"] == board.cert.sha256
    assert entry.data["token"] == TOKEN


async def test_t22a_reauth_serial_mismatch_keeps_entry(hass, board):
    entry = remote_entry(board)
    entry.add_to_hass(hass)
    before = dict(entry.data)
    other = case("pair_201")
    other["body"]["serial"] = "CRU-OTHER-0002"
    board.reply("POST", "/ha/pair", other)
    result = await _reauth(hass, entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": CODE}
    )
    assert result["reason"] == "serial_mismatch"
    assert entry.data == before


async def test_reauth_board_gone_says_cannot_connect_and_can_retry(hass, board):
    entry = remote_entry(board)
    entry.add_to_hass(hass)
    await board.stop()
    result = await _reauth(hass, entry)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "board_unreachable"}
    await board.start()
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "repair"


# --- T-28: trust mode ----------------------------------------------------------


async def _trust_mode(hass, board) -> str:
    result = await to_pair(hass, board)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": CODE}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    return result["data"]["trust_mode"]


@pytest.mark.parametrize(
    ("names", "bundle_set", "mode"),
    [
        (("127.0.0.1",), True, "ca"),
        (("other.example",), True, "pin"),
        (("127.0.0.1",), False, "pin"),
        (None, True, "pin"),
    ],
)
async def test_t28_trust_mode(hass, board, monkeypatch, tmp_path, names, bundle_set, mode):
    ca = make_cert(("Test CA",), is_ca=True)
    if names is not None:
        await board.restart(make_cert(names, issuer=ca))
    if bundle_set:
        bundle = tmp_path / "ca.pem"
        bundle.write_bytes(ca.pem)
        monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(bundle))
    else:
        monkeypatch.delenv("REQUESTS_CA_BUNDLE")
    checks = []
    real_check = aiohttp.Fingerprint.check

    def recording_check(self, transport):
        checks.append(self.fingerprint.hex())
        return real_check(self, transport)

    with patch.object(aiohttp.Fingerprint, "check", recording_check):
        assert await _trust_mode(hass, board) == mode
    # The pair POST went over a connection pinned to the confirmed leaf.
    assert board.cert.sha256 in checks


async def test_ca_trust_needs_the_confirmed_leaf(hass, board, monkeypatch, tmp_path):
    """A CA-valid certificate from another server must not earn CA trust."""
    ca = make_cert(("Test CA",), is_ca=True)
    bundle = tmp_path / "ca.pem"
    bundle.write_bytes(ca.pem)
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(bundle))
    await board.restart(make_cert(("127.0.0.1",), issuer=ca))
    other = make_cert(("127.0.0.1",), issuer=ca)

    async def other_server(host, port, ctx, timeout=10):
        return other.der

    monkeypatch.setattr(remote, "ca_verified_leaf", other_server)
    assert await _trust_mode(hass, board) == "pin"


# --- T-29: options -------------------------------------------------------------


async def test_t29_remote_options_interval_only(hass, board):
    entry = remote_entry(board)
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert [str(k) for k in result["data_schema"].schema] == ["update_interval"]


async def test_t29_local_options_unchanged(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={}, unique_id="exaviz_cruiser")
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert [str(k) for k in result["data_schema"].schema] == [
        "update_interval",
        "switch_mode_discovery",
    ]


# --- Review findings (independent review of the #199 diff) ----------------------


async def test_local_entry_reconfigure_aborts_before_any_input(hass, board):
    entry = MockConfigEntry(domain=DOMAIN, data={}, unique_id="exaviz_cruiser")
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_local"
    assert entry.data == {}
    assert board.connections == 0


async def test_ca_mode_same_leaf_on_a_host_it_does_not_cover_repairs(
    hass, board, monkeypatch, tmp_path
):
    """Same fingerprint, but the CA certificate does not name the new host."""
    ca = make_cert(("Test CA",), is_ca=True)
    bundle = tmp_path / "ca.pem"
    bundle.write_bytes(ca.pem)
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(bundle))
    leaf = make_cert(("board.example",), issuer=ca)
    await board.restart(leaf)
    entry = remote_entry(
        board, host="board.example", fingerprint=leaf.sha256, spki=leaf.spki_sha256,
        trust_mode="ca",
    )
    entry.add_to_hass(hass)
    before = dict(entry.data)
    result = await _reconfigure(hass, entry, board)
    assert result["step_id"] == "fingerprint"
    assert entry.data == before


async def test_options_default_is_the_interval_chosen_at_pairing(hass, board):
    entry = remote_entry(board, update_interval=120)
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    (key,) = result["data_schema"].schema
    assert key.default() == 120


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("fe80::1", ("fe80::1", 443)),
        ("[fe80::1]", ("fe80::1", 443)),
        ("https://[2001:db8::1]:8443", ("2001:db8::1", 8443)),
        ("192.168.1.20", ("192.168.1.20", 443)),
    ],
)
def test_parse_host_accepts_bare_ipv6(typed, expected):
    from custom_components.exaviz.config_flow import _parse_host

    assert _parse_host(typed, 443) == expected


# --- Coverage: local step error branches -------------------------------------

PREREQS_OK = {"all_ok": True, "missing": []}
PREREQS_MISSING = {"all_ok": False, "missing": ["exaviz-dkms"]}


async def _local_steps(hass, prereqs, detect, in_docker=False) -> list[dict]:
    """Menu -> local (auto-detect) -> submit when a form without errors shows.

    `prereqs` and `detect` are side effects: one value per call.
    """
    results = []
    with (
        patch(
            "custom_components.exaviz.config_flow.check_prerequisites",
            side_effect=prereqs,
        ),
        patch(
            "custom_components.exaviz.config_flow.detect_all_poe_systems",
            side_effect=detect,
        ),
        patch("custom_components.exaviz.config_flow.Path") as path,
    ):
        path.return_value.exists.return_value = in_docker
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "local"}
        )
        results.append(result)
        if result["type"] is FlowResultType.FORM and not result["errors"]:
            results.append(
                await hass.config_entries.flow.async_configure(
                    result["flow_id"], {"update_interval": 30}
                )
            )
    return results


async def test_local_in_docker_continues_past_missing_packages(hass, caplog):
    """Docker hides host packages: warn, then trust board detection."""
    shown, created = await _local_steps(
        hass, [PREREQS_MISSING] * 2, [_detection()] * 2, in_docker=True
    )
    assert shown["description_placeholders"]["total_ports"] == "8"
    assert created["type"] is FlowResultType.CREATE_ENTRY
    assert created["data"]["total_poe_ports"] == 8
    assert "inside Docker" in caplog.text
    assert "exaviz-dkms" in caplog.text


@pytest.mark.parametrize(
    ("prereqs", "detect", "error"),
    [
        ([PREREQS_OK, PREREQS_MISSING], [_detection()], "missing_packages"),
        ([PREREQS_OK] * 2, [_detection(), _detection(0)], "no_poe_detected"),
        ([PREREQS_OK, RuntimeError("dpkg crashed")], [_detection()], "unknown"),
    ],
)
async def test_local_submit_errors_keep_the_form(hass, caplog, prereqs, detect, error):
    """The board changed between showing the form and submitting it."""
    shown, submitted = await _local_steps(hass, prereqs, detect)
    assert shown["errors"] == {}
    assert submitted["type"] is FlowResultType.FORM
    assert submitted["step_id"] == "local"
    assert submitted["errors"] == {"base": error}
    assert hass.config_entries.async_entries(DOMAIN) == []
    if error == "unknown":
        assert "Unexpected exception during board detection" in caplog.text


async def test_local_unexpected_error_on_first_show_is_unknown(hass, caplog):
    (shown,) = await _local_steps(hass, RuntimeError("dpkg crashed"), [_detection()])
    assert shown["type"] is FlowResultType.FORM
    assert shown["errors"] == {"base": "unknown"}
    assert "Unexpected exception during initial detection" in caplog.text


# --- Coverage: remote error branches -----------------------------------------


async def test_pair_board_gone_stays_on_step_and_can_retry(hass, board):
    result = await to_pair(hass, board)
    await board.stop()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": CODE}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pair"
    assert result["errors"] == {"base": "board_unreachable"}
    assert hass.config_entries.async_entries(DOMAIN) == []
    await board.start()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": CODE}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_pair_certificate_change_with_board_gone_aborts(hass, board):
    result = await to_pair(hass, board)
    await board.restart(make_cert())

    async def gone(host, port, timeout=10):
        raise remote.CannotConnect("test")

    with patch.object(remote, "fetch_leaf_certificate", gone):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"code": CODE}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "board_unreachable"
    assert pair_calls(board) == []
    assert hass.config_entries.async_entries(DOMAIN) == []


async def test_reauth_probe_serial_mismatch_keeps_entry(hass, board):
    """Another board now answers at the address: abort before any pairing."""
    entry = remote_entry(board)
    entry.add_to_hass(hass)
    before = dict(entry.data)
    other = case("board")
    other["body"]["serial"] = "CRU-OTHER-0002"
    board.reply("GET", "/board", other)
    result = await _reauth(hass, entry)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "serial_mismatch"
    assert entry.data == before
    assert pair_calls(board) == []


async def test_reconfigure_board_unreachable_keeps_entry(hass, board):
    entry = remote_entry(board)
    entry.add_to_hass(hass)
    before = dict(entry.data)
    await board.stop()
    result = await _reconfigure(hass, entry, board)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert result["errors"] == {"base": "board_unreachable"}
    assert entry.data == before


async def test_ca_check_unreachable_falls_back_to_pin(hass, board, monkeypatch, tmp_path):
    """Same certificate and bundle as the T-28 "ca" case, but the board is
    gone when trust is decided: no CA trust without a verified handshake."""
    ca = make_cert(("Test CA",), is_ca=True)
    bundle = tmp_path / "ca.pem"
    bundle.write_bytes(ca.pem)
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(bundle))
    await board.restart(make_cert(("127.0.0.1",), issuer=ca))
    result = await start_remote(hass, board.host, board.port)
    assert result["step_id"] == "fingerprint"
    await board.stop()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"confirm": True}
    )
    assert result["step_id"] == "pair"
    await board.start()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": CODE}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["trust_mode"] == "pin"


async def test_ca_mode_new_key_needs_the_fingerprint_even_when_ca_valid(
    hass, board, monkeypatch, tmp_path
):
    """CA mode pins the key: a CA-valid leaf with a new key is re-confirmed."""
    ca = make_cert(("Test CA",), is_ca=True)
    bundle = tmp_path / "ca.pem"
    bundle.write_bytes(ca.pem)
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(bundle))
    first = make_cert(("127.0.0.1",), issuer=ca)
    await board.restart(make_cert(("127.0.0.1",), issuer=ca))
    entry = remote_entry(
        board, fingerprint=first.sha256, spki=first.spki_sha256, trust_mode="ca"
    )
    entry.add_to_hass(hass)
    before = dict(entry.data)
    result = await _reauth(hass, entry)
    assert result["step_id"] == "fingerprint"
    assert result["description_placeholders"]["fingerprint"] == grouped(
        board.cert.sha256
    )
    assert entry.data == before
    assert pair_calls(board) == []


async def test_reauth_same_key_new_leaf_skips_the_console_compare(hass, board):
    """R8: a re-issued leaf with the confirmed key, same host and port."""
    entry = remote_entry(board, fingerprint="0" * 64)
    entry.add_to_hass(hass)
    result = await _reauth(hass, entry)
    assert result["step_id"] == "repair"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"code": CODE}
    )
    assert result["reason"] == "reauth_successful"
    assert entry.data["fingerprint"] == board.cert.sha256


async def test_reconfigure_same_address_same_key_new_leaf_needs_no_compare(hass, board):
    entry = remote_entry(board, fingerprint="0" * 64)
    entry.add_to_hass(hass)
    result = await _reconfigure(hass, entry, board)
    assert result["reason"] == "reconfigure_successful"


@pytest.mark.parametrize("moved", [{"port": 1}, {"host": "192.0.2.1"}])
async def test_reconfigure_new_address_same_key_new_leaf_still_compares(
    hass, board, moved
):
    """R8: a moved address (host or port) always shows the console fingerprint."""
    entry = remote_entry(board, fingerprint="0" * 64, **moved)
    entry.add_to_hass(hass)
    result = await _reconfigure(hass, entry, board)
    assert result["step_id"] == "fingerprint"


@pytest.mark.parametrize("spki", [None, "zz", "A" * 64])
async def test_reauth_unusable_stored_key_hash_is_a_new_certificate(hass, board, spki):
    data = remote_data(board, fingerprint="0" * 64)
    if spki is None:
        del data["spki"]
    else:
        data["spki"] = spki
    entry = MockConfigEntry(
        domain=DOMAIN, data=data, unique_id="CRU-TEST-0001", entry_id="remote_entry"
    )
    entry.add_to_hass(hass)
    result = await _reauth(hass, entry)
    assert result["step_id"] == "fingerprint"
