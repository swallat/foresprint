# SPDX-License-Identifier: EUPL-1.2
"""Ablage als YAML-Dateien – gedacht für ein Git-Repository.

<daten>/<team>/team.yaml          Team-Konfiguration
<daten>/<team>/people.yaml        Personenliste mit Zugehörigkeiten
<daten>/<team>/products.yaml      Produktliste (optional)
<daten>/<team>/sprints/<id>.yaml  ein Sprint pro Datei
<daten>/<team>/projects.yaml      Projekte der Ticket-Vorplanung (nur mit features.tickets)
<daten>/<team>/tickets.yaml       letzter Ticket-Import (nur mit features.tickets)
<daten>/<team>/preplan.yaml       Vormerkungen und eigene Schätzungen (nur mit features.tickets)
"""

from __future__ import annotations

import contextlib
import copy
import math
import os
import re
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from sprintforecast.git import invalidate_status
from sprintforecast.i18n import t
from sprintforecast.model import (
    DEFAULT_MATCH_ORDER,
    RULE_OPERATORS,
    AbsenceState,
    BudgetBasis,
    CapacitySettings,
    Earmark,
    EstimateSource,
    Features,
    ForecastSettings,
    ManualEstimate,
    Membership,
    Numbering,
    Person,
    Planning,
    PlanningUses,
    Preplan,
    Product,
    ProductBasis,
    ProductValues,
    Prognosis,
    Project,
    Rule,
    Sprint,
    SprintSettings,
    Team,
    Ticket,
    TrackerFields,
    TrackerSettings,
    TrendMode,
    Unit,
    absence_status,
    explicit_state_needed,
)

DATA_ENV = "SPRINTFORECAST_DATA"
# Datum, das als „heute“ gilt (für Rückblicke und Tests).
STICHTAG_ENV = "SPRINTFORECAST_AS_OF"


class DataError(Exception):
    """Eine Datei fehlt oder ist nicht lesbar."""


class FileAccessError(DataError):
    """Eine Datei lässt sich nicht lesen, schreiben oder löschen (fehlende Rechte, in einem
    anderen Programm geöffnet, Datenträger voll). Die Meldung ist für Anwender gedacht."""


class ConflictError(DataError):
    """Eine Datei enthält Konfliktmarkierungen eines unvollständigen Zusammenführens. Bevor
    die YAML geladen wird, wird dies erkannt: Die Bearbeitung des Teams ist gesperrt, bis der
    Konflikt gelöst ist (siehe Seite „Konflikte lösen“)."""

    def __init__(self, files: list[Path]) -> None:
        self.files = files
        super().__init__(
            t(
                "Merge conflict in: {files}. Editing is locked until the conflict is resolved.",
                files=", ".join(str(f) for f in files),
            )
        )


# Konfliktmarkierungen von Git am Zeilenanfang (alle drei müssen vorkommen).
_MARKERS = (
    # Mit „\r?“: Unter Windows schreibt Git die Markierungen mit CRLF in die Datei; `$` träfe
    # dann nicht (vor dem Zeilenende steht noch das „\r“).
    re.compile(r"^<{7}( |\r?$)", re.M),
    re.compile(r"^={7}\r?$", re.M),
    re.compile(r"^>{7}( |\r?$)", re.M),
)


def has_conflict_markers(text: str) -> bool:
    return all(m.search(text) for m in _MARKERS)


# Unterordner, in dem ein Daten-Repository die Teams üblicherweise ablegt (siehe Vorlage).
TEAMS_SUBDIR = "teams"


def _has_teams(path: Path) -> bool:
    return path.is_dir() and any((p / "team.yaml").is_file() for p in path.iterdir())


def teams_dir(path: Path) -> Path | None:
    """``path`` bzw. dessen Unterordner ``teams``, falls dort Teams liegen."""
    if _has_teams(path):
        return path
    if _has_teams(path / TEAMS_SUBDIR):
        return path / TEAMS_SUBDIR
    return None


def saved_data_dir() -> Path | None:
    """In der Weboberfläche (oder mit `sprintforecast data-dir`) gemerkter Datenordner."""
    from sprintforecast import config

    raw = config.load().get("data_dir")
    path = Path(raw) if isinstance(raw, str) and raw else None
    return path if path is not None and path.is_dir() else None


MAX_RECENT = 8


def recent_data_dirs() -> list[Path]:
    """Zuletzt benutzte Datenordner, der neueste zuerst (auch nicht mehr vorhandene – die
    Oberfläche kennzeichnet sie)."""
    from sprintforecast import config

    raw = config.load().get("recent_data_dirs")
    if not isinstance(raw, list):
        return []
    # Leere Einträge würden zu „.“ (dem aktuellen Ordner).
    return [Path(p) for p in raw if isinstance(p, str) and p.strip()]


def save_data_dir(path: Path) -> None:
    """Merkt den Datenordner als aktuellen und reiht ihn in die Liste der zuletzt benutzten ein."""
    from sprintforecast import config

    here = str(path.resolve())
    recent = [here, *(str(p) for p in recent_data_dirs() if str(p) != here)]
    config.update(data_dir=here, recent_data_dirs=recent[:MAX_RECENT])


def forget_data_dir(path: Path) -> None:
    """Entfernt einen Ordner aus der Liste der zuletzt benutzten (der Ordner bleibt bestehen)."""
    from sprintforecast import config

    config.update(
        recent_data_dirs=[str(p) for p in recent_data_dirs() if p != path and p != path.resolve()]
    )


def default_data_dir() -> Path:
    """--data > Umgebungsvariable SPRINTFORECAST_DATA > aktuelles Verzeichnis, falls es
    Teams enthält > gemerkter Datenordner > aktuelles Verzeichnis.

    Enthält ein Verzeichnis selbst keine Teams, aber einen Unterordner ``teams`` mit Teams
    (Aufbau eines Daten-Repositorys), wird dieser verwendet.
    """
    if configured := os.environ.get(DATA_ENV):
        return Path(configured)
    here = Path(".")
    if found := teams_dir(here):
        return found
    if saved := saved_data_dir():
        return teams_dir(saved) or saved
    return here


# C-Implementierung von libyaml, falls PyYAML damit gebaut wurde (deutlich schneller);
# sonst der reine Python-Lader mit identischem Ergebnis.
def _pick_loader() -> type:
    return getattr(yaml, "CSafeLoader", yaml.SafeLoader)


_YAML_LOADER = _pick_loader()


def compose_yaml(text: str) -> yaml.Node | None:
    """Knotenbaum einer YAML-Datei (mit Zeilennummern), gelesen mit demselben Lader wie beim
    Laden der Daten; ``None`` bei leerer Datei. Nur für die Prüfung: Der Standardlader meldet
    doppelte Schlüssel nicht und verliert den Unterschied zwischen leer und fehlend."""
    return yaml.compose(text, Loader=_YAML_LOADER)


def _read(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
        if has_conflict_markers(text):
            raise ConflictError([path])
        content = yaml.load(text, Loader=_YAML_LOADER)
    except FileNotFoundError as e:
        raise DataError(t("File missing: {path}", path=path)) from e
    except OSError as e:  # keine Leserechte, Ordner statt Datei, Netzlaufwerk nicht erreichbar
        raise _not_readable(path, e) from e
    except (yaml.YAMLError, ValueError) as e:  # z. B. ein unmögliches Datum (2026-13-45)
        raise DataError(t("{path}: invalid YAML ({error})", path=path, error=e)) from e
    if content is None:
        return {}
    if not isinstance(content, dict):
        raise DataError(t("{path}: content must be a YAML mapping", path=path))
    return content


def dump_yaml(content: Any) -> str:
    """Einheitliches Format aller Dateien (Zusammenführen und Speichern schreiben gleich)."""
    return yaml.safe_dump(content, allow_unicode=True, sort_keys=False, width=100)


def _reason(error: OSError) -> str:
    return error.strerror or str(error)


def _not_readable(path: Path, error: OSError) -> FileAccessError:
    return FileAccessError(
        t(
            (
                "{path}: cannot be read ({reason}). Check the permissions or close the file in "
                "any other program."
            ),
            path=path,
            reason=_reason(error),
        )
    )


not_readable = _not_readable


def _not_saved(path: Path, error: OSError) -> FileAccessError:
    return FileAccessError(
        t(
            (
                "{path}: not saved ({reason}). The file was not changed. Is the folder "
                "writable, and is the file open in another program?"
            ),
            path=path,
            reason=_reason(error),
        )
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise _not_readable(path, e) from e


def _write(path: Path, header: str, content: dict[str, Any]) -> None:
    """Schreibt stabil: immer Zeilenende LF, nur bei geändertem Inhalt (keine unnötigen
    Änderungen für Git) und über eine Zwischendatei (kein halb geschriebener Stand).
    Schreibfehler (``OSError``) kommen als :class:`FileAccessError` mit verständlicher Meldung."""
    try:
        _write_atomic(path, header, content)
    except OSError as e:
        raise _not_saved(path, e) from e


def write_text(path: Path, text: str, newline: str | None = None) -> None:
    """Schreibt eine Textdatei (z. B. den Bericht) über eine Zwischendatei; Fehler wie bei
    :func:`_write`. Zeilenenden wie bei ``Path.write_text`` (unter Windows CRLF), mit
    ``newline="\\n"`` immer LF."""
    try:
        _replace_with(path, text, newline=newline)
    except OSError as e:
        raise _not_saved(path, e) from e


def _replace_with(path: Path, text: str, newline: str | None) -> None:
    """Schreibt ``text`` in eine Zwischendatei neben ``path`` und ersetzt ``path`` damit: Die
    Datei ist danach entweder ganz neu oder unverändert, nie halb geschrieben."""
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline=newline, dir=path.parent, suffix=".tmp", delete=False
        ) as tmp:
            tmp_name = tmp.name
            tmp.write(text)
        os.replace(tmp_name, path)
        tmp_name = None
    finally:
        if tmp_name:  # Schreib- oder Umbenennungsfehler (z. B. gesperrt): nichts zurücklassen
            Path(tmp_name).unlink(missing_ok=True)


def _write_atomic(path: Path, header: str, content: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = header + dump_yaml(content)
    try:
        current = path.read_bytes()
    except OSError:
        current = None
    if current is not None:
        if current == text.encode("utf-8"):
            return
        if has_conflict_markers(current.decode("utf-8", errors="replace")):
            # Nie über einen unvollständigen Merge schreiben: Die Markierungen gingen verloren.
            raise ConflictError([path])
    _replace_with(path, text, newline="\n")
    clear_team_cache()


def _float(value: Any, where: str) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise DataError(
            t("{where}: number expected, found {value}", where=where, value=repr(value))
        )
    try:
        number = float(value)
    except OverflowError:  # ganze Zahl jenseits des Bereichs von float
        number = math.inf
    if not math.isfinite(number):
        raise DataError(
            t("{where}: finite number expected, found {value}", where=where, value=repr(value))
        )
    return number


def _lenient_float(value: Any, where: str) -> float | None:
    """Wie ``float(value)`` (auch Zahlen in Anführungszeichen), aber mit Dateistelle im Fehler."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as e:  # OverflowError: ganze Zahl > 1e308
        raise DataError(
            t("{where}: number expected, found {value}", where=where, value=repr(value)[:60])
        ) from e
    if not math.isfinite(number):  # auch Text wie "nan" oder "inf"
        raise DataError(
            t(
                "{where}: finite number expected, found {value}",
                where=where,
                value=repr(value)[:60],
            )
        )
    return number


def _mapping(value: Any, where: str, name: str) -> dict[str, Any]:
    """Ein Objekt (``Schlüssel: Wert``); fehlt es oder ist es leer, ein leeres Objekt."""
    if not value:
        return {}
    if not isinstance(value, dict):
        raise DataError(
            t(
                (
                    "{where}: '{name}' must be a mapping (lines of the form 'key: value'), "
                    "found {value}"
                ),
                where=where,
                name=name,
                value=repr(value)[:60],
            )
        )
    return value


def _sequence(value: Any, where: str, name: str) -> list[Any]:
    """Eine Liste (Einträge mit ``- ``); fehlt sie oder ist sie leer, eine leere Liste."""
    if not value:
        return []
    if not isinstance(value, list):
        raise DataError(
            t(
                "{where}: '{name}' must be a list (entries starting with '- '), found {value}",
                where=where,
                name=name,
                value=repr(value)[:60],
            )
        )
    return value


def _code(value: Any, where: str, name: str) -> str | None:
    """Land oder Region als Text (``DE``, ``NW``); fehlt der Eintrag, ``None``. Unquotiert liest
    YAML ``NO`` (Norwegen) und ``ON`` (Ontario) als Wahrheitswert: Das wird erklärt statt still
    zu einem falschen Wert."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise DataError(
            t(
                (
                    "{where}: please put '{name}' in quotes, e.g. {name}: \"NO\" (unquoted, "
                    "YAML reads it as a boolean)"
                ),
                where=where,
                name=name,
            )
        )
    if not isinstance(value, str):
        raise DataError(
            t(
                "{where}: '{name}' must be text (e.g. DE or NW), found {value}",
                where=where,
                name=name,
                value=repr(value)[:60],
            )
        )
    return value


@contextlib.contextmanager
def _well_formed(where: str) -> Iterator[None]:
    """Fängt Aufbaufehler, die die Einzelprüfungen nicht kennen (z. B. ein Text, wo ein Objekt
    steht), und meldet sie mit dem Dateinamen statt als Absturz."""
    try:
        yield
    except DataError:
        raise
    except (AttributeError, TypeError, KeyError, ValueError, OverflowError) as e:
        raise DataError(
            t(
                (
                    "{where}: invalid file structure ({error}). Lists start with '- ', "
                    "mappings consist of lines 'key: value'."
                ),
                where=where,
                error=f"{type(e).__name__}: {e}",
            )
        ) from e


def _date(value: Any, where: str) -> date:
    if isinstance(value, datetime):  # „2026-10-14 08:00:00“ liest YAML als Zeitstempel
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as e:
        raise DataError(
            t(
                "{where}: date in format YYYY-MM-DD expected, found {value}",
                where=where,
                value=repr(value),
            )
        ) from e


def _clean(value: float | None) -> float | int | None:
    if value is None:
        return None
    return int(value) if float(value).is_integer() else round(value, 6)


def _int(value: Any, where: str, name: str, default: int = 0) -> int:
    """A whole number; missing or empty = ``default``. Booleans and fractions are rejected."""
    if value is None or value == "":
        return default
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or not float(value).is_integer()
    ):
        raise DataError(
            t(
                "{where}: '{name}' must be a whole number, found {value}",
                where=where,
                name=name,
                value=repr(value)[:60],
            )
        )
    return int(value)


def _text(value: Any) -> str | None:
    """A free text; missing or empty = ``None``."""
    if value is None or value == "":
        return None
    return str(value)


def _texts(value: Any, where: str, name: str) -> list[str]:
    """A list of texts (labels, keys); a single scalar counts as a list of one."""
    if value is None or value == "":
        return []
    if isinstance(value, dict):
        _sequence(value, where, name)  # raises: an object is not a list
    if not isinstance(value, list):
        value = [value]
    return [str(v) for v in value]


# --- Team -----------------------------------------------------------------------------

TEAM_HEADER = """\
# Team settings. Explanations: `sprintforecast help team`
"""


def _finite(value: Any) -> float:
    """``float(value)`` für Einstellungen in team.yaml; nan und inf sind keine gültigen Werte."""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(t("not a finite number: {value}", value=value))
    return number


def file_name_problem(name: str, portable: bool = True) -> str | None:
    """Warum ``name`` kein sicherer Dateiname (ohne Endung) ist; ``None`` = in Ordnung. Gilt für
    Sprint-IDs, die zu Dateinamen werden: kein Pfadtrenner, kein Laufwerk oder Datenstrom
    (Doppelpunkt), keine Steuerzeichen, keine Windows-Gerätenamen, kein Punkt oder Leerzeichen am
    Rand (``..``).

    Mit ``portable`` (Voreinstellung, für Eingaben von außen wie den Excel-Import) gilt die
    strengste Regel, damit der Name auf jedem System ein Dateiname ist. Ohne ``portable`` gilt nur,
    was auf DIESEM System ein Pfad wäre (unter Linux und macOS: ``/``; ein Rückwärtsschrägstrich
    oder Doppelpunkt ist dort ein gewöhnliches Zeichen); das schützt das Schreiben, ohne
    vorhandene Daten auszuschließen."""
    strict = portable or sys.platform == "win32"
    if not name or len(name) > 80:
        return t("empty or longer than 80 characters")
    forbidden = '<>:"/\\|?*' if strict else "/"
    if any(ord(c) < 32 or c in forbidden for c in name):
        return t("path separator, colon, special or control character")
    if name != name.strip() or name.startswith(".") or name.endswith("."):
        return t("starts or ends with a dot or a space")
    if strict and name.partition(".")[0].strip().lower() in _WINDOWS_DEVICES:
        return t("reserved for devices on Windows")
    return None


def _first_id(value: Any, where: str) -> str | None:
    """ID des ersten Sprints; wie bei den Sprintdateien muss eine Zahl wie 2026.20 in
    Anführungszeichen stehen (sonst wird daraus 2026.2)."""
    if value is None:
        return None
    if isinstance(value, float):
        raise DataError(t('{where}: please quote the id, e.g. id: "2026.20"', where=where))
    text = str(value)
    if problem := file_name_problem(text, portable=False):
        raise DataError(
            t(
                "{where}: id {id} is not allowed ({problem})",
                where=where,
                id=repr(text),
                problem=problem,
            )
        )
    return text


def team_from_dict(key: str, d: dict[str, Any], where: str) -> Team:
    sprint = _mapping(d.get("sprint"), where, "sprint")
    forecast = _mapping(d.get("forecast"), where, "forecast")
    capacity = _mapping(d.get("capacity"), where, "capacity")
    first = _mapping(sprint.get("first"), where, "sprint.first")
    raw_features = _mapping(d.get("features"), where, "features")
    features = (
        Features(
            products=bool(raw_features.get("products", False)),
            po=bool(raw_features.get("po", False)),
            production=bool(raw_features.get("production", False)),
            tickets=bool(raw_features.get("tickets", False)),
        )
        if "features" in d
        else Features(explicit=False)  # ältere Datei: Repository.load leitet die Werte ab
    )
    tracker = TrackerSettings()
    tracker_raw: Any = None
    if features.tickets:
        tracker = _tracker_from(_mapping(d.get("tracker"), where, "tracker"), where)
    elif d.get("tracker"):
        # Feature off: the section must not break the rest of the app. A valid one is still
        # read (switching the feature on again keeps it); an invalid one is kept as it is.
        try:
            tracker = _tracker_from(_mapping(d.get("tracker"), where, "tracker"), where)
        except DataError, ValueError, TypeError:
            tracker_raw = d["tracker"]
    try:
        return Team(
            key=key,
            name=str(d.get("name") or key),
            unit=Unit(d.get("unit", "PT")),
            sprint=SprintSettings(
                length_days=int(sprint.get("length_days", 14)),
                numbering=Numbering(sprint.get("numbering", "yearly")),
                first_id=_first_id(first.get("id"), where),
                first_start=_date(first["start"], where) if first.get("start") else None,
            ),
            forecast=ForecastSettings(
                reference_capacity=_finite(forecast.get("reference_capacity", 67)),
                window=int(forecast.get("window", 5)),
                roadmap_share=_finite(forecast.get("roadmap_share", 0.8)),
                rounding=int(forecast.get("rounding", 1)),
                trend_mode=TrendMode(forecast.get("trend_mode", "flat")),
                horizon=int(forecast.get("horizon", 3)),
                product_basis=ProductBasis(forecast.get("product_basis", "plan")),
            ),
            features=features,
            tracker=tracker,
            tracker_raw=tracker_raw,
            capacity=CapacitySettings(
                overhead_share=_finite(capacity.get("overhead_share", 0.0)),
                overhead_days=_finite(capacity.get("overhead_days", 0.0)),
                country=(_code(capacity.get("country"), where, "capacity.country") or "DE").upper(),
                region=_code(capacity.get("region"), where, "capacity.region"),
                workweek=str(capacity.get("workweek", "auto")),
                rounding=int(capacity.get("rounding", 1)),
                absence_history=int(capacity.get("absence_history", 4)),
            ),
        )
    except (ValueError, TypeError, OverflowError) as e:  # OverflowError: int(inf)
        raise DataError(f"{where}: {e}") from e


def team_to_dict(team: Team) -> dict[str, Any]:
    sprint: dict[str, Any] = {
        "length_days": team.sprint.length_days,
        "numbering": team.sprint.numbering.value,
    }
    if team.sprint.first_id is not None and team.sprint.first_start is not None:
        sprint["first"] = {"id": team.sprint.first_id, "start": team.sprint.first_start}
    forecast: dict[str, Any] = {
        "reference_capacity": _clean(team.forecast.reference_capacity),
        "window": team.forecast.window,
        "roadmap_share": team.forecast.roadmap_share,
        "rounding": team.forecast.rounding,
        "trend_mode": team.forecast.trend_mode.value,
        "horizon": team.forecast.horizon,
    }
    if team.forecast.product_basis is not ProductBasis.PLAN:
        forecast["product_basis"] = team.forecast.product_basis.value
    capacity: dict[str, Any] = {"overhead_share": team.capacity.overhead_share}
    if team.capacity.overhead_days:
        capacity["overhead_days"] = _clean(team.capacity.overhead_days)
    if team.capacity.country != "DE":
        capacity["country"] = team.capacity.country
    capacity |= {"region": team.capacity.region, "rounding": team.capacity.rounding}
    if team.capacity.workweek != "auto":
        capacity["workweek"] = team.capacity.workweek
    if team.capacity.absence_history != CapacitySettings().absence_history:  # auch 0 = aus
        capacity["absence_history"] = team.capacity.absence_history
    features: dict[str, Any] = {
        "products": team.features.products,
        "po": team.features.po,
        "production": team.features.production,
    }
    if team.features.tickets:  # only when on: files of teams without it stay unchanged
        features["tickets"] = True
    out: dict[str, Any] = {
        "name": team.name,
        "unit": team.unit.value,
        "features": features,
        "sprint": sprint,
        "forecast": forecast,
        "capacity": capacity,
    }
    # The tracker section is kept while the feature is on and whenever it holds settings, so
    # switching the feature off and on again does not lose the configuration.
    if team.tracker_raw is not None:  # unreadable while the feature was off: written as it was
        out["tracker"] = team.tracker_raw
    elif team.features.tickets or team.tracker != TrackerSettings():
        out["tracker"] = _tracker_to(team.tracker)
    return out


# --- Tracker (ticket pre-planning, section ``tracker`` in team.yaml) ----------------------

# Parts of a key name that mark a secret; such a key in the tracker section is an error ...
SECRET_WORDS = ("token", "password", "passwort", "secret", "credential")
# ... and so are these names when they are the whole key (a part of a longer name is no hint).
SECRET_NAMES = ("key", "api_key", "apikey", "pat", "auth", "authorization", "bearer")
# Sections whose keys are free text of the user (sprint names), not setting names.
_FREE_KEYS = ("sprint_names",)


def secret_key(section: Any) -> str | None:
    """The first key anywhere in the (nested) tracker section whose name marks a secret, else
    None. Only names are looked at, values are never read."""
    if isinstance(section, list):
        return next((k for item in section if (k := secret_key(item))), None)
    if not isinstance(section, dict):
        return None
    for name, value in section.items():
        plain = str(name).strip().casefold().replace("-", "_")
        if plain in SECRET_NAMES or any(word in plain for word in SECRET_WORDS):
            return str(name)
        if plain not in _FREE_KEYS and (found := secret_key(value)):
            return found
    return None


def _text_value(value: Any, where: str, name: str) -> str:
    """A value compared as text. An unquoted ``2026.20`` is read by YAML as the number 2026.2
    and would silently match the wrong sprint: floats must be quoted."""
    if isinstance(value, float):
        raise DataError(
            t(
                (
                    "{where}: {name}: please put {value} in quotes (otherwise digits are lost, "
                    'e.g. "2026.20")'
                ),
                where=where,
                name=name,
                value=value,
            )
        )
    return str(value)


def _rule_value(value: Any, where: str, name: str) -> str:
    """Leaf values are compared as text; YAML booleans (``in_sprint: [true]``) become
    ``true``/``false``."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return _text_value(value, where, name)


def _rule_node(mapping: dict[str, Any], where: str) -> Rule:
    entries: list[Rule] = []
    for raw_key, value in mapping.items():
        name = str(raw_key)
        if name in RULE_OPERATORS:
            items = _sequence(value, where, name)
            children = [
                _rule_node(_mapping(item, where, f"{name}[{i}]"), where)
                for i, item in enumerate(items)
            ]
            entries.append(Rule(op=name, children=children))
            continue
        if isinstance(value, dict):
            raise DataError(
                t(
                    (
                        "{where}: '{name}' must be a list of values (entries with '- '), found "
                        "{value}"
                    ),
                    where=where,
                    name=name,
                    value=repr(value)[:60],
                )
            )
        if value is None or value == "":
            values: list[str] = []
        elif isinstance(value, list):
            values = [_rule_value(v, where, name) for v in value]
        else:
            values = [_rule_value(value, where, name)]
        entries.append(Rule(source=name, values=values))
    if len(entries) == 1:
        return entries[0]  # a single leaf, or the long form: exactly one of any/all/none
    # Short form (several sources directly in the mapping, OR-combined). Mixed forms and
    # several operators in one mapping land here too; the validation reports them.
    return Rule(op="any", children=entries, short=True)


def _rule_from(raw: Any, where: str) -> Rule | None:
    """Reads an assignment rule (spec section 6.4); missing or empty = ``None``. Unknown
    sources are kept as leaves so that the validation can name them."""
    mapping = _mapping(raw, where, "match")
    if not mapping:
        return None
    return _rule_node(mapping, where)


def _rule_values_to(leaf: Rule) -> list[Any]:
    if leaf.source == "in_sprint":  # written back as YAML booleans
        return [{"true": True, "false": False}.get(v, v) for v in leaf.values]
    return list(leaf.values)


def _rule_to(rule: Rule) -> dict[str, Any]:
    if rule.short:
        out: dict[str, Any] = {}
        for child in rule.children:
            if child.op == "leaf":
                out[child.source or ""] = _rule_values_to(child)
            else:
                out[child.op] = [_rule_to(c) for c in child.children]
        return out
    if rule.op == "leaf":
        return {rule.source or "": _rule_values_to(rule)}
    return {rule.op: [_rule_to(c) for c in rule.children]}


def _choice(value: Any, kind: type[Any], default: str, where: str, name: str) -> Any:
    """A value of a StrEnum; missing = ``default``."""
    try:
        return kind(value if value not in (None, "") else default)
    except ValueError as e:
        raise DataError(
            t(
                "{where}: {name} '{value}' unknown (allowed: {allowed})",
                where=where,
                name=name,
                value=value,
                allowed=", ".join(k.value for k in kind),
            )
        ) from e


def _tracker_from(d: dict[str, Any], where: str) -> TrackerSettings:
    at = f"{where}: tracker"
    # The value is never read, let alone shown: it would end up in the data repository.
    if (name := secret_key(d)) is not None:
        raise DataError(
            t(
                (
                    "{where}: '{name}' does not belong in the file – tokens and passwords "
                    "belong in the environment variable SPRINTFORECAST_JIRA_TOKEN or in the "
                    "keychain"
                ),
                where=at,
                name=name,
            )
        )
    fields = _mapping(d.get("fields"), at, "fields")
    order = _texts(d.get("project_match_order"), at, "project_match_order")
    rough = _float(d.get("rough_factor"), f"{at}: rough_factor")
    return TrackerSettings(
        kind=str(d.get("kind") or "csv"),
        base_url=_text(d.get("base_url")),
        query=_text(d.get("query")),
        fields=TrackerFields(
            estimate=_text(fields.get("estimate")),
            remaining=_text(fields.get("remaining")),
            epic=_text(fields.get("epic")),
        ),
        planning_uses=_choice(
            d.get("planning_uses"), PlanningUses, "remaining", at, "planning_uses"
        ),
        refined_label=_text(d.get("refined_label")),
        refined_also_if=_rule_from(d.get("refined_also_if"), f"{at}.refined_also_if"),
        project_match_order=order or list(DEFAULT_MATCH_ORDER),
        dependency_gap=_int(d.get("dependency_gap"), at, "dependency_gap", 1),
        budget_basis=_choice(
            d.get("budget_basis"), BudgetBasis, "roadmap_share", at, "budget_basis"
        ),
        rough_factor=1.5 if rough is None else rough,
        write_labels=bool(d.get("write_labels", False)),
        sprint_names={
            _text_value(k, at, "sprint_names"): _text_value(v, at, "sprint_names")
            for k, v in _mapping(d.get("sprint_names"), at, "sprint_names").items()
        },
        # Absent = default; an explicitly empty value stays empty so that the check reports it.
        link_type=(_text(d.get("link_type")) or "") if "link_type" in d else "Blocks",
    )


def tracker_from_raw(raw: Any, where: str) -> TrackerSettings:
    """Reads a raw ``tracker`` section (as kept in ``Team.tracker_raw``); raises ``DataError``
    (or ValueError/TypeError) for an unusable one."""
    return _tracker_from(_mapping(raw, where, "tracker"), where)


def _tracker_to(tr: TrackerSettings) -> dict[str, Any]:
    out: dict[str, Any] = {"kind": tr.kind}
    if tr.base_url:
        out["base_url"] = tr.base_url
    if tr.query:
        out["query"] = tr.query
    fields = {
        name: value
        for name, value in (
            ("estimate", tr.fields.estimate),
            ("remaining", tr.fields.remaining),
            ("epic", tr.fields.epic),
        )
        if value
    }
    if fields:
        out["fields"] = fields
    out["planning_uses"] = tr.planning_uses.value
    if tr.refined_label:
        out["refined_label"] = tr.refined_label
    if tr.refined_also_if is not None:
        out["refined_also_if"] = _rule_to(tr.refined_also_if)
    out["project_match_order"] = list(tr.project_match_order)
    out["dependency_gap"] = tr.dependency_gap
    out["budget_basis"] = tr.budget_basis.value
    out["rough_factor"] = _clean(tr.rough_factor)
    out["write_labels"] = tr.write_labels
    if tr.sprint_names:
        out["sprint_names"] = dict(tr.sprint_names)
    if tr.link_type != TrackerSettings().link_type:
        out["link_type"] = tr.link_type
    return out


# --- Personen -------------------------------------------------------------------------

PEOPLE_HEADER = """\
# People. Memberships with period and FTE share (1.0 = full time in the team).
# Never delete people; end the membership with `to:` instead – otherwise history changes.
"""


def people_from_dict(d: dict[str, Any], where: str) -> list[Person]:
    people = []
    for i, p in enumerate(_sequence(d.get("people"), where, "people")):
        at = f"{where}: people[{i}]"
        if not isinstance(p, dict) or "id" not in p:
            raise DataError(t("{where}: field 'id' missing", where=at))
        memberships = [
            Membership(
                start=_date(m.get("from"), at),
                end=_date(m["to"], at) if m.get("to") else None,
                fte=_float(m.get("fte", 1.0), at) or 0.0,
            )
            for m in (
                _mapping(m, at, f"memberships[{j}]")
                for j, m in enumerate(_sequence(p.get("memberships"), at, "memberships"))
            )
        ]
        people.append(
            Person(
                id=str(p["id"]),
                name=str(p.get("name") or p["id"]),
                region=_code(p.get("region"), at, "region"),
                country=(
                    code.upper() if (code := _code(p.get("country"), at, "country")) else None
                ),
                workweek=str(p["workweek"]) if p.get("workweek") else None,
                memberships=memberships,
                production_access=bool(p.get("production_access", False)),
            )
        )
    return people


def people_to_dict(people: list[Person]) -> dict[str, Any]:
    out = []
    for p in people:
        entry: dict[str, Any] = {"id": p.id, "name": p.name}
        if p.country:
            entry["country"] = p.country
        if p.workweek:
            entry["workweek"] = p.workweek
        if p.region:
            entry["region"] = p.region
        if p.production_access:
            entry["production_access"] = True
        entry["memberships"] = [
            {"from": m.start, "to": m.end, "fte": _clean(m.fte)} for m in p.memberships
        ]
        out.append(entry)
    return {"people": out}


# --- Produkte ------------------------------------------------------------------------

PRODUCTS_HEADER = """\
# Products of the team. Period (from/to) = when the team works on the product; po optional.
# Never delete products; end them with `to:` instead – otherwise past evaluations change.
"""


def products_from_dict(d: dict[str, Any], where: str) -> list[Product]:
    products = []
    for i, p in enumerate(_sequence(d.get("products"), where, "products")):
        at = f"{where}: products[{i}]"
        if not isinstance(p, dict) or "id" not in p:
            raise DataError(t("{where}: field 'id' missing", where=at))
        products.append(
            Product(
                id=str(p["id"]),
                name=str(p.get("name") or p["id"]),
                po=str(p["po"]) if p.get("po") else None,
                start=_date(p["from"], at) if p.get("from") else None,
                end=_date(p["to"], at) if p.get("to") else None,
                share=_lenient_float(p.get("share"), f"{at}: share"),
            )
        )
    return products


def products_to_dict(products: list[Product]) -> dict[str, Any]:
    out = []
    for p in products:
        entry: dict[str, Any] = {"id": p.id, "name": p.name}
        if p.po:
            entry["po"] = p.po
        if p.share is not None:
            entry["share"] = _clean(p.share)
        entry["from"] = p.start
        entry["to"] = p.end
        out.append(entry)
    return {"products": out}


# --- Sprints --------------------------------------------------------------------------

SPRINT_HEADER = """\
# Sprint {id}. Explanations of all fields: `sprintforecast help fields`
"""


def _prognoses_from(raw: Any, where: str) -> list[Prognosis]:
    result = []
    for i, p in enumerate(_sequence(raw, where, "prognoses")):
        at_ = f"{where}: prognoses[{i}]"
        if not isinstance(p, dict) or p.get("at") is None:
            raise DataError(t("{where}: field 'at' missing", where=at_))
        stamp = p["at"]
        try:
            when = stamp if isinstance(stamp, datetime) else datetime.fromisoformat(str(stamp))
        except ValueError as e:
            raise DataError(t("{where}: invalid time '{value}'", where=at_, value=stamp)) from e
        result.append(
            Prognosis(
                at=when,
                comment=str(p["comment"]) if p.get("comment") else None,
                forecast_ist=_float(p.get("forecast_ist"), at_),
                not_done=_float(p.get("not_done"), at_),
                additional_done=_float(p.get("additional_done"), at_),
                expected_done=_float(p.get("expected_done"), at_),
                target=str(p["target"]) if p.get("target") is not None else None,
                plan=_float(p.get("plan"), at_),
                preplanned={
                    str(k): _float(v, at_) or 0.0
                    for k, v in _mapping(p.get("preplanned"), at_, "preplanned").items()
                },
            )
        )
    return result


def _prognoses_to(prognoses: list[Prognosis]) -> list[dict[str, Any]]:
    out = []
    for p in prognoses:
        entry: dict[str, Any] = {"at": p.at.replace(microsecond=0)}
        if p.comment:
            entry["comment"] = p.comment
        for key in ("forecast_ist", "not_done", "additional_done", "expected_done"):
            if (value := getattr(p, key)) is not None:
                entry[key] = _clean(value)
        if p.target is not None:
            entry["target"] = p.target
        if p.plan is not None:
            entry["plan"] = _clean(p.plan)
        if p.preplanned:
            entry["preplanned"] = {k: _clean(v) for k, v in p.preplanned.items()}
        out.append(entry)
    return out


def _absence_state(d: dict[str, Any], where: str) -> AbsenceState | None:
    """Gespeicherter Stand der Fehltage; ältere Dateien kennen nur ``absences_confirmed``."""
    raw = d.get("absence_state")
    if raw is not None:
        try:
            return AbsenceState(raw)
        except ValueError as e:
            allowed = ", ".join(s.value for s in AbsenceState)
            raise DataError(
                t(
                    "{where}: absence_state '{value}' unknown (allowed: {allowed})",
                    where=where,
                    value=raw,
                    allowed=allowed,
                )
            ) from e
    return AbsenceState.CONFIRMED if d.get("absences_confirmed") else None


def sprint_from_dict(d: dict[str, Any], where: str) -> Sprint:
    for key in ("id", "start", "end"):
        if d.get(key) is None:
            raise DataError(t("{where}: field '{key}' missing", where=where, key=key))
    if isinstance(d["id"], float):
        raise DataError(t('{where}: please quote the id, e.g. id: "2026.20"', where=where))
    planning = None
    if p := _mapping(d.get("planning"), where, "planning"):
        planning = Planning(
            carryover=_float(p.get("carryover"), where) or 0.0,
            backlog=_float(p.get("backlog"), where) or 0.0,
            corrections=[
                _float(c, where) or 0.0
                for c in _sequence(p.get("corrections"), where, "corrections")
            ],
        )
    products = {}
    for pid, values in _mapping(d.get("products"), where, "products").items():
        at = f"{where}: products.{pid}"
        if not isinstance(values, dict):
            raise DataError(t("{where}: mapping with preplanned/planned/done expected", where=at))
        products[str(pid)] = ProductValues(
            preplanned=_float(values.get("preplanned"), at),
            planned=_float(values.get("planned"), at),
            done=_float(values.get("done"), at),
            production_planned=_float(values.get("production_planned"), at),
            production_done=_float(values.get("production_done"), at),
        )
    absences = {}
    for pid, days in _mapping(d.get("absences"), where, "absences").items():
        absences[str(pid)] = _float(days, f"{where}: absences.{pid}") or 0.0
    return Sprint(
        id=str(d["id"]),
        start=_date(d["start"], where),
        end=_date(d["end"], where),
        absences=absences,
        capacity=_float(d.get("capacity"), f"{where}: capacity"),
        forecast_ist=_float(d.get("forecast_ist"), f"{where}: forecast_ist"),
        velocity=_float(d.get("velocity"), f"{where}: velocity"),
        scope_creep=_float(d.get("scope_creep"), f"{where}: scope_creep"),
        planning=planning,
        forecast_plan=_float(d.get("forecast_plan"), f"{where}: forecast_plan"),
        products=products,
        note=d.get("note"),
        production_planned=_float(d.get("production_planned"), f"{where}: production_planned"),
        production_done=_float(d.get("production_done"), f"{where}: production_done"),
        absence_state=_absence_state(d, where),
        expected_absences={
            str(pid): _float(days, f"{where}: expected_absences.{pid}") or 0.0
            for pid, days in _mapping(
                d.get("expected_absences"), where, "expected_absences"
            ).items()
        },
        not_done=_float(d.get("not_done"), f"{where}: not_done"),
        additional_done=_float(d.get("additional_done"), f"{where}: additional_done"),
        prognoses=_prognoses_from(d.get("prognoses"), where),
    )


def sprint_to_dict(s: Sprint) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": s.id,
        "start": s.start,
        "end": s.end,
        "absences": {k: _clean(v) for k, v in sorted(s.absences.items())},
        **({"absence_state": s.absence_state.value} if explicit_state_needed(s) else {}),
        # Ältere Programmversionen kennen nur dieses Feld.
        **(
            {"absences_confirmed": True}
            if explicit_state_needed(s) and s.absence_state is AbsenceState.CONFIRMED
            else {}
        ),
        "capacity": _clean(s.capacity),
        "forecast_ist": _clean(s.forecast_ist),
        "velocity": _clean(s.velocity),
        "scope_creep": _clean(s.scope_creep),
    }
    if s.planning is not None:
        d["planning"] = {
            "carryover": _clean(s.planning.carryover),
            "backlog": _clean(s.planning.backlog),
            "corrections": [_clean(c) for c in s.planning.corrections],
        }
    if s.forecast_plan is not None:
        d["forecast_plan"] = _clean(s.forecast_plan)
    products = {
        pid: {
            k: _clean(v)
            for k, v in (
                ("preplanned", pv.preplanned),
                ("planned", pv.planned),
                ("done", pv.done),
                ("production_planned", pv.production_planned),
                ("production_done", pv.production_done),
            )
            if v is not None
        }
        for pid, pv in sorted(s.products.items())
        if not pv.is_empty()
    }
    if products:
        d["products"] = products
    if s.expected_absences:
        d["expected_absences"] = {k: _clean(v) for k, v in sorted(s.expected_absences.items())}
    if s.production_planned is not None:
        d["production_planned"] = _clean(s.production_planned)
    if s.production_done is not None:
        d["production_done"] = _clean(s.production_done)
    if s.not_done is not None:
        d["not_done"] = _clean(s.not_done)
    if s.additional_done is not None:
        d["additional_done"] = _clean(s.additional_done)
    if s.prognoses:
        d["prognoses"] = _prognoses_to(s.prognoses)
    if s.note:
        d["note"] = s.note
    return d


# --- Ticket pre-planning: projects.yaml, tickets.yaml, preplan.yaml ----------------------

# Schema version of the three files. Missing = 1; a greater version was written by a newer
# program version and is refused instead of being read half.
SCHEMA = 1

PROJECTS_HEADER = """\
# Projects of the ticket pre-planning: target date, product, priority and assignment rule.
# A ticket belongs to the project whose `match` rule it fulfils (docs/design/ticket-planning.md).
"""

TICKETS_HEADER = """\
# Tickets as last imported from the tracker. Written by the import – do not edit by hand.
"""

PREPLAN_HEADER = """\
# Pre-planning of the PO: earmarks (ticket → future sprint) and own estimates for tickets.
"""


def _schema(d: dict[str, Any], where: str) -> int:
    raw = d.get("schema")
    if raw is None or raw == "":
        return SCHEMA
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise DataError(
            t(
                "{where}: schema must be a whole number, found {value}",
                where=where,
                value=repr(raw)[:60],
            )
        )
    if raw > SCHEMA:
        raise DataError(
            t(
                (
                    "{where}: The file was written by a newer program version (schema {found}, "
                    "this version knows up to {known}). Please update sprintforecast."
                ),
                where=where,
                found=raw,
                known=SCHEMA,
            )
        )
    return raw


def _sprint_ref(value: Any, where: str, name: str) -> str | None:
    """A sprint id as text; like sprint files, ``2026.20`` must be quoted (else 2026.2)."""
    if value is None or value == "":
        return None
    if isinstance(value, float):
        raise DataError(
            t(
                '{where}: please put {name} in quotation marks, e.g. {name}: "2026.20"',
                where=where,
                name=name,
            )
        )
    return str(value)


def projects_from_dict(d: dict[str, Any], where: str) -> list[Project]:
    _schema(d, where)
    projects = []
    for i, p in enumerate(_sequence(d.get("projects"), where, "projects")):
        at = f"{where}: projects[{i}]"
        if not isinstance(p, dict) or "id" not in p:
            raise DataError(t("{where}: field 'id' missing", where=at))
        basis = p.get("budget_basis")
        projects.append(
            Project(
                id=str(p["id"]),
                name=str(p.get("name") or p["id"]),
                product=_text(p.get("product")),
                target=_date(p["target"], at) if p.get("target") else None,
                priority=_int(p.get("priority"), at, "priority", 0),
                budget_basis=(
                    _choice(basis, BudgetBasis, "plan", at, "budget_basis") if basis else None
                ),
                match=_rule_from(p.get("match"), f"{at}: match"),
                note=_text(p.get("note")),
            )
        )
    return projects


def projects_to_dict(projects: list[Project]) -> dict[str, Any]:
    out = []
    for p in projects:
        entry: dict[str, Any] = {"id": p.id, "name": p.name}
        if p.product:
            entry["product"] = p.product
        entry["target"] = p.target
        entry["priority"] = p.priority
        if p.budget_basis is not None:
            entry["budget_basis"] = p.budget_basis.value
        if p.match is not None:
            entry["match"] = _rule_to(p.match)
        if p.note:
            entry["note"] = p.note
        out.append(entry)
    return {"schema": SCHEMA, "projects": out}


def _timestamp(value: Any, where: str, name: str) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    try:
        return datetime.fromisoformat(str(value))
    except ValueError as e:
        raise DataError(
            t("{where}: invalid time '{value}'", where=f"{where}: {name}", value=value)
        ) from e


def tickets_from_dict(
    d: dict[str, Any], where: str
) -> tuple[list[Ticket], datetime | None, str | None]:
    """Tickets of the last import plus its time stamp and source (both optional)."""
    _schema(d, where)
    imported = _timestamp(d.get("imported"), where, "imported")
    source = _text(d.get("source"))
    tickets = []
    for i, raw in enumerate(_sequence(d.get("tickets"), where, "tickets")):
        at = f"{where}: tickets[{i}]"
        if not isinstance(raw, dict) or not raw.get("key"):
            raise DataError(t("{where}: field 'key' is missing", where=at))
        tickets.append(
            Ticket(
                key=str(raw["key"]),
                title=str(raw.get("title") or ""),
                status=_text(raw.get("status")),
                issue_type=_text(raw.get("issue_type")),
                estimate=_float(raw.get("estimate"), f"{at}: estimate"),
                remaining=_float(raw.get("remaining"), f"{at}: remaining"),
                estimate_source=_choice(
                    raw.get("estimate_source"), EstimateSource, "none", at, "estimate_source"
                ),
                refined_unclear=bool(raw.get("refined_unclear", False)),
                in_sprint=_sprint_ref(raw.get("in_sprint"), at, "in_sprint"),
                sprint_name=_text(raw.get("sprint_name")),
                rank=_text(raw.get("rank")),
                epic=_text(raw.get("epic")),
                labels=_texts(raw.get("labels"), at, "labels"),
                components=_texts(raw.get("components"), at, "components"),
                depends_on=_texts(raw.get("depends_on"), at, "depends_on"),
                project=_text(raw.get("project")),
                project_candidates=_texts(raw.get("project_candidates"), at, "project_candidates"),
                done=bool(raw.get("done", False)),
            )
        )
    return tickets, imported, source


def tickets_to_dict(
    tickets: list[Ticket], imported: datetime | None = None, source: str | None = None
) -> dict[str, Any]:
    out: dict[str, Any] = {"schema": SCHEMA}
    if imported is not None:
        out["imported"] = imported.replace(microsecond=0)
    if source:
        out["source"] = source
    entries = []
    for tk in tickets:
        entry: dict[str, Any] = {
            "key": tk.key,
            "title": tk.title,
            "status": tk.status,
            "issue_type": tk.issue_type,
            "estimate": _clean(tk.estimate),
        }
        if tk.remaining is not None:
            entry["remaining"] = _clean(tk.remaining)
        entry["estimate_source"] = tk.estimate_source.value
        if tk.refined_unclear:
            entry["refined_unclear"] = True
        if tk.in_sprint is not None:
            entry["in_sprint"] = tk.in_sprint
        if tk.sprint_name is not None:
            entry["sprint_name"] = tk.sprint_name
        entry["rank"] = tk.rank
        entry["epic"] = tk.epic
        entry["labels"] = list(tk.labels)
        entry["components"] = list(tk.components)
        entry["depends_on"] = list(tk.depends_on)
        if tk.project is not None:
            entry["project"] = tk.project
        if tk.project_candidates:
            entry["project_candidates"] = list(tk.project_candidates)
        if tk.done:
            entry["done"] = True
        entries.append(entry)
    out["tickets"] = entries
    return out


def preplan_from_dict(d: dict[str, Any], where: str) -> Preplan:
    _schema(d, where)
    earmarks = []
    for i, raw in enumerate(_sequence(d.get("earmarks"), where, "earmarks")):
        at = f"{where}: earmarks[{i}]"
        if not isinstance(raw, dict) or not raw.get("ticket"):
            raise DataError(t("{where}: field 'ticket' is missing", where=at))
        sprint = _sprint_ref(raw.get("sprint"), at, "sprint")
        if sprint is None:
            raise DataError(t("{where}: field 'sprint' is missing", where=at))
        earmarks.append(
            Earmark(ticket=str(raw["ticket"]), sprint=sprint, note=_text(raw.get("note")))
        )
    estimates = []
    for i, raw in enumerate(_sequence(d.get("estimates"), where, "estimates")):
        at = f"{where}: estimates[{i}]"
        if not isinstance(raw, dict) or not raw.get("ticket"):
            raise DataError(t("{where}: field 'ticket' is missing", where=at))
        estimates.append(
            ManualEstimate(
                ticket=str(raw["ticket"]),
                estimate=_float(raw.get("estimate"), f"{at}: estimate"),
                note=_text(raw.get("note")),
            )
        )
    return Preplan(earmarks=earmarks, estimates=estimates)


def preplan_to_dict(preplan: Preplan) -> dict[str, Any]:
    earmarks = []
    for e in preplan.earmarks:
        entry: dict[str, Any] = {"ticket": e.ticket, "sprint": e.sprint}
        if e.note:
            entry["note"] = e.note
        earmarks.append(entry)
    estimates = []
    for m in preplan.estimates:
        entry = {"ticket": m.ticket, "estimate": _clean(m.estimate)}
        if m.note:
            entry["note"] = m.note
        estimates.append(entry)
    return {"schema": SCHEMA, "earmarks": earmarks, "estimates": estimates}


# --- Repository -----------------------------------------------------------------------


@dataclass
class TeamData:
    team: Team
    people: list[Person] = field(default_factory=list)
    sprints: list[Sprint] = field(default_factory=list)
    products: list[Product] = field(default_factory=list)
    # Ticket pre-planning; empty unless ``features.tickets`` is on.
    projects: list[Project] = field(default_factory=list)
    tickets: list[Ticket] = field(default_factory=list)
    preplan: Preplan = field(default_factory=Preplan)
    # Time stamp and source (file name or query) of the last ticket import.
    tickets_imported: datetime | None = None
    tickets_source: str | None = None

    def sprint(self, sprint_id: str) -> Sprint | None:
        return next((s for s in self.sprints if s.id == sprint_id), None)

    def ticket(self, key: str) -> Ticket | None:
        return next((tk for tk in self.tickets if tk.key == key), None)

    def project(self, project_id: str) -> Project | None:
        return next((p for p in self.projects if p.id == project_id), None)


# Zwischenspeicher für geladene Teams (Oberfläche: bei jeder Eingabe läuft die Seite neu).
# Schlüssel: (Datenordner, Team); Wert: (Dateiversion, Team). Die Dateiversion besteht aus
# Pfad, Änderungszeit und Größe aller Team-Dateien – neue und gelöschte Dateien ändern sie.
_TEAM_CACHE: dict[tuple[str, str], tuple[tuple, TeamData]] = {}
_TEAM_CACHE_LOCK = threading.Lock()
# Dateien, die gerade erst geändert wurden, werden nicht zwischengespeichert: Bei grober
# Zeitauflösung des Dateisystems könnte eine zweite Änderung in derselben Zeiteinheit sonst
# unbemerkt bleiben.
_TEAM_CACHE_SETTLE = 2.0


def clear_team_cache() -> None:
    """Verwirft alle zwischengespeicherten Teams und Git-Stände (nach jedem Schreiben, beim
    Wechsel des Datenordners und bei Bedarf)."""
    with _TEAM_CACHE_LOCK:
        _TEAM_CACHE.clear()
    invalidate_status()


# Files of a team besides the sprint files (cache key, check of the files).
TEAM_FILES = (
    "team.yaml",
    "people.yaml",
    "products.yaml",
    "projects.yaml",
    "tickets.yaml",
    "preplan.yaml",
)
# The files of the ticket pre-planning; only read while ``features.tickets`` is on.
TICKET_FILES = ("projects.yaml", "tickets.yaml", "preplan.yaml")


def _file_version(base: Path) -> tuple[tuple, bool]:
    """Dateiversion eines Teams und ob eine Datei so frisch ist, dass sie noch unsicher ist."""
    files = [base / name for name in TEAM_FILES]
    files += sorted((base / "sprints").glob("*.yaml"))
    now = time.time()
    version: list[tuple] = []
    fresh = False
    for f in files:
        try:
            info = f.stat()
        except OSError:
            version.append((f.name, None))
            continue
        version.append((f.name, info.st_mtime_ns, info.st_size))
        fresh = fresh or now - info.st_mtime < _TEAM_CACHE_SETTLE
    return tuple(version), fresh


def team_version(base: Path) -> tuple:
    """Dateiversion eines Teams (ändert sich bei jeder Änderung seiner Dateien)."""
    return _file_version(base)[0]


# Kürzel eines neuen Teams = Ordnername. Nur diese Zeichen, damit weder ein Pfadtrenner noch „..“
# aus dem Datenordner hinausführt und der Name auf jedem Dateisystem (auch ohne Unterscheidung
# der Groß-/Kleinschreibung) derselbe bleibt. Am Anfang ein Buchstabe oder eine Ziffer: ein
# führender Bindestrich würde auf der Kommandozeile als Option gelesen.
_TEAM_KEY = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
# Unter Windows als Gerät reserviert, auch mit Endung („con.txt“).
_WINDOWS_DEVICES = frozenset(
    {"con", "prn", "aux", "nul", *(f"com{n}" for n in range(10)), *(f"lpt{n}" for n in range(10))}
)


def team_key_problem(key: str) -> str | None:
    """Warum ``key`` nicht als Kürzel eines NEUEN Teams taugt (``None`` = in Ordnung). Bestehende
    Teams werden beim Laden nicht geprüft, damit ältere Ordnernamen weiter funktionieren."""
    if key.partition(".")[0].lower() in _WINDOWS_DEVICES:
        return t(
            "Key: these names are reserved for devices on Windows (CON, PRN, AUX, NUL, "
            "COM0 to COM9, LPT0 to LPT9)."
        )
    if not _TEAM_KEY.fullmatch(key):
        return t(
            "Key: lower-case letters a–z (no umlauts), digits, hyphen and underscore (at "
            "most 64 characters; starting with a letter or digit)"
        )
    return None


class Repository:
    def __init__(self, root: Path) -> None:
        self.root = root

    def team_dir(self, key: str) -> Path:
        return self.root / key

    def teams(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.iterdir() if (p / "team.yaml").is_file())

    def clashing_team(self, key: str) -> str | None:
        """Ein vorhandenes Team, dessen Ordnername ``key`` gleicht oder sich nur durch Groß- und
        Kleinschreibung unterscheidet (auf Windows und macOS wären es dieselben Ordner)."""
        wanted = key.casefold()
        return next((name for name in self.teams() if name.casefold() == wanted), None)

    def exists(self, key: str) -> bool:
        return (self.team_dir(key) / "team.yaml").is_file()

    def load(self, key: str) -> TeamData:
        base = self.team_dir(key)
        if not (base / "team.yaml").is_file():
            known = ", ".join(self.teams()) or t("none")
            raise DataError(
                t(
                    "Team '{key}' not found in {root} (available: {known})",
                    key=key,
                    root=self.root,
                    known=known,
                )
            )
        team_file = base / "team.yaml"
        with _well_formed(str(team_file)):
            team = team_from_dict(key, _read(team_file), str(team_file))
        people_file = base / "people.yaml"
        people = []
        if people_file.is_file():
            with _well_formed(str(people_file)):
                people = people_from_dict(_read(people_file), str(people_file))
        products_file = base / "products.yaml"
        products = []
        if products_file.is_file():
            with _well_formed(str(products_file)):
                products = products_from_dict(_read(products_file), str(products_file))
        sprints = []
        for f in sorted((base / "sprints").glob("*.yaml")):
            with _well_formed(str(f)):
                sprint = sprint_from_dict(_read(f), str(f))
            if sprint.id != f.stem:
                raise DataError(
                    t("{file}: id '{id}' does not match the file name", file=f, id=sprint.id)
                )
            sprints.append(sprint)
        sprints.sort(key=lambda s: s.start)
        if not team.features.explicit:  # ältere Datei: vorhandene Daten bleiben sichtbar
            team.features = Features(
                products=bool(products),
                po=any(p.po for p in products),
                production=any(p.production_access for p in people),
                explicit=False,
            )
        data = TeamData(team=team, people=people, sprints=sprints, products=products)
        if team.features.tickets:  # off: the three files are not even read
            projects_file = base / "projects.yaml"
            if projects_file.is_file():
                with _well_formed(str(projects_file)):
                    data.projects = projects_from_dict(_read(projects_file), str(projects_file))
            tickets_file = base / "tickets.yaml"
            if tickets_file.is_file():
                with _well_formed(str(tickets_file)):
                    data.tickets, data.tickets_imported, data.tickets_source = tickets_from_dict(
                        _read(tickets_file), str(tickets_file)
                    )
            preplan_file = base / "preplan.yaml"
            if preplan_file.is_file():
                with _well_formed(str(preplan_file)):
                    data.preplan = preplan_from_dict(_read(preplan_file), str(preplan_file))
        return data

    def load_cached(self, key: str) -> TeamData:
        """Wie :meth:`load`, aber nur bei geänderten Dateien neu gelesen. Der Aufrufer erhält
        eine eigene Kopie und darf sie verändern."""
        version, fresh = _file_version(self.team_dir(key))
        cache_key = (str(self.root.resolve()), key)
        with _TEAM_CACHE_LOCK:
            hit = _TEAM_CACHE.get(cache_key)
        if hit is not None and hit[0] == version:
            return copy.deepcopy(hit[1])
        data = self.load(key)
        if not fresh:
            with _TEAM_CACHE_LOCK:
                _TEAM_CACHE[cache_key] = (version, copy.deepcopy(data))
        return data

    def save_team(self, team: Team) -> Path:
        path = self.team_dir(team.key) / "team.yaml"
        _write(path, TEAM_HEADER, team_to_dict(team))
        return path

    def save_people(self, key: str, people: list[Person]) -> Path:
        path = self.team_dir(key) / "people.yaml"
        _write(path, PEOPLE_HEADER, people_to_dict(people))
        return path

    def save_products(self, key: str, products: list[Product]) -> Path:
        path = self.team_dir(key) / "products.yaml"
        _write(path, PRODUCTS_HEADER, products_to_dict(products))
        return path

    def save_projects(self, key: str, projects: list[Project]) -> Path:
        path = self.team_dir(key) / "projects.yaml"
        _write(path, PROJECTS_HEADER, projects_to_dict(projects))
        return path

    def save_tickets(
        self,
        key: str,
        tickets: list[Ticket],
        imported: datetime | None = None,
        source: str | None = None,
    ) -> Path:
        path = self.team_dir(key) / "tickets.yaml"
        _write(path, TICKETS_HEADER, tickets_to_dict(tickets, imported, source))
        return path

    def save_preplan(self, key: str, preplan: Preplan) -> Path:
        path = self.team_dir(key) / "preplan.yaml"
        _write(path, PREPLAN_HEADER, preplan_to_dict(preplan))
        return path

    def sprint_path(self, key: str, sprint_id: str) -> Path:
        if problem := file_name_problem(sprint_id, portable=False):  # wird zum Dateinamen
            raise DataError(
                t(
                    "Sprint ID {id} is not allowed ({problem})",
                    id=repr(sprint_id),
                    problem=problem,
                )
            )
        return self.team_dir(key) / "sprints" / f"{sprint_id}.yaml"

    def _pinned_absence_state(self, path: Path, sprint: Sprint) -> AbsenceState:
        if path.is_file():
            try:
                with _well_formed(str(path)):
                    return absence_status(sprint_from_dict(_read(path), str(path)))
            except ConflictError, FileAccessError:
                raise  # nicht lesbar ist kein „Datei kaputt“: nichts überschreiben
            except DataError:
                pass
        if sprint.velocity is not None:  # bereits ausgewerteter Sprint (z. B. Import)
            return AbsenceState.CONFIRMED
        return absence_status(sprint)

    def delete_sprint(self, key: str, sprint_id: str) -> None:
        """Entfernt eine Sprintdatei (der Sprint entsteht danach wieder aus dem Kalender)."""
        path = self.sprint_path(key, sprint_id)
        try:
            path.unlink(missing_ok=True)
        except OSError as e:
            raise FileAccessError(
                t(
                    (
                        "{path}: not deleted ({reason}). Is the file read-only or open in "
                        "another program?"
                    ),
                    path=path,
                    reason=_reason(e),
                )
            ) from e
        finally:
            clear_team_cache()

    def save_sprint(self, key: str, sprint: Sprint) -> Path:
        """Schreibt den Sprint. Ist sein Stand der Fehltage noch nicht festgelegt, wird er
        jetzt festgelegt (aus der bisherigen Datei, bei neuen Dateien aus dem Inhalt) – damit
        z. B. das Speichern des Plannings Fehltage nicht stillschweigend bestätigt."""
        path = self.sprint_path(key, sprint.id)
        if sprint.absence_state is None:
            sprint.absence_state = self._pinned_absence_state(path, sprint)
        _write(path, SPRINT_HEADER.format(id=sprint.id), sprint_to_dict(sprint))
        return path


def save_sprints_together(repo: Repository, key: str, sprints: list[Sprint]) -> list[Path]:
    """Schreibt mehrere Sprintdateien ganz oder gar nicht: Scheitert eine, werden die schon
    geschriebenen auf ihren vorherigen Stand zurückgesetzt (neue Dateien entfernt)."""
    before: dict[Path, bytes | None] = {}
    for s in sprints:
        path = repo.sprint_path(key, s.id)
        try:
            before[path] = path.read_bytes() if path.is_file() else None
        except OSError as e:
            raise _not_readable(path, e) from e
    written: list[Path] = []
    try:
        for s in sprints:
            written.append(repo.save_sprint(key, s))
    except BaseException:
        for path in written:
            old = before[path]
            try:
                if old is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(old)
            except OSError:
                pass  # der ursprüngliche Fehler zählt; die Meldung nennt die Datei
        clear_team_cache()
        raise
    return written


def import_sprints(repo: Repository, team: Team, sprints: list[Sprint]) -> list[Path]:
    """Übernimmt Sprints (z. B. aus einem Import-Plugin). Ein neues Team wird mit ``team``
    angelegt; bei einem vorhandenen Team bleiben Einstellungen und Personen erhalten und
    gleichnamige Sprintdateien werden ersetzt."""
    # Vorab prüfen, damit nicht erst ein Teil geschrieben wird, bevor ein Konflikt auffällt.
    marked = [
        p
        for p in (
            repo.team_dir(team.key) / "team.yaml",
            repo.team_dir(team.key) / "people.yaml",
            *(repo.sprint_path(team.key, s.id) for s in sprints),
        )
        if p.is_file() and has_conflict_markers(_read_text(p))
    ]
    if marked:
        raise ConflictError(marked)
    paths = []
    if not repo.exists(team.key):
        if problem := team_key_problem(team.key):  # ein neues Team braucht ein brauchbares Kürzel
            raise DataError(problem)
        if clash := repo.clashing_team(team.key):
            raise DataError(
                t(
                    "Team {team} already exists (as {existing}).",
                    team=repr(team.key),
                    existing=clash,
                )
            )
        paths.append(repo.save_team(team))
    if not (repo.team_dir(team.key) / "people.yaml").exists():
        paths.append(repo.save_people(team.key, []))
    paths += [repo.save_sprint(team.key, s) for s in sprints]
    return paths
