# SPDX-License-Identifier: EUPL-1.2
"""Übersetzung der Oberfläche (Deutsch/Englisch).

Quelltexte sind deutsch; ``t("Gespeichert: {names}", names=...)`` liefert je nach Sprache den
deutschen Text oder die Übersetzung aus ``locale_en.EN``. Sprache: Umgebungsvariable
SPRINTFORECAST_LANG > Benutzereinstellung (``sprintforecast language`` bzw. Seitenleiste der
Weboberfläche) > Englisch. Dateiinhalte (YAML) sind unabhängig davon englisch.
"""

from __future__ import annotations

import os

LANG_ENV = "SPRINTFORECAST_LANG"
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
    """Gespeicherte Sprache; die Datei wird nur bei Änderung neu gelesen."""
    from sprintforecast import config

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
    """Sprache für diesen Prozess festlegen (None = wieder aus Einstellung/Umgebung)."""
    global _override
    _override = code if code in LANGUAGES else None


def save_language(code: str) -> None:
    from sprintforecast import config

    if code not in LANGUAGES:
        raise ValueError(code)
    config.update(language=code)


def is_english() -> bool:
    return language() == "en"


def t(text: str, /, **values: object) -> str:
    """Übersetzt ``text`` (deutscher Quelltext) und setzt ``values`` ein."""
    template = text
    if is_english():
        from sprintforecast.locale_en import EN

        template = EN.get(text, text)
    return template.format(**values) if values else template
