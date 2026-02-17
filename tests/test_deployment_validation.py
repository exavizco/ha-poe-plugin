"""Deployment validation tests."""
import py_compile
import tempfile
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).parent.parent


def test_required_files_exist():
    """Verify required files exist for deployment."""
    required = [
        "custom_components/exaviz/__init__.py",
        "custom_components/exaviz/manifest.json",
        "custom_components/exaviz/sensor.py",
        "custom_components/exaviz/switch.py",
        "custom_components/exaviz/services.py",
        "custom_components/exaviz/base_entity.py",
        "custom_components/exaviz/utils.py",
    ]
    for path in required:
        assert (PROJECT_ROOT / path).exists(), f"Missing: {path}"


def test_no_syntax_errors():
    """Verify all Python files compile without syntax errors."""
    py_files = list((PROJECT_ROOT / "custom_components" / "exaviz").glob("*.py"))
    for py_file in py_files:
        try:
            with tempfile.NamedTemporaryFile(suffix=".pyc", delete=True) as tmp:
                py_compile.compile(str(py_file), tmp.name, doraise=True)
        except py_compile.PyCompileError as e:
            pytest.fail(f"Syntax error in {py_file}: {e}")
