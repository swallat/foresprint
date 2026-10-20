# SPDX-License-Identifier: EUPL-1.2
"""Translation of the user interface (English/German).

Source texts are English; ``t("Saved: {names}", names=...)`` returns the English text or, for
German, the translation from ``locale_de.DE``. Language: environment variable
FORESPRINT_LANG > user setting (``foresprint language`` or the sidebar of the web UI)
> English. File contents (YAML) are English regardless of the language.
"""

from __future__ import annotations

import os

LANG_ENV = "FORESPRINT_LANG"
LANGUAGES: dict[str, str] = {"de": "Deutsch", "en": "English"}
DEFAULT = "en"

_override: str | None = None


def language() -> str:
    if _override:
        return _override
    for raw in (os.environ.get(LANG_ENV), _saved()):
        code = (raw or "").strip().lower()[:2]
        if code in LANGUAGES:
            return code
    return DEFAULT


_cache: dict[str, tuple[float, str | None]] = {}


def _saved() -> str | None:
    """Saved language; the file is only re-read when it changes."""
    from foresprint import config

    path = config.config_dir() / "settings.json"
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return None
    cached = _cache.get(str(path))
    if cached is None or cached[0] != stamp:
        value = config.load().get("language")
        cached = _cache[str(path)] = (stamp, value if isinstance(value, str) and value else None)
    return cached[1]


def set_language(code: str | None) -> None:
    """Set the language for this process (None = back to setting/environment)."""
    global _override
    _override = code if code in LANGUAGES else None


def save_language(code: str) -> None:
    from foresprint import config

    if code not in LANGUAGES:
        raise ValueError(code)
    config.update(language=code)


def is_english() -> bool:
    return language() == "en"


def t(text: str, /, **values: object) -> str:
    """Translates ``text`` (English source text) and fills in ``values``."""
    template = text
    if not is_english():
        from foresprint.locale_de import DE

        template = DE.get(text, text)
    return template.format(**values) if values else template
