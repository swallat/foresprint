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
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

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
)
from sprintforecast.storage import (
    DataError,
    Repository,
    TeamData,
    _read,
    people_to_dict,
    products_to_dict,
    sprint_from_dict,
    sprint_to_dict,
    team_from_dict,
    team_to_dict,
)


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
        if isinstance(value, bool) or not isinstance(value, int | float):
            try:
                return float(str(value).replace(",", "."))
            except ValueError:
                raise DataError(
                    t(
                        "{where}: eine Zahl erwartet, gefunden: {value}",
                        where=self.where(number, col),
                        value=repr(value),
                    )
                ) from None
        return float(value)

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
            return value.date()
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value))
        except ValueError:
            raise DataError(
                t(
                    "{where}: Datum erwartet, gefunden: {value}",
                    where=self.where(number, col),
                    value=repr(value),
                )
            ) from None


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


def _settings(sh: _Sheet) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for _, row in sh.rows(SETTINGS_FIRST_ROW):
        path = sh.get(row, 2)
        if not isinstance(path, str) or ("." not in path and path not in ("name", "unit")):
            continue
        value = sh.get(row, 1)
        if value is None:
            continue
        if isinstance(value, datetime):
            value = value.date()
        elif (
            isinstance(value, float)
            and value.is_integer()
            and path.split(".")[-1]
            in {
                "length_days",
                "window",
                "rounding",
                "horizon",
                "absence_history",
            }
        ):
            value = int(value)
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
                production_access=bool(sh.get(row, 5)),
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
            result[key.strip()] = float(value.strip().replace(",", "."))
        except ValueError:
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
    for number, row in fc.rows(FORECAST_FIRST_ROW + 1):
        sid = fc.text(number, row, 0)
        if sid is None:
            continue
        base[sid] = {
            "start": fc.day(number, row, 1),
            "end": fc.day(number, row, 2),
            "forecast_ist": fc.number(number, row, 3),
            "velocity": fc.number(number, row, 4),
            "scope_creep": fc.number(number, row, 5),
            "capacity": fc.number(number, row, 6),
            "row": number,
        }
    listed: dict[str, tuple[int, tuple[Any, ...]]] = {}
    for number, row in sp.rows(2):
        if (sid := sp.text(number, row, 0)) is not None:
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


def plan_import(repo: Repository, data: TeamData) -> ImportPlan:
    """Vergleicht die Mappe mit den vorhandenen Dateien: Liste der Änderungen je Datei und Wert."""
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
    from sprintforecast.storage import people_from_dict, products_from_dict

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
