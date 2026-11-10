"""Real-HA test harness for the exaviz integration.

Run from the repo root: pytest -c tests_ha/pytest.ini --rootdir .
Harness pins: requirements-current.txt (current HA) and requirements-floor.txt
(the HA 2024.12 floor); run both.
"""

import asyncio
from unittest.mock import patch

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


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
