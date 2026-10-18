# SPDX-License-Identifier: EUPL-1.2
"""Import einer Excel-Mappe im Format der Excel-Ausgabe (:mod:`sprintforecast.excel`): das ganze
Team einschließlich Historie – Einstellungen, Personen, Produkte und alle Sprints mit Fehltagen,
Produktwerten und Prognosen.

Gelesen werden nur die Eingaben (gelbe Zellen) nach fester Spaltenposition; berechnete Spalten
(Formeln, Standardverteilung, Namen) werden ignoriert. Vorab zeigt :func:`plan_import`, welche
Werte sich gegenüber den vorhandenen Dateien ändern; erst :func:`apply_import` schreibt.
Der Import des früheren Plugins (:func:`sprintforecast.storage.import_sprints`) bleibt davon
unberührt. Erfordert ``openpyxl`` (``sprintforecast[excel]``)."""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from sprintforecast.excel import (
    ABSENCE_KINDS,
    FORECAST_FIRST_ROW,
    FORMAT_PROPERTY,
    FORMAT_VERSION,
    SETTINGS_FIRST_ROW,
    SHEET_ABSENCES,
    SHEET_FORECAST,
    SHEET_PEOPLE,
    SHEET_PRODUCTS,
    SHEET_PROGNOSES,
    SHEET_SETTINGS,
    SHEET_SPRINTS,
    SHEET_VALUES,
    ExcelUnavailable,
)
from sprintforecast.i18n import t
from sprintforecast.model import (
    AbsenceState,
    Membership,
    Person,
    Product,
    ProductValues,
    Prognosis,
    Sprint,
    Team,
)
from sprintforecast.settings import SETTINGS
from sprintforecast.storage import (
    DataError,
    Repository,
    TeamData,
    _read,
    dump_yaml,
    file_name_problem,
    people_from_dict,
    people_to_dict,
    products_from_dict,
    products_to_dict,
    sprint_from_dict,
    sprint_to_dict,
    team_from_dict,
    team_key_problem,
    team_to_dict,
)
from sprintforecast.validate import Level, check_team


def _openpyxl() -> Any:
    try:
        import openpyxl
    except ImportError as e:
        raise ExcelUnavailable(
            t(
                "Der Excel-Import braucht openpyxl: sprintforecast mit dem Zusatz [excel] "
                "installieren."
            )
        ) from e
    return openpyxl


_TRUE = {"true", "wahr", "ja", "an", "yes", "on", "1", "x"}
_FALSE = {"false", "falsch", "nein", "aus", "no", "off", "0"}
# Plausible Grenzen: Mengen und Tage liegen weit darunter, Daten in einem sinnvollen Zeitraum.
MAX_NUMBER = 1e9
MIN_YEAR, MAX_YEAR = 1990, 2100


def check_sprint_id(sprint_id: str, where: str) -> str:
    """Sprint-IDs werden zu Dateinamen (siehe :func:`sprintforecast.storage.file_name_problem`)."""
    if problem := file_name_problem(sprint_id):
        raise DataError(
            t(
                "{where}: Sprint-ID {id} ist nicht zulässig ({problem})",
                where=where,
                id=repr(sprint_id),
                problem=problem,
            )
        )
    return sprint_id


class _Sheet:
    """Ein Blatt mit Zellzugriff und Fehlermeldungen, die Blatt und Zelle nennen."""

    def __init__(self, ws: Any) -> None:
        self.ws = ws
        self.name = ws.title

    def rows(self, first: int) -> list[tuple[int, tuple[Any, ...]]]:
        """Zeilen ab ``first`` (1-basiert) bis zur letzten gefüllten Zeile."""
        out = []
        for number, row in enumerate(self.ws.iter_rows(min_row=first, values_only=True), first):
            if any(v not in (None, "") for v in row):
                out.append((number, row))
        return out

    def where(self, row: int, col: int) -> str:
        from openpyxl.utils import get_column_letter

        return f"{self.name}!{get_column_letter(col + 1)}{row}"

    def get(self, row: tuple[Any, ...], col: int) -> Any:
        value = row[col] if col < len(row) else None
        if isinstance(value, str):
            value = value.strip()
        return None if value == "" else value

    def number(self, number: int, row: tuple[Any, ...], col: int) -> float | None:
        value = self.get(row, col)
        if value is None:
            return None
        try:
            result = (
                float(str(value).replace(",", "."))
                if isinstance(value, bool) or not isinstance(value, int | float)
                else float(value)
            )
        except ValueError, OverflowError:  # Text oder eine Ganzzahl jenseits von float
            result = math.nan
        if not math.isfinite(result) or isinstance(value, bool):
            # Text, Wahrheitswert, NaN oder unendlich: keine Zahl, mit der gerechnet werden darf.
            raise DataError(
                t(
                    "{where}: eine endliche Zahl erwartet, gefunden: {value}",
                    where=self.where(number, col),
                    value=repr(value)[:60],
                )
            )
        if abs(result) > MAX_NUMBER:
            raise DataError(
                t(
                    "{where}: Zahl außerhalb des zulässigen Bereichs (höchstens {limit}): {value}",
                    where=self.where(number, col),
                    limit=f"{MAX_NUMBER:g}",
                    value=repr(value)[:60],
                )
            )
        return result

    def flag(self, number: int, row: tuple[Any, ...], col: int) -> bool:
        """Wahrheitswert einer Zelle: Excel-Wahrheitswert oder ja/nein-Text; leer = nein. Alles
        andere ist ein Fehler (``bool("aus")`` wäre wahr)."""
        value = self.get(row, col)
        if value is None:
            return False
        if isinstance(value, bool):
            return value
        word = str(value).strip().lower()
        if word in _TRUE:
            return True
        if word in _FALSE:
            return False
        raise DataError(
            t(
                "{where}: ja oder nein (WAHR oder FALSCH) erwartet, gefunden: {value}",
                where=self.where(number, col),
                value=repr(value),
            )
        )

    def text(self, number: int, row: tuple[Any, ...], col: int) -> str | None:
        value = self.get(row, col)
        if value is None:
            return None
        if (isinstance(value, float) and not value.is_integer()) or isinstance(value, datetime):
            raise DataError(
                t(
                    "{where}: Text erwartet (Zahlen und Datumswerte bitte als Text eintragen, "
                    "z. B. 2026.20 in Anführungszeichen oder mit vorangestelltem ' )",
                    where=self.where(number, col),
                )
            )
        return str(int(value)) if isinstance(value, float) else str(value)

    def day(self, number: int, row: tuple[Any, ...], col: int) -> date | None:
        value = self.get(row, col)
        if value is None:
            return None
        if isinstance(value, datetime):
            day = value.date()
        elif isinstance(value, date):
            day = value
        else:
            try:
                day = date.fromisoformat(str(value))
            except ValueError:
                raise DataError(
                    t(
                        "{where}: Datum erwartet, gefunden: {value}",
                        where=self.where(number, col),
                        value=repr(value)[:60],
                    )
                ) from None
        if not MIN_YEAR <= day.year <= MAX_YEAR:
            raise DataError(
                t(
                    "{where}: Datum außerhalb von {first} bis {last}: {value}",
                    where=self.where(number, col),
                    first=MIN_YEAR,
                    last=MAX_YEAR,
                    value=day.isoformat(),
                )
            )
        return day


def _check_format(wb: Any) -> None:
    names = set(wb.sheetnames)
    needed = {SHEET_SETTINGS, SHEET_FORECAST, SHEET_SPRINTS, SHEET_PEOPLE, SHEET_PRODUCTS}
    if missing := sorted(needed - names):
        raise DataError(
            t(
                "Keine Excel-Ausgabe von sprintforecast: Blatt/Blätter fehlen: {missing}",
                missing=", ".join(missing),
            )
        )
    version = None
    props = getattr(getattr(wb, "custom_doc_props", None), "props", None) or []
    for prop in props:
        if prop.name == FORMAT_PROPERTY:
            version = str(prop.value)
    if version is not None and version != FORMAT_VERSION:
        raise DataError(
            t(
                "Die Mappe hat das Format {found}, dieses Programm liest Format {expected}.",
                found=version,
                expected=FORMAT_VERSION,
            )
        )


_SETTING_INTS = {
    "sprint.length_days",
    "forecast.window",
    "forecast.rounding",
    "forecast.horizon",
    "capacity.rounding",
    "capacity.absence_history",
}
_SETTING_FLOATS = {
    "forecast.reference_capacity",
    "forecast.roadmap_share",
    "capacity.overhead_share",
    "capacity.overhead_days",
}
_SETTING_FLAGS = {"features.products", "features.po", "features.production"}
_SETTING_DATES = {"sprint.first.start"}
_SETTING_TEXTS = {
    "name",
    "unit",
    "sprint.numbering",
    "sprint.first.id",
    "forecast.trend_mode",
    "forecast.product_basis",
    "capacity.country",
    "capacity.region",
    "capacity.workweek",
}


def _settings(sh: _Sheet) -> dict[str, Any]:
    """Die Einstellungen als verschachteltes Wörterbuch wie in ``team.yaml``. Nur bekannte
    Schlüssel, jeder Wert mit seinem Typ: Zahlen endlich (ganzzahlige ganz), Schalter ja/nein."""
    result: dict[str, Any] = {}
    for number, row in sh.rows(SETTINGS_FIRST_ROW):
        path = sh.get(row, 2)
        if not isinstance(path, str) or not (
            path in _SETTING_TEXTS | _SETTING_INTS | _SETTING_FLOATS | _SETTING_FLAGS
            or path in _SETTING_DATES
        ):
            if isinstance(path, str) and path and sh.get(row, 1) is not None and "." in path:
                raise DataError(
                    t(
                        "{where}: unbekannter Schlüssel {key}",
                        where=sh.where(number, 2),
                        key=repr(path),
                    )
                )
            continue  # Beschriftungszeilen ohne Schlüssel
        if sh.get(row, 1) is None:
            continue
        value: Any
        if path in _SETTING_INTS:
            number_value = sh.number(number, row, 1)
            if number_value is None or not number_value.is_integer():
                raise DataError(
                    t(
                        "{where}: eine ganze Zahl erwartet, gefunden: {value}",
                        where=sh.where(number, 1),
                        value=repr(sh.get(row, 1)),
                    )
                )
            value = int(number_value)
        elif path in _SETTING_FLOATS:
            value = sh.number(number, row, 1)
        elif path in _SETTING_FLAGS:
            value = sh.flag(number, row, 1)
        elif path in _SETTING_DATES:
            value = sh.day(number, row, 1)
        else:
            value = sh.text(number, row, 1)
        node = result
        *parents, leaf = path.split(".")
        for key in parents:
            node = node.setdefault(key, {})
        node[leaf] = value
    return result


def _people(sh: _Sheet) -> list[Person]:
    people: dict[str, Person] = {}
    for number, row in sh.rows(2):
        pid = sh.text(number, row, 0)
        if pid is None:
            continue
        person = people.get(pid)
        if person is None:
            person = people[pid] = Person(
                id=pid,
                name=sh.text(number, row, 1) or pid,
                country=(sh.text(number, row, 2) or "").upper() or None,
                region=sh.text(number, row, 3),
                workweek=sh.text(number, row, 4),
                production_access=sh.flag(number, row, 5),
            )
        start = sh.day(number, row, 6)
        if start is not None:
            fte = sh.number(number, row, 8)
            person.memberships.append(
                Membership(start=start, end=sh.day(number, row, 7), fte=1.0 if fte is None else fte)
            )
    return list(people.values())


def _products(sh: _Sheet) -> list[Product]:
    products = []
    for number, row in sh.rows(2):
        pid = sh.text(number, row, 0)
        if pid is None:
            continue
        products.append(
            Product(
                id=pid,
                name=sh.text(number, row, 1) or pid,
                po=sh.text(number, row, 2),
                start=sh.day(number, row, 3),
                end=sh.day(number, row, 4),
                share=sh.number(number, row, 5),
            )
        )
    return products


def _preplanned(sh: _Sheet, number: int, row: tuple[Any, ...]) -> dict[str, float]:
    text = sh.text(number, row, 9)
    result: dict[str, float] = {}
    for part in (text or "").split(";"):
        if not part.strip():
            continue
        key, _, value = part.partition("=")
        try:
            number_value = float(value.strip().replace(",", "."))
            if not math.isfinite(number_value) or abs(number_value) > MAX_NUMBER:
                raise ValueError(value)
            result[key.strip()] = number_value
        except ValueError, OverflowError:
            raise DataError(
                t(
                    "{where}: erwartet Kennung=Wert; …, gefunden: {value}",
                    where=sh.where(number, 9),
                    value=repr(text),
                )
            ) from None
    return result


def _sprints(wb: Any) -> list[Sprint]:
    fc = _Sheet(wb[SHEET_FORECAST])
    sp = _Sheet(wb[SHEET_SPRINTS])
    base: dict[str, dict[str, Any]] = {}
    seen_ids: set[str] = set()
    sheet_ids = {sp.text(n, r, 0) for n, r in sp.rows(2)} - {None}
    for number, row in fc.rows(FORECAST_FIRST_ROW + 1):
        sid = fc.text(number, row, 0)
        if sid is None:
            continue
        entry = {
            "start": fc.day(number, row, 1),
            "end": fc.day(number, row, 2),
            "forecast_ist": fc.number(number, row, 3),
            "velocity": fc.number(number, row, 4),
            "scope_creep": fc.number(number, row, 5),
            "capacity": fc.number(number, row, 6),
            "row": number,
        }
        if sid not in sheet_ids and all(entry[k] is None for k in entry if k != "row"):
            continue  # Freitext (Summe, Hinweis) unter den Sprints: keine Sprintzeile
        check_sprint_id(sid, fc.where(number, 0))
        if sid.casefold() in seen_ids:
            raise DataError(
                t(
                    "{where}: Sprint-ID {id} kommt doppelt vor (Groß- und Kleinschreibung gilt auf "
                    "Windows und macOS als gleich).",
                    where=fc.where(number, 0),
                    id=repr(sid),
                )
            )
        seen_ids.add(sid.casefold())
        base[sid] = entry
    listed: dict[str, tuple[int, tuple[Any, ...]]] = {}
    for number, row in sp.rows(2):
        if (sid := sp.text(number, row, 0)) is not None:
            check_sprint_id(sid, sp.where(number, 0))
            if sid.casefold() in {s.casefold() for s in listed}:
                raise DataError(
                    t(
                        "{where}: Sprint-ID {id} kommt doppelt vor (Groß- und Kleinschreibung gilt "
                        "auf Windows und macOS als gleich).",
                        where=sp.where(number, 0),
                        id=repr(sid),
                    )
                )
            listed[sid] = (number, row)
    ids = [
        sid
        for sid, v in base.items()
        if sid in listed
        or any(v[k] is not None for k in ("forecast_ist", "velocity", "scope_creep", "capacity"))
    ]
    for sid in listed:
        if sid not in base:
            number = listed[sid][0]
            raise DataError(
                t(
                    "{where}: Sprint {id} fehlt auf dem Blatt {sheet}",
                    where=sp.where(number, 0),
                    id=sid,
                    sheet=SHEET_FORECAST,
                )
            )
    sprints: dict[str, dict[str, Any]] = {}
    for sid in ids:
        v = base[sid]
        if v["start"] is None or v["end"] is None:
            raise DataError(
                t(
                    "{where}: Start und Ende des Sprints {id} fehlen",
                    where=fc.where(v["row"], 1),
                    id=sid,
                )
            )
        d: dict[str, Any] = {
            "id": sid,
            "start": v["start"],
            "end": v["end"],
            "capacity": v["capacity"],
            "forecast_ist": v["forecast_ist"],
            "velocity": v["velocity"],
            "scope_creep": v["scope_creep"],
        }
        if sid in listed:
            number, row = listed[sid]
            if (state := sp.text(number, row, 1)) is not None:
                if state not in {s.value for s in AbsenceState}:
                    raise DataError(
                        t(
                            "{where}: Stand der Fehltage unbekannt: {value}",
                            where=sp.where(number, 1),
                            value=repr(state),
                        )
                    )
                d["absence_state"] = state
            for key, col in (
                ("forecast_plan", 2),
                ("not_done", 6),
                ("additional_done", 7),
                ("production_planned", 8),
                ("production_done", 9),
            ):
                d[key] = sp.number(number, row, col)
            carry, backlog = sp.number(number, row, 3), sp.number(number, row, 4)
            corr_text = sp.text(number, row, 5)
            if carry is not None or backlog is not None or corr_text:
                corrections = []
                for part in (corr_text or "").split():
                    try:
                        corrections.append(float(part.replace(",", ".")))
                    except ValueError:
                        raise DataError(
                            t(
                                "{where}: Korrekturen bitte als Zahlen mit Leerzeichen getrennt",
                                where=sp.where(number, 5),
                            )
                        ) from None
                d["planning"] = {
                    "carryover": carry or 0.0,
                    "backlog": backlog or 0.0,
                    "corrections": corrections,
                }
            d["note"] = sp.text(number, row, 10)
        sprints[sid] = d

    result = []
    for sid, d in sprints.items():
        raw = {k: v for k, v in d.items() if v is not None}
        result.append(sprint_from_dict(raw, f"{SHEET_FORECAST}: {sid}"))
    by_id = {s.id: s for s in result}

    ab = _Sheet(wb[SHEET_ABSENCES]) if SHEET_ABSENCES in wb.sheetnames else None
    for number, row in ab.rows(2) if ab else []:
        sid, pid, kind = ab.text(number, row, 0), ab.text(number, row, 1), ab.text(number, row, 4)
        days = ab.number(number, row, 3)
        if sid is None or pid is None or days is None:
            continue
        if sid not in by_id or kind not in ABSENCE_KINDS:
            raise DataError(
                t(
                    "{where}: unbekannter Sprint {id} oder Art {kind}",
                    where=ab.where(number, 0),
                    id=sid,
                    kind=repr(kind),
                )
            )
        getattr(by_id[sid], kind)[pid] = days

    vs = _Sheet(wb[SHEET_VALUES]) if SHEET_VALUES in wb.sheetnames else None
    measures = ("preplanned", "planned", "done", "production_planned", "production_done")
    for number, row in vs.rows(2) if vs else []:
        sid, pid = vs.text(number, row, 0), vs.text(number, row, 1)
        if sid is None or pid is None:
            continue
        values = ProductValues(**{m: vs.number(number, row, 5 + k) for k, m in enumerate(measures)})
        if values.is_empty():
            continue
        if sid not in by_id:
            raise DataError(
                t("{where}: unbekannter Sprint {id}", where=vs.where(number, 0), id=sid)
            )
        by_id[sid].products[pid] = values

    pg = _Sheet(wb[SHEET_PROGNOSES]) if SHEET_PROGNOSES in wb.sheetnames else None
    for number, row in pg.rows(2) if pg else []:
        sid = pg.text(number, row, 0)
        at = pg.get(row, 1)
        if sid is None or at is None:
            continue
        if sid not in by_id:
            raise DataError(
                t("{where}: unbekannter Sprint {id}", where=pg.where(number, 0), id=sid)
            )
        if not isinstance(at, datetime):
            raise DataError(
                t("{where}: Zeitpunkt (Datum mit Uhrzeit) erwartet", where=pg.where(number, 1))
            )
        by_id[sid].prognoses.append(
            Prognosis(
                at=at,
                comment=pg.text(number, row, 2),
                forecast_ist=pg.number(number, row, 3),
                not_done=pg.number(number, row, 4),
                additional_done=pg.number(number, row, 5),
                expected_done=pg.number(number, row, 6),
                target=pg.text(number, row, 7),
                plan=pg.number(number, row, 8),
                preplanned=_preplanned(pg, number, row),
            )
        )
    for sprint in result:  # die Oberfläche erwartet „ältere zuerst“
        sprint.prognoses.sort(key=lambda p: p.at)
    return sorted(result, key=lambda s: s.start)


def read_workbook(source: Path | bytes, team_key: str) -> TeamData:
    """Liest die Mappe in ein :class:`TeamData`; Fehler nennen Blatt und Zelle."""
    openpyxl = _openpyxl()
    stream = io.BytesIO(source) if isinstance(source, bytes) else source
    try:
        wb = openpyxl.load_workbook(stream, data_only=True)
    except Exception as e:  # keine gültige xlsx-Datei
        raise DataError(t("Die Datei ist keine lesbare Excel-Mappe: {error}", error=e)) from e
    _check_format(wb)
    where = f"{SHEET_SETTINGS}"
    team = team_from_dict(team_key, _settings(_Sheet(wb[SHEET_SETTINGS])), where)
    data = TeamData(
        team=team,
        people=_people(_Sheet(wb[SHEET_PEOPLE])),
        products=_products(_Sheet(wb[SHEET_PRODUCTS])),
        sprints=_sprints(wb),
    )
    return data


@dataclass
class Change:
    file: str
    path: str
    old: Any
    new: Any


@dataclass
class ImportPlan:
    data: TeamData
    changes: list[Change] = field(default_factory=list)
    # Dateien, die geschrieben werden (relativ zum Teamordner), und Sprintdateien, die es schon
    # gibt, in der Mappe aber nicht vorkommen (bleiben unverändert).
    files: list[str] = field(default_factory=list)
    untouched: list[str] = field(default_factory=list)


def _documents(data: TeamData) -> dict[str, dict[str, Any]]:
    docs = {
        "team.yaml": team_to_dict(data.team),
        "people.yaml": people_to_dict(data.people),
        "products.yaml": products_to_dict(data.products),
    }
    for s in data.sprints:
        docs[f"sprints/{s.id}.yaml"] = sprint_to_dict(s)
    return docs


def _flat(doc: Any) -> dict[str, Any]:
    """Pfad → Wert; Listen werden je Eintrag mit Index aufgeschlüsselt."""

    def walk(value: Any, prefix: str) -> dict[str, Any]:
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for k, v in value.items():
                out |= walk(v, f"{prefix}{k}.")
            return out
        if isinstance(value, list):
            out = {}
            for i, v in enumerate(value):
                out |= walk(v, f"{prefix}{i}.")
            return out
        return {prefix.rstrip("."): value}

    return walk(doc, "")


def check_team_key(repo: Repository, key: str) -> None:
    """Das Kürzel ist ein einfacher Ordnername unterhalb des Datenordners (kein Pfad, kein
    Laufwerk, kein ``..``); ein neues Team muss außerdem ein zulässiges Kürzel tragen und darf
    keinem vorhandenen gleichen (auch nicht bis auf Groß- und Kleinschreibung)."""
    plain = (
        key not in ("", ".", "..")
        and key == Path(key).name
        and not any(c in key for c in "/\\:\x00")
        and not file_name_problem(key)
    )
    if not plain:
        raise DataError(t("Kürzel {key}: kein einfacher Ordnername im Datenordner.", key=repr(key)))
    if not repo.exists(key):
        if problem := team_key_problem(key):
            raise DataError(problem)
        if clash := repo.clashing_team(key):
            raise DataError(
                t("Team {team} existiert bereits (als {existing}).", team=repr(key), existing=clash)
            )


def check_ids(data: TeamData) -> None:
    """Sprint-IDs und die ID des ersten Sprints werden zu Dateinamen: prüfen, bevor sie einen Pfad
    bilden."""
    for sprint in data.sprints:
        check_sprint_id(sprint.id, f"{SHEET_FORECAST}: {sprint.id}")
    if data.team.sprint.first_id is not None:
        check_sprint_id(data.team.sprint.first_id, f"{SHEET_SETTINGS}: sprint.first.id")


def _reload(data: TeamData) -> TeamData:
    """Die Daten so, wie sie nach dem Schreiben wieder geladen würden: jedes Dokument als YAML
    schreiben und mit denselben Prüfungen wie beim Laden einlesen. Fängt alles, was die eigene
    Ladeprüfung später ablehnt (nicht endliche Zahlen, falsche Typen, unzulässige IDs), schon vor
    dem Schreiben ab – und rundet wie das Speichern (6 Stellen)."""
    key = data.team.key

    def back(doc: dict[str, Any]) -> dict[str, Any]:
        return yaml.safe_load(dump_yaml(doc)) or {}

    team = team_from_dict(key, back(team_to_dict(data.team)), "team.yaml")
    people = people_from_dict(back(people_to_dict(data.people)), "people.yaml")
    products = products_from_dict(back(products_to_dict(data.products)), "products.yaml")
    sprints = [
        sprint_from_dict(back(sprint_to_dict(s)), f"sprints/{s.id}.yaml") for s in data.sprints
    ]
    return TeamData(team=team, people=people, sprints=sprints, products=products)


def check_settings(team: Team) -> None:
    """Jede Einstellung muss die Prüfung der Einstellungsseite und der Kommandozeile bestehen
    (Bereiche, Auswahl, Region zum Land): ``Setting.parse`` auf den angezeigten Wert."""
    problems = []
    for setting in SETTINGS:
        value = setting.get(team)
        if value is None and setting.optional:
            continue
        try:
            setting.parse(setting.display(team))
        except ValueError as e:
            problems.append(f"{setting.key}: {e}")
    if problems:
        raise DataError(
            t("Die Mappe enthält ungültige Einstellungen:")
            + "\n"
            + "\n".join(f"- {p}" for p in problems)
        )


def check_valid(data: TeamData, today: date, existing: TeamData | None = None) -> TeamData:
    """Weist die Mappe ab, wenn sie so, wie sie gespeichert würde, nicht ladbar ist oder die
    Prüfung der Daten (wie vor jedem Speichern) Fehler findet. Geprüft wird der Gesamtstand: die
    Mappe samt den vorhandenen Sprintdateien, die in ihr fehlen. Liefert die neu geladenen Daten."""
    check_ids(data)
    reloaded = _reload(data)
    check_settings(reloaded.team)
    union = reloaded
    if existing is not None:
        new_ids = {s.id for s in reloaded.sprints}
        extra = [s for s in existing.sprints if s.id not in new_ids]
        folded = {s.id.casefold(): s.id for s in reloaded.sprints}
        for old in extra:  # auf Windows und macOS dieselbe Datei wie eine importierte ID
            if (clash := folded.get(old.id.casefold())) is not None:
                raise DataError(
                    t(
                        "Sprint-ID {new} aus der Mappe und die vorhandene Sprintdatei {old} "
                        "unterscheiden sich nur durch Groß- und Kleinschreibung (auf Windows und "
                        "macOS dieselbe Datei).",
                        new=repr(clash),
                        old=repr(old.id),
                    )
                )
        union = TeamData(
            team=reloaded.team,
            people=reloaded.people,
            sprints=sorted([*reloaded.sprints, *extra], key=lambda s: s.start),
            products=reloaded.products,
        )
    errors = [i for i in check_team(union, today) if i.level is Level.ERROR]
    if errors:
        raise DataError(
            t("Die Mappe enthält ungültige Werte:")
            + "\n"
            + "\n".join(f"- {i.where}: {i.message}" for i in errors[:20])
        )
    return reloaded


def plan_import(repo: Repository, data: TeamData, today: date | None = None) -> ImportPlan:
    """Vergleicht die Mappe mit den vorhandenen Dateien: Liste der Änderungen je Datei und Wert.
    Weist ein unzulässiges Kürzel, unzulässige IDs, nicht ladbare Werte und Daten mit Prüffehlern
    vorab ab; es wird nichts geschrieben."""
    check_team_key(repo, data.team.key)
    existing = repo.load(data.team.key) if repo.exists(data.team.key) else None
    check_valid(data, today or date.today(), existing)
    team_dir = repo.team_dir(data.team.key)
    new_docs = _documents(data)
    plan = ImportPlan(data=data)
    for name, doc in new_docs.items():
        path = team_dir / name
        old = _read(path) if path.is_file() else None
        # Gleiche Darstellung wie beim Schreiben: erst nach einem Rundlauf vergleichen.
        old_flat = _flat(_normalize(name, old, data.team.key)) if old is not None else None
        new_flat = _flat(doc)
        if old_flat is None:
            plan.changes.append(Change(name, "", None, t("neu angelegt")))
            plan.files.append(name)
            continue
        diff = False
        for key in sorted(old_flat.keys() | new_flat.keys()):
            before, after = old_flat.get(key), new_flat.get(key)
            if before != after:
                diff = True
                plan.changes.append(Change(name, key, before, after))
        if diff:
            plan.files.append(name)
    folder = team_dir / "sprints"
    if folder.is_dir():
        known = {f"sprints/{s.id}.yaml" for s in data.sprints}
        plan.untouched = sorted(
            f"sprints/{p.name}" for p in folder.glob("*.yaml") if f"sprints/{p.name}" not in known
        )
    return plan


def _normalize(name: str, raw: dict[str, Any], key: str) -> dict[str, Any]:
    """Eine vorhandene Datei in dieselbe Form bringen, in der die Mappe sie schreiben würde."""
    if name == "team.yaml":
        return team_to_dict(team_from_dict(key, raw, name))
    if name == "people.yaml":
        return people_to_dict(people_from_dict(raw, name))
    if name == "products.yaml":
        return products_to_dict(products_from_dict(raw, name))
    return sprint_to_dict(sprint_from_dict(raw, name))


def apply_import(repo: Repository, plan: ImportPlan) -> list[Path]:
    """Schreibt die geänderten Dateien (unveränderte bleiben unberührt)."""
    data = plan.data
    key = data.team.key
    check_team_key(repo, key)  # auch hier: ein Plan lässt sich von Hand zusammenbauen
    check_ids(data)
    writers = {
        "team.yaml": lambda: repo.save_team(data.team),
        "people.yaml": lambda: repo.save_people(key, data.people),
        "products.yaml": lambda: repo.save_products(key, data.products),
    }
    paths = []
    sprints = {f"sprints/{s.id}.yaml": s for s in data.sprints}
    for name in plan.files:
        if name in writers:
            paths.append(writers[name]())
        else:
            paths.append(repo.save_sprint(key, sprints[name]))
    return paths
