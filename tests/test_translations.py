"""Every translation file must match the English source key for key.

Home Assistant falls back to raw keys when a translation is missing, so a
language file that lags behind en.json shows users broken setup screens.
"""

import json
import re
from pathlib import Path

import pytest

COMPONENT_DIR = Path(__file__).parent.parent / "custom_components" / "exaviz"
TRANSLATIONS_DIR = COMPONENT_DIR / "translations"
PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")
LANGUAGE_FILES = sorted(TRANSLATIONS_DIR.glob("*.json"))


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _leaves(tree: dict, prefix: str = "") -> dict[str, str]:
    leaves = {}
    for key, value in tree.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            leaves.update(_leaves(value, f"{path}."))
        else:
            leaves[path] = value
    return leaves


EN_LEAVES = _leaves(_load(TRANSLATIONS_DIR / "en.json"))


def test_strings_json_equals_en_json():
    assert _load(COMPONENT_DIR / "strings.json") == _load(TRANSLATIONS_DIR / "en.json")


@pytest.mark.parametrize("path", LANGUAGE_FILES, ids=lambda p: p.stem)
def test_translation_has_same_keys_as_english(path):
    leaves = _leaves(_load(path))
    assert sorted(set(EN_LEAVES) - set(leaves)) == [], "missing keys"
    assert sorted(set(leaves) - set(EN_LEAVES)) == [], "extra keys"


@pytest.mark.parametrize("path", LANGUAGE_FILES, ids=lambda p: p.stem)
def test_translation_keeps_english_placeholders(path):
    leaves = _leaves(_load(path))
    mismatched = {
        key: (sorted(PLACEHOLDER_RE.findall(value)), sorted(PLACEHOLDER_RE.findall(EN_LEAVES[key])))
        for key, value in leaves.items()
        if key in EN_LEAVES
        and set(PLACEHOLDER_RE.findall(value)) != set(PLACEHOLDER_RE.findall(EN_LEAVES[key]))
    }
    assert mismatched == {}
