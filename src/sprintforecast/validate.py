# SPDX-License-Identifier: EUPL-1.2
"""Prüfung der Daten auf Fehler und Plausibilität."""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from sprintforecast.calendar import (
    countries,
    expected_id_form,
    id_fits_numbering,
    subdivisions,
    team_workdays,
    weekend_from_workweek,
)
from sprintforecast.i18n import t
from sprintforecast.storage import DataError, Repository, TeamData


class Level(StrEnum):
    ERROR = "Fehler"
    WARNING = "Hinweis"

    @property
    def label(self) -> str:
        """Anzeigename in der eingestellten Sprache."""
        return t(self.value)


@dataclass
class Issue:
    level: Level
    where: str
    message: str


def _g(value: float) -> str:
    return f"{value:g}"


def _check_product_shares(data: TeamData, today: date, error, warning) -> None:
    """Feste Anteile der gleichzeitig betreuten Produkte dürfen zusammen nicht über 100 %
    liegen (je Sprint und heute); bei genau 100 % bleibt für Produkte ohne Anteil nichts."""
    periods = [(t("Sprint {id}", id=s.id), s.start, s.end) for s in data.sprints]
    periods.append((t("heute"), today, today + timedelta(days=1)))
    reported: set[tuple[float, bool]] = set()
    for label, start, end in periods:
        active = [p for p in data.products if p.active_between(start, end)]
        total = sum(p.share for p in active if p.share is not None)
        rest = any(p.share is None for p in active)
        key = (round(total, 6), rest)
        if key in reported:
            continue
        if total > 1 + 1e-9:
            reported.add(key)
            error(
                "products.yaml",
                t(
                    "Feste Anteile ergeben {total} % ({period}) – mehr als 100 %",
                    total=f"{total * 100:g}",
                    period=label,
                ),
            )
        elif total > 1 - 1e-9 and rest:
            reported.add(key)
            warning(
                "products.yaml",
                t(
                    "Feste Anteile ergeben 100 % ({period}) – für Produkte ohne festen "
                    "Anteil bleibt nichts",
                    period=label,
                ),
            )


def check_team(data: TeamData, today: date) -> list[Issue]:
    issues: list[Issue] = []
    team = data.team

    def error(where: str, msg: str) -> None:
        issues.append(Issue(Level.ERROR, where, msg))

    def warn(where: str, msg: str) -> None:
        issues.append(Issue(Level.WARNING, where, msg))

    f = team.forecast
    if f.reference_capacity <= 0:
        error("team.yaml", t("forecast.reference_capacity muss > 0 sein"))
    if f.window < 1:
        error("team.yaml", t("forecast.window muss ≥ 1 sein"))
    if not 0 <= f.roadmap_share <= 1:
        error("team.yaml", t("forecast.roadmap_share muss zwischen 0 und 1 liegen"))
    if not 0 <= team.capacity.overhead_share < 1:
        error("team.yaml", t("capacity.overhead_share muss zwischen 0 und 1 liegen"))
    country = team.capacity.country
    if country not in countries():
        error("team.yaml", t("Land '{country}' wird nicht unterstützt", country=country))
    elif team.capacity.region and team.capacity.region not in subdivisions(country):
        error(
            "team.yaml",
            t(
                "Region '{region}' gehört nicht zum Land {country}",
                region=team.capacity.region,
                country=country,
            ),
        )
    try:
        weekend_from_workweek(team.capacity.workweek)
    except ValueError:
        error("team.yaml", t("Unbekannte Arbeitswoche '{value}'", value=team.capacity.workweek))
    if team.capacity.absence_history < 0:
        error("team.yaml", t("capacity.absence_history darf nicht negativ sein"))
    if team.capacity.overhead_days < 0:
        error("team.yaml", t("capacity.overhead_days darf nicht negativ sein"))
    if team.sprint.length_days < 1:
        error("team.yaml", t("sprint.length_days muss ≥ 1 sein"))
    if not data.sprints and (team.sprint.first_id is None or team.sprint.first_start is None):
        error(
            "team.yaml",
            t("Ohne Sprintdateien wird sprint.first.id und sprint.first.start benötigt"),
        )
    # Aus der ID des letzten Sprints (ohne Sprintdatei: des ersten) wird die Folge-ID gebildet.
    if data.sprints:
        last_id, last_where = data.sprints[-1].id, f"sprints/{data.sprints[-1].id}.yaml"
    else:
        last_id, last_where = team.sprint.first_id, "team.yaml"
    if last_id is not None and not id_fits_numbering(last_id, team.sprint.numbering):
        error(
            last_where,
            t(
                "ID passt nicht zur Nummerierung (erwartet {expected}) – die ID des "
                "Folgesprints lässt sich nicht bilden",
                expected=expected_id_form(team.sprint.numbering),
            ),
        )

    ids: set[str] = set()
    for p in data.people:
        where = f"people.yaml: {p.id}"
        if p.id in ids:
            error(where, t("id ist doppelt"))
        ids.add(p.id)
        if not p.memberships:
            warn(where, t("keine Zugehörigkeit (memberships) eingetragen"))
        ordered = sorted(p.memberships, key=lambda m: m.start)
        for m in ordered:
            if not 0 <= m.fte <= 1:
                error(where, t("fte {fte} muss zwischen 0 und 1 liegen", fte=m.fte))
            if m.end is not None and m.end < m.start:
                error(
                    where,
                    t(
                        "Zugehörigkeit endet ({end}) vor ihrem Beginn ({start})",
                        end=m.end,
                        start=m.start,
                    ),
                )
        for a, b in itertools.pairwise(ordered):
            if a.end is None or a.end >= b.start:
                error(
                    where,
                    t("Zugehörigkeiten überschneiden sich ({a} / {b})", a=a.start, b=b.start),
                )

    for p in data.people:
        where = f"people.yaml: {p.id}"
        try:
            weekend_from_workweek(p.workweek)
        except ValueError:
            error(where, t("Unbekannte Arbeitswoche '{value}'", value=p.workweek))
        if p.country and p.country not in countries():
            error(where, t("Land '{country}' wird nicht unterstützt", country=p.country))
        elif p.region and p.region not in subdivisions(p.country or country):
            error(
                where,
                t(
                    "Region '{region}' gehört nicht zum Land {country}",
                    region=p.region,
                    country=p.country or country,
                ),
            )

    product_ids: set[str] = set()
    for prod in data.products:
        where = f"products.yaml: {prod.id}"
        if prod.id in product_ids:
            error(where, t("id ist doppelt"))
        product_ids.add(prod.id)
        if prod.share is not None and not 0 < prod.share <= 1:
            error(where, t("share muss zwischen 0 und 1 liegen"))
        if prod.start and prod.end and prod.end < prod.start:
            error(
                where,
                t(
                    "Zeitraum endet ({end}) vor seinem Beginn ({start})",
                    end=prod.end,
                    start=prod.start,
                ),
            )
    products = {p.id: p for p in data.products}
    _check_product_shares(data, today, error, warn)

    people = {p.id: p for p in data.people}
    previous = None
    for s in data.sprints:
        where = f"sprints/{s.id}.yaml"
        if s.end <= s.start:
            error(where, t("end muss nach start liegen"))
        if previous is not None and s.start < previous.end:
            error(where, t("überschneidet sich mit Sprint {id}", id=previous.id))
        if previous is not None and s.start > previous.end:
            warn(
                where,
                t(
                    "Lücke zu Sprint {id} ({end} → {start})",
                    id=previous.id,
                    end=previous.end,
                    start=s.start,
                ),
            )
        previous = s

        for pid, absent in s.expected_absences.items():
            if pid not in people:
                error(where, t("Angekündigte Fehltage für unbekannte Person '{id}'", id=pid))
            elif absent < 0:
                error(where, t("expected_absences.{id} darf nicht negativ sein", id=pid))

        days = len(team_workdays(team, s.start, s.end))
        for pid, absent in s.absences.items():
            person = people.get(pid)
            if person is None:
                error(where, t("Fehltage für unbekannte Person '{id}'", id=pid))
            elif not person.active_between(s.start, s.end):
                warn(where, t("'{id}' ist in diesem Sprint nicht im Team", id=pid))
            if absent < 0:
                error(where, t("Fehltage für '{id}' sind negativ", id=pid))
            elif absent > days:
                error(
                    where,
                    t(
                        "'{id}': {absent} Fehltage, der Sprint hat nur {days} Arbeitstage",
                        id=pid,
                        absent=_g(absent),
                        days=days,
                    ),
                )

        for pid, values in s.products.items():
            product = products.get(pid)
            if product is None:
                error(where, t("Werte für unbekanntes Produkt '{id}'", id=pid))
            elif not product.active_between(s.start, s.end) and not values.is_empty():
                warn(
                    where,
                    t(
                        "Produkt '{id}' wird in diesem Sprint laut Produktliste nicht betreut",
                        id=pid,
                    ),
                )
            for name in (
                "preplanned",
                "planned",
                "done",
                "production_planned",
                "production_done",
            ):
                value = getattr(values, name)
                if value is not None and value < 0:
                    error(
                        where, t("products.{id}.{name} darf nicht negativ sein", id=pid, name=name)
                    )
        for pid, values in s.products.items():
            for whole, part in (
                (values.planned, values.production_planned),
                (values.done, values.production_done),
            ):
                if part is not None and part > (whole or 0.0) + 0.05:
                    warn(
                        where,
                        t(
                            "Produkt '{id}': Produktionszugriff ({part}) ist größer als der "
                            "Gesamtwert ({whole})",
                            id=pid,
                            part=_g(part),
                            whole=_g(whole or 0.0),
                        ),
                    )
        planned = [v.planned for v in s.products.values() if v.planned is not None]
        if planned and s.forecast_ist is not None and sum(planned) > s.forecast_ist + 0.05:
            warn(
                where,
                t(
                    "Planning je Produkt ({planned}) ist größer als das Commitment ({ist})",
                    planned=_g(sum(planned)),
                    ist=_g(s.forecast_ist),
                ),
            )
        done = [v.done for v in s.products.values() if v.done is not None]
        if done and s.velocity is not None and sum(done) > s.velocity + 0.05:
            warn(
                where,
                t(
                    "Erledigt je Produkt ({done}) ist größer als die Velocity ({velocity})",
                    done=_g(sum(done)),
                    velocity=_g(s.velocity),
                ),
            )

        for name in ("not_done", "additional_done", "production_planned", "production_done"):
            value = getattr(s, name)
            if value is not None and value < 0:
                error(where, t("{name} darf nicht negativ sein", name=name))
        if (
            s.production_planned is not None
            and s.forecast_ist is not None
            and s.production_planned > s.forecast_ist + 0.05
        ):
            warn(
                where,
                t(
                    "Produktionszugriff eingeplant ({part}) ist größer als das Commitment "
                    "({whole})",
                    part=_g(s.production_planned),
                    whole=_g(s.forecast_ist),
                ),
            )
        if (
            s.velocity is not None
            and s.forecast_ist is not None
            and (s.not_done is not None or s.additional_done is not None)
        ):
            expected = s.forecast_ist - (s.not_done or 0.0) + (s.additional_done or 0.0)
            if abs(expected - s.velocity) > 0.05:
                warn(
                    where,
                    t(
                        "Commitment ({ist}) − nicht erledigt ({open}) + zusätzlich erledigt "
                        "({extra}) ergibt {expected}, die Velocity ist aber {velocity}",
                        ist=_g(s.forecast_ist),
                        open=_g(s.not_done or 0.0),
                        extra=_g(s.additional_done or 0.0),
                        expected=_g(expected),
                        velocity=_g(s.velocity),
                    ),
                )
        for name in ("capacity", "forecast_ist", "velocity", "forecast_plan"):
            value = getattr(s, name)
            if value is not None and value < 0:
                error(where, t("{name} darf nicht negativ sein", name=name))
        if s.scope_creep is not None and not 0 <= s.scope_creep <= 1:
            warn(
                where,
                t(
                    "scope_creep {value} liegt außerhalb 0–1 (Anteil, nicht Prozent?)",
                    value=_g(s.scope_creep),
                ),
            )
        if s.capacity == 0:
            warn(where, t("Kapazität 0 – normierte Velocity nicht berechenbar"))
        if s.velocity is not None and s.forecast_ist and s.velocity > 2 * s.forecast_ist:
            warn(where, t("Velocity ist mehr als doppelt so hoch wie Commitment – Tippfehler?"))

        if s.planning is not None and s.end > today:
            committed = s.planning.committed
            if s.forecast_ist is not None and committed and abs(s.forecast_ist - committed) > 0.05:
                warn(
                    where,
                    t(
                        "Commitment {ist} weicht von Überkipper + Backlog ({planned}) ab – "
                        "Tippfehler oder Ticket vergessen?",
                        ist=_g(s.forecast_ist),
                        planned=_g(committed),
                    ),
                )
            if sum(s.planning.corrections) > committed:
                warn(where, t("Korrekturen sind größer als Überkipper + Backlog"))

        if s.end <= today:
            if s.velocity is None:
                warn(where, t("Sprint ist beendet, Velocity fehlt (Review erfassen)"))
            if s.capacity is None:
                warn(
                    where,
                    t(
                        "Sprint ist beendet, Kapazität nicht eingefroren "
                        "(wird sonst aus der aktuellen Personenliste berechnet)"
                    ),
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
