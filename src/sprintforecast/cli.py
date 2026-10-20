# SPDX-License-Identifier: EUPL-1.2
"""Command line with guided input (German/English, see i18n)."""

from __future__ import annotations

import copy
import functools
import math
import os
import re
import subprocess
import sys
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from sprintforecast import LOG_ENV, __version__, appsettings, completion, updater
from sprintforecast.calendar import (
    day_label,
    expected_id_form,
    following_sprint,
    holiday_name,
    id_fits_numbering,
    team_workdays,
    workweek_label,
)
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
from sprintforecast.git import GitError, blank_controls, commit, title_for
from sprintforecast.guide import (
    CAPACITY_SOURCES,
    COMMANDS,
    FIELDS,
    TERMS,
    TOPICS,
    WORKFLOW,
)
from sprintforecast.i18n import LANGUAGES, language, save_language, t
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
from sprintforecast.products import (
    MEASURES,
    Distribution,
    balance,
    distribution,
    measure_label,
    missing_footnote,
)
from sprintforecast.report import (
    band_range,
    capacity_label,
    completion_note,
    fmt,
    fmt_capacity,
    pct,
    period,
    reliability_notes,
    render,
    status,
    window_hint,
)
from sprintforecast.settings import FIRST_SPRINT_KEYS, SETTINGS, Setting, applicable, changes
from sprintforecast.storage import (
    AS_OF_ENV,
    DATA_ENV,
    DataError,
    Repository,
    TeamData,
    default_data_dir,
    team_key_problem,
    write_text,
)
from sprintforecast.updater import PACKAGE
from sprintforecast.validate import Issue, Level, check_all, check_team, issues_for

app = typer.Typer(
    help=t("Velocity and capacity forecast for Scrum teams. Start with: `sprintforecast help`."),
    rich_markup_mode="rich",
)
console = Console(emoji=False)  # names like ":smile:" stay text
err = Console(stderr=True, emoji=False)


# Like rich.markup.escape: a tag is "[" + a letter, "#", "/" or "@" ... "]"; backslashes before
# it count (two make one, an odd one escapes the tag). Rich also turns every "\[" into "[", even
# when no tag follows (`D:\Projects\[2024]`): a backslash was missing there.
_BRACKET = re.compile(r"(\\*)\[([a-z#/@][^[]*?]|)")


def _bracket(match: re.Match[str]) -> str:
    slashes, tag = match[1], match[2]
    if tag:
        return f"{slashes}{slashes}\\[{tag}"
    return f"{slashes}\\[" if slashes else "["


def _plain(value: object) -> str:
    """Free text from data or messages for output: square brackets are not markup.

    Unlike rich.markup.escape, a trailing backslash stays unchanged: Rich shows it correctly
    only when no tag follows (table cell, prompt, title, sentence). If the value comes directly
    before a tag (`[bold]{x}[/bold]`), use `_plain_end`."""
    return _BRACKET.sub(_bracket, str(value))


def _plain_end(value: object) -> str:
    """Like `_plain` for a value directly followed by a tag: trailing backslashes are doubled,
    otherwise they would escape the tag (`Eva\\[/red]` showed "[/red]" as text)."""
    text = _plain(value)
    return text + text[len(text.rstrip("\\")) :]


def _guarded(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Prints a data file error as a message (exit code 1): write or read error, no first
    sprint, an ID without a successor ID."""
    if getattr(fn, "_guarded", False):
        return fn

    @functools.wraps(fn)
    def guarded(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except DataError as e:  # message, not a traceback (no write permission, forecast, ...)
            err.print(f"[red]{escape(str(e))}[/red]")
            raise typer.Exit(1) from e

    guarded._guarded = True  # type: ignore[attr-defined]
    return guarded


def command(name: str, help: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Registers a command (English name, translated help)."""

    def register(fn: Callable[..., Any]) -> Callable[..., Any]:
        app.command(name, help=t(help))(_guarded(fn))
        return fn

    return register


@dataclass
class Context:
    repo: Repository
    today: date
    as_of: str | None = None


def _ctx(ctx: typer.Context) -> Context:
    return ctx.obj


def _check_as_of(value: str | None) -> str | None:
    if value:
        try:
            date.fromisoformat(value)
        except ValueError as e:
            raise typer.BadParameter(t("Date in the format YYYY-MM-DD expected")) from e
    return value


@app.callback(invoke_without_command=True)
def _main(
    ctx: typer.Context,
    data: Annotated[
        Path | None,
        typer.Option(
            "--data",
            "-d",
            envvar=DATA_ENV,
            help=t(
                "Folder with the team data (one subfolder per team). Default: current "
                "folder if it contains teams, otherwise the remembered data folder."
            ),
        ),
    ] = None,
    as_of: Annotated[
        str | None,
        typer.Option(
            "--as-of",
            callback=_check_as_of,
            help=t('Date (YYYY-MM-DD) treated as "today" – for retrospectives and tests.'),
        ),
    ] = None,
    version: Annotated[bool, typer.Option("--version", help=t("Show version."))] = False,
) -> None:
    if version:
        console.print(__version__)
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()
    if ctx.invoked_subcommand not in ("update", "completion"):
        _auto_update()
    today = date.fromisoformat(as_of) if as_of else date.today()
    ctx.obj = Context(repo=Repository(data or default_data_dir()), today=today, as_of=as_of)


def _auto_update() -> None:
    """Notices about the last update; check in the background, install at the end."""
    import atexit

    for message in updater.startup_notices():
        err.print(f"[cyan]{_plain_end(message)}[/cyan]")
    auto = updater.AutoUpdate().start()
    atexit.register(auto.finish, lambda text: err.print(f"[cyan]{_plain_end(text)}[/cyan]"))


def _load(c: Context, team: str) -> TeamData:
    try:
        return c.repo.load(team)
    except DataError as e:
        err.print(f"[red]{_plain_end(e)}[/red]")
        raise typer.Exit(1) from e


# --- Input helpers -------------------------------------------------------------------


def _explain(key: str) -> None:
    f = FIELDS[key]
    console.print(
        Panel(
            f"{t(f.what)}\n[dim]{t('Source')}: {t(f.source)}\n{t('Example')}: {t(f.example)}[/dim]",
            title=t(f.title),
            title_align="left",
            border_style="cyan",
        )
    )


def _ask_number(
    label: str, default: float | None, *, allow_empty: bool = True, minimum: float = 0.0
) -> float | None:
    hint = t("empty = not specified") if allow_empty else ""
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
            console.print(f"[red]{t('Please enter a value.')}[/red]")
            continue
        try:
            value = float(raw.replace(",", "."))
        except ValueError:
            console.print(f"[red]{t('Please enter a number (decimal separator , or .).')}[/red]")
            continue
        if not math.isfinite(value):
            console.print(f"[red]{t('Please enter a finite number.')}[/red]")
            continue
        if value < minimum:
            console.print(
                f"[red]{t('The value must be ≥ {value}.', value=fmt_plain(minimum))}[/red]"
            )
            continue
        return value


def _ask_numbers(label: str, default: list[float]) -> list[float]:
    shown = " ".join(fmt_plain(v) for v in default)
    while True:
        raw = Prompt.ask(label, default=shown, show_default=bool(shown), console=console).strip()
        try:
            values = [float(x.replace(",", ".")) for x in raw.split()] if raw else []
        except ValueError:
            console.print(f"[red]{t('Please enter numbers separated by spaces.')}[/red]")
            continue
        if all(math.isfinite(v) for v in values):
            return values
        console.print(f"[red]{t('Please enter a finite number.')}[/red]")


def _ask_date(label: str, default: date | None) -> date:
    while True:
        raw = Prompt.ask(
            f"{label} [dim]({t('YYYY-MM-DD')})[/dim]",
            default=default.isoformat() if default else "",
            show_default=default is not None,
            console=console,
        ).strip()
        try:
            return date.fromisoformat(raw)
        except ValueError:
            console.print(f"[red]{t('Please enter the date as YYYY-MM-DD.')}[/red]")


def fmt_plain(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _find_or_create(data: TeamData, fc: Forecast, sprint_id: str | None, purpose: str) -> Sprint:
    """Returns the sprint from the store or creates it from the calendar."""
    if sprint_id is None:
        entry = fc.default_entry(purpose)
        if entry is None:
            err.print(f"[red]{t('No matching sprint found – please specify a sprint ID.')}[/red]")
            raise typer.Exit(1)
        sprint_id = entry.sprint.id
    sprint = find_sprint(data, sprint_id)
    if sprint is None:
        err.print(
            "[red]"
            + t("Sprint {id} is not part of the team's sprint sequence.", id=_plain(sprint_id))
            + "[/red]"
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
            f"{t('Capacity')}: {capacity_label(e)} PT\n"
            f"{t('norm. velocity trend')}: {fmt(r.normalized_velocity.trend, 2)}\n"
            f"[bold]Forecast PLAN: {fmt(r.plan)} {unit}[/bold]  "
            f"({t('Plannable')} {fmt(r.roadmap, 2)} · {t('Small items')} {fmt(r.small_stuff, 2)})",
            title=t("Forecast sprint {id}", id=_plain(sprint_id)),
            title_align="left",
            border_style="green",
        )
    )


def _capacity_table(data: TeamData, s: Sprint) -> Table:
    breakdown = sprint_capacity(data.team, data.people, s)
    table = Table(
        title=t(
            "Capacity sprint {id} ({start} – {end})",
            id=_plain(s.id),
            start=f"{s.start:%d.%m.}",
            end=f"{s.end:%d.%m.%Y}",
        )
    )
    for i, col in enumerate(("Person", "Working days", "Holidays", "Absences", "PT")):
        table.add_column(t(col), justify="left" if i == 0 else "right")
    digits = breakdown.rounding  # all PD figures like the total: rounded half up
    for pc in breakdown.people:
        table.add_row(
            _plain(pc.person.name),
            str(pc.workdays),
            str(pc.holidays),
            fmt_plain(pc.absence_days),
            fmt_capacity(pc.capacity, digits),
        )
    if breakdown.overhead_days_part:
        days = fmt_plain(data.team.capacity.overhead_days)
        table.add_row(
            t("Scrum events deduction ({days} PT per person × FTE)", days=days),
            "", "", "", f"−{fmt_capacity(breakdown.overhead_days_part, digits)}",
        )  # fmt: skip
    if breakdown.overhead_share_part:
        table.add_row(
            t("Scrum events deduction ({share})", share=pct(data.team.capacity.overhead_share)),
            "", "", "", f"−{fmt_capacity(breakdown.overhead_share_part, digits)}",
        )  # fmt: skip
    if breakdown.approximated:
        from sprintforecast.formulas import fte_change_note

        table.caption = _plain(fte_change_note([p.person.name for p in breakdown.approximated]))
    table.add_row(
        f"[bold]{t('Total')}[/bold]",
        "", "", "",
        f"[bold]{fmt_capacity(breakdown.capacity, digits)}[/bold]",
    )  # fmt: skip
    return table


def _cli_git_hints() -> dict[str, str]:
    """Command line hints for error kinds whose hint from the Git layer addresses the web UI
    (sidebar, pages, buttons)."""
    return {
        "identity": t(
            "Git does not know your name yet. Set it up with `git config --global "
            'user.name "Your Name"` and `git config --global user.email '
            '"you@example.org"`.'
        ),
        "conflict": t(
            "The markers come from an incomplete merge: remove them in an editor and run "
            "the command again with --commit."
        ),
        "tag_exists": t(
            "Remove the existing tag first (`git tag -d <name>`) and run the command again "
            "with --commit. The data is saved, just not committed."
        ),
    }


def _git_problem(e: GitError) -> NoReturn:
    """Prints a Git error with heading, message and next step (exit code 1)."""
    err.print(f"[bold red]{escape(title_for(e.kind))}[/bold red]")
    if str(e):
        err.print(f"[red]{escape(str(e))}[/red]")
    if hint := _cli_git_hints().get(e.kind) or e.hint:
        err.print(escape(hint))
    raise typer.Exit(1) from e


def _maybe_commit(
    c: Context, team: str, paths: list[Path], message: str, tag: str | None, do_commit: bool
) -> list[Issue]:
    """Shows check results for the changed files and commits if requested.
    Returns the check results shown."""
    issues = issues_for(_load(c, team), c.today, [p.name for p in paths])
    for i in issues:
        colour = "red" if i.level is Level.ERROR else "yellow"
        console.print(
            f"[{colour}]{i.level.label}[/{colour}] {_plain(i.where)}: {_plain(i.message)}"
        )
    has_errors = any(i.level is Level.ERROR for i in issues)
    if not do_commit:
        console.print(
            f"[dim]{t('Tip: with --commit the change is committed to Git right away.')}[/dim]"
        )
        return issues
    if has_errors:
        err.print(f"[red]{t('Not committed – please fix the errors first.')}[/red]")
        raise typer.Exit(1)
    try:
        rev = commit(paths, message, tag)
    except GitError as e:
        _git_problem(e)
    suffix = t(", tag {tag}", tag=_plain(tag)) if tag else ""
    console.print(f"[green]{t('Committed ({rev}){suffix}.', rev=rev, suffix=suffix)}[/green]")
    return issues


def _new_errors(c: Context, before: TeamData, after: TeamData, where: str) -> list[Issue]:
    """Errors in the new state (only in files whose name starts with ``where``) that were not
    in the old one."""
    known = {(i.where, i.message) for i in check_team(before, c.today)}
    return [
        i
        for i in check_team(after, c.today)
        if i.level is Level.ERROR
        and i.where.startswith(where)
        and (i.where, i.message) not in known
    ]


def _print_errors(errors: list[Issue]) -> None:
    for i in errors:
        err.print(f"[red]{_plain(i.where)}: {_plain_end(i.message)}[/red]")


def _refuse_invalid(c: Context, before: TeamData, after: TeamData, where: str) -> None:
    """Like the web UI: errors in the new state (only in the affected files, ``where`` is the
    start of the file name) prevent the write instead of being reported afterwards. Errors that
    existed before do not block the change."""
    if errors := _new_errors(c, before, after, where):
        _print_errors(errors)
        err.print(f"[red]{t('Not saved – please fix the errors.')}[/red]")
        raise typer.Exit(1)


def _with_sprint(data: TeamData, sprint: Sprint) -> TeamData:
    """Copy of ``data`` with the (new or changed) sprint."""
    after = copy.copy(data)
    after.sprints = sorted(
        [x for x in data.sprints if x.id != sprint.id] + [sprint], key=lambda x: x.start
    )
    return after


def _saved(path: Path) -> None:
    console.print(f"[green]{t('Saved: {path}', path=_plain_end(path))}[/green]")


NewTeamArg = Annotated[str, typer.Argument(help=t("Team key = folder name, e.g. team-a."))]
TeamArg = Annotated[
    str,
    typer.Argument(
        help=t("Team key = folder name, e.g. team-a."), autocompletion=completion.team_names
    ),
]
SprintArg = Annotated[
    str | None,
    typer.Argument(help=t("Sprint ID, e.g. 2026.21."), autocompletion=completion.sprint_ids),
]
CommitOpt = Annotated[bool, typer.Option("--commit", help=t("Commit the change in Git."))]


# --- Befehle --------------------------------------------------------------------------


@command("help", "Guide, terms, input fields, settings and commands.")
def help_command(
    topic_arg: Annotated[
        str | None,
        typer.Argument(metavar="TOPIC", help=t("Topic: {topics}", topics=", ".join(TOPICS))),
    ] = None,
) -> None:
    topic = topic_arg or "workflow"
    if topic not in TOPICS:
        err.print(f"[red]{t('Unknown topic. Available: {topics}', topics=', '.join(TOPICS))}[/red]")
        raise typer.Exit(1)
    console.print(_help_table(topic))
    if topic == "terms":
        console.print(_two_columns(t("Capacity source in the forecast"), CAPACITY_SOURCES))
    others = ", ".join(k for k in TOPICS if k != topic)
    console.print(
        f"[dim]{t('More topics: {others} (sprintforecast help TOPIC)', others=others)}[/dim]"
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
    if topic == "workflow":
        table = Table(title=title, title_justify="left", show_lines=True)
        for col in ("When", "What", "Command"):
            table.add_column(t(col))
        for step in WORKFLOW:
            table.add_row(
                t(step.when), f"[bold]{t(step.title)}[/bold]\n{t(step.text)}", escape(step.cli)
            )
        table.caption = t("Everything also works in the browser: sprintforecast web")
        return table
    if topic == "terms":
        return _two_columns(title, TERMS)
    if topic == "fields":
        table = Table(title=title, title_justify="left", show_lines=True)
        for col in ("Field", "Meaning", "Source", "Example"):
            table.add_column(t(col))
        for f in FIELDS.values():
            table.add_row(f"[bold]{t(f.title)}[/bold]", t(f.what), t(f.source), t(f.example))
        return table
    if topic == "team":
        table = Table(title=title, title_justify="left", show_lines=True)
        for col in ("Setting", "Key in team.yaml", "Meaning"):
            table.add_column(t(col))
        for setting in SETTINGS:
            table.add_row(f"[bold]{setting.title}[/bold]", setting.key, setting.text)
        table.caption = t("Change interactively: sprintforecast settings TEAM")
        return table
    table = Table(title=title, show_header=False, box=None, padding=(0, 2), title_justify="left")
    table.add_column(style="bold", no_wrap=True)
    table.add_column()
    for left, right in COMMANDS:
        table.add_row(escape(left), escape(t(right)))
    return table


def _ask_setting(setting: Setting, team: Team, *, required: bool = False) -> None:
    console.print(f"[dim]{setting.text}[/dim]")
    label = setting.title
    if (options := setting.options) and len(options) <= 25:
        listed = ", ".join(f"{k} = {v}" for k, v in options.items())
        console.print(f"[dim]{t('Possible: {options}', options=listed)}[/dim]")
    if setting.optional and not required:
        label += f" [dim]({t('empty = not specified')})[/dim]"
    current = setting.display(team)
    while True:
        raw = Prompt.ask(label, default=current, show_default=bool(current), console=console)
        try:
            value = setting.parse(raw)
        except ValueError as e:
            console.print(f"[red]{_plain_end(e)}[/red]")
            continue
        if value is None and required:
            console.print(f"[red]{t('Please enter a value.')}[/red]")
            continue
        setting.set(team, value)
        return


def _exists_text(team: str, existing: str) -> str:
    if existing == team:
        return t("Team {team} already exists.", team=repr(team))
    return t(
        (
            "Team {team} already exists (as {existing}; Windows and macOS do not distinguish "
            "folders by upper and lower case)."
        ),
        team=repr(team),
        existing=repr(existing),
    )


@command("init", "Create a new team with guided input.")
def init(ctx: typer.Context, team: NewTeamArg, commit_: CommitOpt = False) -> None:
    c = _ctx(ctx)
    if clash := c.repo.clashing_team(team):
        err.print(f"[red]{escape(_exists_text(team, clash))}[/red]")
        raise typer.Exit(1)
    if problem := team_key_problem(team):
        err.print(f"[red]{escape(problem)}[/red]")
        raise typer.Exit(1)
    console.print(
        Panel(
            t(
                (
                    "Create new team [bold]{team}[/bold]. All values can be changed later with "
                    "[bold]{command}[/bold].\nThe areas product distribution (several "
                    "products), PO assignment and production access are optional; they are off "
                    "at first (Enter accepts “off”)."
                ),
                team=_plain_end(team),
                command=_plain_end(f"sprintforecast settings {team}"),
            )
        )
    )
    new = Team(key=team, name=team.upper())
    settings = applicable(has_sprints=False)
    by_key = {s.key: s for s in settings}
    _ask_setting(by_key["name"], new)
    console.print(
        Panel(
            t(
                "[bold]First sprint:[/bold] the sprint that is running now or starts next. "
                "Its ID and start are where the count begins; the following sprints follow "
                "from it. If the team has been working for a while, that is e.g. "
                "[bold]2026.15[/bold] rather than 2026.1."
            )
        )
    )
    for key in FIRST_SPRINT_KEYS:
        _ask_setting(by_key[key], new, required=True)
    while not id_fits_numbering(
        new.sprint.first_id or "",
        (new.sprint.first_start or c.today) + timedelta(days=new.sprint.length_days),
        new.sprint.numbering,
    ):
        console.print(
            "[red]"
            + t(
                "Sprint ID {id} does not match the numbering (expected {expected}).",
                id=repr(new.sprint.first_id),
                expected=expected_id_form(new.sprint.numbering),
            )
            + "[/red]"
        )
        _ask_setting(by_key["sprint.first_id"], new, required=True)
    for setting in settings:
        if setting.key != "name" and setting.key not in FIRST_SPRINT_KEYS:
            _ask_setting(setting, new, required=setting.only_without_sprints)
    path = c.repo.save_team(new)
    people = c.repo.save_people(team, [])
    console.print(f"[green]{t('Created: {path}', path=_plain_end(path))}[/green]")
    _maybe_commit(c, team, [path, people], t("{team}: team created", team=new.name), None, commit_)
    console.print(
        t(
            "Next: [bold]{command}[/bold]",
            command=_plain_end(f"sprintforecast people {team}"),
        )
    )


@command(
    "settings",
    "Change team settings with guided input (unit, federal state, reference capacity …).",
)
def settings_command(ctx: typer.Context, team: TeamArg, commit_: CommitOpt = False) -> None:
    c = _ctx(ctx)
    data = _load(c, team)
    before = copy.deepcopy(data.team)
    current = data.team
    console.print(
        Panel(
            t(
                "Settings [bold]{team}[/bold] – Enter keeps the current value.",
                team=_plain_end(current.name),
            ),
            border_style="cyan",
        )
    )
    for setting in applicable(has_sprints=bool(data.sprints)):
        _ask_setting(setting, current)
    diff = changes(before, current)
    if not diff:
        console.print(t("No changes."))
        return
    table = Table(title=t("Changes"))
    for col in ("Setting", "before", "new"):
        table.add_column(t(col))
    for setting, old, new in diff:
        table.add_row(setting.title, _plain(old) if old else "–", _plain(new) if new else "–")
    console.print(table)
    if any(setting.retroactive for setting, _, _ in diff):
        console.print(
            "[yellow]"
            + t(
                "Note: at least one change applies retroactively to all calculated values "
                "(Ø, trend, Forecast PLAN)."
            )
            + "[/yellow]"
        )
    if not Confirm.ask(t("Save?"), default=True, console=console):
        raise typer.Exit()
    after = copy.copy(data)
    after.team = current
    old = copy.copy(data)
    old.team = before  # ``current`` was changed in place, ``before`` is the copy
    _refuse_invalid(c, old, after, "team.yaml")
    path = c.repo.save_team(current)
    _saved(path)
    _maybe_commit(c, team, [path], t("{team}: settings changed", team=current.name), None, commit_)


def _people_table(people: list[Person], day: date, show_former: bool) -> Table:
    table = Table(title=t("People (as of {day})", day=f"{day:%d.%m.%Y}"))
    for col in ("Name", "State", "FTE today", "Periods in the team"):
        table.add_column(t(col))
    shown = [p for p in people if show_former or p.is_current(day)]
    if hidden := len(people) - len(shown):
        table.caption = t("{count} former person(s) hidden – show with --former", count=hidden)
    for p in shown:
        spans = ", ".join(
            f"{m.start:%d.%m.%Y}–{m.end:%d.%m.%Y}"
            if m.end
            else t("from {day}", day=f"{m.start:%d.%m.%Y}")
            for m in p.memberships
        )
        spans += (
            "" if not p.memberships else f" ({'/'.join(fmt_plain(m.fte) for m in p.memberships)})"
        )
        fte = p.fte_on(day)
        table.add_row(
            _plain(p.name),
            _plain(p.region) if p.region else "–",
            fmt_plain(fte) if fte else "–",
            spans,
        )
    return table


def _choose_person(people: list[Person]) -> Person:
    """Selection by name; identical names are told apart by the internal ID."""
    names = [p.name for p in people]
    labels = [p.name if names.count(p.name) == 1 else f"{p.name} ({p.id})" for p in people]
    by_label = {label.lower(): p for label, p in zip(labels, people, strict=True)}
    console.print(f"[dim]{t('People')}: " + _plain_end(", ".join(labels)) + "[/dim]")
    while True:
        raw = Prompt.ask(t("Name"), console=console).strip().lower()
        if raw in by_label:
            return by_label[raw]
        matches = [p for label, p in by_label.items() if label.startswith(raw)] if raw else []
        if len(matches) == 1:
            return matches[0]
        console.print(
            f"[red]{t('Name not found unambiguously – please enter it as shown above.')}[/red]"
        )


@command("people", "Show and maintain the list of people (joining, FTE change, leaving).")
def people_command(
    ctx: typer.Context,
    team: TeamArg,
    commit_: CommitOpt = False,
    former: Annotated[
        bool,
        typer.Option("--former", help=t("Show people who left.")),
    ] = False,
) -> None:
    c = _ctx(ctx)
    data = _load(c, team)
    people = data.people
    before = copy.deepcopy(data)  # the list is changed in place below
    changed = False
    while True:
        console.print(_people_table(people, c.today, former))
        action = Prompt.ask(
            t("Action: n = new person, f = change FTE, a = leaves the team, q = done"),
            choices=["n", "f", "a", "q"],
            default="q",
            console=console,
        )
        if action == "q":
            break
        if action == "n":
            name = Prompt.ask(t("Name"), console=console).strip()
            if not name:
                console.print(f"[red]{t('Please enter a name.')}[/red]")
                continue
            if any(p.name.lower() == name.lower() for p in people):
                console.print(
                    f"[red]{t('This person already exists – choose "f" to change the FTE.')}[/red]"
                )
                continue
            pid = new_person_id(name, {p.id for p in people})
            region = (
                Prompt.ask(
                    t("German state, if different from the team (empty = team setting)"),
                    default="",
                    show_default=False,
                    console=console,
                )
                .strip()
                .upper()
                or None
            )
            start = _ask_date(t("In the team from"), c.today)
            fte = _ask_number(
                t("FTE share in the team (1 = full time, 0.5 = half time)"), 1, allow_empty=False
            )
            person = Person(pid, name, region, [Membership(start=start, fte=fte or 1.0)])
            tentative = copy.copy(data)
            tentative.people = [*people, person]
            if errors := _new_errors(c, data, tentative, "people.yaml"):
                _print_errors(errors)  # report right away instead of discarding only on save
                continue
            people.append(person)
        else:
            candidates = [p for p in people if p.is_current(c.today)]
            if not candidates:
                console.print(f"[red]{t('No active people.')}[/red]")
                continue
            person = _choose_person(candidates)
            active = next((m for m in person.memberships if m.end is None), None)
            if active is None:
                console.print(f"[red]{t('No open membership.')}[/red]")
                continue
            when = _ask_date(
                t("Valid from") if action == "f" else t("Last day in the team"), c.today
            )
            if when <= active.start:
                console.print(
                    f"[red]{t('The date must be after the start of the current membership.')}[/red]"
                )
                continue
            if action == "f":
                fte = _ask_number(t("New FTE share"), active.fte, allow_empty=False)
                active.end = when - timedelta(days=1)
                person.memberships.append(Membership(start=when, fte=fte or active.fte))
            else:
                active.end = when
        changed = True
    if changed:
        after = copy.copy(data)
        after.people = people
        _refuse_invalid(c, before, after, "people.yaml")
        path = c.repo.save_people(team, people)
        _saved(path)
        _maybe_commit(
            c,
            team,
            [path],
            t("{team}: people list updated", team=data.team.name),
            None,
            commit_,
        )


@command("absences", "Record planned absences per person for a sprint (default: next sprint).")
def absences_command(
    ctx: typer.Context, team: TeamArg, sprint: SprintArg = None, commit_: CommitOpt = False
) -> None:
    c = _ctx(ctx)
    data = _load(c, team)
    if not data.people:
        err.print(
            "[red]"
            + t(
                "No people recorded. First: {command}",
                command=_plain_end(f"sprintforecast people {team}"),
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
        t("{team} {id}: absences recorded", team=data.team.name, id=s.id),
        None,
        commit_,
    )


def _sprint_panel(data: TeamData, s: Sprint) -> Panel:
    days = team_workdays(data.team, s.start, s.end)
    region, country = data.team.capacity.region, data.team.capacity.country
    holiday_names = [
        f"{d:%d.%m.} {holiday_name(d, region, country)}"
        for d in days
        if holiday_name(d, region, country)
    ]
    last = days[-1] if days else s.end
    text = t(
        (
            "Sprint [bold]{id}[/bold]: {start} – {last} (last working day; the next sprint "
            "starts on {next}), {days} working days ({week})"
        ),
        id=_plain_end(s.id),
        start=f"{s.start:%d.%m.%Y}",
        last=f"{last:%d.%m.%Y}",
        next=f"{s.end:%d.%m.}",
        days=len(days),
        week=workweek_label(data.team),
    )
    if holiday_names:
        text += "\n" + t(
            "including holidays ({region}): {holidays}",
            region=_plain(region) if region else t("nationwide"),
            holidays=", ".join(holiday_names),
        )
    return Panel(text, border_style="cyan")


def _ask_absences(c: Context, data: TeamData, s: Sprint) -> Path:
    """Asks for the absences of each active person and saves the sprint."""
    before = copy.deepcopy(data)  # the sprint is changed in place below
    days = team_workdays(data.team, s.start, s.end)
    console.print(_sprint_panel(data, s))
    _explain("absences")
    for p in data.people:
        if not p.active_between(s.start, s.end):
            continue
        value = _ask_number(_plain(p.name), s.absences.get(p.id, 0.0), allow_empty=False)
        if value:
            s.absences[p.id] = min(value, len(days))
        else:
            s.absences.pop(p.id, None)
    s.absence_state = AbsenceState.CONFIRMED  # all people were asked, including "0"
    if s.capacity is not None and Confirm.ask(
        t(
            (
                "A fixed capacity ({capacity}) is recorded for the sprint. Remove it so it is "
                "calculated from the absences?"
            ),
            capacity=fmt_capacity(s.capacity, data.team.capacity.rounding),
        ),
        default=s.end > c.today,
        console=console,
    ):
        s.capacity = None
    _refuse_invalid(c, before, _with_sprint(data, s), "sprints/")
    return c.repo.save_sprint(data.team.key, s)


def _require_products(data: TeamData, team: str) -> None:
    """Ends the command when the team does not use the product distribution."""
    if not data.team.features.products:
        err.print(
            "[yellow]"
            + t(
                (
                    "The product distribution is switched off for this team. Switch it on "
                    "with: {command}"
                ),
                command=_plain_end(f"sprintforecast settings {team}"),
            )
            + "[/yellow]"
        )
        raise typer.Exit(1)


def _require_tickets(data: TeamData, team: str) -> None:
    """Ends the command when the team does not use the ticket pre-planning."""
    if not data.team.features.tickets:
        err.print(
            "[yellow]"
            + t(
                ("Ticket pre-planning is switched off for this team. Switch it on with: {command}"),
                command=_plain_end(f"sprintforecast settings {team}"),
            )
            + "[/yellow]"
        )
        raise typer.Exit(1)


def _ask_product_values(data: TeamData, fc: Forecast, s: Sprint, measure: str) -> bool:
    """Asks for a value (preplanned/planned/done) per product. True if something changed."""
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
                f"{_plain(r.product.name)} – {measure_label(measure)} ({unit})",
                getattr(values, measure),
            ),
        )
        if values.is_empty():
            s.products.pop(r.product.id, None)
        else:
            s.products[r.product.id] = values
    return s.products != before


def _distribution_table(d: Distribution, unit: str) -> Table:
    basis = t("Plannable share") if d.basis.value == "roadmap" else "Forecast PLAN"
    table = Table(title=t("Products sprint {id}", id=_plain(d.sprint.id)))
    table.add_column(t("Product"))
    if d.features.po:
        table.add_column("PO")
    for m in MEASURES:
        table.add_column(f"{measure_label(m)} {unit}", justify="right")
    for r in d.rows:
        table.add_row(
            _plain(r.product.name) + ("" if r.active else f" [dim]({t('not handled')})[/dim]"),
            *((_plain(r.product.po or ""),) if d.features.po else ()),
            *(fmt(r.value(m), 2) for m in MEASURES),
        )
    table.add_row(
        f"[bold]{t('Total')}[/bold]",
        *(("",) if d.features.po else ()),
        *(fmt(d.total(m), 2) for m in MEASURES),
    )
    if d.available is not None and d.active_count:
        table.caption = t(
            "Standard = {basis}{frozen} {available} / {count} products",
            basis=basis,
            frozen=f" ({t('frozen')})" if d.plan_frozen else "",
            available=fmt(d.available, 2),
            count=d.active_count,
        )
    return table


@command(
    "planning",
    "Guided sprint planning: 1. absences, 2. Forecast PLAN and scheduling per product, "
    "3. commitment (default: next planning).",
)
def planning(
    ctx: typer.Context, team: TeamArg, sprint: SprintArg = None, commit_: CommitOpt = False
) -> None:
    c = _ctx(ctx)
    data = _load(c, team)
    fc = build_forecast(data, c.today)
    s = _find_or_create(data, fc, sprint, "planning")
    before = copy.deepcopy(data)  # the sprint is changed in place below
    paths: list[Path] = []
    console.rule(t("Planning {id} – step 1: absences", id=_plain(s.id)))
    if data.people and Confirm.ask(
        t("Record or check the known absences for the sprint?"),
        default=data.sprint(s.id) is None,
        console=console,
    ):
        paths.append(_ask_absences(c, data, s))
        console.print(_capacity_table(data, s))
    elif data.sprint(s.id) is None:
        hint = t(
            "Without confirmed absences the capacity is only estimated (calendar and history)."
        )
        console.print(f"[yellow]{hint}[/yellow]")
    data = _load(c, team) if paths else data
    fc = build_forecast(data, c.today)
    s = copy.deepcopy(data.sprint(s.id) or s)
    console.rule(t("Planning {id} – step 2: Forecast PLAN and planning", id=_plain(s.id)))
    if data.sprint(s.id):
        _show_sprint_forecast(c, team, s.id)
    if (
        data.team.features.products
        and data.products
        and Confirm.ask(t("Record planning per product?"), default=True, console=console)
    ):
        _ask_product_values(data, fc, s, "planned")
    console.rule(t("Planning {id} – step 3: commitment", id=_plain(s.id)))
    unit = data.team.unit.value
    plan_values = None
    if Confirm.ask(
        t(
            "Record the cross-check (carry-over, backlog, corrections)? Optional – only "
            "affects the planning delta"
        ),
        default=s.planning is not None,
        console=console,
    ):
        p = s.planning or Planning()
        _explain("carryover")
        carryover = (
            _ask_number(t("Carry-over ({unit})", unit=unit), p.carryover, allow_empty=False) or 0.0
        )
        _explain("backlog")
        backlog = _ask_number(f"Backlog ({unit})", p.backlog, allow_empty=False) or 0.0
        _explain("corrections")
        corrections = _ask_numbers(t("Corrections ({unit})", unit=unit), p.corrections)
        plan_values = Planning(carryover=carryover, backlog=backlog, corrections=corrections)
    _explain("forecast_ist")
    default = s.commitment
    if default is None and plan_values is not None and plan_values.committed:
        default = plan_values.committed
        console.print(f"[dim]{t('Prefilled with carry-over + backlog.')}[/dim]")
    apply_planning(s, _ask_number(t("Commitment ({unit})", unit=unit), default), plan_values)
    refreeze = False
    if offer := refreeze_offer(s, fc.entry(s.id)):
        refreeze = Confirm.ask(
            t(
                (
                    "The frozen Forecast PLAN ({frozen}) differs from the current one "
                    "({current}). Freeze again?"
                ),
                frozen=fmt(offer[0]),
                current=fmt(offer[1]),
            ),
            default=False,
            console=console,
        )
    freeze_plan(s, fc.entry(s.id), c.today, refreeze=refreeze)
    _refuse_invalid(c, before, _with_sprint(data, s), "sprints/")
    path = c.repo.save_sprint(team, s)
    _saved(path)
    fc = build_forecast(_load(c, team), c.today)
    if (e := fc.entry(s.id)) and e.result.planning_total is not None:
        delta = e.result.planning_delta or 0.0
        colour = "green" if delta >= 0 else "red"
        console.print(
            t(
                (
                    "Planning total {total} {unit} · Forecast PLAN {plan} {unit} · "
                    "[{colour}]delta {delta} {unit}[/{colour}]"
                ),
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
        t("{team} {id}: planning recorded", team=data.team.name, id=s.id),
        None,
        commit_,
    )


@command("review", "Record the sprint review: velocity, scope creep; freezes the capacity.")
def review(
    ctx: typer.Context,
    team: TeamArg,
    sprint: SprintArg = None,
    commit_: Annotated[
        bool, typer.Option("--commit", help=t("Commit and set tag TEAM/SPRINT."))
    ] = False,
) -> None:
    c = _ctx(ctx)
    data = _load(c, team)
    fc = build_forecast(data, c.today)
    s = _find_or_create(data, fc, sprint, "review")
    before = copy.deepcopy(data)  # the sprint is changed in place below
    unit = data.team.unit.value
    console.print(
        Panel(
            f"Review Sprint [bold]{_plain_end(s.id)}[/bold] ({s.start:%d.%m.} – {s.end:%d.%m.%Y})"
        )
    )
    if s.capacity is None:
        if data.people:
            frozen = sprint_capacity(data.team, data.people, s).rounded
            console.print(
                t(
                    "Capacity according to people list and absences: [bold]{capacity} PT[/bold]",
                    capacity=fmt_capacity(frozen, data.team.capacity.rounding),
                )
            )
            if not Confirm.ask(
                t("Is that correct (otherwise correct the absences)?"),
                default=True,
                console=console,
            ):
                frozen = _ask_number(t("Actual capacity (PT)"), frozen, allow_empty=False)
        else:
            _explain("capacity")
            frozen = _ask_number(t("Capacity (PT)"), None, allow_empty=False)
        s.capacity = frozen
    _explain("velocity")
    s.velocity = _ask_number(f"Velocity ({unit})", s.velocity)
    _explain("scope_creep")
    s.scope_creep = _ask_number(t("Scope creep (share 0–1)"), s.scope_creep)
    if (
        data.team.features.products
        and data.products
        and Confirm.ask(t("Record done per product?"), default=True, console=console)
    ):
        _ask_product_values(data, fc, s, "done")
    _refuse_invalid(c, before, _with_sprint(data, s), "sprints/")
    path = c.repo.save_sprint(team, s)
    _saved(path)
    _maybe_commit(
        c,
        team,
        [path],
        t("{team} {id}: review recorded", team=data.team.name, id=s.id),
        f"{team}/{s.id}",
        commit_,
    )


@command("forecast", "Show the forecast for the current and the coming sprints.")
def forecast(
    ctx: typer.Context,
    team: TeamArg,
    history: Annotated[
        int,
        typer.Option("--history", min=0, help=t("Number of past sprints shown.")),
    ] = 5,
    explain: Annotated[
        str | None,
        typer.Option(
            "--explain",
            help=t(
                'Show the calculation (formulas with numbers) of a sprint; "-" = next planning.'
            ),
        ),
    ] = None,
) -> None:
    c = _ctx(ctx)
    fc = build_forecast(_load(c, team), c.today)
    team_ = fc.data.team
    unit = team_.unit.value
    table = Table(
        title=t(
            "Sprint forecast {team} (as of {day})",
            team=_plain(team_.name),
            day=f"{c.today:%d.%m.%Y}",
        )
    )
    columns = [
        "Sprint",
        t("Period"),
        "Status",
        t("Capacity PT"),
        "Velocity",
        t("norm. vel. (Ø/trend)"),
        f"Forecast PLAN {unit}",
        t("Range"),
        t("Plannable"),
        t("Small items"),
    ]
    for i, col in enumerate(columns):
        # never truncate in the middle of a number: let the others wrap instead
        band = col == t("Range")
        table.add_column(
            col, justify="left" if i < 3 else "right", no_wrap=band, min_width=9 if band else None
        )
    for e in fc.history(history) + fc.upcoming():
        r = e.result
        future = e.sprint.end > c.today
        n_vel = r.normalized_velocity.trend if future else r.normalized_velocity.average
        table.add_row(
            _plain(e.sprint.id),
            period(e),
            status(fc, e).replace("**", ""),
            capacity_label(e) if future else fmt_capacity(r.capacity.value, e.capacity_digits),
            fmt(r.velocity.value, 2),
            fmt(n_vel, 2),
            f"[bold]{fmt(r.plan)}[/bold]" if future else fmt(r.plan),
            band_range(fc, e) if future else "",
            fmt(r.roadmap, 2) if future else "",
            fmt(r.small_stuff, 2) if future else "",
            style=None if future else "dim",
        )
    console.print(table)
    if any(e.result.plan_capacity_source in UNSURE_SOURCES for e in fc.upcoming()):
        console.print(
            "[yellow]"
            + t(
                (
                    "⚠ Trend/calendar = no absences known, capacity estimated. More reliable "
                    "with: {command}"
                ),
                command=_plain(f"sprintforecast absences {team} <SPRINT>"),
            )
            + "[/yellow]"
        )
    for note in reliability_notes(fc, code=False):
        console.print(f"[yellow]⚠ {escape(note)}[/yellow]")
    if explain is not None:
        from sprintforecast.formulas import steps

        default = fc.default_entry("planning")
        entry = default if explain == "-" else fc.entry(explain)
        if entry is None:
            err.print(f"[red]{t('Sprint {id} is not in the forecast.', id=_plain(explain))}[/red]")
            raise typer.Exit(1)
        from sprintforecast.formulas import plain_explanation

        console.print(escape(plain_explanation(fc, entry, note=False)).replace("**", ""))
        table = Table(
            title=t("Calculation sprint {id}", id=_plain(entry.sprint.id)), show_lines=True
        )
        for col in ("Metric", "Formula", "Calculation"):
            table.add_column(t(col))
        for step in steps(fc, entry, note=False):
            table.add_row(
                f"[bold]{step.name}[/bold]", escape(step.formula), escape(step.calculation)
            )
        console.print(table)
    else:
        console.print(f"[dim]{t('Calculation of a sprint: --explain SPRINT (or - )')}[/dim]")


def _finite_option(value: float | None) -> float | None:
    """Typer check: nan and inf are not numbers one could calculate with."""
    if value is not None and not math.isfinite(value):
        raise typer.BadParameter(t("Please enter a finite number."))
    return value


@command(
    "analysis",
    "Supplementary analyses: spread, focus factor, buffer, completion (--remaining).",
)
def analyse(
    ctx: typer.Context,
    team: TeamArg,
    rest: Annotated[
        float | None,
        typer.Option(
            "--remaining",
            callback=_finite_option,
            help=t("Remaining amount for which the completion sprint is estimated."),
        ),
    ] = None,
    total: Annotated[
        bool,
        typer.Option(
            "--total",
            help=t("Use the entire forecast for --remaining instead of only the plannable share."),
        ),
    ] = False,
    share_percent: Annotated[
        float,
        typer.Option(
            "--share",
            min=1,
            max=100,
            callback=_finite_option,
            help=t(
                "Project share in %: which part of the plannable share or total capacity "
                "goes into the remaining amount (default 100)."
            ),
        ),
    ] = 100.0,
) -> None:
    from sprintforecast.analysis import (
        available_count,
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

    table = Table(
        title=t("Range {team} – in addition to the Forecast PLAN", team=_plain(data.team.name))
    )
    for i, col in enumerate(
        ("Sprint", f"Forecast PLAN {unit}", t("conservative"), t("medium"), t("optimistic"))
    ):
        table.add_column(col, justify="left" if i == 0 else "right")
    for e in fc.upcoming():
        b = band(fc, e)
        table.add_row(
            _plain(e.sprint.id),
            fmt(e.result.plan),
            *(fmt(v) for v in ((b.low, b.mid, b.high) if b else (None, None, None))),
        )
    console.print(table)
    console.print(
        "[dim]"
        + t(
            (
                "conservative/median/optimistic = lowest/median/highest normalized velocity of "
                "the last {window} sprints × capacity."
            ),
            window=data.team.forecast.window,
        )
        + "[/dim]"
    )

    focus = Table(title=t("Focus factor (velocity / capacity)"))
    focus.add_column("Sprint")
    focus.add_column(t("Focus factor"), justify="right")
    for e in fc.history(data.team.forecast.window):
        focus.add_row(_plain(e.sprint.id), fmt(focus_factor(e), 2))
    focus.add_row("[bold]Ø[/bold]", f"[bold]{fmt(average_focus_factor(fc), 2)}[/bold]")
    console.print(focus)

    hint = buffer_hint(fc)
    if hint.average_scope_creep is None:
        console.print(t("Buffer: scope creep was not recorded recently – no recommendation."))
    else:
        colour = "yellow" if hint.buffer_too_small else "green"
        verdict = (
            t("buffer smaller than the unplanned share")
            if hint.buffer_too_small
            else t("fine")
            if hint.sufficient_data
            else t("too few values for a recommendation")
        )
        console.print(
            t(
                (
                    "Buffer: Ø scope creep {scope} of the commitment = {late} of the Forecast "
                    "PLAN ({count} sprints), small-items share {small} – "
                ),
                scope=pct(hint.average_scope_creep),
                late=pct(hint.average_late_share),
                count=hint.samples,
                small=pct(hint.configured_small_stuff),
            )
            + f"[{colour}]{verdict}[/{colour}]"
        )

    if rest is not None:
        basis_share = 1.0 if total else data.team.forecast.roadmap_share
        share = basis_share * share_percent / 100
        result = completion(data, c.today, rest, share)
        if result is None:
            err.print(f"[red]{t('Not enough history for a completion forecast.')}[/red]")
            raise typer.Exit(1)
        basis = (
            t("entire forecast") if total else t("plannable share {share}", share=pct(basis_share))
        )
        if share_percent < 100:
            basis += t(
                " × project share {project} % = {share} of the forecast",
                project=fmt(share_percent, 0),
                share=pct(share),
            )
        later = t(
            "later than {last} ({count} sprints)",
            last=_plain(result.sprints[-1]) if result.sprints else "–",
            count=len(result.sprints),
        )
        console.print(
            t(
                (
                    "Completion of {rest} {unit} ({basis}, from the next sprint): in 50 % of "
                    "the simulations by [bold]{p50}[/bold], in 85 % by [bold]{p85}[/bold] "
                    "(model-dependent frequency, sample of {samples} sprints; ≈ {per_sprint} "
                    "{unit} per sprint)."
                ),
                rest=fmt(rest, 1),
                unit=unit,
                basis=basis,
                p50=_plain_end(result.p50) if result.p50 else later,
                p85=_plain_end(result.p85) if result.p85 else later,
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
                + t(
                    "Calculated with Ø capacity because there is no people list: {sprints}",
                    sprints=_plain_end(listed),
                )
                + "[/dim]"
            )
        if note := completion_note(result.samples):
            hint = window_hint(
                data.team.forecast.window, result.samples, available_count(fc), simulation=True
            )
            note = f"{note} {hint}".strip()
            console.print(f"[yellow]⚠ {escape(note)}[/yellow]")


@command("report", "Create the Markdown report (for the Git web interface / PO round).")
def report_command(
    ctx: typer.Context,
    team: Annotated[str | None, typer.Argument(help=t("Team; omit for all teams."))] = None,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help=t("File; default <team>/FORECAST.md, - = stdout."),
        ),
    ] = None,
) -> None:
    c = _ctx(ctx)
    teams = [team] if team else c.repo.teams()
    for key in teams:
        data = _load(c, key)
        try:
            forecast_ = build_forecast(data, c.today)
        except DataError as e:  # without a team argument the loop runs over all teams
            if key in str(e):
                raise
            raise DataError(t("Team {team}: {error}", team=key, error=e)) from e
        text = render(forecast_)
        if output is not None and str(output) == "-":
            sys.stdout.write(text)
            continue
        target = output if output is not None and team else c.repo.team_dir(key) / "FORECAST.md"
        write_text(target, text)
        console.print(f"[green]{_plain_end(target)}[/green]")


@command(
    "excel",
    "Excel-Liste eines Teams schreiben (Formeln, Trend-Diagramm, Aufteilung je Produkt).",
)
def excel(
    ctx: typer.Context,
    team: Annotated[str, typer.Argument(help=t("Team."))],
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help=t(
                "File; default <team>-forecast.xlsx in the current folder (not in the data "
                "folder: spreadsheets are not committed)."
            ),
        ),
    ] = None,
) -> None:
    from sprintforecast.excel import ExcelUnavailable, build_workbook, import_unsafe_sprint_ids

    c = _ctx(ctx)
    data = _load(c, team)
    for warning in import_unsafe_sprint_ids(data):
        err.print(f"[yellow]{escape(warning)}[/yellow]")
    try:
        content = build_workbook(build_forecast(data, c.today))
    except ExcelUnavailable as e:
        err.print(f"[red]{escape(str(e))}[/red]")
        raise typer.Exit(1) from e
    target = output or Path(f"{team}-forecast.xlsx")
    try:
        target.write_bytes(content)
    except OSError as e:
        raise DataError(t("{path}: not written ({reason})", path=target, reason=e)) from e
    console.print(f"[green]{_plain_end(target)}[/green]")


@command(
    "excel-import",
    "Read an Excel list back from the Excel output: preview the changes, write them with --apply.",
)
def excel_import(
    ctx: typer.Context,
    team: Annotated[str, typer.Argument(help=t("Team."))],
    file: Annotated[
        Path, typer.Argument(metavar="FILE", help=t("Excel file from “sprintforecast excel”."))
    ],
    apply: Annotated[
        bool,
        typer.Option("--apply", help=t("Write the changes (otherwise preview only).")),
    ] = False,
) -> None:
    from sprintforecast.excel import ExcelUnavailable
    from sprintforecast.excel_import import apply_import, plan_import, read_workbook_keyed

    c = _ctx(ctx)
    try:
        data, file_team = read_workbook_keyed(file, team)
    except ExcelUnavailable as e:
        err.print(f"[red]{escape(str(e))}[/red]")
        raise typer.Exit(1) from e
    if file_team is None:
        warning = t(
            (
                "The workbook names no team (older Excel export); it is not checked whether it "
                "belongs to {team}."
            ),
            team=repr(team),
        )
        err.print(f"[yellow]{escape(warning)}[/yellow]")
    plan = plan_import(c.repo, data, c.today)
    if not plan.changes:
        console.print(t("No changes compared to the existing files."))
        return
    table = Table(t("File"), t("Value"), t("before"), t("new"))
    for change in plan.changes[:200]:
        table.add_row(
            _plain(change.file),
            _plain(change.path),
            _plain("–" if change.old is None else change.old),
            _plain("–" if change.new is None else change.new),
        )
    console.print(table)
    if len(plan.changes) > 200:
        console.print(t("… and {count} more changes", count=len(plan.changes) - 200))
    for name in plan.untouched:
        note = t("Not in the workbook, stays unchanged: {file}", file=_plain(name))
        console.print(f"[dim]{note}[/dim]")
    if not apply:
        console.print(t("Preview only – write with --apply."))
        return
    for path in apply_import(c.repo, plan):
        console.print(f"[green]{_plain_end(path)}[/green]")


def _ticket_note(change: Any) -> str:
    """Readable text for the ``note`` of a change of the import preview."""
    from sprintforecast.ticket_import import DROPPED_ENDED, UNCLEAR_NO_ESTIMATE, UNCLEAR_RULE

    note = change.note
    if not note:
        return ""
    if change.kind == "sprint_unresolved":
        return t('Sprint name "{name}"', name=_plain(note))
    if change.kind == "changed":
        return {"estimate": t("Estimate"), "remaining": t("Remaining")}.get(note, _plain(note))
    if change.kind == "refined_unclear":
        if note == UNCLEAR_RULE:
            return t("only via refined_also_if, label missing")
        if note == UNCLEAR_NO_ESTIMATE:
            return t("label without estimate")
    if change.kind == "earmark_dropped" and note == DROPPED_ENDED:
        return t("sprint ended")
    if change.kind == "missing":
        return t("earmark for sprint {sprint} stays", sprint=_plain(note))
    return _plain(note)


def _ticket_preview(plan: Any, limit: int = 15) -> None:
    """Shows what an import would change, grouped by kind (spec section 6.5)."""
    from sprintforecast.ticket_import import KINDS

    titles = {
        "new": t("New tickets"),
        "changed": t("Changed numbers"),
        "done": t("Done"),
        "missing": t("No longer in the import"),
        "unassigned": t("Not assigned to a project yet"),
        "unknown_epic": t("Unknown epics (candidates for a new project)"),
        "refined_unclear": t("Refined status unclear"),
        "earmark_dropped": t("Earmark dropped"),
        "earmark_from_label": t("Earmark taken from the label planned_for_…"),
        "sprint_unresolved": t(
            "Sprint not recognised (map it under tracker.sprint_names in team.yaml)"
        ),
    }
    for kind in KINDS:
        rows = plan.of_kind(kind)
        if not rows:
            continue
        table = Table(
            t("Ticket"), t("Title"), t("before"), t("new"), t("Notice"),
            title=f"{titles[kind]} ({len(rows)})",
        )  # fmt: skip
        for row in rows[:limit]:
            old = _plain(row.old if row.old not in (None, [], "") else "–")
            new = _plain(row.new if row.new not in (None, [], "") else "–")
            table.add_row(_plain(row.key), _plain(row.title), old, new, _ticket_note(row))
        console.print(table)
        if len(rows) > limit:
            console.print(t("… and {count} more", count=len(rows) - limit))
    for warning in plan.warnings:
        console.print(f"[yellow]{_plain(warning)}[/yellow]")


# The variants of the distribution (spec section 5.5), for the option --variant (not imported
# from preplan: the module loads only when the feature is used).
VARIANT_CHOICES = ("median", "conservative", "optimistic")


def _check_variant(value: str) -> str:
    if value not in VARIANT_CHOICES:
        raise typer.BadParameter(t("Variant expected: median, conservative or optimistic"))
    return value


def _no_tickets(data: TeamData) -> bool:
    """Says how to import when there are no tickets; True = there are none."""
    if data.tickets:
        return False
    how = "--fetch" if data.team.tracker.kind == "jira" else "--import DATEI"
    console.print(
        t(
            "No tickets yet – import first: sprintforecast tickets TEAM {how}",
            how=how,
        )
    )
    return True


def _no_budget_warning() -> None:
    console.print(
        "[yellow]"
        + t(
            "No budget yet: without past sprints with velocity there is no forecast, so "
            "the tickets cannot be distributed."
        )
        + "[/yellow]"
    )


def _print_ticket_issues(data: TeamData, today: date, printed: list[Issue] | None = None) -> None:
    """Check results of the ticket files (e.g. an earmark that exceeds its sprint); ``printed``
    are check results already shown (they are not printed twice)."""
    for issue in issues_for(data, today, ["projects.yaml", "tickets.yaml", "preplan.yaml"]):
        if printed and issue in printed:
            continue
        colour = "red" if issue.level is Level.ERROR else "yellow"
        console.print(
            f"[{colour}]{issue.level.label}[/{colour}] {_plain(issue.where)}: "
            f"{_plain(issue.message)}"
        )


def _ticket_report(
    data: TeamData,
    today: date,
    sprint_count: int,
    printed: list[Issue] | None = None,
    variant: str = "median",
) -> None:
    """Distribution of the tickets: project traffic light with the range of the variants,
    sprints, refinement list. ``variant`` selects the distribution of the sprint table and the
    refinement list; the project table shows the median variant and the range. ``printed`` are
    check results already printed (they are not printed twice)."""
    from sprintforecast.preplan import (
        LIGHTS,
        REASONS,
        SOURCES,
        VARIANT_NAMES,
        Variant,
        distribute_variants,
        project_range,
    )

    if _no_tickets(data):
        return
    _print_ticket_issues(data, today, printed)
    variants = distribute_variants(data, today)
    dist = variants.median
    if dist.no_forecast:
        _no_budget_warning()
    if not variants.available:
        console.print(
            "[yellow]"
            + t("No range: fewer than two sprints with velocity. Only the median variant is shown.")
            + "[/yellow]"
        )
    # Sprint table, refinement list and open points follow the chosen variant.
    shown = variants.get(variant) or dist
    if shown is dist and variant != "median":
        console.print(
            "[yellow]"
            + t(
                "The {variant} variant is not available (no range) – showing the median.",
                variant=t(VARIANT_NAMES[variant]),
            )
            + "[/yellow]"
        )
    colours = {"on_track": "green", "tight": "yellow", "missed": "red", "empty": "dim"}
    last = (
        [t("Last sprint optimistic"), t("Last sprint median"),
         t("Last sprint conservative")]
        if variants.available
        else [t("Last sprint")]
    )  # fmt: skip
    projects = Table(
        t("Project"), t("Target"), t("Target sprint"), *last, t("Traffic light"), t("Outstanding"),
        t("Not distributable"),
        title=t("Projects"),
    )  # fmt: skip
    for row in dist.projects:
        project = data.project(row.project)
        name = project.name if project else row.project
        target = f"{project.target:%d.%m.%Y}" if project and project.target else "–"
        light = f"[{colours[row.light]}]{t(LIGHTS[row.light])}[/{colours[row.light]}]"
        if variants.available:
            span = project_range(variants, row.project)
            if not span.uniform:
                best, worst = (t(LIGHTS[x]) for x in span.light_range)
                light += f" [dim]({best} – {worst})[/dim]"
            sprints_ = [span.last_sprint[v] for v in (Variant.OPTIMISTIC, Variant.MEDIAN,
                                                      Variant.CONSERVATIVE)]  # fmt: skip
        else:
            sprints_ = [row.last_sprint]
        projects.add_row(
            _plain(name), target, _plain(row.target_sprint or "–"),
            *(_plain(sprint or "–") for sprint in sprints_), light, str(row.open_tickets),
            str(row.not_distributable),
        )  # fmt: skip
    console.print(projects)
    if shown is not dist:
        console.print(
            "[dim]"
            + t(
                (
                    "Sprints, refinement list and tickets that cannot be distributed: "
                    "{variant} variant"
                ),
                variant=t(VARIANT_NAMES[shown.variant.value]),
            )
            + "[/dim]"
        )
    dist = shown

    names = {tk.key: tk for tk in data.tickets}
    sprints = Table(
        t("Sprint"), t("Budget"), t("Used"), t("Free"), t("Tickets"), title=t("Sprints")
    )
    for sprint_id in dist.sprints[:sprint_count]:
        cells = [b for b in dist.budgets if b.sprint == sprint_id]
        base = sum(b.base for b in cells)
        used = sum(b.fixed + b.placed for b in cells)
        keys = ", ".join(
            f"{p.ticket} ({fmt_plain(p.size)})" if p.size is not None else p.ticket
            for p in dist.in_sprint(sprint_id)
        )
        sprints.add_row(
            _plain(sprint_id), fmt_plain(base), fmt_plain(used), fmt_plain(base - used),
            _plain(keys or "–"),
        )  # fmt: skip
    console.print(sprints)

    refine = Table(t("Sprint"), t("Latest by"), t("Ticket"), t("Estimate"),
                   title=t("To refine"))  # fmt: skip
    shown = [r for r in dist.refinement if r.sprint in dist.sprints[:sprint_count]]
    for item in shown:
        ticket = names.get(item.ticket)
        title = ticket.title if ticket else ""
        refine.add_row(
            _plain(item.sprint), f"{item.deadline:%d.%m.%Y}",
            _plain(f"{item.ticket} {title}".strip()), t(SOURCES[item.source.value]),
        )  # fmt: skip
    if shown:
        console.print(refine)

    open_ = dist.not_distributable()
    if open_:
        table = Table(t("Ticket"), t("Reason"), title=t("Not distributable"))
        for p in open_:
            table.add_row(_plain(p.ticket), t(REASONS[p.reason]))
        console.print(table)
    if dist.unclear:
        console.print(
            t(
                "Refined status unclear (counts as rough): {keys}",
                keys=_plain(", ".join(dist.unclear)),
            )
        )
    for cycle in dist.cycles:
        console.print(f"[red]{t('circular dependencies')}: {_plain(' → '.join(cycle))}[/red]")


def _given(ctx: typer.Context, name: str) -> bool:
    """Was this option given on the command line (rather than left at its default)?"""
    source = ctx.get_parameter_source(name)
    return source is not None and source.name == "COMMANDLINE"


def _source_failed(error: Exception) -> typer.Exit:
    """Prints a source error (no markup interpretation) and returns the exit to raise."""
    err.print(f"[red]{_plain_end(error)}[/red]")
    return typer.Exit(1)


def _close_source(source: Any) -> None:
    close = getattr(source, "close", None)
    if close is not None:
        close()


def _jira_settings(data: TeamData, option: str) -> Any:
    """The tracker settings of a team that uses Jira; ends the command otherwise."""
    tracker = data.team.tracker
    if tracker.kind != "jira":
        err.print(
            "[red]"
            + t(
                "{option} needs tracker.kind: jira in team.yaml (currently: {kind}).",
                option=option,
                kind=_plain(tracker.kind),
            )
            + "[/red]"
        )
        raise typer.Exit(1)
    return tracker


def _ticket_set_token(data: TeamData) -> None:
    """Asks for the token (hidden input) and stores it in the keychain."""
    from sprintforecast.sources import SourceError
    from sprintforecast.sources.jira import (
        TOKEN_ENV,
        keychain_user,
        keyring_available,
        keyring_missing_error,
        store_token,
    )

    tracker = _jira_settings(data, "--set-token")
    if not tracker.base_url:
        err.print(f"[red]{t('tracker.base_url is missing (team.yaml)')}[/red]")
        raise typer.Exit(1)
    try:
        user = keychain_user(tracker.base_url)  # an unusable address fails before the prompt
    except SourceError as e:
        raise _source_failed(e) from e
    if not keyring_available():
        raise _source_failed(keyring_missing_error())
    if os.environ.get(TOKEN_ENV, "").strip():
        console.print(
            "[yellow]"
            + t(
                "Note: {variable} is set and takes precedence over the keychain.",
                variable=TOKEN_ENV,
            )
            + "[/yellow]"
        )
    token = typer.prompt(t("Jira token (the input stays hidden)"), hide_input=True)
    try:
        store_token(tracker.base_url, token.strip())
    except SourceError as e:
        raise _source_failed(e) from e
    console.print(
        "[green]"
        + t(
            "Token for {host} stored in the keychain. Check it with: {command}",
            host=_plain(user),
            command=_plain_end(f"sprintforecast tickets {data.team.key} --test-connection"),
        )
        + "[/green]"
    )


def _ticket_test_connection(data: TeamData) -> None:
    """Connects to Jira, shows the account and the resolved fields; writes nothing."""
    from sprintforecast import sources
    from sprintforecast.sources import SourceError

    tracker = _jira_settings(data, "--test-connection")
    source = None
    try:
        source = sources.open_source(tracker)
        name = source.test_connection()  # type: ignore[attr-defined]
        resolved = source.resolve_fields()  # type: ignore[attr-defined]
    except SourceError as e:
        raise _source_failed(e) from e
    finally:
        _close_source(source)
    console.print(
        "[green]"
        + t(
            "Connected to {host} as {name}.",
            host=_plain(getattr(source, "host", "")),
            name=_plain(name),
        )
        + "[/green]"
    )
    for setting, field_id in (
        ("estimate", resolved.estimate),
        ("remaining", resolved.remaining),
        ("epic", resolved.epic),
    ):
        label = getattr(tracker.fields, setting)
        if label:
            console.print(
                t("Field {setting}: “{name}” is {id}", setting=setting, name=_plain(label),
                  id=_plain(field_id))
            )  # fmt: skip
    console.print(
        t(
            "Sprint field: {sprint} · rank field: {rank}",
            sprint=_plain(", ".join(resolved.sprint) or "–"),
            rank=_plain(", ".join(resolved.rank) or "–"),
        )
    )


def _ticket_read(data: TeamData, file: Path | None, fetch: bool) -> tuple[list[Any], str]:
    """Reads the tickets from the CSV file or the tracker: ``(raw tickets, source name)``.
    Ends the command on a source error."""
    from sprintforecast import sources
    from sprintforecast.sources import SourceError

    tracker = data.team.tracker
    if fetch:
        _jira_settings(data, "--fetch")
    source = None
    try:
        source = sources.open_source(tracker, file)
        raws = source.fetch()
    except SourceError as e:
        raise _source_failed(e) from e
    finally:
        _close_source(source)
    name = str(source.name)  # type: ignore[union-attr]
    if fetch:
        console.print(
            t(
                "Jira {host}: {count} tickets read",
                host=_plain(getattr(source, "host", "")),
                count=len(raws),
            )
        )
        if not raws and data.tickets:
            # "No result" never counts as "no work": do not wipe the last import.
            err.print(
                "[red]"
                + t(
                    "The query returned no tickets – nothing written. Check the JQL "
                    "(tracker.query) and the permissions of the token."
                )
                + "[/red]"
            )
            raise typer.Exit(1)
    return raws, name


def _ticket_handover(
    c: Context,
    data: TeamData,
    team: str,
    sprint_count: int,
    apply: bool,
    overwrite: bool,
    commit_: bool,
) -> None:
    """Proposes the sums of the placed tickets per sprint and product (median variant) as the
    PO pre-planning (``preplanned``); with ``apply`` writes where nothing is entered yet (or the
    same is), with ``overwrite`` everywhere."""
    from sprintforecast.preplan import distribute, handover_rows

    _require_products(data, team)
    if not data.products:
        err.print(
            "[red]"
            + t(
                "No products recorded. First: {command}",
                command=_plain_end(f"sprintforecast product-list {team}"),
            )
            + "[/red]"
        )
        raise typer.Exit(1)
    if _no_tickets(data):
        return
    _print_ticket_issues(data, c.today)
    dist = distribute(data, c.today)
    if dist.no_forecast:
        _no_budget_warning()
    rows = handover_rows(data, dist, sprint_count)
    if not rows:
        console.print(t("Nothing to hand over: no ticket is distributed in the sprints shown."))
        return
    names = {p.id: p.name for p in data.products}
    notes = {
        "write": t("will be written") if apply else t("new"),
        "same": t("unchanged"),
        "keep": t("PO value stays (--overwrite replaces it)"),
        "overwrite": t("will be replaced") if apply else t("would be replaced (--overwrite)"),
    }
    table = Table(
        t("Sprint"), t("Product"), measure_label("preplanned"), t("Proposal"), t("Notice"),
        title=t("Handover to the PO pre-planning (median variant)"),
    )  # fmt: skip
    for row in rows:
        table.add_row(
            _plain(row.sprint), _plain(names.get(row.product, row.product)),
            fmt_plain(row.current) if row.current is not None else "–", fmt_plain(row.proposed),
            notes[row.action(overwrite)],
        )  # fmt: skip
    console.print(table)
    writable = [r for r in rows if r.writes(overwrite)]
    if not apply:
        console.print(t("Preview only – write with --apply."))
        return
    if not writable:
        console.print(t("Nothing to write: the PO pre-planning is already in place."))
        return
    fc = build_forecast(data, c.today)
    changed: dict[str, Sprint] = {}
    for row in writable:
        # A sprint that exists only in the calendar gets its file here, like `products`.
        sprint = changed.get(row.sprint) or copy.deepcopy(
            _find_or_create(data, fc, row.sprint, "planning")
        )
        values = sprint.products.get(row.product, ProductValues())
        values.preplanned = row.proposed
        sprint.products[row.product] = values
        changed[row.sprint] = sprint
    # The sprint sequence must stay gapless: also create the calendar-only sprints in between.
    pending = {sid for sid in changed if data.sprint(sid) is None}
    last = data.sprints[-1] if data.sprints else None
    while pending:
        last = following_sprint(data.team, last)
        pending.discard(last.id)
        if data.sprint(last.id) is None:
            changed.setdefault(last.id, last)
    after = data
    for sprint in changed.values():
        after = _with_sprint(after, sprint)
    _refuse_invalid(c, data, after, "sprints/")
    paths = [c.repo.save_sprint(team, sprint) for sprint in changed.values()]
    _saved(", ".join(p.name for p in paths))
    _maybe_commit(
        c, team, paths, t("{team}: PO pre-planning from the tickets", team=data.team.name),
        None, commit_,
    )  # fmt: skip


def _ticket_write_labels(c: Any, data: TeamData, apply: bool) -> None:
    """Preview, and with ``apply`` the write, of the ``planned_for_<sprint_id>`` labels
    (spec section 6.6). Reads the tickets fresh so that the labels are current; changes only
    labels of the tickets listed in the preview."""
    from sprintforecast import sources
    from sprintforecast.label_writeback import apply_label_writes, plan_label_writes
    from sprintforecast.sources import SourceError
    from sprintforecast.ticket_import import plan_import

    tracker = _jira_settings(data, "--write-labels")
    if not tracker.write_labels:
        err.print(
            "[red]" + t("--write-labels needs tracker.write_labels: true in team.yaml.") + "[/red]"
        )
        raise typer.Exit(1)
    source = None
    try:
        source = sources.open_source(tracker)
        raws = source.fetch()
        if not raws:
            raise SourceError(
                t(
                    "The query returned no tickets – nothing written. Check the JQL "
                    "(tracker.query) and the permissions of the token."
                )
            )
        fc = build_forecast(data, c.today)
        import_plan = plan_import(data, fc, raws, c.today, adopt_labels=False)
        plan = plan_label_writes(import_plan.tickets, import_plan.preplan)
        for warning in plan.warnings:
            console.print(f"[yellow]{_plain(warning)}[/yellow]")
        if not plan.writes:
            console.print(t("No label changes needed."))
            return
        table = Table(t("Ticket"), t("Title"), t("Add label"), t("Remove label"))
        for write in plan.writes:
            table.add_row(
                _plain(write.key),
                _plain(write.title),
                _plain(", ".join(write.add) or "–"),
                _plain(", ".join(write.remove) or "–"),
            )
        console.print(table)
        if not apply:
            console.print(t("Preview only – write to Jira with --apply."))
            return
        written = apply_label_writes(source, plan)
    except SourceError as e:
        raise _source_failed(e) from e
    finally:
        _close_source(source)
    console.print(
        t("{count} tickets changed in Jira. Then run --fetch --apply to read the new state.",
          count=written)
    )  # fmt: skip


@command(
    "tickets",
    (
        "Ticket pre-planning: read tickets from Jira or a CSV file, distribute them over "
        "future sprints, project traffic light with range and refinement list; hand over to "
        "the PO pre-planning."
    ),
)
def tickets(
    ctx: typer.Context,
    team: TeamArg,
    file: Annotated[
        Path | None,
        typer.Option(
            "--import",
            metavar="FILE",
            help=t("Read a CSV export of the ticket system (preview); also possible with Jira."),
        ),
    ] = None,
    fetch: Annotated[
        bool,
        typer.Option(
            "--fetch",
            help=t("Read the tickets from Jira (tracker.kind: jira, read-only; preview)."),
        ),
    ] = False,
    test_connection: Annotated[
        bool,
        typer.Option(
            "--test-connection",
            help=t(
                "Check the connection to Jira and show the account of the token (writes nothing)."
            ),
        ),
    ] = False,
    set_token: Annotated[
        bool,
        typer.Option(
            "--set-token",
            help=t("Store the Jira token (hidden input) in the keychain."),
        ),
    ] = False,
    handover: Annotated[
        bool,
        typer.Option(
            "--handover",
            help=t(
                "Propose the sums of the distributed tickets per sprint and product as the "
                "PO pre-planning (median variant; write with --apply)."
            ),
        ),
    ] = False,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite",
            help=t("With --handover, also replace PO pre-planning that is already entered."),
        ),
    ] = False,
    variant: Annotated[
        str,
        typer.Option(
            "--variant",
            callback=_check_variant,
            help=t(
                "Variant for the sprint table and the refinement list: median (Forecast "
                "PLAN), conservative or optimistic."
            ),
        ),
    ] = "median",
    write_labels: Annotated[
        bool,
        typer.Option(
            "--write-labels",
            help=t(
                "Write earmarks to Jira as the label planned_for_<sprint> "
                "(tracker.write_labels; preview, write with --apply)."
            ),
        ),
    ] = False,
    apply: Annotated[
        bool,
        typer.Option("--apply", help=t("Write the import or handover (otherwise preview only).")),
    ] = False,
    commit_: CommitOpt = False,
    sprints: Annotated[
        int, typer.Option("--sprints", min=1, help=t("Number of future sprints shown."))
    ] = 6,
) -> None:
    c = _ctx(ctx)
    data = _load(c, team)
    _require_tickets(data, team)
    actions = [
        name
        for name, given in (
            ("--import", file is not None),
            ("--fetch", fetch),
            ("--test-connection", test_connection),
            ("--set-token", set_token),
            ("--handover", handover),
            ("--write-labels", write_labels),
        )
        if given
    ]
    if len(actions) > 1:
        err.print(
            "[red]" + t("{options} are mutually exclusive.", options=" / ".join(actions)) + "[/red]"
        )
        raise typer.Exit(1)
    if test_connection or set_token:
        refused = [
            name
            for name, given in (
                ("--apply", apply),
                ("--commit", commit_),
                ("--sprints", _given(ctx, "sprints")),
                ("--variant", _given(ctx, "variant")),
                ("--overwrite", overwrite),
            )
            if given
        ]
        if refused:
            err.print(
                "[red]"
                + t(
                    "{options} do not belong to --test-connection and --set-token.",
                    options=" / ".join(refused),
                )
                + "[/red]"
            )
            raise typer.Exit(1)
    if overwrite and not handover:
        err.print(f"[red]{t('--overwrite belongs to --handover.')}[/red]")
        raise typer.Exit(1)
    if handover and _given(ctx, "variant"):
        err.print(
            "[red]"
            + t("--variant does not belong to --handover (it uses the median variant).")
            + "[/red]"
        )
        raise typer.Exit(1)
    if write_labels:
        if commit_ or _given(ctx, "sprints"):
            err.print(
                "[red]"
                + t(
                    "{options} do not go with --write-labels.",
                    options=" / ".join(
                        n
                        for n, g in (("--commit", commit_), ("--sprints", _given(ctx, "sprints")))
                        if g
                    ),
                )
                + "[/red]"
            )
            raise typer.Exit(1)
        _ticket_write_labels(c, data, apply)
        return
    if set_token:
        _ticket_set_token(data)
        return
    if test_connection:
        _ticket_test_connection(data)
        return
    if handover:
        if commit_ and not apply:
            err.print(f"[red]{t('--commit needs --apply.')}[/red]")
            raise typer.Exit(1)
        _ticket_handover(c, data, team, sprints, apply, overwrite, commit_)
        return
    importing = file is not None or fetch
    if importing and commit_ and not apply:
        err.print(f"[red]{t('--commit needs --apply.')}[/red]")
        raise typer.Exit(1)
    printed: list[Issue] = []
    if importing:
        from sprintforecast.ticket_import import apply_import, plan_import

        raws, source_name = _ticket_read(data, file, fetch)
        fc = build_forecast(data, c.today)
        plan = plan_import(data, fc, raws, c.today, source=source_name)
        _ticket_preview(plan)
        if plan.unchanged(data):
            # Nothing to write: no time-stamp-only rewrite of tickets.yaml.
            console.print(t("No changes compared to the existing files."))
        elif not apply:
            console.print(t("Preview only – write with --apply."))
        else:
            paths = apply_import(c.repo, team, plan)
            for path in paths:
                console.print(f"[green]{_plain_end(path)}[/green]")
            printed = _maybe_commit(
                c, team, paths, t("{team}: Tickets imported", team=_plain(data.team.name)),
                None, commit_,
            )  # fmt: skip
            data = _load(c, team)
        if not apply:
            if _given(ctx, "variant"):
                console.print(
                    "[yellow]"
                    + t("--variant takes effect only after writing (with --apply).")
                    + "[/yellow]"
                )
            return
    elif apply or commit_:
        err.print(
            "[red]"
            + t("--apply and --commit belong to --import, --fetch and --handover.")
            + "[/red]"
        )
        raise typer.Exit(1)
    _ticket_report(data, c.today, sprints, printed, variant)


@command("check", "Check all team data for errors and plausibility (for CI and before committing).")
def check_command(
    ctx: typer.Context,
    strict: Annotated[
        bool,
        typer.Option("--strict", help=t("Treat notes as errors too.")),
    ] = False,
) -> None:
    c = _ctx(ctx)
    results = check_all(c.repo, c.today)
    if not results:
        err.print(f"[red]{t('No teams found in {root}', root=_plain_end(c.repo.root))}[/red]")
        raise typer.Exit(1)
    failed = False
    for key, issues in results.items():
        if not issues:
            console.print(f"[green]✔ {_plain_end(key)}[/green]")
            continue
        console.print(f"[bold]{_plain_end(key)}[/bold]")
        for i in issues:
            colour = "red" if i.level is Level.ERROR else "yellow"
            # names from the files can contain control characters (line break, ESC)
            where, message = blank_controls(i.where), blank_controls(i.message)
            console.print(
                f"  [{colour}]{i.level.label}[/{colour}] {_plain(where)}: {_plain(message)}"
            )
            failed |= i.level is Level.ERROR or strict
    raise typer.Exit(1 if failed else 0)


@command("web", "Start the web interface locally (reachable from this computer only).")
def web(
    ctx: typer.Context,
    port: Annotated[
        int,
        typer.Option(min=1, max=65535, help=t("Port; if it is in use, a free one is chosen.")),
    ] = 8501,
    browser: Annotated[
        bool,
        typer.Option(
            help=t("Open the browser automatically; --no-browser opens no window at all.")
        ),
    ] = True,
    app_mode: Annotated[
        bool,
        typer.Option(
            "--app/--no-app",
            help=t(
                "Open as an app in its own window (Edge, Chrome, Comet, Chromium, Brave, "
                "Vivaldi; otherwise Firefox or the default browser). Closing the window "
                "stops the server. With --no-app a browser tab opens instead."
            ),
        ),
    ] = True,
    browser_path: Annotated[
        str | None,
        typer.Option(
            "--browser",
            envvar=BROWSER_ENV,
            help=t("Use this browser for --app (program name or path)."),
        ),
    ] = None,
) -> None:
    import importlib.util

    if importlib.util.find_spec("streamlit") is None:
        err.print(
            "[red]"
            + escape(  # "[web]" is the extra in the command, not markup
                t(
                    "The web interface needs Streamlit: uv tool install "
                    '"sprintforecast[web] @ git+…" or uv sync --extra web'
                )
            )
            + "[/red]"
        )
        raise typer.Exit(1)
    c = _ctx(ctx)
    app_mode = app_mode and browser  # --no-browser: no window, no self-exit
    env = os.environ | {DATA_ENV: str(c.repo.root.resolve())} | updater.web_environment(sys.argv)
    if c.as_of:
        env[AS_OF_ENV] = c.as_of
    if app_mode:
        env[IDLE_ENV] = str(_IDLE_EXIT_SECONDS)  # the server exits by itself without a session
    actual_port = free_port(port)
    if actual_port != port:
        console.print(
            "[yellow]"
            + t("Port {port} is in use – using {actual}.", port=port, actual=actual_port)
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
    for option, value in appsettings.theme_options().items():
        if value:
            cmd_line += [f"--{option}", value]
    console.print(t("Web interface: [bold]{url}[/bold] (stop with Ctrl+C)", url=url))
    popen: dict = popen_options()
    log_handle = None
    if log := os.environ.get(LOG_ENV):
        # Double-click start: no console window, server output goes to the log
        try:
            log_handle = open(log, "a", encoding="utf-8")  # noqa: SIM115
        except OSError as e:
            # Startup must not fail because of the log; without a console the output is
            # lost then, but the UI runs.
            err.print(
                "[yellow]"
                + escape(
                    t(
                        "Log file not writable ({path}): {error}",
                        path=log,
                        error=e.strerror or e,
                    )
                )
                + "[/yellow]"
            )
            popen["stdout"] = popen["stderr"] = subprocess.DEVNULL
        else:
            popen["stdout"] = popen["stderr"] = log_handle
        if sys.platform == "win32":
            popen["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        server = subprocess.Popen(cmd_line, env=env, **popen)
    finally:
        if log_handle is not None:
            log_handle.close()  # the child has its own copy of the handle
    adopt(server)  # everything the server starts later ends with it
    try:
        if app_mode:
            _open_app_window(url, server, browser_path)
        server.wait()
    except KeyboardInterrupt:
        pass
    finally:
        terminate_tree(server)


# If the browser process ends sooner, it probably handed over to a running instance, so the
# server must not be stopped.
_HANDOFF_SECONDS = 5.0
# How long after a browser visit no session may remain connected (idle.py).
_IDLE_EXIT_SECONDS = 20


def _open_app_window(url: str, server: subprocess.Popen, explicit: str | None) -> None:
    """Opens the app window; returns when the server should keep running."""
    if not wait_until_ready(url, server):
        err.print(f"[red]{t('The web interface did not start – see the output above.')}[/red]")
        raise typer.Exit(1)
    try:
        found = find_browser(explicit)
    except FileNotFoundError as e:
        console.print(
            f"[yellow]{t('{error} – searching automatically.', error=_plain(e))}[/yellow]"
        )
        # otherwise find_browser would read the invalid setting again
        os.environ.pop(BROWSER_ENV, None)
        os.environ.pop(BROWSER_ENV.replace("FORESPRINT_", "SPRINTFORECAST_"), None)
        found = find_browser(None)
    match found.kind:
        case BrowserKind.APP:
            console.print(t("Opening {browser} as an app window …", browser=_plain(found.name)))
            started = time.monotonic()
            window = subprocess.Popen(browser_command(found, url))
            adopt(window)
            while window.poll() is None:
                if server.poll() is not None:
                    # server ended (e.g. restart for an update) -> close the window
                    window.terminate()
                    return
                time.sleep(0.5)
            if time.monotonic() - started >= _HANDOFF_SECONDS:
                console.print(t("App window closed – stopping the web interface."))
                raise KeyboardInterrupt
            console.print(
                "[yellow]"
                + t(
                    "The browser was already running and took over the window – the web "
                    "interface keeps running, stop with Ctrl+C."
                )
                + "[/yellow]"
            )
        case BrowserKind.WINDOW:
            console.print(
                t(
                    "No app-capable browser found – opening {browser} (new window).",
                    browser=_plain(found.name),
                )
            )
            subprocess.Popen(browser_command(found, url))
        case BrowserKind.DEFAULT:
            console.print(t("No app-capable browser found – opening the default browser."))
            webbrowser.open(url)
        case BrowserKind.NONE:
            console.print(
                "[yellow]"
                + t("No browser found. Please open {url} in a browser.", url=url)
                + "[/yellow]"
            )


@command("sprints", "Sprint calendar: show and create upcoming sprints and adjust end dates.")
def sprints(
    ctx: typer.Context,
    team: TeamArg,
    count: Annotated[
        int,
        typer.Option(
            "--count", min=1, max=60, help=t("Number of sprints starting with the current one.")
        ),
    ] = 6,
    create: Annotated[
        bool,
        typer.Option("--create", help=t("Create missing sprint files.")),
    ] = False,
    end: Annotated[
        list[str] | None,
        typer.Option(
            "--end",
            help=t(
                "Different last day, e.g. --end 2026.25=2027-01-12 (repeatable); following "
                "sprints shift accordingly."
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
    planned = absence_sprints(data, fc, count)
    rows = calendar_table(data, planned, c.today)
    for raw in end or []:
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
                    "--end {value}: expected SPRINT=YYYY-MM-DD of a sprint shown",
                    value=_plain(raw),
                )
                + "[/red]"
            )
            raise typer.Exit(1)
        row["Last day"] = last
    after, errors = apply_calendar(data, planned, rows)
    for e in errors:
        err.print(f"[red]{_plain_end(e)}[/red]")
    if errors:
        raise typer.Exit(1)
    shown = calendar_table(data, after, c.today)
    table = Table(title=t("Sprint calendar {team}", team=_plain(data.team.name)))
    for col in shown[0]:
        table.add_column(t(col), justify="right" if col == "Working days" else "left")
    for r in shown:
        table.add_row(
            _plain(r["Sprint"]),
            day_label(r["Start"]),
            day_label(r["Last day"]),
            str(r["Working days"]),
            t(r["Status"]),
        )
    table.caption = t(
        (
            "Working days: {week} from the start up to and including the last day (holidays "
            "are only deducted in the capacity). The next sprint starts the day after the last "
            "day."
        ),
        week=workweek_label(data.team),
    )
    console.print(table)
    changed = calendar_to_save(data, planned, after, create_missing=create)
    blocking = [
        i
        for i in check_team(with_sprints(data, changed), c.today)
        if i.level is Level.ERROR and i.where.startswith("sprints/")
    ]
    if blocking:
        for i in blocking:
            err.print(f"[red]{_plain(i.where)}: {_plain_end(i.message)}[/red]")
        raise typer.Exit(1)
    if not changed:
        if not create:
            console.print(f"[dim]{t('Create missing sprint files with --create.')}[/dim]")
        return
    paths = [c.repo.save_sprint(team, s) for s in changed]
    _saved(", ".join(p.name for p in paths))
    _maybe_commit(c, team, paths, t("{team}: sprint calendar", team=data.team.name), None, commit_)


@command(
    "rename-sprint",
    "Change a sprint ID; the saved sprints after it count on from the new ID.",
)
def rename_sprint(
    ctx: typer.Context,
    team: TeamArg,
    sprint: Annotated[str, typer.Argument(help=t("Current sprint ID, e.g. 2026.1."))],
    new: Annotated[str, typer.Argument(help=t("New sprint ID, e.g. 2026.15."))],
    commit_: CommitOpt = False,
) -> None:
    from sprintforecast.renaming import apply_renames, plan_renames

    c = _ctx(ctx)
    data = _load(c, team)
    try:
        renames = plan_renames(data, sprint, new)
    except DataError as e:
        err.print(f"[red]{_plain_end(e)}[/red]")
        raise typer.Exit(1) from e
    if not renames:
        console.print(t("Nothing to change: sprint {id} already has that ID.", id=_plain(sprint)))
        return
    table = Table(title=t("Sprint IDs {team}", team=_plain(data.team.name)))
    for col in ("before", "new", "Start"):
        table.add_column(t(col))
    for r in renames:
        s = data.sprint(r.old)
        assert s is not None
        table.add_row(_plain(r.old), f"[bold]{_plain_end(r.new)}[/bold]", day_label(s.start))
    console.print(table)
    try:
        applied = apply_renames(c.repo, data, renames)
    except DataError as e:
        err.print(f"[red]{_plain_end(e)}[/red]")
        raise typer.Exit(1) from e
    _saved(", ".join(p.name for p in applied.files))
    _maybe_commit(
        c,
        team,
        applied.touched,
        t("{team}: sprint {old} is now {new}", team=data.team.name, old=sprint, new=new),
        None,
        commit_,
    )


@command(
    "products",
    "Distribution across the products: default, PO pre-planning, planning, done, balance.",
)
def products_command(
    ctx: typer.Context,
    team: TeamArg,
    sprint: SprintArg = None,
    preplanning: Annotated[
        bool,
        typer.Option("--preplanning", help=t("Record PO pre-planning per product.")),
    ] = False,
    history: Annotated[
        int, typer.Option("--history", min=1, help=t("Sprints for the balance."))
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
                "No products recorded. First: {command}",
                command=_plain_end(f"sprintforecast product-list {team}"),
            )
            + "[/red]"
        )
        raise typer.Exit(1)
    fc = build_forecast(data, c.today)
    s = copy.deepcopy(_find_or_create(data, fc, sprint, "planning"))
    unit = data.team.unit.value
    if preplanning and _ask_product_values(data, fc, s, "preplanned"):
        path = c.repo.save_sprint(team, s)
        _saved(path)
        _maybe_commit(
            c,
            team,
            [path],
            t("{team} {id}: PO pre-planning", team=data.team.name, id=s.id),
            None,
            commit_,
        )
        data = _load(c, team)
        fc = build_forecast(data, c.today)
    entry = fc.entry(s.id)
    if entry is not None:
        console.print(_distribution_table(distribution(fc, entry), unit))
    entries = [e for e in fc.entries if e.sprint.start <= s.start][-history:]
    rows = [b for b in balance(fc, entries) if b.sprints]  # only products with at least one value
    if rows:
        with_missing = any(b.missing for b in rows)
        columns = ("Product", "Sprints", "Σ standard", "Σ done", "Balance")
        table = Table(title=t("Balance: Σ done − Σ standard"))
        for i, col in enumerate((*columns, *(("no value",) if with_missing else ()))):
            table.add_column(t(col), justify="left" if i == 0 else "right")
        for b in rows:
            colour = "green" if b.difference >= 0 else "red"
            table.add_row(
                _plain(b.product.name),
                str(b.sprints),
                fmt(b.standard, 2),
                fmt(b.done, 2),
                f"[{colour}]{fmt(b.difference, 2)}[/{colour}]",
                *((str(b.missing),) if with_missing else ()),
            )
        console.print(table)
        if with_missing:
            console.print(f"[dim]{missing_footnote()}[/dim]")


@command("product-list", "Maintain the team's products (new, change PO, hand over).")
def product_list_command(ctx: typer.Context, team: TeamArg, commit_: CommitOpt = False) -> None:
    c = _ctx(ctx)
    data = _load(c, team)
    _require_products(data, team)
    products = data.products
    before = copy.deepcopy(data)  # the list is changed in place below
    with_po = data.team.features.po
    changed = False
    while True:
        table = Table(title=t("Products"))
        for col in ("Name", *(("PO",) if with_po else ()), "from", "until"):
            table.add_column(t(col))
        for p in products:
            table.add_row(
                _plain(p.name),
                *((_plain(p.po or ""),) if with_po else ()),
                f"{p.start:%d.%m.%Y}" if p.start else "–",
                f"{p.end:%d.%m.%Y}" if p.end else "–",
            )
        console.print(table)
        action = Prompt.ask(
            t("Action: n = new product, p = change PO, e = end product, q = done")
            if with_po
            else t("Action: n = new product, e = hand over product, q = done"),
            choices=["n", "p", "e", "q"] if with_po else ["n", "e", "q"],
            default="q",
            console=console,
        )
        if action == "q":
            break
        if action == "n":
            name = Prompt.ask(t("Name"), console=console).strip()
            if not name or any(p.name.lower() == name.lower() for p in products):
                console.print(f"[red]{t('Please enter a new, unique name.')}[/red]")
                continue
            po = (
                (
                    Prompt.ask(
                        t("PO (empty = not specified)"),
                        default="",
                        show_default=False,
                        console=console,
                    ).strip()
                    or None
                )
                if with_po
                else None
            )
            start = _ask_date(t("Handled from"), c.today)
            pid = new_person_id(name, {p.id for p in products}, fallback="produkt")
            product = Product(id=pid, name=name, po=po, start=start)
            tentative = copy.copy(data)
            tentative.products = [*products, product]
            if errors := _new_errors(c, data, tentative, "products.yaml"):
                _print_errors(errors)
                continue
            products.append(product)
        else:
            current = [p for p in products if p.end is None or p.end >= c.today]
            if not current:
                console.print(f"[red]{t('No active products.')}[/red]")
                continue
            names = {p.name.lower(): p for p in current}
            console.print(
                f"[dim]{t('Products')}: "
                + _plain_end(", ".join(p.name for p in current))
                + "[/dim]"
            )
            raw = Prompt.ask(t("Name"), console=console).strip().lower()
            product = names.get(raw)
            if product is None:
                console.print(f"[red]{t('Product not found.')}[/red]")
                continue
            if action == "p":
                product.po = (
                    Prompt.ask(t("New PO"), default=product.po or "", console=console).strip()
                    or None
                )
            else:
                product.end = _ask_date(t("Last day handled"), c.today)
        changed = True
    if changed:
        after = copy.copy(data)
        after.products = products
        _refuse_invalid(c, before, after, "products.yaml")
        path = c.repo.save_products(team, products)
        _saved(path)
        _maybe_commit(
            c,
            team,
            [path],
            t("{team}: product list updated", team=data.team.name),
            None,
            commit_,
        )


@command(
    "data-dir",
    "Show or set the remembered data folder (applies when the current directory contains no "
    "teams and neither --data nor FORESPRINT_DATA is set).",
)
def data_dir_command(
    path: Annotated[
        Path | None,
        typer.Argument(
            metavar="PATH", help=t("Save the folder (must be inside a Git repository).")
        ),
    ] = None,
) -> None:
    from sprintforecast.git import classify, repo_root, root_problem
    from sprintforecast.gitsync import git_available
    from sprintforecast.storage import save_data_dir, saved_data_dir, teams_dir

    if path is None:
        saved = saved_data_dir()
        console.print(
            t("Remembered: {path}", path=_plain(saved)) if saved else t("No data folder saved.")
        )
        console.print(t("Used (without --data): {path}", path=_plain(default_data_dir().resolve())))
        return
    if not path.is_dir():
        err.print(f"[red]{escape(t('Folder not found: {path}', path=path))}[/red]")
        raise typer.Exit(1)
    if not git_available():
        _git_problem(classify("", missing=True))
    if repo_root(path) is None:
        if problem := root_problem(path):
            _git_problem(problem)  # heading, message from Git and next step
        else:
            err.print(
                "[red]"
                + escape(
                    t("{path} is not inside a Git repository (git init or git clone).", path=path)
                )
                + "[/red]"
            )
        raise typer.Exit(1)
    target = teams_dir(path) or path
    try:
        save_data_dir(target)
    except SettingsError as e:
        err.print(f"[red]{escape(str(e))}[/red]")
        raise typer.Exit(1) from e
    console.print(f"[green]{escape(t('Data folder saved: {path}', path=target.resolve()))}[/green]")


@command("language", "Show or set the interface language (de, en).")
def language_command(
    code: Annotated[str | None, typer.Argument(help=t("de or en"))] = None,
) -> None:
    if code is None:
        console.print(f"{language()} ({LANGUAGES[language()]})")
        return
    code = code.strip().lower()[:2]
    if code not in LANGUAGES:
        err.print(f"[red]{t('Allowed: {values}', values=', '.join(LANGUAGES))}[/red]")
        raise typer.Exit(1)
    try:
        save_language(code)
    except SettingsError as e:
        err.print(f"[red]{_plain_end(e)}[/red]")
        raise typer.Exit(1) from e
    from sprintforecast.i18n import set_language

    set_language(code)
    console.print(f"[green]{t('Language: {language}', language=LANGUAGES[code])}[/green]")


@command("shortcut", "Create a launcher to double-click (desktop/start menu, macOS: Applications).")
def shortcut_command() -> None:
    from sprintforecast import shortcuts

    try:
        paths = shortcuts.create()
    except (RuntimeError, OSError) as e:
        err.print(f"[red]{_plain_end(e)}[/red]")
        raise typer.Exit(1) from e
    for path in paths:
        console.print(f"[green]{t('Created: {path}', path=_plain_end(path))}[/green]")
    console.print(
        t(
            "Double-click starts the web interface as an app. The data folder is set up on "
            "first start."
        )
    )


@command("completion", "Print the Tab completion script for a shell (bash, zsh, fish, powershell).")
def completion_command(
    shell: Annotated[
        completion.Shell,
        typer.Argument(help=t("Shell the script is written for.")),
    ],
    prog: Annotated[
        str | None,
        typer.Option(
            "--prog-name",
            help=t("Command name the script is registered for (default: the name used now)."),
        ),
    ] = None,
) -> None:
    typer.echo(completion.script(shell, prog or completion.prog_name()))


@command(
    "update",
    "Update sprintforecast to the latest version (plugins are kept).",
)
def update_command(
    check_: Annotated[
        bool,
        typer.Option("--check", help=t("Only check, do not install.")),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help=t("Reinstall even without a new version.")),
    ] = False,
    auto: Annotated[
        str | None,
        typer.Option(
            help=t("Set automatic mode: on (installs itself), notice (only report), off."),
        ),
    ] = None,
) -> None:
    if auto is not None:
        # what gets stored are the values on/notice/off
        values = {"on": "on", "notice": "notice", "off": "off"}
        word = auto.strip().lower()
        try:
            mode = updater.Mode(values[word])
        except KeyError:
            err.print(f"[red]{t('--auto: on, notice or off')}[/red]")
            raise typer.Exit(1) from None
        try:
            updater.update_state(strict=True, mode=mode.value)
        except OSError as e:
            err.print(
                "[red]"
                + escape(
                    t(
                        "The settings could not be saved ({path}): {error}",
                        path=updater.state_file(),
                        error=e.strerror or e,
                    )
                )
                + "[/red]"
            )
            raise typer.Exit(1) from e
        console.print(t("Automatic update: [bold]{mode}[/bold]", mode=word))
        if os.environ.get(updater.MODE_ENV):
            console.print(
                f"[yellow]{t('Note: {name} takes precedence.', name=updater.MODE_ENV)}[/yellow]"
            )
        return
    result = updater.check(force=True)
    inst = result.installation
    if inst is None:
        console.print(
            t(
                (
                    "Version {version} – not installed with `uv tool install` (e.g. "
                    "development with `uv run`). Update with `git pull` or by running the "
                    "install script again."
                ),
                version=result.current,
            )
        )
        raise typer.Exit(1)
    if inst.pinned and not force:
        console.print(
            t(
                (
                    "Version {version}, pinned to [bold]{ref}[/bold]. For another version, run "
                    "the install script again with FORESPRINT_REF."
                ),
                version=result.current,
                ref=inst.ref,
            )
        )
        return
    if result.error:
        err.print(f"[red]{t('Check failed: {error}', error=_plain_end(result.error))}[/red]")
        if not force:
            raise typer.Exit(1)
    console.print(
        t(
            (
                "Installed: [bold]{current}[/bold] · available: [bold]{latest}[/bold] ({repo}, "
                "{ref})"
            ),
            current=result.current,
            latest=result.latest or "–",
            repo=inst.repo,
            ref=inst.ref,
        )
    )
    if not result.available and not force:
        console.print(f"[green]{t('sprintforecast is up to date.')}[/green]")
        return
    if check_:
        console.print(t("Update with: sprintforecast update"))
        return
    uv = updater.find_uv()
    if uv is None:
        err.print(f"[red]{t('uv not found – please run the install script again.')}[/red]")
        raise typer.Exit(1)
    if sys.platform == "win32":
        updater.schedule_after_exit(uv, visible=True)
        updater.update_state(attempted=result.latest, failure_reported=False)
        console.print(
            t(
                "The update starts after this command in a separate window (Windows locks "
                "running programs)."
            )
        )
        return
    code = updater.run_upgrade(uv)
    if code != 0:
        err.print(f"[red]{t('Update failed (exit code {code}).', code=code)}[/red]")
        raise typer.Exit(code)
    version = subprocess.run(
        [sys.executable, "-c", f"import importlib.metadata as m; print(m.version({PACKAGE!r}))"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    updater.update_state(seen_version=version or result.latest)
    console.print(
        f"[green]{t('Installed: version {version}.', version=version or result.latest)}[/green]"
    )


@command(
    "capacity",
    "Show the capacity calculation of a sprint in detail (default: next sprint).",
)
def capacity_command(ctx: typer.Context, team: TeamArg, sprint: SprintArg = None) -> None:
    c = _ctx(ctx)
    data = _load(c, team)
    s = _find_or_create(data, build_forecast(data, c.today), sprint, "next")
    console.print(_capacity_table(data, s))
    if s.capacity is not None:
        console.print(
            "[dim]"
            + t(
                "Recorded/frozen in the sprint file: {capacity} PT",
                capacity=fmt_capacity(s.capacity, data.team.capacity.rounding),
            )
            + "[/dim]"
        )
    if data.sprint(s.id) is None:
        hint = (
            t(
                "No sprint file yet – until then the forecast uses the calendar and the "
                "people list; the unknown absences are estimated from the history (without "
                "history, no deduction)."
            )
            if data.people
            else t("No sprint file yet – until then the forecast uses the capacity trend.")
        )
        console.print(f"[yellow]{hint}[/yellow]")


# Extensions (e.g. import plugins) register their commands last.
for _plugin in load_plugins():
    if _plugin.register_cli is not None:
        _plugin.register_cli(app)
for _command in app.registered_commands:  # also the commands of the extensions
    if _command.callback is not None:
        _command.callback = _guarded(_command.callback)
