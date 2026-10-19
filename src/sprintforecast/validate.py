# SPDX-License-Identifier: EUPL-1.2
"""Prüfung der Daten auf Fehler und Plausibilität."""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from yaml.constructor import SafeConstructor

from sprintforecast.calendar import (
    countries,
    expected_id_form,
    following_sprint,
    id_fits_numbering,
    subdivisions,
    team_workdays,
    weekend_from_workweek,
)
from sprintforecast.git import blank_controls
from sprintforecast.i18n import t
from sprintforecast.model import RULE_SOURCES, Rule, Ticket
from sprintforecast.storage import (
    TEAM_FILES,
    TICKET_FILES,
    DataError,
    Repository,
    TeamData,
    compose_yaml,
)


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


# --- Ticket pre-planning ---------------------------------------------------------------


def rule_problems(rule: Rule) -> list[str]:
    """Why an assignment rule is invalid (spec section 6.4): unknown sources, leaves without
    values, operators without conditions, short and long form mixed. Empty = valid."""
    problems: list[str] = []

    def walk(node: Rule) -> None:
        if node.op == "leaf":
            if node.source not in RULE_SOURCES:
                problems.append(
                    t(
                        "unbekannte Quelle '{source}' (erlaubt: {allowed})",
                        source=node.source,
                        allowed=", ".join(RULE_SOURCES),
                    )
                )
            if not node.values:
                problems.append(t("'{source}' ohne Werte (leere Liste)", source=node.source))
            return
        if node.short and any(child.op != "leaf" for child in node.children):
            problems.append(
                t(
                    "Kurz- und Langform gemischt: any, all und none stehen je allein, nicht "
                    "neben Quellen oder nebeneinander"
                )
            )
        if not node.children:
            problems.append(
                t("keine Bedingung") if node.short else t("'{op}' ohne Bedingungen", op=node.op)
            )
        for child in node.children:
            walk(child)

    walk(rule)
    return problems


def find_cycles(tickets: list[Ticket]) -> list[list[str]]:
    """Cycles in ``depends_on`` (keys in dependency order), each reported once. Dependencies on
    keys outside the list are ignored."""
    graph = {tk.key: [] for tk in tickets}
    for tk in tickets:
        graph[tk.key] = [d for d in tk.depends_on if d in graph]
    state: dict[str, int] = {}  # 1 = on the current path, 2 = finished
    cycles: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for start in graph:
        if state.get(start):
            continue
        state[start] = 1
        path = [start]
        stack = [iter(graph[start])]
        while stack:
            for nxt in stack[-1]:
                if state.get(nxt, 0) == 1:  # back edge: the path from nxt onwards is a cycle
                    cycle = path[path.index(nxt) :]
                    first = cycle.index(min(cycle))
                    canon = cycle[first:] + cycle[:first]
                    if tuple(canon) not in seen:
                        seen.add(tuple(canon))
                        cycles.append(canon)
                elif not state.get(nxt):
                    state[nxt] = 1
                    path.append(nxt)
                    stack.append(iter(graph[nxt]))
                    break
            else:
                state[path.pop()] = 2
                stack.pop()
    return cycles


def _known_sprint_ids(data: TeamData, ahead: int = 52) -> set[str]:
    """Ids of the sprint files plus the following sprints from the calendar (earmarks name
    sprints that have no file yet)."""
    ids = {s.id for s in data.sprints}
    last = data.sprints[-1] if data.sprints else None
    try:
        for _ in range(ahead):
            last = following_sprint(data.team, last)
            ids.add(last.id)
    except DataError:
        pass  # no first sprint: reported above
    return ids


def _check_tickets(data: TeamData, today: date, error, warn) -> None:
    """Projects, tickets and pre-planning (only with ``features.tickets``)."""
    team = data.team
    tr = team.tracker
    if tr.dependency_gap not in (0, 1):
        error("team.yaml", t("tracker.dependency_gap muss 0 oder 1 sein"))
    order = tr.project_match_order
    if any(s not in RULE_SOURCES for s in order) or len(set(order)) != len(order):
        error(
            "team.yaml",
            t(
                "tracker.project_match_order: nur Quellen aus {allowed}, jede höchstens einmal",
                allowed=", ".join(RULE_SOURCES),
            ),
        )
    if tr.rough_factor <= 0:
        error("team.yaml", t("tracker.rough_factor muss > 0 sein"))
    if tr.refined_also_if is not None:
        for problem in rule_problems(tr.refined_also_if):
            error("team.yaml", t("tracker.refined_also_if: {problem}", problem=problem))

    products = {p.id: p for p in data.products}
    project_ids: set[str] = set()
    for pr in data.projects:
        where = f"projects.yaml: {pr.id}"
        if pr.id in project_ids:
            error(where, t("id ist doppelt"))
        project_ids.add(pr.id)
        if team.features.products:
            if not pr.product:
                error(where, t("product fehlt (die Produktverteilung ist an)"))
            elif pr.product not in products:
                error(where, t("unbekanntes Produkt '{id}'", id=pr.product))
            elif (end := products[pr.product].end) is not None and end < today:
                warn(where, t("Produkt '{id}' ist seit {end} beendet", id=pr.product, end=end))
        elif pr.product:
            error(where, t("product muss leer sein (die Produktverteilung ist aus)"))
        if pr.target is None:
            error(where, t("target fehlt"))
        elif pr.target < today:
            warn(where, t("target {date} liegt in der Vergangenheit", date=pr.target))
        if pr.match is not None:
            for problem in rule_problems(pr.match):
                error(where, t("match: {problem}", problem=problem))
        elif not any(tk.project == pr.id for tk in data.tickets):
            warn(where, t("weder eine match-Regel noch zugeordnete Tickets"))

    known_sprints = _known_sprint_ids(data)
    keys: set[str] = set()
    for tk in data.tickets:
        where = f"tickets.yaml: {tk.key}"
        if tk.key in keys:
            error(where, t("key ist doppelt"))
        keys.add(tk.key)
        for name in ("estimate", "remaining"):
            value = getattr(tk, name)
            if value is not None and value < 0:
                error(where, t("{name} darf nicht negativ sein", name=name))
        if tk.project is not None and tk.project not in project_ids:
            error(where, t("unbekanntes Projekt '{id}'", id=tk.project))
        if tk.in_sprint is not None and tk.in_sprint not in known_sprints:
            warn(where, t("in_sprint '{id}' ist kein bekannter Sprint", id=tk.in_sprint))
    for cycle in find_cycles(data.tickets):
        error(
            "tickets.yaml",
            t("Abhängigkeiten im Kreis: {cycle}", cycle=" → ".join([*cycle, cycle[0]])),
        )

    earmarked: set[str] = set()
    for e in data.preplan.earmarks:
        where = f"preplan.yaml: {e.ticket}"
        if e.ticket in earmarked:
            error(where, t("mehrere Vormerkungen für dasselbe Ticket"))
        earmarked.add(e.ticket)
        if e.ticket not in keys:
            warn(where, t("Vormerkung für ein unbekanntes Ticket (nicht im letzten Import)"))
        if e.sprint not in known_sprints:
            warn(where, t("Sprint '{id}' ist nicht bekannt", id=e.sprint))
    estimated: set[str] = set()
    for m in data.preplan.estimates:
        where = f"preplan.yaml: {m.ticket}"
        if m.ticket in estimated:
            error(where, t("mehrere Schätzungen für dasselbe Ticket"))
        estimated.add(m.ticket)
        if m.ticket not in keys:
            warn(where, t("Schätzung für ein unbekanntes Ticket (nicht im letzten Import)"))
        if m.estimate is None:
            error(where, t("estimate fehlt"))
        elif m.estimate < 0:
            error(where, t("{name} darf nicht negativ sein", name="estimate"))


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
    # Kalender, Fehltage und Prognose bilden die Folge-IDs ab dem laufenden Sprint bis über den
    # letzten hinaus (ohne Sprintdateien: aus dem ersten Sprint). Abgeschlossene Sprints davor
    # spielen keine Rolle; der letzte zählt immer.
    chain = [(f"sprints/{s.id}.yaml", s.id, s.end) for s in data.sprints if s.end > today]
    if data.sprints and data.sprints[-1].end <= today:
        last = data.sprints[-1]
        chain.append((f"sprints/{last.id}.yaml", last.id, last.end))
    if not data.sprints and team.sprint.first_id and team.sprint.first_start:
        first_end = team.sprint.first_start + timedelta(days=max(team.sprint.length_days, 1))
        chain.append(("team.yaml", team.sprint.first_id, first_end))
    for where, sprint_id, next_start in chain:
        if not id_fits_numbering(sprint_id, next_start, team.sprint.numbering):
            error(
                where,
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
    if team.features.tickets:
        _check_tickets(data, today, error, warn)
    return issues


def issues_for(data: TeamData, today: date, filenames: list[str]) -> list[Issue]:
    """Prüfergebnisse, die eine der genannten Dateien betreffen (z. B. "2026.21.yaml")."""
    return [i for i in check_team(data, today) if any(name in i.where for name in filenames)]


# --- Stille Annahmen beim Laden --------------------------------------------------------
#
# Das Laden ändert sich dadurch nicht: Ein doppelter Schlüssel gilt weiter als „der letzte
# gewinnt“, ein leerer Wert als 0. Die Prüfung macht das nur sichtbar. Gemeldet werden leere
# Werte nur dort, wo eine Zahl erwartet wird und das Programm den Leerwert still als 0 liest.
# Absichtlich leere Felder (``to:``, ``capacity:``, ``forecast_ist:``, ``region:`` …) sind
# gültig und bleiben ohne Meldung.

_EMPTY_AS_ZERO: tuple[tuple[str, ...], ...] = (
    ("people", "*", "memberships", "*", "fte"),
    ("planning", "carryover"),
    ("planning", "backlog"),
    ("planning", "corrections", "*"),
    ("absences", "*"),
    ("expected_absences", "*"),
    ("prognoses", "*", "preplanned", "*"),
    ("projects", "*", "priority"),
)
_NULL_TAG = "tag:yaml.org,2002:null"
_STR_TAG = "tag:yaml.org,2002:str"
_MERGE_TAG = "tag:yaml.org,2002:merge"


def _format_path(path: tuple[str | int, ...]) -> str:
    out = ""
    for part in path:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else part)
    return out


def _is_empty_value(node: yaml.Node) -> bool:
    if not isinstance(node, yaml.ScalarNode):
        return False
    return node.tag == _NULL_TAG or (node.tag == _STR_TAG and node.value == "")


def _matches(path: tuple[str | int, ...], pattern: tuple[str, ...]) -> bool:
    return len(path) == len(pattern) and all(
        want == "*" or want == str(got) for want, got in zip(pattern, path, strict=True)
    )


# Mappings, deren Schlüssel das Programm mit str() liest (Personen- und Produktkürzel): Dort
# sind ``1`` und ``"1"`` derselbe Schlüssel. Überall sonst behält der Lader beide Einträge.
_STR_KEYED: tuple[tuple[str, ...], ...] = (
    ("products",),
    ("absences",),
    ("expected_absences",),
    ("prognoses", "*", "preplanned"),
    ("tracker", "sprint_names"),
)
# Obergrenze der besuchten Knoten je Datei: schützt vor Anker-Bomben (Verweise, die sich
# vielfach vervielfachen). Echte Dateien liegen weit darunter.
_MAX_VISITS = 50_000
# Weitere Grenzen je Datei: Rechenzeit, Zahl der Meldungen und Angaben je Zeilenliste. Die Seite
# „Prüfung“ zeichnet jede Meldung einzeln.
_MAX_SECONDS = 2.0
_MAX_ISSUES = 50
_MAX_PLACES = 10

# Pfad als verkettete Liste (Elternpfad, Teil): Tiefe kostet so nichts beim Anlegen.
type _Path = tuple[_Path | None, str | int] | None


def _materialize(cell: _Path) -> tuple[str | int, ...]:
    parts: list[str | int] = []
    while cell is not None:
        cell, part = cell
        parts.append(part)
    return tuple(reversed(parts))


def _key_of(node: yaml.Node, as_text: bool, canon: dict[Any, str]) -> tuple[str, Any]:
    """Anzeigetext und Vergleichsschlüssel. Mit ``as_text`` (Stellen, an denen das Programm
    ``str()`` bildet) gilt der Text, sonst zusätzlich der Typ (``1`` ist nicht ``"1"``).
    ``canon`` gehört zum umgebenden Mapping: Der Lader baut erst das Dict mit Python-Gleichheit
    (``1 == 1.0 == True``, das erste Schlüsselobjekt bleibt) und bildet erst dann ``str()``;
    ``canon`` merkt sich je Schlüsselobjekt den Text des ersten Eintrags."""
    if not isinstance(node, yaml.ScalarNode):
        return str(id(node)), ("node", id(node))
    if node.tag == _STR_TAG:
        value: Any = node.value
    else:
        try:
            value = SafeConstructor().construct_object(node, deep=True)
        except Exception:  # ungewöhnlicher Schlüssel: der Text genügt
            value = node.value
    # Steuerzeichen aus Dateien (Zeilenumbruch, ESC) gehören nie in eine Meldung
    shown = blank_controls(str(value))
    try:
        hash(value)
    except TypeError:  # nicht hashbar: der Lader würde den Schlüssel ohnehin ablehnen
        return shown, (str(value) if as_text else ("node", id(node)))
    if as_text:
        return shown, canon.setdefault(value, str(value))
    # Wie der Lader: Python-Gleichheit (1 == 1.0 == True), aber nicht 1 == "1"
    return shown, value


def _inherited(
    node: yaml.MappingNode,
    as_text: bool,
    canon: dict[Any, str],
    taken: set[Any],
    visiting: frozenset[int],
) -> list[tuple[yaml.Node, yaml.Node]]:
    """Einträge, die ``node`` über ``<<`` erbt und die der Lader behält (Regeln von PyYAML:
    ausdrückliche Schlüssel gewinnen immer; bei mehreren ``<<`` im selben Mapping das spätere,
    bei einer Liste ``<<: [a, b]`` die frühere Quelle; in einer Quelle deren eigene Schlüssel
    vor den von ihr geerbten). ``taken`` sind die schon vergebenen Schlüssel."""
    result: list[tuple[yaml.Node, yaml.Node]] = []
    merges = [vn for kn, vn in node.value if kn.tag == _MERGE_TAG]
    for value_node in reversed(merges):  # das letzte ``<<`` überschreibt die früheren
        sources = value_node.value if isinstance(value_node, yaml.SequenceNode) else [value_node]
        for source in sources:
            if not isinstance(source, yaml.MappingNode) or id(source) in visiting:
                continue
            own = [
                (kn, vn, _key_of(kn, as_text, canon)[1])
                for kn, vn in source.value
                if kn.tag != _MERGE_TAG
            ]
            fresh = [(kn, vn, c) for kn, vn, c in own if c not in taken]
            taken.update(c for _, _, c in fresh)
            result += [(kn, vn) for kn, vn, _ in fresh]
            result += _inherited(source, as_text, canon, taken, visiting | {id(source)})
    return result


def _position(found: list[tuple[int, int]]) -> tuple[str, str]:
    """Fundstellen (Zeile, Spalte) als Text; stehen alle in einer Zeile (Flow-Schreibweise
    ``{a: 1, a: 2}``), mit Spalten."""
    if len({line for line, _ in found}) == 1:
        line = found[0][0]
        cols = _listed([c for _, c in found])
        return (
            t("alle in Zeile {line}, Spalten {cols}", line=line, cols=cols),
            t("Zeile {line}, Spalte {col}", line=line, col=found[-1][1]),
        )
    return (
        t("Zeilen {lines}", lines=_listed([n for n, _ in found])),
        t("Zeile {line}", line=found[-1][0]),
    )


def _listed(numbers: list[int]) -> str:
    """Zahlen als Liste, bei sehr vielen gekürzt (die Meldung bliebe sonst riesig)."""
    shown = ", ".join(str(n) for n in numbers[:_MAX_PLACES])
    if len(numbers) > _MAX_PLACES:
        shown += t(" … und {n} weitere", n=len(numbers) - _MAX_PLACES)
    return shown


def check_yaml_text(text: str, name: str) -> list[Issue]:
    """Doppelte Schlüssel und still als 0 gelesene Leerwerte in einer YAML-Datei (als Hinweis)."""
    try:
        root = compose_yaml(text)
    except yaml.YAMLError:
        return []  # ungültiges YAML meldet das Laden als Fehler
    except RecursionError:
        return [
            Issue(Level.WARNING, name, t("Die Datei ist zu tief verschachtelt, nicht geprüft."))
        ]
    issues: list[Issue] = []
    omitted = 0

    def report(message: str) -> None:
        nonlocal omitted
        if len(issues) < _MAX_ISSUES:
            issues.append(Issue(Level.WARNING, name, message))
        else:
            omitted += 1

    # Schritte: (Knoten, Pfad) beim Betreten, (Knoten, None) beim Verlassen. Iterativ, damit
    # extreme Verschachtelung nicht an der Rekursionsgrenze scheitert. Ein Knoten wird je Pfad
    # besucht (Anker/Verweise bringen ihn unter jedem Pfad zur Geltung); ``active`` hält die
    # Knoten auf dem Weg zur Wurzel und beendet Verweise im Kreis.
    stack: list[tuple[yaml.Node, _Path | None, bool]] = []
    if root is not None:
        stack.append((root, None, True))
    active: set[int] = set()
    visited: set[int] = set()  # Knoten, die schon einmal betreten wurden (Verweise treffen sie)
    duplicates_done: set[int] = set()  # Mappings, deren doppelte Schlüssel schon gemeldet sind
    visits = repeats = 0
    stopped = ""
    deadline = time.monotonic() + _MAX_SECONDS
    while stack:
        node, cell, entering = stack.pop()
        if not entering:
            active.discard(id(node))
            continue
        visits += 1
        if id(node) in visited:
            repeats += 1
        visited.add(id(node))
        if visits > _MAX_VISITS or (visits % 1024 == 0 and time.monotonic() > deadline):
            # Nur wenn Verweise die Hauptursache sind, ist „Anker“ der richtige Hinweis.
            stopped = (
                t(
                    "Die Datei verweist so oft auf dieselben Teile (Anker), dass sie nicht "
                    "vollständig geprüft wurde."
                )
                if repeats * 2 > visits
                else t("Die Datei ist zu groß oder zu verschachtelt, um sie vollständig zu prüfen.")
            )
            break
        if isinstance(node, yaml.ScalarNode):
            path = _materialize(cell)
            if _is_empty_value(node) and any(_matches(path, p) for p in _EMPTY_AS_ZERO):
                report(
                    t(
                        "Der Wert von '{where}' (Zeile {line}) ist leer. Das Programm rechnet "
                        "dort stillschweigend mit 0. Bitte eine Zahl eintragen (0, wenn es "
                        "wirklich null sein soll).",
                        where=_format_path(path),
                        line=node.start_mark.line + 1,
                    )
                )
            continue
        if id(node) in active:  # Verweis auf einen Elternknoten: nicht endlos wiederholen
            continue
        active.add(id(node))
        stack.append((node, None, False))
        children: list[tuple[yaml.Node, _Path | None, bool]] = []
        if isinstance(node, yaml.SequenceNode):
            children = [(item, (cell, i), True) for i, item in enumerate(node.value)]
        else:
            path = _materialize(cell)
            as_text = any(_matches(path, p) for p in _STR_KEYED)
            canon: dict[Any, str] = {}  # je Schlüsselobjekt der Text des ersten Eintrags
            found: dict[Any, list[tuple[int, int]]] = {}
            shown: dict[Any, str] = {}
            kept: dict[Any, tuple[yaml.Node, str]] = {}  # je Schlüssel der letzte Eintrag
            for key_node, value_node in node.value:
                if key_node.tag == _MERGE_TAG:  # geerbte Einträge: siehe _inherited
                    continue
                text_of_key, compare = _key_of(key_node, as_text, canon)
                mark = key_node.start_mark
                found.setdefault(compare, []).append((mark.line + 1, mark.column + 1))
                shown[compare] = text_of_key
                kept[compare] = (value_node, text_of_key)
            # Der Lader behält nur den letzten Eintrag: überdeckte Werte werden nicht gelesen.
            children = [(value_node, (cell, text), True) for value_node, text in kept.values()]
            # Geerbte Einträge (``<<``) zählen nur, wo kein ausdrücklicher Eintrag sie ersetzt.
            for key_node, value_node in _inherited(
                node, as_text, canon, set(found), frozenset({id(node)})
            ):
                text_of_key = _key_of(key_node, as_text, canon)[0]
                children.append((value_node, (cell, text_of_key), True))
            first_time = id(node) not in duplicates_done  # Verweise: nur einmal melden
            duplicates_done.add(id(node))
            for compare, places in found.items():
                if len(places) > 1 and first_time:
                    where = _format_path((*path, shown[compare]))
                    lines, last = _position(places)
                    report(
                        t(
                            "Der Schlüssel '{where}' steht mehrfach in der Datei ({lines}). Das "
                            "Programm liest nur den letzten Eintrag ({last}), die anderen "
                            "werden stillschweigend ignoriert. Bitte die überzähligen Zeilen "
                            "löschen und den richtigen Wert stehen lassen.",
                            where=where,
                            lines=lines,
                            last=last,
                        )
                    )
        stack.extend(reversed(children))
    if omitted:
        issues.append(
            Issue(
                Level.WARNING,
                name,
                t("… und {n} weitere Hinweise in dieser Datei", n=omitted),
            )
        )
    if stopped:
        issues.append(Issue(Level.WARNING, name, stopped))
    return issues


def _tickets_enabled(base: Path) -> bool:
    """``features.tickets`` according to team.yaml in ``base`` (unreadable = off)."""
    try:
        raw = yaml.safe_load((base / "team.yaml").read_text(encoding="utf-8"))
        return bool(raw["features"]["tickets"])
    except OSError, UnicodeDecodeError, KeyError, TypeError, yaml.YAMLError:
        return False  # the loader reports problems with the file


def check_team_files(base: Path, tickets: bool | None = None) -> list[Issue]:
    """Stille Annahmen in den Dateien eines Teams (Ordner ``base``): doppelte Schlüssel und
    leere Zahlenfelder, je als Hinweis mit Dateiname, Zeile und Schlüsselpfad. Die Dateien der
    Ticket-Vorplanung nur mit ``features.tickets`` (``tickets``; ohne Angabe nach team.yaml)."""
    if tickets is None:
        tickets = _tickets_enabled(base)
    files = [base / name for name in TEAM_FILES if tickets or name not in TICKET_FILES]
    files += sorted((base / "sprints").glob("*.yaml"))
    issues: list[Issue] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError, UnicodeDecodeError:
            continue  # fehlende oder unlesbare Dateien meldet das Laden
        name = path.relative_to(base).as_posix()
        issues += check_yaml_text(text, name)
    return issues


def check_all(repo: Repository, today: date) -> dict[str, list[Issue]]:
    result = {}
    for key in repo.teams():
        try:
            data = repo.load(key)
            result[key] = check_team(data, today) + check_team_files(
                repo.team_dir(key), data.team.features.tickets
            )
        except DataError as e:
            result[key] = [Issue(Level.ERROR, key, str(e))]
    return result
