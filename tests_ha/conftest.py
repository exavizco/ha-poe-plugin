"""Real-HA test harness for the exaviz integration.

Run from the repo root: pytest -c tests_ha/pytest.ini --rootdir .
"""

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
