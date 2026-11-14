"""Real-HA test harness for the exaviz integration.

Run from the repo root: pytest -c tests_ha/pytest.ini --rootdir .
Harness pins: requirements-current.txt (current HA) and requirements-floor.txt
(the HA 2024.12 floor); run both.
"""

import asyncio
import threading
from unittest.mock import patch

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


def pytest_addoption(parser):
    parser.addoption(
        "--update-card-fixture",
        action="store_true",
        help="Rewrite the card's read-scope states fixture (T-43) instead of comparing.",
    )


@pytest.fixture(autouse=True, scope="session")
def pycares_shutdown_thread() -> None:
    """Start pycares' shutdown thread before any test snapshots its threads.

    pycares 4.9+ destroys each resolver channel on one daemon thread that it
    starts the first time a channel is closed or collected and never stops.
    The 2024.12 harness fails whichever test starts it as a lingering thread;
    newer harnesses allow it by name.
    Destroying one channel here puts the thread in every test's "before" set.
    """
    import pycares

    pycares.Channel().close()
    if tuple(int(n) for n in pycares.__version__.split(".")[:2]) >= (4, 9):
        # If a release stops starting it here, fail now, not in a later test.
        assert any(
            "_run_safe_shutdown_loop" in t.name for t in threading.enumerate()
        ), "pycares did not start its shutdown thread"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let HA load custom_components/exaviz."""


@pytest.fixture(autouse=True)
def no_frontend_registration(request):
    """Skip static path registration so no test needs a real http server."""
    if request.node.get_closest_marker("frontend_smoke"):
        yield
        return
    with patch("custom_components.exaviz._register_frontend"):
        yield


@pytest.fixture
async def board(socket_enabled):
    """A fake board on 127.0.0.1 over TLS, stopped after the test."""
    from tests.fake_board import FakeBoard

    # A client that rejects the board's certificate aborts the handshake; the
    # server side logs that on the loop, which the harness counts as an error.
    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()

    def handler(loop, context):
        if context.get("message", "").startswith(
            "Error on transport creation for incoming connection"
        ):
            return
        if previous:
            previous(loop, context)
        else:
            loop.default_exception_handler(context)

    loop.set_exception_handler(handler)
    fake = await FakeBoard().start()
    yield fake
    await fake.stop()
    loop.set_exception_handler(previous)


@pytest.fixture
def short_remote_timeout():
    """Cap the remote client's timeouts at 1 s.

    For tests that connect to a board stopped with stop_holding_port():
    Linux refuses that connection at once, but macOS drops it, and the
    client would wait its full timeout there.
    """
    from custom_components.exaviz import remote

    real_connect = remote._tls_connect
    real_init = remote.RemoteClient.__init__

    async def tls_connect(host, port, ctx, timeout):
        return await real_connect(host, port, ctx, min(timeout, 1))

    def init(self, *args, timeout=remote.DEFAULT_TIMEOUT, **kwargs):
        real_init(self, *args, timeout=min(timeout, 1), **kwargs)

    with patch.object(remote, "_tls_connect", tls_connect), \
         patch.object(remote.RemoteClient, "__init__", init):
        yield
