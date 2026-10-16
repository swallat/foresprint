# SPDX-License-Identifier: EUPL-1.2
"""Verbindet Ablage, Kapazitätsrechner und Rechenkern."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sprintforecast.calendar import following_sprint
from sprintforecast.capacity import sprint_capacity
from sprintforecast.engine import CapacitySource, SprintInput, SprintResult, compute
from sprintforecast.model import Planning, Sprint
from sprintforecast.storage import TeamData


@dataclass
class TimelineEntry:
    sprint: Sprint
    # False für Sprints, die nur aus dem Kalender erzeugt wurden (keine Datei).
    recorded: bool
    result: SprintResult


@dataclass
class Forecast:
    data: TeamData
    today: date
    entries: list[TimelineEntry]

    @property
    def current(self) -> TimelineEntry | None:
        return next((e for e in self.entries if e.sprint.start <= self.today < e.sprint.end), None)

    def upcoming(self) -> list[TimelineEntry]:
        """Laufender Sprint und die folgenden ``horizon`` Sprints."""
        horizon = self.data.team.forecast.horizon
        future = [e for e in self.entries if e.sprint.end > self.today]
        return future[: horizon + 1]

    def history(self, count: int | None = None) -> list[TimelineEntry]:
        past = [e for e in self.entries if e.sprint.end <= self.today]
        return past if count is None else past[-count:]

    def entry(self, sprint_id: str) -> TimelineEntry | None:
        return next((e for e in self.entries if e.sprint.id == sprint_id), None)

    def default_entry(self, purpose: str) -> TimelineEntry | None:
        """Vorschlag je Zweck: current (laufend), planning (nächstes Planning), next (Fehltage),
        review (Review)."""
        if purpose == "current":
            return self.current
        if purpose == "planning":
            # Der laufende Sprint, solange sein Planning fehlt – sonst der nächste.
            current = self.current
            if current is not None and current.sprint.forecast_ist is None:
                return current
            return self.default_entry("next")
        if purpose == "next":
            future = [e for e in self.entries if e.sprint.start > self.today]
            return future[0] if future else None
        if purpose == "review":
            open_past = [e for e in self.history() if e.sprint.velocity is None]
            return open_past[-1] if open_past else self.current
        raise ValueError(purpose)


def timeline(data: TeamData, today: date) -> list[tuple[Sprint, bool]]:
    """Erfasste Sprints plus erzeugte Folgesprints bis ``horizon`` Sprints nach heute."""
    entries = [(s, True) for s in data.sprints]
    horizon = data.team.forecast.horizon
    last = data.sprints[-1] if data.sprints else None
    while sum(1 for s, _ in entries if s.start > today) < horizon:
        last = following_sprint(data.team, last)
        entries.append((last, False))
    return entries


def find_sprint(data: TeamData, sprint_id: str, max_ahead: int = 200) -> Sprint | None:
    """Sprint aus der Ablage oder – falls noch ohne Datei – aus dem Kalender erzeugt."""
    if (existing := data.sprint(sprint_id)) is not None:
        return existing
    last = data.sprints[-1] if data.sprints else None
    for _ in range(max_ahead):
        last = following_sprint(data.team, last)
        if last.id == sprint_id:
            return last
    return None


def apply_planning(sprint: Sprint, forecast_ist: float | None, planning: Planning | None) -> bool:
    """Übernimmt die Planning-Eingaben in ``sprint``.

    Die Kontrollrechnung (Überkipper, Backlog, Korrekturen) ist optional; leer bzw. 0 heißt
    „nicht erfasst“. Ein leerer Forecast IST wird mit Überkipper + Backlog vorbelegt.
    Liefert True, wenn vorbelegt wurde.
    """
    if planning is not None and not (
        planning.carryover or planning.backlog or planning.corrections
    ):
        planning = None
    sprint.planning = planning
    planned = planning.committed if planning is not None else 0.0
    prefilled = forecast_ist is None and planned > 0
    sprint.forecast_ist = planned if prefilled else forecast_ist
    return prefilled


def freeze_plan(sprint: Sprint, entry: TimelineEntry | None, today: date) -> None:
    """Merkt den Forecast PLAN zum Planning – Basis der Standardverteilung je Produkt.
    Abgeschlossene Sprints bleiben unverändert."""
    if entry is None or sprint.end <= today or entry.result.plan is None:
        return
    sprint.forecast_plan = entry.result.plan


def resolve_capacity(
    data: TeamData, sprint: Sprint, recorded: bool
) -> tuple[float | None, CapacitySource | None]:
    if sprint.capacity is not None:
        return sprint.capacity, CapacitySource.RECORDED
    if recorded and data.people:
        return sprint_capacity(data.team, data.people, sprint).capacity, CapacitySource.PEOPLE
    return None, None


def build_forecast(data: TeamData, today: date | None = None) -> Forecast:
    today = today or date.today()
    line = timeline(data, today)
    inputs = []
    for sprint, recorded in line:
        capacity, source = resolve_capacity(data, sprint, recorded)
        inputs.append(
            SprintInput(
                id=sprint.id,
                capacity=capacity,
                capacity_source=source,
                forecast_ist=sprint.forecast_ist,
                velocity=sprint.velocity,
                scope_creep=sprint.scope_creep,
                planning=sprint.planning,
            )
        )
    results = compute(inputs, data.team.forecast)
    entries = [
        TimelineEntry(sprint=s, recorded=r, result=res)
        for (s, r), res in zip(line, results, strict=True)
    ]
    return Forecast(data=data, today=today, entries=entries)
