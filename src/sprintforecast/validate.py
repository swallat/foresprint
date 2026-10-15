# SPDX-License-Identifier: EUPL-1.2
"""Prüfung der Daten auf Fehler und Plausibilität."""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from sprintforecast.calendar import workdays
from sprintforecast.storage import DataError, Repository, TeamData


class Level(StrEnum):
    ERROR = "Fehler"
    WARNING = "Hinweis"


@dataclass
class Issue:
    level: Level
    where: str
    message: str


def check_team(data: TeamData, today: date) -> list[Issue]:
    issues: list[Issue] = []
    team = data.team

    def error(where: str, msg: str) -> None:
        issues.append(Issue(Level.ERROR, where, msg))

    def warn(where: str, msg: str) -> None:
        issues.append(Issue(Level.WARNING, where, msg))

    f = team.forecast
    if f.reference_capacity <= 0:
        error("team.yaml", "forecast.reference_capacity muss > 0 sein")
    if f.window < 1:
        error("team.yaml", "forecast.window muss ≥ 1 sein")
    if not 0 <= f.roadmap_share <= 1:
        error("team.yaml", "forecast.roadmap_share muss zwischen 0 und 1 liegen")
    if not 0 <= team.capacity.overhead_share < 1:
        error("team.yaml", "capacity.overhead_share muss zwischen 0 und 1 liegen")
    if team.sprint.length_days < 1:
        error("team.yaml", "sprint.length_days muss ≥ 1 sein")
    if not data.sprints and (team.sprint.first_id is None or team.sprint.first_start is None):
        error(
            "team.yaml", "Ohne Sprintdateien wird sprint.first.id und sprint.first.start benötigt"
        )

    ids: set[str] = set()
    for p in data.people:
        where = f"people.yaml: {p.id}"
        if p.id in ids:
            error(where, "id ist doppelt")
        ids.add(p.id)
        if not p.memberships:
            warn(where, "keine Zugehörigkeit (memberships) eingetragen")
        ordered = sorted(p.memberships, key=lambda m: m.start)
        for m in ordered:
            if not 0 < m.fte <= 1:
                error(where, f"fte {m.fte} muss zwischen 0 und 1 liegen")
            if m.end is not None and m.end < m.start:
                error(where, f"Zugehörigkeit endet ({m.end}) vor ihrem Beginn ({m.start})")
        for a, b in itertools.pairwise(ordered):
            if a.end is None or a.end >= b.start:
                error(where, f"Zugehörigkeiten überschneiden sich ({a.start} / {b.start})")

    people = {p.id: p for p in data.people}
    previous = None
    for s in data.sprints:
        where = f"sprints/{s.id}.yaml"
        if s.end <= s.start:
            error(where, "end muss nach start liegen")
        if previous is not None and s.start < previous.end:
            error(where, f"überschneidet sich mit Sprint {previous.id}")
        if previous is not None and s.start > previous.end:
            warn(where, f"Lücke zu Sprint {previous.id} ({previous.end} → {s.start})")
        previous = s

        days = len(workdays(s.start, s.end))
        for pid, absent in s.absences.items():
            person = people.get(pid)
            if person is None:
                error(where, f"Fehltage für unbekannte Person '{pid}'")
            elif not person.active_between(s.start, s.end):
                warn(where, f"'{pid}' ist in diesem Sprint nicht im Team")
            if absent < 0:
                error(where, f"Fehltage für '{pid}' sind negativ")
            elif absent > days:
                error(where, f"'{pid}': {absent} Fehltage, der Sprint hat nur {days} Arbeitstage")

        for name in ("capacity", "forecast_ist", "velocity"):
            value = getattr(s, name)
            if value is not None and value < 0:
                error(where, f"{name} darf nicht negativ sein")
        if s.scope_creep is not None and not 0 <= s.scope_creep <= 1:
            warn(where, f"scope_creep {s.scope_creep} liegt außerhalb 0–1 (Anteil, nicht Prozent?)")
        if s.capacity == 0:
            warn(where, "Kapazität 0 – normierte Velocity nicht berechenbar")
        if s.velocity is not None and s.forecast_ist and s.velocity > 2 * s.forecast_ist:
            warn(where, "Velocity ist mehr als doppelt so hoch wie Forecast IST – Tippfehler?")

        if s.planning is not None and s.end > today:
            planned = s.planning.committed
            if s.forecast_ist is not None and planned and abs(s.forecast_ist - planned) > 0.05:
                warn(
                    where,
                    f"Forecast IST {s.forecast_ist:g} weicht von Überkipper + Backlog "
                    f"({planned:g}) ab – Tippfehler oder Ticket vergessen?",
                )
            if sum(s.planning.corrections) > planned:
                warn(where, "Korrekturen sind größer als Überkipper + Backlog")

        if s.end <= today:
            if s.velocity is None:
                warn(where, "Sprint ist beendet, Velocity fehlt (Review erfassen)")
            if s.capacity is None:
                warn(
                    where,
                    "Sprint ist beendet, Kapazität nicht eingefroren "
                    "(wird sonst aus der aktuellen Personenliste berechnet)",
                )
    return issues


def issues_for(data: TeamData, today: date, filenames: list[str]) -> list[Issue]:
    """Prüfergebnisse, die eine der genannten Dateien betreffen (z. B. "2026.21.yaml")."""
    return [i for i in check_team(data, today) if any(name in i.where for name in filenames)]


def check_all(repo: Repository, today: date) -> dict[str, list[Issue]]:
    result = {}
    for key in repo.teams():
        try:
            result[key] = check_team(repo.load(key), today)
        except DataError as e:
            result[key] = [Issue(Level.ERROR, key, str(e))]
    return result
