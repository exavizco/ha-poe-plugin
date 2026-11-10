"""Config flow for Exaviz PoE management: this board, or one on the network."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import remote
from .board_detector import check_prerequisites, detect_all_poe_systems
from .const import (
    CONF_BOARD_TYPE,
    CONF_CONNECTION,
    CONF_FINGERPRINT,
    CONF_HOST,
    CONF_PORT,
    CONF_SCOPE,
    CONF_SERIAL,
    CONF_SPKI,
    CONF_SWITCH_MODE_DISCOVERY,
    CONF_TOKEN,
    CONF_TOKEN_ID,
    CONF_TRUST_MODE,
    CONF_UPDATE_INTERVAL,
    CONNECTION_REMOTE,
    DEFAULT_HTTPS_PORT,
    DEFAULT_SWITCH_MODE_DISCOVERY,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    TRUST_CA,
    TRUST_PIN,
)

_LOGGER = logging.getLogger(__name__)


async def validate_board_detection(hass: HomeAssistant) -> dict[str, Any]:
    """Detect board type and PoE systems.

    Checks prerequisites first (exaviz-dkms, exaviz-netplan) and then
    runs board detection.  Missing packages raise MissingPackages so the
    UI can show a targeted error message.
    """
    # Check prerequisites (best-effort — Docker hides host packages).
    # Inside a Docker container dpkg-query sees the container's packages,
    # not the host's, so we log a warning instead of blocking setup.
    prereqs = await check_prerequisites()
    if not prereqs["all_ok"]:
        in_docker = Path("/.dockerenv").exists()
        if in_docker:
            _LOGGER.warning(
                "Prerequisite check found missing packages (%s) but running "
                "inside Docker — host packages are not visible.  Continuing "
                "with board detection.",
                ", ".join(prereqs["missing"]),
            )
        else:
            raise MissingPackages(
                f"Missing required packages: {', '.join(prereqs['missing'])}. "
                "Install from apt.exaviz.com on the host OS."
            )

    try:
        detection = await detect_all_poe_systems()
        
        if detection["total_poe_ports"] == 0:
            raise NoPoEDetected("No PoE systems detected on this board")
        
        return {
            "title": f"Exaviz {detection['board_type'].value.title()}",
            "board_info": {
                "board_type": detection["board_type"].value,
                "addon_boards": len(detection["addon_boards"]),
                "onboard_ports": len(detection["onboard_ports"]),
                "total_poe_ports": detection["total_poe_ports"],
            },
        }
    except (MissingPackages, NoPoEDetected):
        raise
    except Exception as ex:
        _LOGGER.error("Board detection failed: %s", ex)
        raise CannotConnect from ex


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Exaviz local board PoE management."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> ExavizOptionsFlow:
        """Return the options flow handler."""
        return ExavizOptionsFlow(config_entry)

    def __init__(self) -> None:
        """Remote-flow state carried between steps."""
        self._host = ""
        self._port = DEFAULT_HTTPS_PORT
        self._interval = DEFAULT_UPDATE_INTERVAL
        self._der = b""
        self._board: dict[str, Any] = {}
        self._trust_mode = TRUST_PIN

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask where the board is."""
        return self.async_show_menu(step_id="user", menu_options=["local", "remote"])

    async def async_step_local(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the local step - auto-detect board."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_board_detection(self.hass)
            except MissingPackages:
                errors["base"] = "missing_packages"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except NoPoEDetected:
                errors["base"] = "no_poe_detected"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception during board detection")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(f"exaviz_{info['board_info']['board_type']}")
                self._abort_if_unique_id_configured()
                
                return self.async_create_entry(
                    title=info["title"],
                    data={
                        "board_type": info["board_info"]["board_type"],
                        "addon_boards": info["board_info"]["addon_boards"],
                        "onboard_ports": info["board_info"]["onboard_ports"],
                        "total_poe_ports": info["board_info"]["total_poe_ports"],
                        CONF_UPDATE_INTERVAL: user_input.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
                    },
                )

        # Auto-detect on first show
        if user_input is None:
            try:
                info = await validate_board_detection(self.hass)
                # Show confirmation with detected info
                return self.async_show_form(
                    step_id="local",
                    data_schema=vol.Schema(
                        {
                            vol.Optional(
                                CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL
                            ): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
                        }
                    ),
                    description_placeholders={
                        "board_type": info["board_info"]["board_type"].title(),
                        "total_ports": str(info["board_info"]["total_poe_ports"]),
                        "addon_boards": str(info["board_info"]["addon_boards"]),
                        "onboard_ports": str(info["board_info"]["onboard_ports"]),
                    },
                    errors=errors,
                )
            except MissingPackages:
                errors["base"] = "missing_packages"
            except (CannotConnect, NoPoEDetected):
                errors["base"] = "no_poe_detected"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception during initial detection")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="local",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL
                    ): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
                }
            ),
            errors=errors,
        )

    # --- Remote board ---------------------------------------------------

    async def async_step_remote(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask for the board's address, then read its certificate and /board."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._interval = user_input.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
            error = await self._probe_address(user_input)
            if error is None and self._board.get("board_type") != "cruiser":
                error = "unsupported_board"
            if error is None:
                await self.async_set_unique_id(self._board["serial"])
                return await self.async_step_fingerprint()
            errors["base"] = error
        return self.async_show_form(
            step_id="remote",
            data_schema=_address_schema(
                user_input or {}, {vol.Optional(CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL): _INTERVAL}
            ),
            errors=errors,
        )

    async def async_step_fingerprint(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show the leaf fingerprint; the user compares it with the board."""
        if user_input is None:
            return self.async_show_form(
                step_id="fingerprint",
                data_schema=vol.Schema({vol.Required("confirm", default=False): bool}),
                description_placeholders={
                    "fingerprint": _grouped(remote.fingerprint_of(self._der))
                },
            )
        if not user_input["confirm"]:
            return self.async_abort(reason="fingerprint_rejected")
        self._trust_mode = await self._decide_trust_mode()
        return await self.async_step_pair()

    async def async_step_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Redeem the pairing code over a connection pinned to the leaf."""
        errors: dict[str, str] = {}
        placeholders = {"retry_after": ""}
        step_id = "pair"
        if self.source in (config_entries.SOURCE_REAUTH, config_entries.SOURCE_RECONFIGURE):
            # Re-pair text: start pairing now, revoke the old token after.
            step_id = "repair"
            placeholders["old_token_id"] = self._existing_entry().data[CONF_TOKEN_ID]
        if user_input is not None:
            client = remote.RemoteClient(
                async_get_clientsession(self.hass),
                _url(self._host, self._port),
                pin=remote.fingerprint_of(self._der),
            )
            try:
                reply = await client.pair(user_input["code"])
            except remote.CertificateChanged:
                return await self._refetch_fingerprint()
            except remote.AuthFailed:
                errors["base"] = "invalid_code"
            except remote.TooManyAttempts as err:
                errors["base"] = "too_many_attempts"
                placeholders["retry_after"] = str(err.retry_after or 60)
            except remote.Conflict:
                errors["base"] = "token_limit"
            except remote.Forbidden:
                _LOGGER.error("The board refused pairing as not HTTPS; this is a bug")
                errors["base"] = "https_required"
            except remote.CannotConnect:
                errors["base"] = "board_unreachable"
            except remote.RemoteError as err:
                _LOGGER.error("Pairing failed: %s", err)
                errors["base"] = "unknown"
            else:
                if reply.get("serial") != self._board["serial"]:
                    return self.async_abort(reason="serial_mismatch")
                return self._finish_pairing(reply)
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema({vol.Required("code"): str}),
            errors=errors,
            description_placeholders=placeholders,
        )

    async_step_repair = async_step_pair

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """The board answered 401 or presented a new certificate."""
        entry = self._get_reauth_entry()
        error = await self._probe_address(
            {CONF_HOST: entry.data[CONF_HOST], CONF_PORT: entry.data[CONF_PORT]}
        )
        if error is not None:
            return self.async_abort(reason=error)
        if self._board["serial"] != entry.data[CONF_SERIAL]:
            return self.async_abort(reason="serial_mismatch")
        if await self._same_certificate(entry.data):
            self._trust_mode = entry.data[CONF_TRUST_MODE]
            return await self.async_step_pair()
        return await self.async_step_fingerprint()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Move the entry to a new address; re-pair if the certificate changed."""
        entry = self._get_reconfigure_entry()
        # HA offers Reconfigure on every entry of the domain; a board that runs
        # Home Assistant itself has no address to change.
        if entry.data.get(CONF_CONNECTION) != CONNECTION_REMOTE:
            return self.async_abort(reason="reconfigure_local")
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await self._probe_address(user_input)
            if error is None:
                if self._board["serial"] != entry.data[CONF_SERIAL]:
                    return self.async_abort(reason="serial_mismatch")
                if await self._same_certificate(entry.data):
                    self._update_and_reload(
                        entry,
                        {**entry.data, CONF_HOST: self._host, CONF_PORT: self._port},
                    )
                    return self.async_abort(reason="reconfigure_successful")
                return await self.async_step_fingerprint()
            errors["base"] = error
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_address_schema(user_input or dict(entry.data), {}),
            errors=errors,
        )

    # --- Remote helpers -------------------------------------------------

    def _update_and_reload(
        self, entry: config_entries.ConfigEntry, data: dict[str, Any]
    ) -> None:
        """Save new data and reload the entry exactly once.

        A loaded entry is reloaded by its update listener. An entry whose
        setup failed (revoked token at startup, board moved) has no listener
        yet, so schedule its reload here.
        """
        # Read the state first: the listener's reload can start eagerly inside
        # async_update_entry.
        has_listener = entry.state is config_entries.ConfigEntryState.LOADED
        self.hass.config_entries.async_update_entry(entry, data=data)
        if not has_listener:
            self.hass.config_entries.async_schedule_reload(entry.entry_id)

    def _existing_entry(self) -> config_entries.ConfigEntry:
        if self.source == config_entries.SOURCE_REAUTH:
            return self._get_reauth_entry()
        return self._get_reconfigure_entry()

    async def _probe_address(self, user_input: dict[str, Any]) -> str | None:
        """Read the leaf certificate, then GET /board pinned to it.

        Sets host, port, leaf and board on success; returns an error key
        otherwise. Sends no credential.
        """
        try:
            self._host, self._port = _parse_host(
                user_input.get(CONF_HOST, ""),
                user_input.get(CONF_PORT, DEFAULT_HTTPS_PORT),
            )
        except _HttpsRequired:
            return "https_required"
        except _InvalidHost:
            return "invalid_host"
        try:
            self._der = await remote.fetch_leaf_certificate(self._host, self._port)
            self._board = await remote.RemoteClient(
                async_get_clientsession(self.hass),
                _url(self._host, self._port),
                pin=remote.fingerprint_of(self._der),
            ).probe()
        except remote.NoManagement:
            return "no_management"
        except remote.ManagementTooOld:
            return "management_too_old"
        except remote.UnsupportedContract:
            return "unsupported_contract"
        except remote.RemoteError as err:
            _LOGGER.debug("Board probe failed: %s", err)
            return "board_unreachable"
        return None

    async def _ca_context(self):
        return await self.hass.async_add_executor_job(remote.build_ca_context)

    async def _decide_trust_mode(self) -> str:
        """CA when the leaf verifies for this host against HA's CA bundle."""
        try:
            if await remote.tls_verifies(self._host, self._port, await self._ca_context()):
                return TRUST_CA
        except remote.CannotConnect:
            pass
        return TRUST_PIN

    async def _same_certificate(self, data: dict[str, Any]) -> bool:
        """Pin: same leaf. CA: same key, and it verifies for this host."""
        if data[CONF_TRUST_MODE] != TRUST_CA:
            return remote.fingerprint_of(self._der) == data[CONF_FINGERPRINT]
        # CA mode checks the host name on every connection, so an unchanged
        # leaf is not enough when the address changed.
        if remote.spki_of(self._der) != data[CONF_SPKI]:
            return False
        try:
            return await remote.tls_verifies(self._host, self._port, await self._ca_context())
        except remote.CannotConnect:
            return False

    async def _refetch_fingerprint(self) -> FlowResult:
        try:
            self._der = await remote.fetch_leaf_certificate(self._host, self._port)
        except remote.CannotConnect:
            return self.async_abort(reason="board_unreachable")
        return await self.async_step_fingerprint()

    def _finish_pairing(self, reply: dict[str, Any]) -> FlowResult:
        pairing = {
            CONF_TOKEN: reply["token"],
            CONF_TOKEN_ID: reply["token_id"],
            CONF_SCOPE: reply["scope"],
        }
        trust = {
            CONF_FINGERPRINT: remote.fingerprint_of(self._der),
            CONF_SPKI: remote.spki_of(self._der),
            CONF_TRUST_MODE: self._trust_mode,
        }
        if self.source in (config_entries.SOURCE_REAUTH, config_entries.SOURCE_RECONFIGURE):
            entry = self._existing_entry()
            data = {**entry.data, **pairing}
            if self.source == config_entries.SOURCE_RECONFIGURE or trust[
                CONF_FINGERPRINT
            ] != entry.data[CONF_FINGERPRINT]:
                data.update(trust, **{CONF_HOST: self._host, CONF_PORT: self._port})
            self._update_and_reload(entry, data)
            reason = (
                "reauth_successful"
                if self.source == config_entries.SOURCE_REAUTH
                else "reconfigure_successful"
            )
            return self.async_abort(reason=reason)
        serial = self._board["serial"]
        return self.async_create_entry(
            title=self._board.get("board_name") or f"Exaviz Cruiser {serial}",
            data={
                CONF_CONNECTION: CONNECTION_REMOTE,
                CONF_HOST: self._host,
                CONF_PORT: self._port,
                **pairing,
                **trust,
                CONF_SERIAL: serial,
                CONF_BOARD_TYPE: self._board["board_type"],
                CONF_UPDATE_INTERVAL: self._interval,
            },
        )


class ExavizOptionsFlow(config_entries.OptionsFlow):
    """Handle Exaviz integration options (post-setup)."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Stash the entry (private attr avoids the HA deprecation warning)."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the integration options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = self._config_entry.options
        schema: dict[Any, Any] = {
            vol.Optional(
                CONF_UPDATE_INTERVAL,
                # Options win over the interval chosen at setup, as in the
                # coordinator; show the value that is in effect.
                default=opts.get(
                    CONF_UPDATE_INTERVAL,
                    self._config_entry.data.get(
                        CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                    ),
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
        }
        # Switch-mode discovery is a local arp-scan; it means nothing remotely.
        if self._config_entry.data.get(CONF_CONNECTION) != CONNECTION_REMOTE:
            schema[
                vol.Optional(
                    CONF_SWITCH_MODE_DISCOVERY,
                    default=opts.get(
                        CONF_SWITCH_MODE_DISCOVERY, DEFAULT_SWITCH_MODE_DISCOVERY
                    ),
                )
            ] = bool
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect to the board."""


class NoPoEDetected(HomeAssistantError):
    """Error to indicate no PoE systems were detected."""


class MissingPackages(HomeAssistantError):
    """Error to indicate required Exaviz host packages are not installed."""


class _HttpsRequired(Exception):
    """The address uses http://."""


class _InvalidHost(Exception):
    """The address has a path, query, credentials or another scheme."""


_INTERVAL = vol.All(vol.Coerce(int), vol.Range(min=10, max=300))


def _address_schema(values: dict[str, Any], extra: dict[Any, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=values.get(CONF_HOST, "")): str,
            vol.Optional(
                CONF_PORT, default=values.get(CONF_PORT, DEFAULT_HTTPS_PORT)
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
            **extra,
        }
    )


def _parse_host(value: str, port: int) -> tuple[str, int]:
    """A bare host or an https:// URL with nothing after the host and port."""
    value = value.strip()
    if "://" in value:
        scheme = value.split("://", 1)[0].lower()
        if scheme == "http":
            raise _HttpsRequired
        if scheme != "https":
            raise _InvalidHost
    else:
        value = f"https://{value}"
    try:
        parts = urlsplit(value)
        url_port = parts.port
    except ValueError as err:
        raise _InvalidHost from err
    if (
        not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or parts.path not in ("", "/")
    ):
        raise _InvalidHost
    return parts.hostname, url_port or port


def _url(host: str, port: int) -> str:
    return f"https://{host}:{port}"


def _grouped(fingerprint: str) -> str:
    return " ".join(fingerprint[i : i + 4] for i in range(0, len(fingerprint), 4))
