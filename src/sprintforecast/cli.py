# SPDX-License-Identifier: EUPL-1.2
"""Kommandozeile mit geführter Eingabe."""

from __future__ import annotations

import copy
import os
import subprocess
import sys
import time
import webbrowser
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from sprintforecast import __version__
from sprintforecast.calendar import holiday_name, workdays
from sprintforecast.capacity import sprint_capacity
from sprintforecast.engine import CapacitySource
from sprintforecast.forecast import Forecast, apply_planning, build_forecast, find_sprint
from sprintforecast.git import GitError, commit
from sprintforecast.guide import CAPACITY_SOURCES, COMMANDS, FIELDS, TERMS, TOPICS, WORKFLOW
from sprintforecast.launcher import (
    BROWSER_ENV,
    browser_command,
    find_browser,
    free_port,
    wait_until_ready,
)
from sprintforecast.launcher import Kind as BrowserKind
from sprintforecast.model import (
    Membership,
    Numbering,
    Person,
    Planning,
    Sprint,
    Team,
    new_person_id,
)
from sprintforecast.plugins import load_plugins
from sprintforecast.report import capacity_label, fmt, pct, period, render, status
from sprintforecast.settings import SETTINGS, Setting, applicable, changes
from sprintforecast.storage import (
    DATA_ENV,
    STICHTAG_ENV,
    DataError,
    Repository,
    TeamData,
    default_data_dir,
)
from sprintforecast.validate import Level, check_all, issues_for

app = typer.Typer(
    help="Velocity- und Kapazitäts-Forecast für Scrum-Teams. Einstieg: `sprintforecast hilfe`.",
    rich_markup_mode="rich",
)
console = Console()
err = Console(stderr=True)


@dataclass
class Context:
    repo: Repository
    today: date
    stichtag: str | None = None


def _ctx(ctx: typer.Context) -> Context:
    return ctx.obj


@app.callback(invoke_without_command=True)
def _main(
    ctx: typer.Context,
    daten: Annotated[
        Path | None,
        typer.Option(
            "--daten",
            "-d",
            envvar=DATA_ENV,
            help="Verzeichnis mit den Team-Daten (je Team ein Unterordner). "
            "Standard: aktuelles Verzeichnis.",
        ),
    ] = None,
    stichtag: Annotated[
        str | None,
        typer.Option(help="Datum (JJJJ-MM-TT), das als „heute“ gilt – für Rückblicke und Tests."),
    ] = None,
    version: Annotated[bool, typer.Option("--version", help="Version anzeigen.")] = False,
) -> None:
    if version:
        console.print(__version__)
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()
    today = date.fromisoformat(stichtag) if stichtag else date.today()
    ctx.obj = Context(repo=Repository(daten or default_data_dir()), today=today, stichtag=stichtag)


def _load(c: Context, team: str) -> TeamData:
    try:
        return c.repo.load(team)
    except DataError as e:
        err.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e


# --- Eingabe-Helfer -------------------------------------------------------------------


def _explain(key: str) -> None:
    f = FIELDS[key]
    console.print(
        Panel(
            f"{f.what}\n[dim]Quelle: {f.source}\nBeispiel: {f.example}[/dim]",
            title=f.title,
            title_align="left",
            border_style="cyan",
        )
    )


def _ask_number(
    label: str, default: float | None, *, allow_empty: bool = True, minimum: float = 0.0
) -> float | None:
    hint = "leer = keine Angabe" if allow_empty else ""
    shown = "" if default is None else fmt_plain(default)
    while True:
        raw = Prompt.ask(
            f"{label}" + (f" [dim]({hint})[/dim]" if hint else ""),
            default=shown,
            show_default=bool(shown),
            console=console,
        ).strip()
        if raw == "":
            if allow_empty:
                return None
            console.print("[red]Bitte einen Wert eingeben.[/red]")
            continue
        try:
            value = float(raw.replace(",", "."))
        except ValueError:
            console.print("[red]Bitte eine Zahl eingeben (Dezimaltrennzeichen , oder .).[/red]")
            continue
        if value < minimum:
            console.print(f"[red]Der Wert muss ≥ {fmt_plain(minimum)} sein.[/red]")
            continue
        return value


def _ask_numbers(label: str, default: list[float]) -> list[float]:
    shown = " ".join(fmt_plain(v) for v in default)
    while True:
        raw = Prompt.ask(label, default=shown, show_default=bool(shown), console=console).strip()
        try:
            return [float(x.replace(",", ".")) for x in raw.split()] if raw else []
        except ValueError:
            console.print("[red]Bitte Zahlen mit Leerzeichen getrennt eingeben.[/red]")


def _ask_date(label: str, default: date | None) -> date:
    while True:
        raw = Prompt.ask(
            f"{label} [dim](JJJJ-MM-TT)[/dim]",
            default=default.isoformat() if default else "",
            show_default=default is not None,
            console=console,
        ).strip()
        try:
            return date.fromisoformat(raw)
        except ValueError:
            console.print("[red]Datum bitte im Format JJJJ-MM-TT eingeben.[/red]")


def fmt_plain(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _find_or_create(data: TeamData, fc: Forecast, sprint_id: str | None, purpose: str) -> Sprint:
    """Liefert den Sprint aus der Ablage oder erzeugt ihn aus dem Kalender."""
    if sprint_id is None:
        entry = fc.default_entry(purpose)
        if entry is None:
            err.print("[red]Kein passender Sprint gefunden – bitte Sprint-ID angeben.[/red]")
            raise typer.Exit(1)
        sprint_id = entry.sprint.id
    sprint = find_sprint(data, sprint_id)
    if sprint is None:
        err.print(f"[red]Sprint {sprint_id} liegt nicht in der Sprintfolge des Teams.[/red]")
        raise typer.Exit(1)
    return sprint


def _show_sprint_forecast(c: Context, team: str, sprint_id: str) -> None:
    fc = build_forecast(_load(c, team), c.today)
    e = fc.entry(sprint_id)
    if e is None:
        return
    r = e.result
    unit = fc.data.team.unit.value
    console.print(
        Panel(
            f"Kapazität: {capacity_label(e)} PT\n"
            f"n. Velocity-Trend: {fmt(r.normalized_velocity.trend, 2)}\n"
            f"[bold]Forecast PLAN: {fmt(r.plan)} {unit}[/bold]  "
            f"(Roadmap {fmt(r.roadmap, 2)} · Kleinkram {fmt(r.small_stuff, 2)})",
            title=f"Prognose Sprint {sprint_id}",
            title_align="left",
            border_style="green",
        )
    )


def _capacity_table(data: TeamData, s: Sprint) -> Table:
    breakdown = sprint_capacity(data.team, data.people, s)
    table = Table(title=f"Kapazität Sprint {s.id} ({s.start:%d.%m.} – {s.end:%d.%m.%Y})")
    for col in ("Person", "Arbeitstage", "Feiertage", "Fehltage", "PT"):
        table.add_column(col, justify="left" if col == "Person" else "right")
    for pc in breakdown.people:
        table.add_row(
            pc.person.name,
            str(pc.workdays),
            str(pc.holidays),
            fmt_plain(pc.absence_days),
            fmt(pc.capacity),
        )
    if breakdown.overhead:
        table.add_row("Abzug Scrum-Termine", "", "", "", f"−{fmt(breakdown.overhead)}")
    table.add_row("[bold]Summe[/bold]", "", "", "", f"[bold]{fmt(breakdown.capacity)}[/bold]")
    return table


def _maybe_commit(
    c: Context, team: str, paths: list[Path], message: str, tag: str | None, do_commit: bool
) -> None:
    """Zeigt Prüfergebnisse zu den geänderten Dateien und committet, falls gewünscht."""
    issues = issues_for(_load(c, team), c.today, [p.name for p in paths])
    for i in issues:
        colour = "red" if i.level is Level.ERROR else "yellow"
        console.print(f"[{colour}]{i.level}[/{colour}] {i.where}: {i.message}")
    has_errors = any(i.level is Level.ERROR for i in issues)
    if not do_commit:
        console.print("[dim]Tipp: mit --commit wird die Änderung direkt in Git übernommen.[/dim]")
        return
    if has_errors:
        err.print("[red]Nicht committet – bitte zuerst die Fehler beheben.[/red]")
        raise typer.Exit(1)
    try:
        rev = commit(paths, message, tag)
    except GitError as e:
        err.print(f"[red]Git: {e}[/red]")
        raise typer.Exit(1) from e
    console.print(f"[green]Committet ({rev}){f', Tag {tag}' if tag else ''}.[/green]")


TeamArg = Annotated[str, typer.Argument(help="Team-Kürzel = Verzeichnisname, z. B. team-a.")]
SprintArg = Annotated[str | None, typer.Argument(help="Sprint-ID, z. B. 2026.21.")]
CommitOpt = Annotated[bool, typer.Option("--commit", help="Änderung in Git committen.")]


# --- Befehle --------------------------------------------------------------------------


@app.command()
def hilfe(
    thema: Annotated[str | None, typer.Argument(help=f"Thema: {', '.join(TOPICS)}")] = None,
) -> None:
    """Anleitung, Begriffe, Eingabefelder, Einstellungen und Befehle."""
    thema = thema or "ablauf"
    if thema not in TOPICS:
        err.print(f"[red]Unbekanntes Thema. Verfügbar: {', '.join(TOPICS)}[/red]")
        raise typer.Exit(1)
    console.print(_help_table(thema))
    if thema == "begriffe":
        console.print(_two_columns("Kapazitätsquelle im Forecast", CAPACITY_SOURCES))
    others = ", ".join(t for t in TOPICS if t != thema)
    console.print(f"[dim]Weitere Themen: {others} (sprintforecast hilfe THEMA)[/dim]")


def _two_columns(title: str, rows: list[tuple[str, str]]) -> Table:
    table = Table(title=title, show_header=False, box=None, padding=(0, 2), title_justify="left")
    table.add_column(style="bold", no_wrap=True)
    table.add_column()
    for left, right in rows:
        table.add_row(escape(left), escape(right))
    return table


def _help_table(thema: str) -> Table:
    title = TOPICS[thema]
    if thema == "ablauf":
        table = Table(title=title, title_justify="left", show_lines=True)
        for col in ("Wann", "Was", "Befehl"):
            table.add_column(col)
        for step in WORKFLOW:
            table.add_row(step.when, f"[bold]{step.title}[/bold]\n{step.text}", escape(step.cli))
        table.caption = "Alles geht auch im Browser: sprintforecast web"
        return table
    if thema == "begriffe":
        return _two_columns(title, TERMS)
    if thema == "felder":
        table = Table(title=title, title_justify="left", show_lines=True)
        for col in ("Feld", "Bedeutung", "Quelle", "Beispiel"):
            table.add_column(col)
        for f in FIELDS.values():
            table.add_row(f"[bold]{f.title}[/bold]", f.what, f.source, f.example)
        return table
    if thema == "team":
        table = Table(title=title, title_justify="left", show_lines=True)
        for col in ("Einstellung", "Schlüssel in team.yaml", "Bedeutung"):
            table.add_column(col)
        for st in SETTINGS:
            table.add_row(f"[bold]{st.label}[/bold]", st.key, st.help)
        table.caption = "Geführt ändern: sprintforecast einstellungen TEAM"
        return table
    return _two_columns(title, COMMANDS)


def _ask_setting(setting: Setting, team: Team, *, required: bool = False) -> None:
    console.print(f"[dim]{setting.help}[/dim]")
    label = setting.label
    if setting.choices:
        options = ", ".join(f"{k} = {v}" for k, v in setting.choices.items())
        console.print(f"[dim]Möglich: {options}[/dim]")
    if setting.optional and not required:
        label += " [dim](leer = keine Angabe)[/dim]"
    current = setting.display(team)
    while True:
        raw = Prompt.ask(label, default=current, show_default=bool(current), console=console)
        try:
            value = setting.parse(raw)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            continue
        if value is None and required:
            console.print("[red]Bitte einen Wert eingeben.[/red]")
            continue
        setting.set(team, value)
        return


@app.command()
def init(ctx: typer.Context, team: TeamArg, commit_: CommitOpt = False) -> None:
    """Neues Team geführt anlegen."""
    c = _ctx(ctx)
    if c.repo.exists(team):
        err.print(f"[red]Team '{team}' existiert bereits.[/red]")
        raise typer.Exit(1)
    console.print(
        Panel(
            f"Neues Team [bold]{team}[/bold] anlegen. Alle Werte sind später mit "
            f"[bold]sprintforecast einstellungen {team}[/bold] änderbar."
        )
    )
    t = Team(key=team, name=team.upper())
    for setting in applicable(has_sprints=False):
        if setting.key == "sprint.first_id":
            year = t.sprint.first_start.year if t.sprint.first_start else date.today().year
            t.sprint.first_id = f"{year}.1" if t.sprint.numbering is Numbering.YEARLY else "1"
        _ask_setting(setting, t, required=setting.only_without_sprints)
    path = c.repo.save_team(t)
    people = c.repo.save_people(team, [])
    console.print(f"[green]Angelegt: {path}[/green]")
    _maybe_commit(c, team, [path, people], f"{t.name}: Team angelegt", None, commit_)
    console.print(f"Weiter mit: [bold]sprintforecast personen {team}[/bold]")


@app.command()
def einstellungen(ctx: typer.Context, team: TeamArg, commit_: CommitOpt = False) -> None:
    """Team-Einstellungen geführt ändern (Einheit, Bundesland, Referenzkapazität, Trend …)."""
    c = _ctx(ctx)
    data = _load(c, team)
    before = copy.deepcopy(data.team)
    t = data.team
    console.print(
        Panel(
            f"Einstellungen [bold]{t.name}[/bold] – Enter übernimmt den aktuellen Wert.",
            border_style="cyan",
        )
    )
    for setting in applicable(has_sprints=bool(data.sprints)):
        _ask_setting(setting, t)
    diff = changes(before, t)
    if not diff:
        console.print("Keine Änderungen.")
        return
    table = Table(title="Änderungen")
    for col in ("Einstellung", "bisher", "neu"):
        table.add_column(col)
    for setting, old, new in diff:
        table.add_row(setting.label, old or "–", new or "–")
    console.print(table)
    if any(setting.retroactive for setting, _, _ in diff):
        console.print(
            "[yellow]Hinweis: Mindestens eine Änderung wirkt rückwirkend auf alle "
            "berechneten Werte (Ø, Trend, Forecast PLAN).[/yellow]"
        )
    if not Confirm.ask("Speichern?", default=True, console=console):
        raise typer.Exit()
    path = c.repo.save_team(t)
    console.print(f"[green]Gespeichert: {path}[/green]")
    _maybe_commit(c, team, [path], f"{t.name}: Einstellungen geändert", None, commit_)


def _people_table(people: list[Person], day: date, show_former: bool) -> Table:
    table = Table(title=f"Personen (Stand {day:%d.%m.%Y})")
    for col in ("Name", "Bundesland", "FTE heute", "Zeiträume im Team"):
        table.add_column(col)
    shown = [p for p in people if show_former or p.is_current(day)]
    if hidden := len(people) - len(shown):
        table.caption = f"{hidden} ehemalige Person(en) ausgeblendet – anzeigen mit --ehemalige"
    for p in shown:
        spans = ", ".join(
            f"{m.start:%d.%m.%Y}–{m.end:%d.%m.%Y}" if m.end else f"ab {m.start:%d.%m.%Y}"
            for m in p.memberships
        )
        spans += (
            "" if not p.memberships else f" ({'/'.join(fmt_plain(m.fte) for m in p.memberships)})"
        )
        fte = p.fte_on(day)
        table.add_row(p.name, p.region or "–", fmt_plain(fte) if fte else "–", spans)
    return table


def _choose_person(people: list[Person]) -> Person:
    """Auswahl über den Namen; bei gleichen Namen mit interner ID unterschieden."""
    names = [p.name for p in people]
    labels = [p.name if names.count(p.name) == 1 else f"{p.name} ({p.id})" for p in people]
    by_label = {label.lower(): p for label, p in zip(labels, people, strict=True)}
    console.print("[dim]Personen: " + ", ".join(labels) + "[/dim]")
    while True:
        raw = Prompt.ask("Name", console=console).strip().lower()
        if raw in by_label:
            return by_label[raw]
        matches = [p for label, p in by_label.items() if label.startswith(raw)] if raw else []
        if len(matches) == 1:
            return matches[0]
        console.print(
            "[red]Name nicht eindeutig gefunden – bitte wie oben angezeigt eingeben.[/red]"
        )


@app.command()
def personen(
    ctx: typer.Context,
    team: TeamArg,
    commit_: CommitOpt = False,
    ehemalige: Annotated[bool, typer.Option(help="Ausgeschiedene Personen anzeigen.")] = False,
) -> None:
    """Personenliste anzeigen und pflegen (Eintritt, FTE-Änderung, Austritt)."""
    c = _ctx(ctx)
    data = _load(c, team)
    people = data.people
    changed = False
    while True:
        console.print(_people_table(people, c.today, ehemalige))
        action = Prompt.ask(
            "Aktion: n = neue Person, f = FTE ändern, a = Austritt, q = fertig",
            choices=["n", "f", "a", "q"],
            default="q",
            console=console,
        )
        if action == "q":
            break
        if action == "n":
            name = Prompt.ask("Name", console=console).strip()
            if not name:
                console.print("[red]Bitte einen Namen eingeben.[/red]")
                continue
            if any(p.name.lower() == name.lower() for p in people):
                console.print(
                    "[red]Diese Person gibt es schon – für eine FTE-Änderung „f“ wählen.[/red]"
                )
                continue
            pid = new_person_id(name, {p.id for p in people})
            region = (
                Prompt.ask(
                    "Bundesland, falls abweichend vom Team (leer = Team-Einstellung)",
                    default="",
                    show_default=False,
                    console=console,
                )
                .strip()
                .upper()
                or None
            )
            start = _ask_date("Im Team ab", c.today)
            fte = _ask_number(
                "FTE-Anteil im Team (1 = Vollzeit, 0.5 = halbe Stelle)", 1, allow_empty=False
            )
            people.append(Person(pid, name, region, [Membership(start=start, fte=fte or 1.0)]))
        else:
            candidates = [p for p in people if p.is_current(c.today)]
            if not candidates:
                console.print("[red]Keine aktiven Personen.[/red]")
                continue
            person = _choose_person(candidates)
            active = next((m for m in person.memberships if m.end is None), None)
            if active is None:
                console.print("[red]Keine offene Zugehörigkeit.[/red]")
                continue
            when = _ask_date("Gültig ab" if action == "f" else "Letzter Tag im Team", c.today)
            if when <= active.start:
                console.print(
                    "[red]Datum muss nach Beginn der aktuellen Zugehörigkeit liegen.[/red]"
                )
                continue
            if action == "f":
                fte = _ask_number("Neuer FTE-Anteil", active.fte, allow_empty=False)
                active.end = when - timedelta(days=1)
                person.memberships.append(Membership(start=when, fte=fte or active.fte))
            else:
                active.end = when
        changed = True
    if changed:
        path = c.repo.save_people(team, people)
        console.print(f"[green]Gespeichert: {path}[/green]")
        _maybe_commit(
            c, team, [path], f"{data.team.name}: Personenliste aktualisiert", None, commit_
        )


@app.command()
def fehltage(
    ctx: typer.Context, team: TeamArg, sprint: SprintArg = None, commit_: CommitOpt = False
) -> None:
    """Planbare Fehltage je Person für einen Sprint erfassen (Standard: nächster Sprint)."""
    c = _ctx(ctx)
    data = _load(c, team)
    if not data.people:
        err.print(f"[red]Keine Personen erfasst. Zuerst: sprintforecast personen {team}[/red]")
        raise typer.Exit(1)
    fc = build_forecast(data, c.today)
    s = _find_or_create(data, fc, sprint, "next")
    days = workdays(s.start, s.end)
    region = data.team.capacity.region
    hol = [f"{d:%d.%m.} {holiday_name(d, region)}" for d in days if holiday_name(d, region)]
    console.print(
        Panel(
            f"Sprint [bold]{s.id}[/bold]: {s.start:%d.%m.%Y} – {s.end:%d.%m.%Y}, "
            f"{len(days)} Arbeitstage"
            + (f"\nFeiertage ({region or 'bundesweit'}): {', '.join(hol)}" if hol else ""),
            border_style="cyan",
        )
    )
    _explain("absences")
    for p in data.people:
        if not p.active_between(s.start, s.end):
            continue
        value = _ask_number(f"{p.name}", s.absences.get(p.id, 0.0), allow_empty=False)
        if value:
            s.absences[p.id] = min(value, len(days))
        else:
            s.absences.pop(p.id, None)
    if s.capacity is not None and Confirm.ask(
        f"Für den Sprint ist eine feste Kapazität ({fmt_plain(s.capacity)}) eingetragen. "
        "Entfernen, damit sie aus den Fehltagen berechnet wird?",
        default=s.end > c.today,
        console=console,
    ):
        s.capacity = None
    path = c.repo.save_sprint(team, s)
    console.print(_capacity_table(data, s))
    console.print(f"[green]Gespeichert: {path}[/green]")
    _show_sprint_forecast(c, team, s.id)
    _maybe_commit(c, team, [path], f"{data.team.name} {s.id}: Fehltage erfasst", None, commit_)


@app.command()
def planning(
    ctx: typer.Context, team: TeamArg, sprint: SprintArg = None, commit_: CommitOpt = False
) -> None:
    """Sprint Planning erfassen: Forecast IST und Planning-Werte (Standard: laufender Sprint)."""
    c = _ctx(ctx)
    data = _load(c, team)
    fc = build_forecast(data, c.today)
    s = _find_or_create(data, fc, sprint, "current")
    if data.sprint(s.id) is not None:
        _show_sprint_forecast(c, team, s.id)
    else:
        console.print(
            "[yellow]Für diesen Sprint wurden noch keine Fehltage erfasst – die Kapazität ist "
            f"nur geschätzt. Empfehlung: zuerst `sprintforecast fehltage {team} {s.id}`.[/yellow]"
        )
        if not Confirm.ask("Trotzdem fortfahren?", default=False, console=console):
            raise typer.Exit()
    unit = data.team.unit.value
    planning = None
    if Confirm.ask(
        "Kontrollrechnung (Überkipper, Backlog, Korrekturen) erfassen? Optional – wirkt nur "
        "auf das Planning-Delta",
        default=s.planning is not None,
        console=console,
    ):
        p = s.planning or Planning()
        _explain("carryover")
        carryover = _ask_number(f"Überkipper ({unit})", p.carryover, allow_empty=False) or 0.0
        _explain("backlog")
        backlog = _ask_number(f"Backlog ({unit})", p.backlog, allow_empty=False) or 0.0
        _explain("corrections")
        corrections = _ask_numbers(f"Korrekturen ({unit})", p.corrections)
        planning = Planning(carryover=carryover, backlog=backlog, corrections=corrections)
    _explain("forecast_ist")
    default = s.forecast_ist
    if default is None and planning is not None and planning.committed:
        default = planning.committed
        console.print("[dim]Vorbelegt mit Überkipper + Backlog.[/dim]")
    apply_planning(s, _ask_number(f"Forecast IST ({unit})", default), planning)
    path = c.repo.save_sprint(team, s)
    console.print(f"[green]Gespeichert: {path}[/green]")
    fc = build_forecast(_load(c, team), c.today)
    if (e := fc.entry(s.id)) and e.result.planning_total is not None:
        delta = e.result.planning_delta or 0.0
        colour = "green" if delta >= 0 else "red"
        console.print(
            f"Planning-Summe {fmt(e.result.planning_total, 2)} {unit} · Forecast PLAN "
            f"{fmt(e.result.plan)} {unit} · [{colour}]Delta {fmt(delta, 2)} {unit}[/{colour}]"
        )
    _maybe_commit(c, team, [path], f"{data.team.name} {s.id}: Planning erfasst", None, commit_)


@app.command()
def review(
    ctx: typer.Context,
    team: TeamArg,
    sprint: SprintArg = None,
    commit_: Annotated[
        bool, typer.Option("--commit", help="Committen und Tag TEAM/SPRINT setzen.")
    ] = False,
) -> None:
    """Sprint Review erfassen: Velocity, Scope Creep; friert die Kapazität ein."""
    c = _ctx(ctx)
    data = _load(c, team)
    fc = build_forecast(data, c.today)
    s = _find_or_create(data, fc, sprint, "review")
    unit = data.team.unit.value
    console.print(Panel(f"Review Sprint [bold]{s.id}[/bold] ({s.start:%d.%m.} – {s.end:%d.%m.%Y})"))
    if s.capacity is None:
        if data.people:
            frozen = sprint_capacity(data.team, data.people, s).capacity
            console.print(
                f"Kapazität laut Personenliste und Fehltagen: [bold]{fmt(frozen)} PT[/bold]"
            )
            if not Confirm.ask(
                "Stimmt das (sonst Fehltage korrigieren)?", default=True, console=console
            ):
                frozen = _ask_number("Tatsächliche Kapazität (PT)", frozen, allow_empty=False)
        else:
            _explain("capacity")
            frozen = _ask_number("Kapazität (PT)", None, allow_empty=False)
        s.capacity = frozen
    _explain("velocity")
    s.velocity = _ask_number(f"Velocity ({unit})", s.velocity)
    _explain("scope_creep")
    s.scope_creep = _ask_number("Scope Creep (Anteil 0–1)", s.scope_creep)
    path = c.repo.save_sprint(team, s)
    console.print(f"[green]Gespeichert: {path}[/green]")
    _maybe_commit(
        c, team, [path], f"{data.team.name} {s.id}: Review erfasst", f"{team}/{s.id}", commit_
    )


@app.command()
def forecast(
    ctx: typer.Context,
    team: TeamArg,
    verlauf: Annotated[int, typer.Option(help="Anzahl vergangener Sprints in der Anzeige.")] = 5,
) -> None:
    """Prognose für den laufenden und die kommenden Sprints anzeigen."""
    c = _ctx(ctx)
    fc = build_forecast(_load(c, team), c.today)
    team_ = fc.data.team
    unit = team_.unit.value
    table = Table(title=f"Sprint-Forecast {team_.name} (Stand {c.today:%d.%m.%Y})")
    for col in (
        "Sprint",
        "Zeitraum",
        "Status",
        "Kapazität PT",
        "Velocity",
        "n. Vel. (Ø/Trend)",
        f"Forecast PLAN {unit}",
        "Roadmap",
        "Kleinkram",
    ):
        table.add_column(
            col, justify="left" if col in ("Sprint", "Zeitraum", "Status") else "right"
        )
    for e in fc.history(verlauf) + fc.upcoming():
        r = e.result
        future = e.sprint.end > c.today
        n_vel = r.normalized_velocity.trend if future else r.normalized_velocity.average
        table.add_row(
            e.sprint.id,
            period(e),
            status(fc, e).replace("**", ""),
            capacity_label(e) if future else fmt(r.capacity.value),
            fmt(r.velocity.value, 2),
            fmt(n_vel, 2),
            f"[bold]{fmt(r.plan)}[/bold]" if future else fmt(r.plan),
            fmt(r.roadmap, 2) if future else "",
            fmt(r.small_stuff, 2) if future else "",
            style=None if future else "dim",
        )
    console.print(table)
    if any(e.result.plan_capacity_source is CapacitySource.TREND for e in fc.upcoming()):
        console.print(
            "[yellow]⚠ Trend = keine Fehltage erfasst, Kapazität geschätzt. "
            f"Belastbarer mit: sprintforecast fehltage {team} <SPRINT>[/yellow]"
        )


@app.command()
def analyse(
    ctx: typer.Context,
    team: TeamArg,
    rest: Annotated[
        float | None,
        typer.Option(help="Restmenge, für die der Fertigstellungs-Sprint geschätzt wird."),
    ] = None,
    gesamt: Annotated[
        bool,
        typer.Option(
            "--gesamt",
            help="Für --rest den ganzen Forecast nutzen statt nur des Roadmap-Anteils.",
        ),
    ] = False,
    anteil: Annotated[
        float,
        typer.Option(
            min=1,
            max=100,
            help="Projektanteil in %: welcher Teil der Roadmap- bzw. Gesamtkapazität in die "
            "Restmenge fließt (Standard 100).",
        ),
    ] = 100.0,
) -> None:
    """Ergänzende Analysen: Bandbreite, Fokusfaktor, Puffer, Fertigstellung (--rest)."""
    from sprintforecast.analysis import (
        average_focus_factor,
        band,
        buffer_hint,
        completion,
        focus_factor,
    )

    c = _ctx(ctx)
    data = _load(c, team)
    fc = build_forecast(data, c.today)
    unit = data.team.unit.value

    table = Table(title=f"Bandbreite {data.team.name} – zusätzlich zum Forecast PLAN")
    for col in ("Sprint", f"Forecast PLAN {unit}", "konservativ", "mittel", "optimistisch"):
        table.add_column(col, justify="left" if col == "Sprint" else "right")
    for e in fc.upcoming():
        b = band(fc, e)
        table.add_row(
            e.sprint.id,
            fmt(e.result.plan),
            *(fmt(v) for v in ((b.low, b.mid, b.high) if b else (None, None, None))),
        )
    console.print(table)
    console.print(
        "[dim]konservativ/mittel/optimistisch = niedrigste/mittlere/höchste normierte Velocity "
        f"der letzten {data.team.forecast.window} Sprints × Kapazität.[/dim]"
    )

    focus = Table(title="Fokusfaktor (Velocity / Kapazität)")
    focus.add_column("Sprint")
    focus.add_column("Fokusfaktor", justify="right")
    for e in fc.history(data.team.forecast.window):
        focus.add_row(e.sprint.id, fmt(focus_factor(e), 2))
    focus.add_row("[bold]Ø[/bold]", f"[bold]{fmt(average_focus_factor(fc), 2)}[/bold]")
    console.print(focus)

    hint = buffer_hint(fc)
    if hint.average_scope_creep is None:
        console.print("Puffer: Scope Creep wurde zuletzt nicht erfasst – keine Empfehlung.")
    else:
        colour = "yellow" if hint.buffer_too_small else "green"
        console.print(
            f"Puffer: Ø Scope Creep {pct(hint.average_scope_creep)} ({hint.samples} Sprints), "
            f"Kleinkram-Anteil {pct(hint.configured_small_stuff)} – "
            f"[{colour}]"
            + (
                "Puffer kleiner als der ungeplante Anteil"
                if hint.buffer_too_small
                else "passt"
                if hint.sufficient_data
                else "zu wenige Werte für eine Empfehlung"
            )
            + f"[/{colour}]"
        )

    if rest is not None:
        basis_share = 1.0 if gesamt else data.team.forecast.roadmap_share
        share = basis_share * anteil / 100
        result = completion(data, c.today, rest, share)
        if result is None:
            err.print("[red]Zu wenig Historie für eine Fertigstellungsprognose.[/red]")
            raise typer.Exit(1)
        basis = "gesamter Forecast" if gesamt else f"Roadmap-Anteil {pct(basis_share)}"
        if anteil < 100:
            basis += f" × Projektanteil {fmt(anteil, 0)} % = {pct(share)} des Forecasts"
        console.print(
            f"Fertigstellung von {fmt(rest, 1)} {unit} ({basis}, ab dem nächsten Sprint): "
            f"wahrscheinlich bis [bold]{result.p50 or 'nach dem Zeitraum'}[/bold], "
            f"mit 85 % Sicherheit bis [bold]{result.p85 or 'nach dem Zeitraum'}[/bold] "
            f"(≈ {fmt(result.per_sprint, 1)} {unit} je Sprint)."
        )
        if result.trend_capacity_sprints:
            console.print(
                f"[dim]Ohne erfasste Fehltage gerechnet mit Ø Kapazität: "
                f"{', '.join(result.trend_capacity_sprints[:4])}"
                f"{' …' if len(result.trend_capacity_sprints) > 4 else ''}[/dim]"
            )


@app.command()
def bericht(
    ctx: typer.Context,
    team: Annotated[str | None, typer.Argument(help="Team; ohne Angabe für alle Teams.")] = None,
    ausgabe: Annotated[
        Path | None,
        typer.Option("--ausgabe", "-o", help="Datei; Standard <team>/FORECAST.md, - = stdout."),
    ] = None,
) -> None:
    """Markdown-Bericht erzeugen (für Git-Weboberfläche / PO-Runde)."""
    c = _ctx(ctx)
    teams = [team] if team else c.repo.teams()
    for key in teams:
        text = render(build_forecast(_load(c, key), c.today))
        if ausgabe is not None and str(ausgabe) == "-":
            sys.stdout.write(text)
            continue
        target = ausgabe if ausgabe is not None and team else c.repo.team_dir(key) / "FORECAST.md"
        target.write_text(text, encoding="utf-8")
        console.print(f"[green]{target}[/green]")


@app.command()
def pruefen(
    ctx: typer.Context,
    streng: Annotated[bool, typer.Option(help="Hinweise ebenfalls als Fehler werten.")] = False,
) -> None:
    """Alle Team-Daten auf Fehler und Plausibilität prüfen (für CI und vor dem Commit)."""
    c = _ctx(ctx)
    results = check_all(c.repo, c.today)
    if not results:
        err.print(f"[red]Keine Teams gefunden unter {c.repo.root}[/red]")
        raise typer.Exit(1)
    failed = False
    for key, issues in results.items():
        if not issues:
            console.print(f"[green]✔ {key}[/green]")
            continue
        console.print(f"[bold]{key}[/bold]")
        for i in issues:
            colour = "red" if i.level is Level.ERROR else "yellow"
            console.print(f"  [{colour}]{i.level}[/{colour}] {i.where}: {i.message}")
            failed |= i.level is Level.ERROR or streng
    raise typer.Exit(1 if failed else 0)


@app.command()
def web(
    ctx: typer.Context,
    port: Annotated[int, typer.Option(help="Port; ist er belegt, wird ein freier gewählt.")] = 8501,
    browser: Annotated[bool, typer.Option(help="Browser automatisch öffnen.")] = True,
    app_mode: Annotated[
        bool,
        typer.Option(
            "--app",
            help="Als App in eigenem Fenster öffnen (Edge, Chrome, Comet, Chromium, Brave, "
            "Vivaldi; sonst "
            "Firefox oder Standardbrowser). Fenster schließen beendet den Server.",
        ),
    ] = False,
    browser_path: Annotated[
        str | None,
        typer.Option(
            "--browser",
            envvar=BROWSER_ENV,
            help="Browser für --app fest vorgeben (Programmname oder Pfad).",
        ),
    ] = None,
) -> None:
    """Weboberfläche lokal starten (nur auf diesem Rechner erreichbar)."""
    import importlib.util

    if importlib.util.find_spec("streamlit") is None:
        err.print(
            "[red]Für die Weboberfläche wird Streamlit benötigt: "
            'uv tool install "sprintforecast[web] @ git+…" bzw. uv sync --extra web[/red]'
        )
        raise typer.Exit(1)
    c = _ctx(ctx)
    env = os.environ | {DATA_ENV: str(c.repo.root.resolve())}
    if c.stichtag:
        env[STICHTAG_ENV] = c.stichtag
    actual_port = free_port(port)
    if actual_port != port:
        console.print(f"[yellow]Port {port} ist belegt – verwende {actual_port}.[/yellow]")
    url = f"http://localhost:{actual_port}"
    app_file = Path(__file__).parent / "web" / "app.py"
    cmd = [
        sys.executable, "-m", "streamlit", "run", str(app_file),
        "--server.address", "localhost",
        "--server.port", str(actual_port),
        "--server.headless", "false" if browser and not app_mode else "true",
        "--browser.gatherUsageStats", "false",
        "--client.toolbarMode", "minimal",
    ]  # fmt: skip
    console.print(f"Weboberfläche: [bold]{url}[/bold] (Beenden mit Strg+C)")
    server = subprocess.Popen(cmd, env=env)
    try:
        if app_mode:
            _open_app_window(url, server, browser_path)
        server.wait()
    except KeyboardInterrupt:
        pass
    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()


# Endet der Browserprozess schneller, hat er vermutlich an eine laufende Instanz übergeben –
# dann darf der Server nicht beendet werden.
_HANDOFF_SECONDS = 5.0


def _open_app_window(url: str, server: subprocess.Popen, explicit: str | None) -> None:
    """Öffnet das App-Fenster; kehrt zurück, wenn der Server weiterlaufen soll."""
    if not wait_until_ready(url, server):
        err.print("[red]Die Weboberfläche ist nicht gestartet – siehe Ausgabe oben.[/red]")
        raise typer.Exit(1)
    try:
        found = find_browser(explicit)
    except FileNotFoundError as e:
        console.print(f"[yellow]{e} – suche automatisch.[/yellow]")
        found = find_browser(None)
    match found.kind:
        case BrowserKind.APP:
            console.print(f"Öffne {found.name} als App-Fenster …")
            started = time.monotonic()
            subprocess.run(browser_command(found, url))
            if time.monotonic() - started >= _HANDOFF_SECONDS:
                console.print("App-Fenster geschlossen – beende die Weboberfläche.")
                raise KeyboardInterrupt
            console.print(
                "[yellow]Der Browser lief bereits und hat das Fenster übernommen – die "
                "Weboberfläche läuft weiter, beenden mit Strg+C.[/yellow]"
            )
        case BrowserKind.WINDOW:
            console.print(
                f"Kein App-fähiger Browser gefunden – öffne {found.name} (neues Fenster)."
            )
            subprocess.Popen(browser_command(found, url))
        case BrowserKind.DEFAULT:
            console.print("Kein App-fähiger Browser gefunden – öffne den Standardbrowser.")
            webbrowser.open(url)
        case BrowserKind.NONE:
            console.print(
                f"[yellow]Kein Browser gefunden. Bitte {url} in einem Browser öffnen.[/yellow]"
            )


@app.command()
def kapazitaet(ctx: typer.Context, team: TeamArg, sprint: SprintArg = None) -> None:
    """Kapazitätsberechnung eines Sprints im Detail anzeigen (Standard: nächster Sprint)."""
    c = _ctx(ctx)
    data = _load(c, team)
    s = _find_or_create(data, build_forecast(data, c.today), sprint, "next")
    console.print(_capacity_table(data, s))
    if s.capacity is not None:
        console.print(
            f"[dim]In der Sprintdatei eingetragen/eingefroren: {fmt(s.capacity)} PT[/dim]"
        )
    if data.sprint(s.id) is None:
        console.print(
            "[yellow]Noch keine Sprintdatei – die Prognose nutzt bis dahin den "
            "Kapazitäts-Trend.[/yellow]"
        )


# Erweiterungen (z. B. Import-Plugins) registrieren ihre Befehle zuletzt.
for _plugin in load_plugins():
    if _plugin.register_cli is not None:
        _plugin.register_cli(app)
