# SPDX-License-Identifier: EUPL-1.2
"""Golden references of the team settings (settings.py): the description of every setting
(texts in English and German, kind, limits, options) and what parsing a set of inputs gives,
with the display of the value after writing it into a new team."""

from __future__ import annotations

from datetime import date

from foresprint import i18n
from foresprint.model import Team
from foresprint.settings import SETTINGS, Kind, applicable, changes

INPUTS = [
    "", "  ", "x", "0", "1", "5", "5.5", "5,5", "-1", "1000", "90", "100", "12%", "12.5 %", "1_0",
    "1__0", "_1", "1_", "inf", "nan", "0x10", "1e2", "2026-01-05", "2026-13-40", "05.01.2026",
    "on", "off", "an", "aus", "ON", "yes", "DE", "de", "SA", "ZZ", "NW", "nw", "XX", "PT", "sp",
    "SP", "mon-fri", "auto", "flat", "linear", "classic", "klassisch", "plan", "roadmap",
    "yearly", "sequential", "2026.15", "15", "a/b", "a:b", "CON", " lead ", "Team Atlas",
]  # fmt: skip


def _display_value(setting, value):
    team = Team(key="t", name="T")
    setting.set(team, value)
    return setting.display(team)


def _parse(setting, raw):
    try:
        value = setting.parse(raw)
    except ValueError as e:
        return {"error": str(e)}
    result = {"display": _display_value(setting, value)}
    result["kind"] = "none" if value is None else type(value).__name__
    return result


def _describe(setting, code):
    i18n.set_language(code)
    try:
        options = setting.options
        return {
            "title": setting.title,
            "text": setting.text,
            "options": None if options is None else [[k, v] for k, v in options.items()],
        }
    finally:
        i18n.set_language("en")


def generate(ctx) -> None:
    default = Team(key="t", name="T")
    settings = []
    for s in SETTINGS:
        entry = {
            "key": s.key,
            "kind": s.kind.value,
            "optional": s.optional,
            "only_without_sprints": s.only_without_sprints,
            "retroactive": s.retroactive,
            "minimum": s.minimum,
            "maximum": s.maximum,
            "step": s.step,
            "default": s.display(default),
            "en": _describe(s, "en"),
            "de": _describe(s, "de"),
            "parse": {},
        }
        for lang in ("en", "de"):
            i18n.set_language(lang)
            try:
                entry["parse"][lang] = {raw: _parse(s, raw) for raw in INPUTS}
            finally:
                i18n.set_language("en")
        settings.append(entry)
    changed = Team(key="t", name="T")
    for s in SETTINGS:
        if s.kind is Kind.INT and s.minimum is not None:
            s.set(changed, int(s.minimum))
    changes_ = [(s.key, a, b) for s, a, b in changes(default, changed)]
    document = {
        "settings": settings,
        "applicable_without_sprints": [s.key for s in applicable(False)],
        "applicable_with_sprints": [s.key for s in applicable(True)],
        "changes": changes_,
        "today": date(2026, 1, 1).isoformat(),
    }
    ctx.write("settings/settings.json", ctx.dump_json(ctx.jsonable(document)))
