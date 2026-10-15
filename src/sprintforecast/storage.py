# SPDX-License-Identifier: EUPL-1.2
"""Ablage als YAML-Dateien – gedacht für ein Git-Repository.

<daten>/<team>/team.yaml          Team-Konfiguration
<daten>/<team>/people.yaml        Personenliste mit Zugehörigkeiten
<daten>/<team>/sprints/<id>.yaml  ein Sprint pro Datei
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from sprintforecast.model import (
    CapacitySettings,
    ForecastSettings,
    Membership,
    Numbering,
    Person,
    Planning,
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


def default_data_dir() -> Path:
    """--daten > Umgebungsvariable SPRINTFORECAST_DATEN > aktuelles Verzeichnis."""
    return Path(os.environ.get(DATA_ENV) or ".")


def _read(path: Path) -> dict[str, Any]:
    try:
        content = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise DataError(f"Datei fehlt: {path}") from e
    except yaml.YAMLError as e:
        raise DataError(f"{path}: kein gültiges YAML ({e})") from e
    if content is None:
        return {}
    if not isinstance(content, dict):
        raise DataError(f"{path}: Inhalt muss ein YAML-Objekt sein")
    return content


def _write(path: Path, header: str, content: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(content, allow_unicode=True, sort_keys=False, width=100)
    path.write_text(header + body, encoding="utf-8")


def _float(value: Any, where: str) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise DataError(f"{where}: Zahl erwartet, gefunden {value!r}")
    return float(value)


def _date(value: Any, where: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as e:
        raise DataError(f"{where}: Datum im Format JJJJ-MM-TT erwartet, gefunden {value!r}") from e


def _clean(value: float | None) -> float | int | None:
    if value is None:
        return None
    return int(value) if float(value).is_integer() else round(value, 6)


# --- Team -----------------------------------------------------------------------------

TEAM_HEADER = """\
# Team-Konfiguration. Erläuterungen: `sprintforecast hilfe team`
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
                trend_mode=TrendMode(forecast.get("trend_mode", "klassisch")),
                horizon=int(forecast.get("horizon", 3)),
            ),
            capacity=CapacitySettings(
                overhead_share=float(capacity.get("overhead_share", 0.0)),
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
    return {
        "name": team.name,
        "unit": team.unit.value,
        "sprint": sprint,
        "forecast": {
            "reference_capacity": _clean(team.forecast.reference_capacity),
            "window": team.forecast.window,
            "roadmap_share": team.forecast.roadmap_share,
            "rounding": team.forecast.rounding,
            "trend_mode": team.forecast.trend_mode.value,
            "horizon": team.forecast.horizon,
        },
        "capacity": {
            "overhead_share": team.capacity.overhead_share,
            "region": team.capacity.region,
            "rounding": team.capacity.rounding,
        },
    }


# --- Personen -------------------------------------------------------------------------

PEOPLE_HEADER = """\
# Personenliste. Zugehörigkeiten mit Zeitraum und FTE-Anteil (1.0 = Vollzeit im Team).
# Personen nie löschen, sondern Zugehörigkeit mit `to:` beenden – sonst ändert sich die Historie.
"""


def people_from_dict(d: dict[str, Any], where: str) -> list[Person]:
    people = []
    for i, p in enumerate(d.get("people") or []):
        at = f"{where}: people[{i}]"
        if "id" not in p:
            raise DataError(f"{at}: Feld 'id' fehlt")
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
            )
        )
    return people


def people_to_dict(people: list[Person]) -> dict[str, Any]:
    out = []
    for p in people:
        entry: dict[str, Any] = {"id": p.id, "name": p.name}
        if p.region:
            entry["region"] = p.region
        entry["memberships"] = [
            {"from": m.start, "to": m.end, "fte": _clean(m.fte)} for m in p.memberships
        ]
        out.append(entry)
    return {"people": out}


# --- Sprints --------------------------------------------------------------------------

SPRINT_HEADER = """\
# Sprint {id}. Erläuterungen zu allen Feldern: `sprintforecast hilfe sprint`
"""


def sprint_from_dict(d: dict[str, Any], where: str) -> Sprint:
    for key in ("id", "start", "end"):
        if d.get(key) is None:
            raise DataError(f"{where}: Feld '{key}' fehlt")
    if isinstance(d["id"], float):
        raise DataError(f'{where}: id bitte in Anführungszeichen setzen, z. B. id: "2026.20"')
    planning = None
    if p := d.get("planning"):
        planning = Planning(
            carryover=_float(p.get("carryover"), where) or 0.0,
            backlog=_float(p.get("backlog"), where) or 0.0,
            corrections=[_float(c, where) or 0.0 for c in p.get("corrections") or []],
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
        note=d.get("note"),
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
    if s.note:
        d["note"] = s.note
    return d


# --- Repository -----------------------------------------------------------------------


@dataclass
class TeamData:
    team: Team
    people: list[Person] = field(default_factory=list)
    sprints: list[Sprint] = field(default_factory=list)

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
            known = ", ".join(self.teams()) or "keine"
            raise DataError(f"Team '{key}' nicht gefunden unter {self.root} (vorhanden: {known})")
        team = team_from_dict(key, _read(base / "team.yaml"), str(base / "team.yaml"))
        people_file = base / "people.yaml"
        people = (
            people_from_dict(_read(people_file), str(people_file)) if people_file.is_file() else []
        )
        sprints = []
        for f in sorted((base / "sprints").glob("*.yaml")):
            sprint = sprint_from_dict(_read(f), str(f))
            if sprint.id != f.stem:
                raise DataError(f"{f}: id '{sprint.id}' passt nicht zum Dateinamen")
            sprints.append(sprint)
        sprints.sort(key=lambda s: s.start)
        return TeamData(team=team, people=people, sprints=sprints)

    def save_team(self, team: Team) -> Path:
        path = self.team_dir(team.key) / "team.yaml"
        _write(path, TEAM_HEADER, team_to_dict(team))
        return path

    def save_people(self, key: str, people: list[Person]) -> Path:
        path = self.team_dir(key) / "people.yaml"
        _write(path, PEOPLE_HEADER, people_to_dict(people))
        return path

    def sprint_path(self, key: str, sprint_id: str) -> Path:
        return self.team_dir(key) / "sprints" / f"{sprint_id}.yaml"

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
