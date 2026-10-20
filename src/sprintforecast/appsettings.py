# SPDX-License-Identifier: EUPL-1.2
"""Application settings of the single user / machine (not shared with the team).

They live in the user settings file next to the language (see :mod:`config`), never in the team
data folder. Each setting is a small function pair here (read with default, validated save), so
a new one only needs an entry here and a row on the "App settings" page.
"""

from __future__ import annotations

from sprintforecast import config

# Theme of the web UI: "system" follows the setting of the browser/operating system. The
# labels are English source texts, translated on display.
THEMES: dict[str, str] = {"system": "As system", "light": "Light", "dark": "Dark"}
DEFAULT_THEME = "system"

# Indigo + mint scheme. Streamlit follows the system only while the light/dark sections are set
# (``theme.base`` is then ignored), so a fixed theme uses the plain options instead.
_LIGHT = {"primaryColor": "#5b5bf0"}
_DARK = {
    "primaryColor": "#8f8ff7",
    "backgroundColor": "#12121f",
    "secondaryBackgroundColor": "#1c1c30",
    "textColor": "#ebebf5",
    "linkColor": "#4fd8ba",
}


def theme() -> str:
    value = config.load().get("theme")
    return value if value in THEMES else DEFAULT_THEME


def save_theme(code: str) -> None:
    if code not in THEMES:
        raise ValueError(code)
    config.update(theme=code)


def theme_options(code: str | None = None) -> dict[str, str | None]:
    """Streamlit options for the theme; ``None`` = unset. Every option is listed, so switching
    the theme at runtime can reset the ones of the previous choice."""
    code = code or theme()
    options: dict[str, str | None] = {"theme.base": code if code != "system" else None}
    fixed = {"light": _LIGHT, "dark": _DARK}.get(code, {})
    for key in _DARK:
        options[f"theme.{key}"] = fixed.get(key)
    for section, palette in (("light", _LIGHT), ("dark", _DARK)):
        for key in palette:
            options[f"theme.{section}.{key}"] = palette[key] if code == "system" else None
    return options
