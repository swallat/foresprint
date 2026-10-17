# SPDX-License-Identifier: EUPL-1.2
"""Kommandozeile mit geführter Eingabe (Deutsch/Englisch, siehe i18n)."""

from __future__ import annotations

import copy
import functools
import os
import subprocess
import sys
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from sprintforecast import LOG_ENV, __version__, updater
from sprintforecast.calendar import day_label, holiday_name, team_workdays, workweek_label
from sprintforecast.capacity import sprint_capacity
from sprintforecast.config import SettingsError
from sprintforecast.engine import UNSURE_SOURCES
from sprintforecast.forecast import (
    Forecast,
    apply_planning,
    build_forecast,
    find_sprint,
    freeze_plan,
    refreeze_offer,
)
from sprintforecast.git import GitError, commit
from sprintforecast.guide import (
    CAPACITY_SOURCES,
    COMMAND_ALIASES,
    COMMANDS,
    FIELDS,
    TERMS,
    TOPIC_ALIASES,
    TOPICS,
    WORKFLOW,
    command_text,
)
from sprintforecast.i18n import LANGUAGES, is_english, language, save_language, t
from sprintforecast.idle import IDLE_ENV
from sprintforecast.launcher import (
    BROWSER_ENV,
    browser_command,
    find_browser,
    free_port,
    wait_until_ready,
)
from sprintforecast.launcher import Kind as BrowserKind
from sprintforecast.model import (
    AbsenceState,
    Membership,
    Numbering,
    Person,
    Planning,
    Product,
    ProductValues,
    Sprint,
    Team,
    new_person_id,
)
from sprintforecast.plugins import load_plugins
from sprintforecast.proctree import adopt, popen_options, terminate_tree
from sprintforecast.products import MEASURES, Distribution, balance, distribution, measure_label
from sprintforecast.report import (
    capacity_label,
    fmt,
    fmt_capacity,
    pct,
    period,
    reliability_notes,
    render,
    status,
)
from sprintforecast.settings import SETTINGS, Setting, applicable, changes
from sprintforecast.storage import (
    DATA_ENV,
    STICHTAG_ENV,
    DataError,
    FileAccessError,
    Repository,
    TeamData,
    default_data_dir,
    write_text,
)
from sprintforecast.updater import PACKAGE
from sprintforecast.validate import Level, check_all, check_team, issues_for

app = typer.Typer(
    help=t("Velocity- und Kapazitäts-Forecast für Scrum-Teams. Einstieg: `sprintforecast hilfe`."),
    rich_markup_mode="rich",
)
console = Console()
err = Console(stderr=True)


def _guarded(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Gibt einen Schreib- oder Lesefehler der Datendateien als Meldung aus (Exit-Code 1)."""
    if getattr(fn, "_guarded", False):
        return fn

    @functools.wraps(fn)
    def guarded(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except FileAccessError as e:  # Meldung statt Traceback (kein Schreibrecht u. Ä.)
            err.print(f"[red]{escape(str(e))}[/red]")
            raise typer.Exit(1) from e

    guarded._guarded = True  # type: ignore[attr-defined]
    return guarded


def command(name: str, help: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Registriert einen Befehl unter dem deutschen und – falls vorhanden – dem englischen
    Namen; der Name der jeweils anderen Sprache bleibt in der Hilfe ausgeblendet."""
    alias = COMMAND_ALIASES.get(name)

    def register(fn: Callable[..., Any]) -> Callable[..., Any]:
        app.command(name, help=t(help), hidden=bool(alias) and is_english())(_guarded(fn))
        if alias:
            app.command(alias, help=t(help), hidden=not is_english())(_guarded(fn))
        return fn

    return register


@dataclass
class Context:
    repo: Repository
    today: date
    stichtag: str | None = None


def _ctx(ctx: typer.Context) -> Context:
    return ctx.obj


def _check_stichtag(value: str | None) -> str | None:
    if value:
        try:
            date.fromisoformat(value)
        except ValueError as e:
            raise typer.BadParameter(t("Datum im Format JJJJ-MM-TT erwartet")) from e
    return value


@app.callback(invoke_without_command=True)
def _main(
    ctx: typer.Context,
    daten: Annotated[
        Path | None,
        typer.Option(
            "--daten",
            "--data",
            "-d",
            envvar=DATA_ENV,
            help=t(
                "Verzeichnis mit den Team-Daten (je Team ein Unterordner). "
                "Standard: aktuelles Verzeichnis."
            ),
        ),
    ] = None,
    stichtag: Annotated[
        str | None,
        typer.Option(
            "--stichtag",
            "--as-of",
            callback=_check_stichtag,
            help=t("Datum (JJJJ-MM-TT), das als „heute“ gilt – für Rückblicke und Tests."),
        ),
    ] = None,
    version: Annotated[bool, typer.Option("--version", help=t("Version anzeigen."))] = False,
) -> None:
    if version:
        console.print(__version__)
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()
    if ctx.invoked_subcommand not in {"aktualisieren", "update"}:
        _auto_update()
    today = date.fromisoformat(stichtag) if stichtag else date.today()
    ctx.obj = Context(repo=Repository(daten or default_data_dir()), today=today, stichtag=stichtag)


def _auto_update() -> None:
    """Hinweise zur letzten Aktualisierung; Prüfung im Hintergrund, Installation am Ende."""
    import atexit

    for message in updater.startup_notices():
        err.print(f"[cyan]{message}[/cyan]")
    auto = updater.AutoUpdate().start()
    atexit.register(auto.finish, lambda text: err.print(f"[cyan]{text}[/cyan]"))


def _load(c: Context, team: str) -> TeamData:
    try:
        return c.repo.load(team)
    except DataError as e:
        err.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e


def cmd(text: str) -> str:
    """Befehl in der Schreibweise der eingestellten Sprache."""
    return command_text(text)


# --- Eingabe-Helfer -------------------------------------------------------------------


def _explain(key: str) -> None:
    f = FIELDS[key]
    console.print(
        Panel(
            f"{t(f.what)}\n[dim]{t('Quelle')}: {t(f.source)}\n"
            f"{t('Beispiel')}: {t(f.example)}[/dim]",
            title=t(f.title),
            title_align="left",
            border_style="cyan",
        )
    )


def _ask_number(
    label: str, default: float | None, *, allow_empty: bool = True, minimum: float = 0.0
) -> float | None:
    hint = t("leer = keine Angabe") if allow_empty else ""
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
            console.print(f"[red]{t('Bitte einen Wert eingeben.')}[/red]")
            continue
        try:
            value = float(raw.replace(",", "."))
        except ValueError:
            console.print(
                f"[red]{t('Bitte eine Zahl eingeben (Dezimaltrennzeichen , oder .).')}[/red]"
            )
            continue
        if value < minimum:
            console.print(
                f"[red]{t('Der Wert muss ≥ {value} sein.', value=fmt_plain(minimum))}[/red]"
            )
            continue
        return value


def _ask_numbers(label: str, default: list[float]) -> list[float]:
    shown = " ".join(fmt_plain(v) for v in default)
    while True:
        raw = Prompt.ask(label, default=shown, show_default=bool(shown), console=console).strip()
        try:
            return [float(x.replace(",", ".")) for x in raw.split()] if raw else []
        except ValueError:
            console.print(f"[red]{t('Bitte Zahlen mit Leerzeichen getrennt eingeben.')}[/red]")


def _ask_date(label: str, default: date | None) -> date:
    while True:
        raw = Prompt.ask(
            f"{label} [dim]({t('JJJJ-MM-TT')})[/dim]",
            default=default.isoformat() if default else "",
            show_default=default is not None,
            console=console,
        ).strip()
        try:
            return date.fromisoformat(raw)
        except ValueError:
            console.print(f"[red]{t('Datum bitte im Format JJJJ-MM-TT eingeben.')}[/red]")


def fmt_plain(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _find_or_create(data: TeamData, fc: Forecast, sprint_id: str | None, purpose: str) -> Sprint:
    """Liefert den Sprint aus der Ablage oder erzeugt ihn aus dem Kalender."""
    if sprint_id is None:
        entry = fc.default_entry(purpose)
        if entry is None:
            err.print(
                f"[red]{t('Kein passender Sprint gefunden – bitte Sprint-ID angeben.')}[/red]"
            )
            raise typer.Exit(1)
        sprint_id = entry.sprint.id
    sprint = find_sprint(data, sprint_id)
    if sprint is None:
        err.print(
            f"[red]{t('Sprint {id} liegt nicht in der Sprintfolge des Teams.', id=sprint_id)}[/red]"
        )
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
            f"{t('Kapazität')}: {capacity_label(e)} PT\n"
            f"{t('n. Velocity-Trend')}: {fmt(r.normalized_velocity.trend, 2)}\n"
            f"[bold]Forecast PLAN: {fmt(r.plan)} {unit}[/bold]  "
            f"(Roadmap {fmt(r.roadmap, 2)} · {t('Kleinkram')} {fmt(r.small_stuff, 2)})",
            title=t("Prognose Sprint {id}", id=sprint_id),
            title_align="left",
            border_style="green",
        )
    )


def _capacity_table(data: TeamData, s: Sprint) -> Table:
    breakdown = sprint_capacity(data.team, data.people, s)
    table = Table(
        title=t(
            "Kapazität Sprint {id} ({start} – {end})",
            id=s.id,
            start=f"{s.start:%d.%m.}",
            end=f"{s.end:%d.%m.%Y}",
        )
    )
    for i, col in enumerate(("Person", "Arbeitstage", "Feiertage", "Fehltage", "PT")):
        table.add_column(t(col), justify="left" if i == 0 else "right")
    digits = breakdown.rounding  # alle PT-Zahlen wie die Summe: kaufmännisch gerundet
    for pc in breakdown.people:
        table.add_row(
            pc.person.name,
            str(pc.workdays),
            str(pc.holidays),
            fmt_plain(pc.absence_days),
            fmt_capacity(pc.capacity, digits),
        )
    if breakdown.overhead_days_part:
        days = fmt_plain(data.team.capacity.overhead_days)
        table.add_row(
            t("Abzug Scrum-Termine ({days} PT je Person × FTE)", days=days),
            "", "", "", f"−{fmt_capacity(breakdown.overhead_days_part, digits)}",
        )  # fmt: skip
    if breakdown.overhead_share_part:
        table.add_row(
            t("Abzug Scrum-Termine ({share})", share=pct(data.team.capacity.overhead_share)),
            "", "", "", f"−{fmt_capacity(breakdown.overhead_share_part, digits)}",
        )  # fmt: skip
    if breakdown.approximated:
        from sprintforecast.formulas import fte_change_note

        table.caption = fte_change_note([p.person.name for p in breakdown.approximated])
    table.add_row(
        f"[bold]{t('Summe')}[/bold]",
        "", "", "",
        f"[bold]{fmt_capacity(breakdown.capacity, digits)}[/bold]",
    )  # fmt: skip
    return table


def _maybe_commit(
    c: Context, team: str, paths: list[Path], message: str, tag: str | None, do_commit: bool
) -> None:
    """Zeigt Prüfergebnisse zu den geänderten Dateien und committet, falls gewünscht."""
    issues = issues_for(_load(c, team), c.today, [p.name for p in paths])
    for i in issues:
        colour = "red" if i.level is Level.ERROR else "yellow"
        console.print(f"[{colour}]{i.level.label}[/{colour}] {i.where}: {i.message}")
    has_errors = any(i.level is Level.ERROR for i in issues)
    if not do_commit:
        console.print(
            f"[dim]{t('Tipp: mit --commit wird die Änderung direkt in Git übernommen.')}[/dim]"
        )
        return
    if has_errors:
        err.print(f"[red]{t('Nicht committet – bitte zuerst die Fehler beheben.')}[/red]")
        raise typer.Exit(1)
    try:
        rev = commit(paths, message, tag)
    except GitError as e:
        err.print(f"[red]Git: {e}[/red]")
        raise typer.Exit(1) from e
    suffix = t(", Tag {tag}", tag=tag) if tag else ""
    console.print(f"[green]{t('Committet ({rev}){suffix}.', rev=rev, suffix=suffix)}[/green]")


def _saved(path: Path) -> None:
    console.print(f"[green]{t('Gespeichert: {path}', path=path)}[/green]")


TeamArg = Annotated[str, typer.Argument(help=t("Team-Kürzel = Verzeichnisname, z. B. team-a."))]
SprintArg = Annotated[str | None, typer.Argument(help=t("Sprint-ID, z. B. 2026.21."))]
CommitOpt = Annotated[bool, typer.Option("--commit", help=t("Änderung in Git committen."))]


# --- Befehle --------------------------------------------------------------------------


def _topic_names() -> list[str]:
    """Themen in der Schreibweise der eingestellten Sprache."""
    english = {de: en for en, de in TOPIC_ALIASES.items()}
    return [english.get(k, k) if is_english() else k for k in TOPICS]


@command("hilfe", "Anleitung, Begriffe, Eingabefelder, Einstellungen und Befehle.")
def hilfe(
    thema: Annotated[
        str | None,
        typer.Argument(help=t("Thema: {topics}", topics=", ".join(_topic_names()))),
    ] = None,
) -> None:
    topic = TOPIC_ALIASES.get(thema or "", thema) if thema else "ablauf"
    if topic not in TOPICS:
        err.print(
            f"[red]{t('Unbekanntes Thema. Verfügbar: {topics}', topics=', '.join(_topic_names()))}"
            "[/red]"
        )
        raise typer.Exit(1)
    console.print(_help_table(topic))
    if topic == "begriffe":
        console.print(_two_columns(t("Kapazitätsquelle im Forecast"), CAPACITY_SOURCES))
    others = ", ".join(n for k, n in zip(TOPICS, _topic_names(), strict=True) if k != topic)
    console.print(
        f"[dim]{t('Weitere Themen: {others} (sprintforecast hilfe THEMA)', others=others)}[/dim]"
    )


def _two_columns(title: str, rows: list[tuple[str, str]]) -> Table:
    table = Table(title=title, show_header=False, box=None, padding=(0, 2), title_justify="left")
    table.add_column(style="bold", no_wrap=True)
    table.add_column()
    for left, right in rows:
        table.add_row(escape(t(left)), escape(t(right)))
    return table


def _help_table(topic: str) -> Table:
    title = t(TOPICS[topic])
    if topic == "ablauf":
        table = Table(title=title, title_justify="left", show_lines=True)
        for col in ("Wann", "Was", "Befehl"):
            table.add_column(t(col))
        for step in WORKFLOW:
            table.add_row(
                t(step.when), f"[bold]{t(step.title)}[/bold]\n{t(step.text)}", escape(cmd(step.cli))
            )
        table.caption = t("Alles geht auch im Browser: sprintforecast web")
        return table
    if topic == "begriffe":
        return _two_columns(title, TERMS)
    if topic == "felder":
        table = Table(title=title, title_justify="left", show_lines=True)
        for col in ("Feld", "Bedeutung", "Quelle", "Beispiel"):
            table.add_column(t(col))
        for f in FIELDS.values():
            table.add_row(f"[bold]{t(f.title)}[/bold]", t(f.what), t(f.source), t(f.example))
        return table
    if topic == "team":
        table = Table(title=title, title_justify="left", show_lines=True)
        for col in ("Einstellung", "Schlüssel in team.yaml", "Bedeutung"):
            table.add_column(t(col))
        for setting in SETTINGS:
            table.add_row(f"[bold]{setting.title}[/bold]", setting.key, setting.text)
        table.caption = cmd(t("Geführt ändern: sprintforecast einstellungen TEAM"))
        return table
    table = Table(title=title, show_header=False, box=None, padding=(0, 2), title_justify="left")
    table.add_column(style="bold", no_wrap=True)
    table.add_column()
    for left, right in COMMANDS:
        table.add_row(escape(cmd(left)), escape(t(right)))
    return table


def _ask_setting(setting: Setting, team: Team, *, required: bool = False) -> None:
    console.print(f"[dim]{setting.text}[/dim]")
    label = setting.title
    if (options := setting.options) and len(options) <= 25:
        listed = ", ".join(f"{k} = {v}" for k, v in options.items())
        console.print(f"[dim]{t('Möglich: {options}', options=listed)}[/dim]")
    if setting.optional and not required:
        label += f" [dim]({t('leer = keine Angabe')})[/dim]"
    current = setting.display(team)
    while True:
        raw = Prompt.ask(label, default=current, show_default=bool(current), console=console)
        try:
            value = setting.parse(raw)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            continue
        if value is None and required:
            console.print(f"[red]{t('Bitte einen Wert eingeben.')}[/red]")
            continue
        setting.set(team, value)
        return


@command("init", "Neues Team geführt anlegen.")
def init(ctx: typer.Context, team: TeamArg, commit_: CommitOpt = False) -> None:
    c = _ctx(ctx)
    if c.repo.exists(team):
        err.print(f"[red]{t('Team {team} existiert bereits.', team=repr(team))}[/red]")
        raise typer.Exit(1)
    console.print(
        Panel(
            t(
                "Neues Team [bold]{team}[/bold] anlegen. Alle Werte sind später mit "
                "[bold]{command}[/bold] änderbar.\nOptional sind die Bereiche Produktverteilung "
                "(mehrere Produkte), Zuordnung PO und Produktionszugriff; sie sind zunächst "
                "aus (Enter übernimmt „aus“).",
                team=team,
                command=cmd(f"sprintforecast einstellungen {team}"),
            )
        )
    )
    new = Team(key=team, name=team.upper())
    for setting in applicable(has_sprints=False):
        if setting.key == "sprint.first_id":
            year = new.sprint.first_start.year if new.sprint.first_start else date.today().year
            new.sprint.first_id = f"{year}.1" if new.sprint.numbering is Numbering.YEARLY else "1"
        _ask_setting(setting, new, required=setting.only_without_sprints)
    path = c.repo.save_team(new)
    people = c.repo.save_people(team, [])
    console.print(f"[green]{t('Angelegt: {path}', path=path)}[/green]")
    _maybe_commit(c, team, [path, people], t("{team}: Team angelegt", team=new.name), None, commit_)
    console.print(
        t("Weiter mit: [bold]{command}[/bold]", command=cmd(f"sprintforecast personen {team}"))
    )


@command(
    "einstellungen", "Team-Einstellungen geführt ändern (Einheit, Bundesland, Referenzkapazität …)."
)
def einstellungen(ctx: typer.Context, team: TeamArg, commit_: CommitOpt = False) -> None:
    c = _ctx(ctx)
    data = _load(c, team)
    before = copy.deepcopy(data.team)
    current = data.team
    console.print(
        Panel(
            t(
                "Einstellungen [bold]{team}[/bold] – Enter übernimmt den aktuellen Wert.",
                team=current.name,
            ),
            border_style="cyan",
        )
    )
    for setting in applicable(has_sprints=bool(data.sprints)):
        _ask_setting(setting, current)
    diff = changes(before, current)
    if not diff:
        console.print(t("Keine Änderungen."))
        return
    table = Table(title=t("Änderungen"))
    for col in ("Einstellung", "bisher", "neu"):
        table.add_column(t(col))
    for setting, old, new in diff:
        table.add_row(setting.title, old or "–", new or "–")
    console.print(table)
    if any(setting.retroactive for setting, _, _ in diff):
        console.print(
            "[yellow]"
            + t(
                "Hinweis: Mindestens eine Änderung wirkt rückwirkend auf alle berechneten Werte "
                "(Ø, Trend, Forecast PLAN)."
            )
            + "[/yellow]"
        )
    if not Confirm.ask(t("Speichern?"), default=True, console=console):
        raise typer.Exit()
    path = c.repo.save_team(current)
    _saved(path)
    _maybe_commit(
        c, team, [path], t("{team}: Einstellungen geändert", team=current.name), None, commit_
    )


def _people_table(people: list[Person], day: date, show_former: bool) -> Table:
    table = Table(title=t("Personen (Stand {day})", day=f"{day:%d.%m.%Y}"))
    for col in ("Name", "Bundesland", "FTE heute", "Zeiträume im Team"):
        table.add_column(t(col))
    shown = [p for p in people if show_former or p.is_current(day)]
    if hidden := len(people) - len(shown):
        table.caption = cmd(
            t(
                "{count} ehemalige Person(en) ausgeblendet – anzeigen mit --ehemalige",
                count=hidden,
            )
        )
    for p in shown:
        spans = ", ".join(
            f"{m.start:%d.%m.%Y}–{m.end:%d.%m.%Y}"
            if m.end
            else t("ab {day}", day=f"{m.start:%d.%m.%Y}")
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
    console.print(f"[dim]{t('Personen')}: " + ", ".join(labels) + "[/dim]")
    while True:
        raw = Prompt.ask(t("Name"), console=console).strip().lower()
        if raw in by_label:
            return by_label[raw]
        matches = [p for label, p in by_label.items() if label.startswith(raw)] if raw else []
        if len(matches) == 1:
            return matches[0]
        console.print(
            f"[red]{t('Name nicht eindeutig gefunden – bitte wie oben angezeigt eingeben.')}[/red]"
        )


@command("personen", "Personenliste anzeigen und pflegen (Eintritt, FTE-Änderung, Austritt).")
def personen(
    ctx: typer.Context,
    team: TeamArg,
    commit_: CommitOpt = False,
    ehemalige: Annotated[
        bool,
        typer.Option("--ehemalige", "--former", help=t("Ausgeschiedene Personen anzeigen.")),
    ] = False,
) -> None:
    c = _ctx(ctx)
    data = _load(c, team)
    people = data.people
    changed = False
    while True:
        console.print(_people_table(people, c.today, ehemalige))
        action = Prompt.ask(
            t("Aktion: n = neue Person, f = FTE ändern, a = Austritt, q = fertig"),
            choices=["n", "f", "a", "q"],
            default="q",
            console=console,
        )
        if action == "q":
            break
        if action == "n":
            name = Prompt.ask(t("Name"), console=console).strip()
            if not name:
                console.print(f"[red]{t('Bitte einen Namen eingeben.')}[/red]")
                continue
            if any(p.name.lower() == name.lower() for p in people):
                console.print(
                    f"[red]{t('Diese Person gibt es schon – für eine FTE-Änderung „f“ wählen.')}"
                    "[/red]"
                )
                continue
            pid = new_person_id(name, {p.id for p in people})
            region = (
                Prompt.ask(
                    t("Bundesland, falls abweichend vom Team (leer = Team-Einstellung)"),
                    default="",
                    show_default=False,
                    console=console,
                )
                .strip()
                .upper()
                or None
            )
            start = _ask_date(t("Im Team ab"), c.today)
            fte = _ask_number(
                t("FTE-Anteil im Team (1 = Vollzeit, 0.5 = halbe Stelle)"), 1, allow_empty=False
            )
            people.append(Person(pid, name, region, [Membership(start=start, fte=fte or 1.0)]))
        else:
            candidates = [p for p in people if p.is_current(c.today)]
            if not candidates:
                console.print(f"[red]{t('Keine aktiven Personen.')}[/red]")
                continue
            person = _choose_person(candidates)
            active = next((m for m in person.memberships if m.end is None), None)
            if active is None:
                console.print(f"[red]{t('Keine offene Zugehörigkeit.')}[/red]")
                continue
            when = _ask_date(t("Gültig ab") if action == "f" else t("Letzter Tag im Team"), c.today)
            if when <= active.start:
                console.print(
                    f"[red]{t('Datum muss nach Beginn der aktuellen Zugehörigkeit liegen.')}[/red]"
                )
                continue
            if action == "f":
                fte = _ask_number(t("Neuer FTE-Anteil"), active.fte, allow_empty=False)
                active.end = when - timedelta(days=1)
                person.memberships.append(Membership(start=when, fte=fte or active.fte))
            else:
                active.end = when
        changed = True
    if changed:
        path = c.repo.save_people(team, people)
        _saved(path)
        _maybe_commit(
            c,
            team,
            [path],
            t("{team}: Personenliste aktualisiert", team=data.team.name),
            None,
            commit_,
        )


@command(
    "fehltage", "Planbare Fehltage je Person für einen Sprint erfassen (Standard: nächster Sprint)."
)
def fehltage(
    ctx: typer.Context, team: TeamArg, sprint: SprintArg = None, commit_: CommitOpt = False
) -> None:
    c = _ctx(ctx)
    data = _load(c, team)
    if not data.people:
        err.print(
            "[red]"
            + t(
                "Keine Personen erfasst. Zuerst: {command}",
                command=cmd(f"sprintforecast personen {team}"),
            )
            + "[/red]"
        )
        raise typer.Exit(1)
    fc = build_forecast(data, c.today)
    s = _find_or_create(data, fc, sprint, "next")
    path = _ask_absences(c, data, s)
    console.print(_capacity_table(data, s))
    _saved(path)
    _show_sprint_forecast(c, team, s.id)
    _maybe_commit(
        c,
        team,
        [path],
        t("{team} {id}: Fehltage erfasst", team=data.team.name, id=s.id),
        None,
        commit_,
    )


def _sprint_panel(data: TeamData, s: Sprint) -> Panel:
    days = team_workdays(data.team, s.start, s.end)
    region, country = data.team.capacity.region, data.team.capacity.country
    hol = [
        f"{d:%d.%m.} {holiday_name(d, region, country)}"
        for d in days
        if holiday_name(d, region, country)
    ]
    last = days[-1] if days else s.end
    text = t(
        "Sprint [bold]{id}[/bold]: {start} – {last} (letzter Arbeitstag; der nächste Sprint "
        "beginnt am {next}), {days} Arbeitstage ({week})",
        id=s.id,
        start=f"{s.start:%d.%m.%Y}",
        last=f"{last:%d.%m.%Y}",
        next=f"{s.end:%d.%m.}",
        days=len(days),
        week=workweek_label(data.team),
    )
    if hol:
        text += "\n" + t(
            "davon Feiertage ({region}): {holidays}",
            region=region or t("bundesweit"),
            holidays=", ".join(hol),
        )
    return Panel(text, border_style="cyan")


def _ask_absences(c: Context, data: TeamData, s: Sprint) -> Path:
    """Fragt die Fehltage je aktiver Person ab und speichert den Sprint."""
    days = team_workdays(data.team, s.start, s.end)
    console.print(_sprint_panel(data, s))
    _explain("absences")
    for p in data.people:
        if not p.active_between(s.start, s.end):
            continue
        value = _ask_number(f"{p.name}", s.absences.get(p.id, 0.0), allow_empty=False)
        if value:
            s.absences[p.id] = min(value, len(days))
        else:
            s.absences.pop(p.id, None)
    s.absence_state = AbsenceState.CONFIRMED  # alle Personen wurden gefragt, auch „0“
    if s.capacity is not None and Confirm.ask(
        t(
            "Für den Sprint ist eine feste Kapazität ({capacity}) eingetragen. Entfernen, damit "
            "sie aus den Fehltagen berechnet wird?",
            capacity=fmt_capacity(s.capacity, data.team.capacity.rounding),
        ),
        default=s.end > c.today,
        console=console,
    ):
        s.capacity = None
    return c.repo.save_sprint(data.team.key, s)


def _require_products(data: TeamData, team: str) -> None:
    """Beendet den Befehl, wenn das Team die Produktverteilung nicht nutzt."""
    if not data.team.features.products:
        err.print(
            "[yellow]"
            + t(
                "Die Produktverteilung ist für dieses Team ausgeschaltet. Einschalten mit: "
                "{command}",
                command=cmd(f"sprintforecast einstellungen {team}"),
            )
            + "[/yellow]"
        )
        raise typer.Exit(1)


def _ask_product_values(data: TeamData, fc: Forecast, s: Sprint, measure: str) -> bool:
    """Fragt einen Wert (preplanned/planned/done) je Produkt ab. True, wenn etwas geändert."""
    entry = fc.entry(s.id)
    if not data.products or entry is None:
        return False
    d = distribution(fc, entry)
    if not d.rows:
        return False
    unit = data.team.unit.value
    console.print(_distribution_table(d, unit))
    _explain(measure)
    before = copy.deepcopy(s.products)
    for r in d.rows:
        values = s.products.get(r.product.id, ProductValues())
        setattr(
            values,
            measure,
            _ask_number(
                f"{r.product.name} – {measure_label(measure)} ({unit})", getattr(values, measure)
            ),
        )
        if values.is_empty():
            s.products.pop(r.product.id, None)
        else:
            s.products[r.product.id] = values
    return s.products != before


def _distribution_table(d: Distribution, unit: str) -> Table:
    basis = t("Roadmap-Anteil") if d.basis.value == "roadmap" else "Forecast PLAN"
    table = Table(title=t("Produkte Sprint {id}", id=d.sprint.id))
    table.add_column(t("Produkt"))
    if d.features.po:
        table.add_column("PO")
    for m in MEASURES:
        table.add_column(f"{measure_label(m)} {unit}", justify="right")
    for r in d.rows:
        table.add_row(
            r.product.name + ("" if r.active else f" [dim]({t('nicht betreut')})[/dim]"),
            *((r.product.po or "",) if d.features.po else ()),
            *(fmt(r.value(m), 2) for m in MEASURES),
        )
    table.add_row(
        f"[bold]{t('Summe')}[/bold]",
        *(("",) if d.features.po else ()),
        *(fmt(d.total(m), 2) for m in MEASURES),
    )
    if d.available is not None and d.active_count:
        table.caption = t(
            "Standard = {basis}{frozen} {available} / {count} Produkte",
            basis=basis,
            frozen=f" ({t('eingefroren')})" if d.plan_frozen else "",
            available=fmt(d.available, 2),
            count=d.active_count,
        )
    return table


@command(
    "planning",
    "Sprint Planning geführt: 1. Fehltage, 2. Forecast PLAN und Einplanung je Produkt, "
    "3. Commitment (Standard: nächstes Planning).",
)
def planning(
    ctx: typer.Context, team: TeamArg, sprint: SprintArg = None, commit_: CommitOpt = False
) -> None:
    c = _ctx(ctx)
    data = _load(c, team)
    fc = build_forecast(data, c.today)
    s = _find_or_create(data, fc, sprint, "planning")
    paths: list[Path] = []
    console.rule(t("Planning {id} – Schritt 1: Fehltage", id=s.id))
    if data.people and Confirm.ask(
        t("Bekannte Fehltage für den Sprint erfassen bzw. prüfen?"),
        default=data.sprint(s.id) is None,
        console=console,
    ):
        paths.append(_ask_absences(c, data, s))
        console.print(_capacity_table(data, s))
    elif data.sprint(s.id) is None:
        hint = t(
            "Ohne bestätigte Fehltage ist die Kapazität nur geschätzt (Kalender und Historie)."
        )
        console.print(f"[yellow]{hint}[/yellow]")
    data = _load(c, team) if paths else data
    fc = build_forecast(data, c.today)
    s = copy.deepcopy(data.sprint(s.id) or s)
    console.rule(t("Planning {id} – Schritt 2: Forecast PLAN und Einplanung", id=s.id))
    if data.sprint(s.id):
        _show_sprint_forecast(c, team, s.id)
    if (
        data.team.features.products
        and data.products
        and Confirm.ask(t("Planning je Produkt erfassen?"), default=True, console=console)
    ):
        _ask_product_values(data, fc, s, "planned")
    console.rule(t("Planning {id} – Schritt 3: Commitment", id=s.id))
    unit = data.team.unit.value
    plan_values = None
    if Confirm.ask(
        t(
            "Kontrollrechnung (Überkipper, Backlog, Korrekturen) erfassen? Optional – wirkt nur "
            "auf das Planning-Delta"
        ),
        default=s.planning is not None,
        console=console,
    ):
        p = s.planning or Planning()
        _explain("carryover")
        carryover = (
            _ask_number(t("Überkipper ({unit})", unit=unit), p.carryover, allow_empty=False) or 0.0
        )
        _explain("backlog")
        backlog = _ask_number(f"Backlog ({unit})", p.backlog, allow_empty=False) or 0.0
        _explain("corrections")
        corrections = _ask_numbers(t("Korrekturen ({unit})", unit=unit), p.corrections)
        plan_values = Planning(carryover=carryover, backlog=backlog, corrections=corrections)
    _explain("forecast_ist")
    default = s.forecast_ist
    if default is None and plan_values is not None and plan_values.committed:
        default = plan_values.committed
        console.print(f"[dim]{t('Vorbelegt mit Überkipper + Backlog.')}[/dim]")
    apply_planning(s, _ask_number(t("Commitment ({unit})", unit=unit), default), plan_values)
    refreeze = False
    if offer := refreeze_offer(s, fc.entry(s.id)):
        refreeze = Confirm.ask(
            t(
                "Der eingefrorene Forecast PLAN ({frozen}) weicht vom aktuellen ({current}) ab. "
                "Neu einfrieren?",
                frozen=fmt(offer[0]),
                current=fmt(offer[1]),
            ),
            default=False,
            console=console,
        )
    freeze_plan(s, fc.entry(s.id), c.today, refreeze=refreeze)
    path = c.repo.save_sprint(team, s)
    _saved(path)
    fc = build_forecast(_load(c, team), c.today)
    if (e := fc.entry(s.id)) and e.result.planning_total is not None:
        delta = e.result.planning_delta or 0.0
        colour = "green" if delta >= 0 else "red"
        console.print(
            t(
                "Planning-Summe {total} {unit} · Forecast PLAN {plan} {unit} · "
                "[{colour}]Delta {delta} {unit}[/{colour}]",
                total=fmt(e.result.planning_total, 2),
                plan=fmt(e.result.plan),
                delta=fmt(delta, 2),
                unit=unit,
                colour=colour,
            )
        )
    _maybe_commit(
        c,
        team,
        [path],
        t("{team} {id}: Planning erfasst", team=data.team.name, id=s.id),
        None,
        commit_,
    )


@command("review", "Sprint Review erfassen: Velocity, Scope Creep; friert die Kapazität ein.")
def review(
    ctx: typer.Context,
    team: TeamArg,
    sprint: SprintArg = None,
    commit_: Annotated[
        bool, typer.Option("--commit", help=t("Committen und Tag TEAM/SPRINT setzen."))
    ] = False,
) -> None:
    c = _ctx(ctx)
    data = _load(c, team)
    fc = build_forecast(data, c.today)
    s = _find_or_create(data, fc, sprint, "review")
    unit = data.team.unit.value
    console.print(Panel(f"Review Sprint [bold]{s.id}[/bold] ({s.start:%d.%m.} – {s.end:%d.%m.%Y})"))
    if s.capacity is None:
        if data.people:
            frozen = sprint_capacity(data.team, data.people, s).rounded
            console.print(
                t(
                    "Kapazität laut Personenliste und Fehltagen: [bold]{capacity} PT[/bold]",
                    capacity=fmt_capacity(frozen, data.team.capacity.rounding),
                )
            )
            if not Confirm.ask(
                t("Stimmt das (sonst Fehltage korrigieren)?"), default=True, console=console
            ):
                frozen = _ask_number(t("Tatsächliche Kapazität (PT)"), frozen, allow_empty=False)
        else:
            _explain("capacity")
            frozen = _ask_number(t("Kapazität (PT)"), None, allow_empty=False)
        s.capacity = frozen
    _explain("velocity")
    s.velocity = _ask_number(f"Velocity ({unit})", s.velocity)
    _explain("scope_creep")
    s.scope_creep = _ask_number(t("Scope Creep (Anteil 0–1)"), s.scope_creep)
    if (
        data.team.features.products
        and data.products
        and Confirm.ask(t("Erledigt je Produkt erfassen?"), default=True, console=console)
    ):
        _ask_product_values(data, fc, s, "done")
    path = c.repo.save_sprint(team, s)
    _saved(path)
    _maybe_commit(
        c,
        team,
        [path],
        t("{team} {id}: Review erfasst", team=data.team.name, id=s.id),
        f"{team}/{s.id}",
        commit_,
    )


@command("forecast", "Prognose für den laufenden und die kommenden Sprints anzeigen.")
def forecast(
    ctx: typer.Context,
    team: TeamArg,
    verlauf: Annotated[
        int,
        typer.Option(
            "--verlauf", "--history", help=t("Anzahl vergangener Sprints in der Anzeige.")
        ),
    ] = 5,
    rechenweg: Annotated[
        str | None,
        typer.Option(
            "--rechenweg",
            "--explain",
            help=t("Rechenweg (Formeln mit Zahlen) eines Sprints zeigen; „-“ = nächstes Planning."),
        ),
    ] = None,
) -> None:
    c = _ctx(ctx)
    fc = build_forecast(_load(c, team), c.today)
    team_ = fc.data.team
    unit = team_.unit.value
    table = Table(
        title=t("Sprint-Forecast {team} (Stand {day})", team=team_.name, day=f"{c.today:%d.%m.%Y}")
    )
    columns = [
        "Sprint",
        t("Zeitraum"),
        "Status",
        t("Kapazität PT"),
        "Velocity",
        t("n. Vel. (Ø/Trend)"),
        f"Forecast PLAN {unit}",
        "Roadmap",
        t("Kleinkram"),
    ]
    for i, col in enumerate(columns):
        table.add_column(col, justify="left" if i < 3 else "right")
    for e in fc.history(verlauf) + fc.upcoming():
        r = e.result
        future = e.sprint.end > c.today
        n_vel = r.normalized_velocity.trend if future else r.normalized_velocity.average
        table.add_row(
            e.sprint.id,
            period(e),
            status(fc, e).replace("**", ""),
            capacity_label(e) if future else fmt_capacity(r.capacity.value, e.capacity_digits),
            fmt(r.velocity.value, 2),
            fmt(n_vel, 2),
            f"[bold]{fmt(r.plan)}[/bold]" if future else fmt(r.plan),
            fmt(r.roadmap, 2) if future else "",
            fmt(r.small_stuff, 2) if future else "",
            style=None if future else "dim",
        )
    console.print(table)
    if any(e.result.plan_capacity_source in UNSURE_SOURCES for e in fc.upcoming()):
        console.print(
            "[yellow]"
            + t(
                "⚠ Trend/Kalender = keine Fehltage bekannt, Kapazität geschätzt. "
                "Belastbarer mit: {command}",
                command=cmd(f"sprintforecast fehltage {team} <SPRINT>"),
            )
            + "[/yellow]"
        )
    for note in reliability_notes(fc):
        console.print(f"[yellow]⚠ {escape(note)}[/yellow]")
    if rechenweg is not None:
        from sprintforecast.formulas import steps

        default = fc.default_entry("planning")
        entry = default if rechenweg == "-" else fc.entry(rechenweg)
        if entry is None:
            err.print(f"[red]{t('Sprint {id} nicht in der Prognose.', id=rechenweg)}[/red]")
            raise typer.Exit(1)
        from sprintforecast.formulas import plain_explanation

        console.print(escape(plain_explanation(fc, entry)).replace("**", ""))
        table = Table(title=t("Rechenweg Sprint {id}", id=entry.sprint.id), show_lines=True)
        for col in ("Kennzahl", "Formel", "Rechnung"):
            table.add_column(t(col))
        for step in steps(fc, entry):
            table.add_row(
                f"[bold]{step.name}[/bold]", escape(step.formula), escape(step.calculation)
            )
        console.print(table)
    else:
        console.print(
            f"[dim]{cmd(t('Rechenweg eines Sprints: --rechenweg SPRINT (bzw. - )'))}[/dim]"
        )


@command(
    "analyse", "Ergänzende Analysen: Bandbreite, Fokusfaktor, Puffer, Fertigstellung (--rest)."
)
def analyse(
    ctx: typer.Context,
    team: TeamArg,
    rest: Annotated[
        float | None,
        typer.Option(
            "--rest",
            "--remaining",
            help=t("Restmenge, für die der Fertigstellungs-Sprint geschätzt wird."),
        ),
    ] = None,
    gesamt: Annotated[
        bool,
        typer.Option(
            "--gesamt",
            "--total",
            help=t("Für --rest den ganzen Forecast nutzen statt nur des Roadmap-Anteils."),
        ),
    ] = False,
    anteil: Annotated[
        float,
        typer.Option(
            "--anteil",
            "--share",
            min=1,
            max=100,
            help=t(
                "Projektanteil in %: welcher Teil der Roadmap- bzw. Gesamtkapazität in die "
                "Restmenge fließt (Standard 100)."
            ),
        ),
    ] = 100.0,
) -> None:
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

    table = Table(title=t("Bandbreite {team} – zusätzlich zum Forecast PLAN", team=data.team.name))
    for i, col in enumerate(
        ("Sprint", f"Forecast PLAN {unit}", t("konservativ"), t("mittel"), t("optimistisch"))
    ):
        table.add_column(col, justify="left" if i == 0 else "right")
    for e in fc.upcoming():
        b = band(fc, e)
        table.add_row(
            e.sprint.id,
            fmt(e.result.plan),
            *(fmt(v) for v in ((b.low, b.mid, b.high) if b else (None, None, None))),
        )
    console.print(table)
    console.print(
        "[dim]"
        + t(
            "konservativ/mittel/optimistisch = niedrigste/mittlere/höchste normierte Velocity der "
            "letzten {window} Sprints × Kapazität.",
            window=data.team.forecast.window,
        )
        + "[/dim]"
    )

    focus = Table(title=t("Fokusfaktor (Velocity / Kapazität)"))
    focus.add_column("Sprint")
    focus.add_column(t("Fokusfaktor"), justify="right")
    for e in fc.history(data.team.forecast.window):
        focus.add_row(e.sprint.id, fmt(focus_factor(e), 2))
    focus.add_row("[bold]Ø[/bold]", f"[bold]{fmt(average_focus_factor(fc), 2)}[/bold]")
    console.print(focus)

    hint = buffer_hint(fc)
    if hint.average_scope_creep is None:
        console.print(t("Puffer: Scope Creep wurde zuletzt nicht erfasst – keine Empfehlung."))
    else:
        colour = "yellow" if hint.buffer_too_small else "green"
        verdict = (
            t("Puffer kleiner als der ungeplante Anteil")
            if hint.buffer_too_small
            else t("passt")
            if hint.sufficient_data
            else t("zu wenige Werte für eine Empfehlung")
        )
        console.print(
            t(
                "Puffer: Ø Scope Creep {scope} des Commitments = {late} des Forecast PLAN "
                "({count} Sprints), Kleinkram-Anteil {small} – ",
                scope=pct(hint.average_scope_creep),
                late=pct(hint.average_late_share),
                count=hint.samples,
                small=pct(hint.configured_small_stuff),
            )
            + f"[{colour}]{verdict}[/{colour}]"
        )

    if rest is not None:
        basis_share = 1.0 if gesamt else data.team.forecast.roadmap_share
        share = basis_share * anteil / 100
        result = completion(data, c.today, rest, share)
        if result is None:
            err.print(f"[red]{t('Zu wenig Historie für eine Fertigstellungsprognose.')}[/red]")
            raise typer.Exit(1)
        basis = (
            t("gesamter Forecast")
            if gesamt
            else t("Roadmap-Anteil {share}", share=pct(basis_share))
        )
        if anteil < 100:
            basis += t(
                " × Projektanteil {project} % = {share} des Forecasts",
                project=fmt(anteil, 0),
                share=pct(share),
            )
        later = t(
            "später als {last} ({count} Sprints)",
            last=result.sprints[-1] if result.sprints else "–",
            count=len(result.sprints),
        )
        console.print(
            t(
                "Fertigstellung von {rest} {unit} ({basis}, ab dem nächsten Sprint): "
                "in 50 % der Simulationen bis [bold]{p50}[/bold], in 85 % bis [bold]{p85}"
                "[/bold] (modellabhängige Häufigkeit, Stichprobe {samples} Sprints; "
                "≈ {per_sprint} {unit} je Sprint).",
                rest=fmt(rest, 1),
                unit=unit,
                basis=basis,
                p50=result.p50 or later,
                p85=result.p85 or later,
                samples=result.samples,
                per_sprint=fmt(result.per_sprint, 1),
            )
        )
        if result.trend_capacity_sprints:
            listed = ", ".join(result.trend_capacity_sprints[:4])
            if len(result.trend_capacity_sprints) > 4:
                listed += " …"
            console.print(
                "[dim]"
                + t("Ohne Personenliste gerechnet mit Ø Kapazität: {sprints}", sprints=listed)
                + "[/dim]"
            )


@command("bericht", "Markdown-Bericht erzeugen (für Git-Weboberfläche / PO-Runde).")
def bericht(
    ctx: typer.Context,
    team: Annotated[str | None, typer.Argument(help=t("Team; ohne Angabe für alle Teams."))] = None,
    ausgabe: Annotated[
        Path | None,
        typer.Option(
            "--ausgabe",
            "--output",
            "-o",
            help=t("Datei; Standard <team>/FORECAST.md, - = stdout."),
        ),
    ] = None,
) -> None:
    c = _ctx(ctx)
    teams = [team] if team else c.repo.teams()
    for key in teams:
        text = render(build_forecast(_load(c, key), c.today))
        if ausgabe is not None and str(ausgabe) == "-":
            sys.stdout.write(text)
            continue
        target = ausgabe if ausgabe is not None and team else c.repo.team_dir(key) / "FORECAST.md"
        write_text(target, text)
        console.print(f"[green]{target}[/green]")


@command(
    "pruefen", "Alle Team-Daten auf Fehler und Plausibilität prüfen (für CI und vor dem Commit)."
)
def pruefen(
    ctx: typer.Context,
    streng: Annotated[
        bool,
        typer.Option("--streng", "--strict", help=t("Hinweise ebenfalls als Fehler werten.")),
    ] = False,
) -> None:
    c = _ctx(ctx)
    results = check_all(c.repo, c.today)
    if not results:
        err.print(f"[red]{t('Keine Teams gefunden unter {root}', root=c.repo.root)}[/red]")
        raise typer.Exit(1)
    failed = False
    for key, issues in results.items():
        if not issues:
            console.print(f"[green]✔ {key}[/green]")
            continue
        console.print(f"[bold]{key}[/bold]")
        for i in issues:
            colour = "red" if i.level is Level.ERROR else "yellow"
            console.print(f"  [{colour}]{i.level.label}[/{colour}] {i.where}: {i.message}")
            failed |= i.level is Level.ERROR or streng
    raise typer.Exit(1 if failed else 0)


@command("web", "Weboberfläche lokal starten (nur auf diesem Rechner erreichbar).")
def web(
    ctx: typer.Context,
    port: Annotated[
        int, typer.Option(help=t("Port; ist er belegt, wird ein freier gewählt."))
    ] = 8501,
    browser: Annotated[
        bool,
        typer.Option(
            help=t("Browser automatisch öffnen; --no-browser öffnet nirgends ein Fenster.")
        ),
    ] = True,
    app_mode: Annotated[
        bool,
        typer.Option(
            "--app/--no-app",
            help=t(
                "Als App in eigenem Fenster öffnen (Edge, Chrome, Comet, Chromium, Brave, "
                "Vivaldi; sonst Firefox oder Standardbrowser). Fenster schließen beendet den "
                "Server. Mit --no-app öffnet sich stattdessen ein Browser-Tab."
            ),
        ),
    ] = True,
    browser_path: Annotated[
        str | None,
        typer.Option(
            "--browser",
            envvar=BROWSER_ENV,
            help=t("Browser für --app fest vorgeben (Programmname oder Pfad)."),
        ),
    ] = None,
) -> None:
    import importlib.util

    if importlib.util.find_spec("streamlit") is None:
        err.print(
            "[red]"
            + t(
                "Für die Weboberfläche wird Streamlit benötigt: "
                'uv tool install "sprintforecast[web] @ git+…" bzw. uv sync --extra web'
            )
            + "[/red]"
        )
        raise typer.Exit(1)
    c = _ctx(ctx)
    app_mode = app_mode and browser  # --no-browser: kein Fenster, kein Selbst-Beenden
    env = os.environ | {DATA_ENV: str(c.repo.root.resolve())} | updater.web_environment(sys.argv)
    if c.stichtag:
        env[STICHTAG_ENV] = c.stichtag
    if app_mode:
        env[IDLE_ENV] = str(_IDLE_EXIT_SECONDS)  # Server beendet sich selbst ohne Sitzung
    actual_port = free_port(port)
    if actual_port != port:
        console.print(
            "[yellow]"
            + t("Port {port} ist belegt – verwende {actual}.", port=port, actual=actual_port)
            + "[/yellow]"
        )
    url = f"http://localhost:{actual_port}"
    app_file = Path(__file__).parent / "web" / "app.py"
    cmd_line = [
        sys.executable, "-m", "streamlit", "run", str(app_file),
        "--server.address", "localhost",
        "--server.port", str(actual_port),
        "--server.headless", "false" if browser and not app_mode else "true",
        "--browser.gatherUsageStats", "false",
        "--client.toolbarMode", "minimal",
    ]  # fmt: skip
    console.print(t("Weboberfläche: [bold]{url}[/bold] (Beenden mit Strg+C)", url=url))
    popen: dict = popen_options()
    if log := os.environ.get(LOG_ENV):
        # Doppelklick-Start: kein Konsolenfenster, Ausgaben des Servers ins Protokoll
        popen["stdout"] = popen["stderr"] = open(log, "a", encoding="utf-8")  # noqa: SIM115
        if sys.platform == "win32":
            popen["creationflags"] = subprocess.CREATE_NO_WINDOW
    server = subprocess.Popen(cmd_line, env=env, **popen)
    adopt(server)  # alles, was der Server später startet, endet mit ihm
    try:
        if app_mode:
            _open_app_window(url, server, browser_path)
        server.wait()
    except KeyboardInterrupt:
        pass
    finally:
        terminate_tree(server)


# Endet der Browserprozess schneller, hat er vermutlich an eine laufende Instanz übergeben –
# dann darf der Server nicht beendet werden.
_HANDOFF_SECONDS = 5.0
# So lange darf nach dem Besuch eines Browsers keine Sitzung mehr verbunden sein (idle.py).
_IDLE_EXIT_SECONDS = 20


def _open_app_window(url: str, server: subprocess.Popen, explicit: str | None) -> None:
    """Öffnet das App-Fenster; kehrt zurück, wenn der Server weiterlaufen soll."""
    if not wait_until_ready(url, server):
        err.print(f"[red]{t('Die Weboberfläche ist nicht gestartet – siehe Ausgabe oben.')}[/red]")
        raise typer.Exit(1)
    try:
        found = find_browser(explicit)
    except FileNotFoundError as e:
        console.print(f"[yellow]{t('{error} – suche automatisch.', error=e)}[/yellow]")
        os.environ.pop(BROWSER_ENV, None)  # sonst läse find_browser die ungültige Vorgabe erneut
        found = find_browser(None)
    match found.kind:
        case BrowserKind.APP:
            console.print(t("Öffne {browser} als App-Fenster …", browser=found.name))
            started = time.monotonic()
            window = subprocess.Popen(browser_command(found, url))
            adopt(window)
            while window.poll() is None:
                if server.poll() is not None:
                    # Server beendet (z. B. Neustart für eine Aktualisierung) → Fenster zu
                    window.terminate()
                    return
                time.sleep(0.5)
            if time.monotonic() - started >= _HANDOFF_SECONDS:
                console.print(t("App-Fenster geschlossen – beende die Weboberfläche."))
                raise KeyboardInterrupt
            console.print(
                "[yellow]"
                + t(
                    "Der Browser lief bereits und hat das Fenster übernommen – die Weboberfläche "
                    "läuft weiter, beenden mit Strg+C."
                )
                + "[/yellow]"
            )
        case BrowserKind.WINDOW:
            console.print(
                t(
                    "Kein App-fähiger Browser gefunden – öffne {browser} (neues Fenster).",
                    browser=found.name,
                )
            )
            subprocess.Popen(browser_command(found, url))
        case BrowserKind.DEFAULT:
            console.print(t("Kein App-fähiger Browser gefunden – öffne den Standardbrowser."))
            webbrowser.open(url)
        case BrowserKind.NONE:
            console.print(
                "[yellow]"
                + t("Kein Browser gefunden. Bitte {url} in einem Browser öffnen.", url=url)
                + "[/yellow]"
            )


@command("sprints", "Sprintkalender: kommende Sprints anzeigen, anlegen und Enddaten anpassen.")
def sprints(
    ctx: typer.Context,
    team: TeamArg,
    anzahl: Annotated[
        int,
        typer.Option("--anzahl", "--count", help=t("Anzahl Sprints ab dem laufenden.")),
    ] = 6,
    anlegen: Annotated[
        bool,
        typer.Option("--anlegen", "--create", help=t("Fehlende Sprintdateien anlegen.")),
    ] = False,
    ende: Annotated[
        list[str] | None,
        typer.Option(
            "--ende",
            "--end",
            help=t(
                "Abweichender letzter Tag, z. B. --ende 2026.25=2027-01-12 (mehrfach möglich); "
                "folgende Sprints verschieben sich."
            ),
        ),
    ] = None,
    commit_: CommitOpt = False,
) -> None:
    from sprintforecast.web.logic import (
        absence_sprints,
        apply_calendar,
        calendar_table,
        calendar_to_save,
        with_sprints,
    )

    c = _ctx(ctx)
    data = _load(c, team)
    fc = build_forecast(data, c.today)
    planned = absence_sprints(data, fc, anzahl)
    rows = calendar_table(data, planned, c.today)
    for raw in ende or []:
        sid, _, day = raw.partition("=")
        row = next((r for r in rows if r["Sprint"] == sid.strip()), None)
        try:
            last = date.fromisoformat(day.strip())
        except ValueError:
            last = None
        if row is None or last is None:
            err.print(
                "[red]"
                + t(
                    "--ende {value}: erwartet SPRINT=JJJJ-MM-TT eines gezeigten Sprints",
                    value=raw,
                )
                + "[/red]"
            )
            raise typer.Exit(1)
        row["Letzter Tag"] = last
    after, errors = apply_calendar(data, planned, rows)
    for e in errors:
        err.print(f"[red]{e}[/red]")
    if errors:
        raise typer.Exit(1)
    shown = calendar_table(data, after, c.today)
    table = Table(title=t("Sprintkalender {team}", team=data.team.name))
    for col in shown[0]:
        table.add_column(t(col), justify="right" if col == "Arbeitstage" else "left")
    for r in shown:
        table.add_row(
            r["Sprint"],
            day_label(r["Start"]),
            day_label(r["Letzter Tag"]),
            str(r["Arbeitstage"]),
            t(r["Status"]),
        )
    table.caption = t(
        "Arbeitstage: {week} vom Start bis einschließlich zum letzten Tag (Feiertage zieht erst "
        "die Kapazität ab). Der nächste Sprint beginnt am Tag nach dem letzten Tag.",
        week=workweek_label(data.team),
    )
    console.print(table)
    changed = calendar_to_save(data, planned, after, create_missing=anlegen)
    blocking = [
        i
        for i in check_team(with_sprints(data, changed), c.today)
        if i.level is Level.ERROR and i.where.startswith("sprints/")
    ]
    if blocking:
        for i in blocking:
            err.print(f"[red]{i.where}: {i.message}[/red]")
        raise typer.Exit(1)
    if not changed:
        if not anlegen:
            console.print(f"[dim]{cmd(t('Fehlende Sprintdateien anlegen mit --anlegen.'))}[/dim]")
        return
    paths = [c.repo.save_sprint(team, s) for s in changed]
    _saved(", ".join(p.name for p in paths))
    _maybe_commit(c, team, paths, t("{team}: Sprintkalender", team=data.team.name), None, commit_)


@command(
    "produkte", "Verteilung auf die Produkte: Standard, PO-Vorplanung, Planning, Erledigt, Saldo."
)
def produkte(
    ctx: typer.Context,
    team: TeamArg,
    sprint: SprintArg = None,
    vorplanung: Annotated[
        bool,
        typer.Option("--vorplanung", "--preplanning", help=t("PO-Vorplanung je Produkt erfassen.")),
    ] = False,
    verlauf: Annotated[
        int, typer.Option("--verlauf", "--history", help=t("Sprints für den Saldo."))
    ] = 6,
    commit_: CommitOpt = False,
) -> None:
    c = _ctx(ctx)
    data = _load(c, team)
    _require_products(data, team)
    if not data.products:
        err.print(
            "[red]"
            + t(
                "Keine Produkte erfasst. Zuerst: {command}",
                command=cmd(f"sprintforecast produktliste {team}"),
            )
            + "[/red]"
        )
        raise typer.Exit(1)
    fc = build_forecast(data, c.today)
    s = copy.deepcopy(_find_or_create(data, fc, sprint, "planning"))
    unit = data.team.unit.value
    if vorplanung and _ask_product_values(data, fc, s, "preplanned"):
        path = c.repo.save_sprint(team, s)
        _saved(path)
        _maybe_commit(
            c,
            team,
            [path],
            t("{team} {id}: PO-Vorplanung", team=data.team.name, id=s.id),
            None,
            commit_,
        )
        data = _load(c, team)
        fc = build_forecast(data, c.today)
    entry = fc.entry(s.id)
    if entry is not None:
        console.print(_distribution_table(distribution(fc, entry), unit))
    entries = [e for e in fc.entries if e.sprint.start <= s.start][-verlauf:]
    rows = balance(fc, entries)
    if rows:
        table = Table(title=t("Saldo: Σ Erledigt − Σ Standard"))
        for i, col in enumerate(("Produkt", "Sprints", "Σ Standard", "Σ Erledigt", "Saldo")):
            table.add_column(t(col), justify="left" if i == 0 else "right")
        for b in rows:
            colour = "green" if b.difference >= 0 else "red"
            table.add_row(
                b.product.name,
                str(b.sprints),
                fmt(b.standard, 2),
                fmt(b.done, 2),
                f"[{colour}]{fmt(b.difference, 2)}[/{colour}]",
            )
        console.print(table)


@command("produktliste", "Produkte des Teams pflegen (neu, PO ändern, abgeben).")
def produktliste(ctx: typer.Context, team: TeamArg, commit_: CommitOpt = False) -> None:
    c = _ctx(ctx)
    data = _load(c, team)
    _require_products(data, team)
    products = data.products
    with_po = data.team.features.po
    changed = False
    while True:
        table = Table(title=t("Produkte"))
        for col in ("Name", *(("PO",) if with_po else ()), "ab", "bis"):
            table.add_column(t(col))
        for p in products:
            table.add_row(
                p.name,
                *((p.po or "",) if with_po else ()),
                f"{p.start:%d.%m.%Y}" if p.start else "–",
                f"{p.end:%d.%m.%Y}" if p.end else "–",
            )
        console.print(table)
        action = Prompt.ask(
            t("Aktion: n = neues Produkt, p = PO ändern, e = Produkt abgeben, q = fertig")
            if with_po
            else t("Aktion: n = neues Produkt, e = Produkt abgeben, q = fertig"),
            choices=["n", "p", "e", "q"] if with_po else ["n", "e", "q"],
            default="q",
            console=console,
        )
        if action == "q":
            break
        if action == "n":
            name = Prompt.ask(t("Name"), console=console).strip()
            if not name or any(p.name.lower() == name.lower() for p in products):
                console.print(f"[red]{t('Bitte einen neuen, eindeutigen Namen eingeben.')}[/red]")
                continue
            po = (
                (
                    Prompt.ask(
                        t("PO (leer = keine Angabe)"),
                        default="",
                        show_default=False,
                        console=console,
                    ).strip()
                    or None
                )
                if with_po
                else None
            )
            start = _ask_date(t("Betreut ab"), c.today)
            pid = new_person_id(name, {p.id for p in products}, fallback="produkt")
            products.append(Product(id=pid, name=name, po=po, start=start))
        else:
            current = [p for p in products if p.end is None or p.end >= c.today]
            if not current:
                console.print(f"[red]{t('Keine aktiven Produkte.')}[/red]")
                continue
            names = {p.name.lower(): p for p in current}
            console.print(f"[dim]{t('Produkte')}: " + ", ".join(p.name for p in current) + "[/dim]")
            raw = Prompt.ask(t("Name"), console=console).strip().lower()
            product = names.get(raw)
            if product is None:
                console.print(f"[red]{t('Produkt nicht gefunden.')}[/red]")
                continue
            if action == "p":
                product.po = (
                    Prompt.ask(t("Neuer PO"), default=product.po or "", console=console).strip()
                    or None
                )
            else:
                product.end = _ask_date(t("Letzter betreuter Tag"), c.today)
        changed = True
    if changed:
        path = c.repo.save_products(team, products)
        _saved(path)
        _maybe_commit(
            c,
            team,
            [path],
            t("{team}: Produktliste aktualisiert", team=data.team.name),
            None,
            commit_,
        )


@command(
    "datenordner",
    "Gemerkten Datenordner anzeigen oder setzen (gilt, wenn das aktuelle Verzeichnis keine Teams "
    "enthält und weder --daten noch SPRINTFORECAST_DATEN gesetzt sind).",
)
def datenordner(
    pfad: Annotated[
        Path | None,
        typer.Argument(help=t("Ordner merken (muss in einem Git-Repository liegen).")),
    ] = None,
) -> None:
    from sprintforecast.git import repo_root
    from sprintforecast.storage import save_data_dir, saved_data_dir, teams_dir

    if pfad is None:
        saved = saved_data_dir()
        console.print(t("Gemerkt: {path}", path=saved) if saved else t("Kein Datenordner gemerkt."))
        console.print(t("Verwendet (ohne --daten): {path}", path=default_data_dir().resolve()))
        return
    if not pfad.is_dir():
        err.print(f"[red]{t('Ordner nicht gefunden: {path}', path=pfad)}[/red]")
        raise typer.Exit(1)
    if repo_root(pfad) is None:
        err.print(
            "[red]"
            + t("{path} liegt in keinem Git-Repository (git init bzw. git clone).", path=pfad)
            + "[/red]"
        )
        raise typer.Exit(1)
    target = teams_dir(pfad) or pfad
    try:
        save_data_dir(target)
    except SettingsError as e:
        err.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    console.print(f"[green]{t('Datenordner gemerkt: {path}', path=target.resolve())}[/green]")


@command("sprache", "Sprache der Oberfläche anzeigen oder einstellen (de, en).")
def sprache(
    code: Annotated[str | None, typer.Argument(help=t("de oder en"))] = None,
) -> None:
    if code is None:
        console.print(f"{language()} ({LANGUAGES[language()]})")
        return
    code = code.strip().lower()[:2]
    if code not in LANGUAGES:
        err.print(f"[red]{t('Erlaubt: {values}', values=', '.join(LANGUAGES))}[/red]")
        raise typer.Exit(1)
    try:
        save_language(code)
    except SettingsError as e:
        err.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    from sprintforecast.i18n import set_language

    set_language(code)
    console.print(f"[green]{t('Sprache: {language}', language=LANGUAGES[code])}[/green]")


@command("verknuepfung", "Starter zum Doppelklicken anlegen (Desktop/Startmenü, macOS: Programme).")
def verknuepfung() -> None:
    from sprintforecast import shortcuts

    try:
        paths = shortcuts.create()
    except (RuntimeError, OSError) as e:
        err.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e
    for path in paths:
        console.print(f"[green]{t('Angelegt: {path}', path=path)}[/green]")
    console.print(
        t(
            "Doppelklick startet die Weboberfläche als App. Beim ersten Start wird der "
            "Datenordner eingerichtet."
        )
    )


@command(
    "aktualisieren",
    "sprintforecast auf die neueste Version aktualisieren (Plugins bleiben erhalten).",
)
def aktualisieren(
    pruefen_: Annotated[
        bool,
        typer.Option("--pruefen", "--check", help=t("Nur prüfen, nicht installieren.")),
    ] = False,
    erzwingen: Annotated[
        bool,
        typer.Option("--erzwingen", "--force", help=t("Auch ohne neue Version neu installieren.")),
    ] = False,
    auto: Annotated[
        str | None,
        typer.Option(
            help=t("Automatik einstellen: an (installiert selbst), hinweis (nur melden), aus."),
        ),
    ] = None,
) -> None:
    if auto is not None:
        aliases = {"on": "an", "notice": "hinweis", "off": "aus"}
        try:
            mode = updater.Mode(aliases.get(auto.strip().lower(), auto.strip().lower()))
        except ValueError:
            err.print(f"[red]{t('--auto: an, hinweis oder aus')}[/red]")
            raise typer.Exit(1) from None
        updater.update_state(mode=mode.value)
        console.print(t("Automatische Aktualisierung: [bold]{mode}[/bold]", mode=t(mode.value)))
        if os.environ.get(updater.MODE_ENV):
            console.print(
                f"[yellow]{t('Hinweis: {name} hat Vorrang.', name=updater.MODE_ENV)}[/yellow]"
            )
        return
    result = updater.check(force=True)
    inst = result.installation
    if inst is None:
        console.print(
            t(
                "Version {version} – nicht mit `uv tool install` installiert (z. B. Entwicklung "
                "mit `uv run`). Aktualisieren mit `git pull` bzw. erneut mit dem "
                "Installationsskript.",
                version=result.current,
            )
        )
        raise typer.Exit(1)
    if inst.pinned and not erzwingen:
        console.print(
            t(
                "Version {version}, fest installiert auf [bold]{ref}[/bold]. Für eine andere "
                "Version das Installationsskript mit SPRINTFORECAST_REF erneut ausführen.",
                version=result.current,
                ref=inst.ref,
            )
        )
        return
    if result.error:
        err.print(f"[red]{t('Prüfung fehlgeschlagen: {error}', error=result.error)}[/red]")
        if not erzwingen:
            raise typer.Exit(1)
    console.print(
        t(
            "Installiert: [bold]{current}[/bold] · verfügbar: [bold]{latest}[/bold] "
            "({repo}, {ref})",
            current=result.current,
            latest=result.latest or "–",
            repo=inst.repo,
            ref=inst.ref,
        )
    )
    if not result.available and not erzwingen:
        console.print(f"[green]{t('sprintforecast ist aktuell.')}[/green]")
        return
    if pruefen_:
        console.print(cmd(t("Aktualisieren mit: sprintforecast aktualisieren")))
        return
    uv = updater.find_uv()
    if uv is None:
        err.print(
            f"[red]{t('uv nicht gefunden – bitte das Installationsskript erneut ausführen.')}[/red]"
        )
        raise typer.Exit(1)
    if sys.platform == "win32":
        updater.schedule_after_exit(uv, visible=True)
        updater.update_state(attempted=result.latest, failure_reported=False)
        console.print(
            t(
                "Die Aktualisierung startet nach diesem Befehl in einem eigenen Fenster "
                "(Windows sperrt laufende Programme)."
            )
        )
        return
    code = updater.run_upgrade(uv)
    if code != 0:
        err.print(f"[red]{t('Aktualisierung fehlgeschlagen (Exit-Code {code}).', code=code)}[/red]")
        raise typer.Exit(code)
    version = subprocess.run(
        [sys.executable, "-c", f"import importlib.metadata as m; print(m.version({PACKAGE!r}))"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    updater.update_state(seen_version=version or result.latest)
    console.print(
        f"[green]{t('Installiert: Version {version}.', version=version or result.latest)}[/green]"
    )


@command(
    "kapazitaet",
    "Kapazitätsberechnung eines Sprints im Detail anzeigen (Standard: nächster Sprint).",
)
def kapazitaet(ctx: typer.Context, team: TeamArg, sprint: SprintArg = None) -> None:
    c = _ctx(ctx)
    data = _load(c, team)
    s = _find_or_create(data, build_forecast(data, c.today), sprint, "next")
    console.print(_capacity_table(data, s))
    if s.capacity is not None:
        console.print(
            "[dim]"
            + t(
                "In der Sprintdatei eingetragen/eingefroren: {capacity} PT",
                capacity=fmt_capacity(s.capacity, data.team.capacity.rounding),
            )
            + "[/dim]"
        )
    if data.sprint(s.id) is None:
        hint = (
            t(
                "Noch keine Sprintdatei – die Prognose rechnet bis dahin mit Kalender und "
                "Personenliste; die unbekannten Fehltage werden nach der Historie geschätzt "
                "(ohne Historie ohne Abzug)."
            )
            if data.people
            else t("Noch keine Sprintdatei – die Prognose nutzt bis dahin den Kapazitäts-Trend.")
        )
        console.print(f"[yellow]{hint}[/yellow]")


# Erweiterungen (z. B. Import-Plugins) registrieren ihre Befehle zuletzt.
for _plugin in load_plugins():
    if _plugin.register_cli is not None:
        _plugin.register_cli(app)
for _command in app.registered_commands:  # auch die Befehle der Erweiterungen
    if _command.callback is not None:
        _command.callback = _guarded(_command.callback)
