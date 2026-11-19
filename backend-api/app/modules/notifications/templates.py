"""Push texts per `<ENTITY_TYPE>.<STATUS>` and language (templates/vi.json, templates/en.json).

A status without a template sends no push (e.g. FOOD_ORDER.PENDING, which the guest created
themselves). Missing English falls back to Vietnamese. Payloads never contain personal data.
"""

import json
from functools import cache
from pathlib import Path

_DIR = Path(__file__).parent / "templates"
LANGUAGES = ("vi", "en")
DEFAULT_LANGUAGE = "vi"


@cache
def _load(lang: str) -> dict[str, dict[str, str]]:
    return json.loads((_DIR / f"{lang}.json").read_text(encoding="utf-8"))


def template_key(entity_type: str, status: str) -> str:
    return f"{entity_type}.{status}"


def render(entity_type: str, status: str, lang: str) -> dict[str, str] | None:
    key = template_key(entity_type, status)
    chosen = lang if lang in LANGUAGES else DEFAULT_LANGUAGE
    return _load(chosen).get(key) or _load(DEFAULT_LANGUAGE).get(key)


def keys(lang: str) -> set[str]:
    return set(_load(lang))
