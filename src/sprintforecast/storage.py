# SPDX-License-Identifier: EUPL-1.2
"""Ablage als YAML-Dateien – gedacht für ein Git-Repository.

<daten>/<team>/team.yaml          Team-Konfiguration
<daten>/<team>/people.yaml        Personenliste mit Zugehörigkeiten
<daten>/<team>/products.yaml      Produktliste (optional)
<daten>/<team>/sprints/<id>.yaml  ein Sprint pro Datei
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from sprintforecast.i18n import t
from sprintforecast.model import (
    CapacitySettings,
    ForecastSettings,
    Membership,
    Numbering,
    Person,
    Planning,
    Product,
    ProductBasis,
    ProductValues,
    Prognosis,
    Sprint,
    SprintSettings,
    Team,
    TrendMode,
    Unit,
)

DATA_ENV = "SPRINTFORECAST_DATEN"
# Datum, das als „heute“ gilt (für Rückblicke und Tests).
STICHTAG_ENV = "SPRINTFORECAST_STICHTAG"


class DataError(Exception):
    """Eine Datei fehlt oder ist nicht lesbar."""


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
    """In der Weboberfläche (oder mit `sprintforecast datenordner`) gemerkter Datenordner."""
    from sprintforecast import config

    raw = config.load().get("data_dir")
    path = Path(raw) if raw else None
    return path if path is not None and path.is_dir() else None


def save_data_dir(path: Path) -> None:
    from sprintforecast import config

    config.update(data_dir=str(path.resolve()))


def default_data_dir() -> Path:
    """--daten > Umgebungsvariable SPRINTFORECAST_DATEN > aktuelles Verzeichnis, falls es
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


def _read(path: Path) -> dict[str, Any]:
    try:
        content = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise DataError(t("Datei fehlt: {path}", path=path)) from e
    except yaml.YAMLError as e:
        raise DataError(t("{path}: kein gültiges YAML ({error})", path=path, error=e)) from e
    if content is None:
        return {}
    if not isinstance(content, dict):
        raise DataError(t("{path}: Inhalt muss ein YAML-Objekt sein", path=path))
    return content


def _write(path: Path, header: str, content: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(content, allow_unicode=True, sort_keys=False, width=100)
    path.write_text(header + body, encoding="utf-8")


def _float(value: Any, where: str) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise DataError(
            t("{where}: Zahl erwartet, gefunden {value}", where=where, value=repr(value))
        )
    return float(value)


def _date(value: Any, where: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as e:
        raise DataError(
            t(
                "{where}: Datum im Format JJJJ-MM-TT erwartet, gefunden {value}",
                where=where,
                value=repr(value),
            )
        ) from e


def _clean(value: float | None) -> float | int | None:
    if value is None:
        return None
    return int(value) if float(value).is_integer() else round(value, 6)


# --- Team -----------------------------------------------------------------------------

TEAM_HEADER = """\
# Team settings. Explanations: `sprintforecast help team`
"""


def team_from_dict(key: str, d: dict[str, Any], where: str) -> Team:
    sprint = d.get("sprint") or {}
    forecast = d.get("forecast") or {}
    capacity = d.get("capacity") or {}
    first = sprint.get("first") or {}
    try:
        return Team(
            key=key,
            name=str(d.get("name") or key),
            unit=Unit(d.get("unit", "PT")),
            sprint=SprintSettings(
                length_days=int(sprint.get("length_days", 14)),
                numbering=Numbering(sprint.get("numbering", "yearly")),
                first_id=str(first["id"]) if first.get("id") is not None else None,
                first_start=_date(first["start"], where) if first.get("start") else None,
            ),
            forecast=ForecastSettings(
                reference_capacity=float(forecast.get("reference_capacity", 67)),
                window=int(forecast.get("window", 5)),
                roadmap_share=float(forecast.get("roadmap_share", 0.8)),
                rounding=int(forecast.get("rounding", 1)),
                trend_mode=TrendMode(forecast.get("trend_mode", "classic")),
                horizon=int(forecast.get("horizon", 3)),
                product_basis=ProductBasis(forecast.get("product_basis", "plan")),
            ),
            capacity=CapacitySettings(
                overhead_share=float(capacity.get("overhead_share", 0.0)),
                overhead_days=float(capacity.get("overhead_days", 0.0)),
                region=capacity.get("region"),
                rounding=int(capacity.get("rounding", 1)),
            ),
        )
    except (ValueError, TypeError) as e:
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
    capacity |= {"region": team.capacity.region, "rounding": team.capacity.rounding}
    return {
        "name": team.name,
        "unit": team.unit.value,
        "sprint": sprint,
        "forecast": forecast,
        "capacity": capacity,
    }


# --- Personen -------------------------------------------------------------------------

PEOPLE_HEADER = """\
# People. Memberships with period and FTE share (1.0 = full time in the team).
# Never delete people; end the membership with `to:` instead – otherwise history changes.
"""


def people_from_dict(d: dict[str, Any], where: str) -> list[Person]:
    people = []
    for i, p in enumerate(d.get("people") or []):
        at = f"{where}: people[{i}]"
        if "id" not in p:
            raise DataError(t("{where}: Feld 'id' fehlt", where=at))
        memberships = [
            Membership(
                start=_date(m.get("from"), at),
                end=_date(m["to"], at) if m.get("to") else None,
                fte=_float(m.get("fte", 1.0), at) or 0.0,
            )
            for m in p.get("memberships") or []
        ]
        people.append(
            Person(
                id=str(p["id"]),
                name=str(p.get("name") or p["id"]),
                region=p.get("region"),
                memberships=memberships,
                production_access=bool(p.get("production_access", False)),
            )
        )
    return people


def people_to_dict(people: list[Person]) -> dict[str, Any]:
    out = []
    for p in people:
        entry: dict[str, Any] = {"id": p.id, "name": p.name}
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
    for i, p in enumerate(d.get("products") or []):
        at = f"{where}: products[{i}]"
        if not isinstance(p, dict) or "id" not in p:
            raise DataError(t("{where}: Feld 'id' fehlt", where=at))
        products.append(
            Product(
                id=str(p["id"]),
                name=str(p.get("name") or p["id"]),
                po=str(p["po"]) if p.get("po") else None,
                start=_date(p["from"], at) if p.get("from") else None,
                end=_date(p["to"], at) if p.get("to") else None,
                share=float(p["share"]) if p.get("share") is not None else None,
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
    for i, p in enumerate(raw or []):
        at_ = f"{where}: prognoses[{i}]"
        if not isinstance(p, dict) or p.get("at") is None:
            raise DataError(t("{where}: Feld 'at' fehlt", where=at_))
        stamp = p["at"]
        try:
            when = stamp if isinstance(stamp, datetime) else datetime.fromisoformat(str(stamp))
        except ValueError as e:
            raise DataError(
                t("{where}: ungültiger Zeitpunkt '{value}'", where=at_, value=stamp)
            ) from e
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
                    str(k): _float(v, at_) or 0.0 for k, v in (p.get("preplanned") or {}).items()
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


def sprint_from_dict(d: dict[str, Any], where: str) -> Sprint:
    for key in ("id", "start", "end"):
        if d.get(key) is None:
            raise DataError(t("{where}: Feld '{key}' fehlt", where=where, key=key))
    if isinstance(d["id"], float):
        raise DataError(
            t('{where}: id bitte in Anführungszeichen setzen, z. B. id: "2026.20"', where=where)
        )
    planning = None
    if p := d.get("planning"):
        planning = Planning(
            carryover=_float(p.get("carryover"), where) or 0.0,
            backlog=_float(p.get("backlog"), where) or 0.0,
            corrections=[_float(c, where) or 0.0 for c in p.get("corrections") or []],
        )
    products = {}
    for pid, values in (d.get("products") or {}).items():
        at = f"{where}: products.{pid}"
        if not isinstance(values, dict):
            raise DataError(t("{where}: Objekt mit preplanned/planned/done erwartet", where=at))
        products[str(pid)] = ProductValues(
            preplanned=_float(values.get("preplanned"), at),
            planned=_float(values.get("planned"), at),
            done=_float(values.get("done"), at),
            production_planned=_float(values.get("production_planned"), at),
            production_done=_float(values.get("production_done"), at),
        )
    absences = {}
    for pid, days in (d.get("absences") or {}).items():
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
        not_done=_float(d.get("not_done"), f"{where}: not_done"),
        additional_done=_float(d.get("additional_done"), f"{where}: additional_done"),
        prognoses=_prognoses_from(d.get("prognoses"), where),
    )


def sprint_to_dict(s: Sprint) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": s.id,
        "start": s.start,
        "end": s.end,
        "absences": {k: _clean(v) for k, v in s.absences.items()},
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
        for pid, pv in s.products.items()
        if not pv.is_empty()
    }
    if products:
        d["products"] = products
    if s.not_done is not None:
        d["not_done"] = _clean(s.not_done)
    if s.additional_done is not None:
        d["additional_done"] = _clean(s.additional_done)
    if s.prognoses:
        d["prognoses"] = _prognoses_to(s.prognoses)
    if s.note:
        d["note"] = s.note
    return d


# --- Repository -----------------------------------------------------------------------


@dataclass
class TeamData:
    team: Team
    people: list[Person] = field(default_factory=list)
    sprints: list[Sprint] = field(default_factory=list)
    products: list[Product] = field(default_factory=list)

    def sprint(self, sprint_id: str) -> Sprint | None:
        return next((s for s in self.sprints if s.id == sprint_id), None)


class Repository:
    def __init__(self, root: Path) -> None:
        self.root = root

    def team_dir(self, key: str) -> Path:
        return self.root / key

    def teams(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.iterdir() if (p / "team.yaml").is_file())

    def exists(self, key: str) -> bool:
        return (self.team_dir(key) / "team.yaml").is_file()

    def load(self, key: str) -> TeamData:
        base = self.team_dir(key)
        if not (base / "team.yaml").is_file():
            known = ", ".join(self.teams()) or t("keine")
            raise DataError(
                t(
                    "Team '{key}' nicht gefunden unter {root} (vorhanden: {known})",
                    key=key,
                    root=self.root,
                    known=known,
                )
            )
        team = team_from_dict(key, _read(base / "team.yaml"), str(base / "team.yaml"))
        people_file = base / "people.yaml"
        people = (
            people_from_dict(_read(people_file), str(people_file)) if people_file.is_file() else []
        )
        products_file = base / "products.yaml"
        products = (
            products_from_dict(_read(products_file), str(products_file))
            if products_file.is_file()
            else []
        )
        sprints = []
        for f in sorted((base / "sprints").glob("*.yaml")):
            sprint = sprint_from_dict(_read(f), str(f))
            if sprint.id != f.stem:
                raise DataError(
                    t("{file}: id '{id}' passt nicht zum Dateinamen", file=f, id=sprint.id)
                )
            sprints.append(sprint)
        sprints.sort(key=lambda s: s.start)
        return TeamData(team=team, people=people, sprints=sprints, products=products)

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

    def sprint_path(self, key: str, sprint_id: str) -> Path:
        return self.team_dir(key) / "sprints" / f"{sprint_id}.yaml"

    def delete_sprint(self, key: str, sprint_id: str) -> None:
        """Entfernt eine Sprintdatei (der Sprint entsteht danach wieder aus dem Kalender)."""
        self.sprint_path(key, sprint_id).unlink(missing_ok=True)

    def save_sprint(self, key: str, sprint: Sprint) -> Path:
        path = self.sprint_path(key, sprint.id)
        _write(path, SPRINT_HEADER.format(id=sprint.id), sprint_to_dict(sprint))
        return path


def import_sprints(repo: Repository, team: Team, sprints: list[Sprint]) -> list[Path]:
    """Übernimmt Sprints (z. B. aus einem Import-Plugin). Ein neues Team wird mit ``team``
    angelegt; bei einem vorhandenen Team bleiben Einstellungen und Personen erhalten und
    gleichnamige Sprintdateien werden ersetzt."""
    paths = []
    if not repo.exists(team.key):
        paths.append(repo.save_team(team))
    if not (repo.team_dir(team.key) / "people.yaml").exists():
        paths.append(repo.save_people(team.key, []))
    paths += [repo.save_sprint(team.key, s) for s in sprints]
    return paths
