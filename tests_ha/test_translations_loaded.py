"""Home Assistant serves every shipped language from its own file.

HA fills a key that a language lacks with the English text. Comparing what HA
loads with the language file itself catches any key that falls back.
"""

import json
from pathlib import Path

import pytest
from homeassistant.helpers.translation import async_get_translations

from custom_components.exaviz.const import DOMAIN

TRANSLATIONS = Path(__file__).parents[1] / "custom_components" / DOMAIN / "translations"
LANGUAGES = sorted(p.stem for p in TRANSLATIONS.glob("*.json") if p.stem != "en")
CATEGORIES = ("config", "options", "services", "entity")


def flatten(tree: dict, prefix: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in tree.items():
        if isinstance(value, dict):
            out.update(flatten(value, f"{prefix}.{key}"))
        else:
            out[f"{prefix}.{key}"] = value
    return out


def test_every_language_is_checked():
    assert len(LANGUAGES) == 9


@pytest.mark.parametrize("language", LANGUAGES)
async def test_no_key_falls_back_to_english(hass, language):
    own = json.loads((TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8"))
    english = json.loads((TRANSLATIONS / "en.json").read_text(encoding="utf-8"))
    for category in CATEGORIES:
        loaded = await async_get_translations(hass, language, category, [DOMAIN])
        prefix = f"component.{DOMAIN}.{category}"
        expected = flatten(own.get(category, {}), prefix)
        assert set(loaded) == set(flatten(english.get(category, {}), prefix))
        assert loaded == expected, f"{language} {category} falls back for: " + ", ".join(
            k for k in loaded if loaded[k] != expected.get(k)
        )
