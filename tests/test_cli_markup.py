# SPDX-License-Identifier: EUPL-1.2
"""Free text from the data (names, sprint IDs, paths) is not evaluated as Rich markup on the
command line: "[x]" stays, "[/x]" does not abort the output, a trailing backslash appears exactly
once.

The commands run on a copy of the demo data in which team, people, products, sprint IDs and the
data path look like markup. Each run also checks that no tag is left over as text
("[/bold]" after a value with a backslash) and that no backslash appears twice."""

import dataclasses
import os
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from rich.errors import MarkupError
from rich.text import Text
from typer.testing import CliRunner

from sprintforecast import analysis, cli, i18n, shortcuts, updater
from sprintforecast.cli import _plain, _plain_end, app
from sprintforecast.storage import DATA_ENV, save_data_dir

runner = CliRunner(env={"COLUMNS": "1000"})

# Backslash in the name: only possible where it is not a path separator.
BS = "" if sys.platform == "win32" else "\\"
# Paths in the output have backslashes on Windows.
SEP = os.sep
# These tags appear in the output only as markup; as text they would be an error (the data
# contains "[red]", but never "[bold]" or "[dim]").
CLOSERS = [f"[/{tag}]" for tag in ("red", "green", "yellow", "cyan", "bold", "dim")]
OPENERS = ["[bold]", "[dim]", "[green]", "[yellow]", "[cyan]"]


def run(data_dir: Path, *args: str, input: str | None = None):
    return runner.invoke(
        app, ["--data", str(data_dir), "--as-of", "2026-10-15", *args], input=input
    )


def replace(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def check(result, *expected: str, code: int = 0, absent: tuple[str, ...] = ()) -> str:
    """Exit code as in the normal case, no MarkupError, the values appear literally."""
    output = result.output
    assert result.exit_code == code, output
    assert not isinstance(result.exception, MarkupError), result.exception
    for text in expected:
        assert text in output, f"{text!r} fehlt in:\n{output}"
    for text in absent:
        assert text not in output, f"{text!r} darf nicht vorkommen in:\n{output}"
    for tag in (*CLOSERS, *OPENERS):
        assert tag not in output, f"{tag} als Text in:\n{output}"
    if BS:
        assert BS * 2 not in output, f"doppelter Backslash in:\n{output}"
    return output


def write_team(
    root: Path,
    key: str,
    *,
    products: bool = True,
    people: bool = True,
    unit: str = "PT",
    issue: bool = False,
) -> Path:
    """Small team without sprint files in a folder whose name looks like markup."""
    team = root / key
    team.mkdir()
    data = {
        "name": "Klein",
        "unit": unit,
        "features": {"products": products},
        "sprint": {"length_days": 14, "first": {"id": "2026.1", "start": date(2026, 10, 7)}},
    }
    (team / "team.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    persons = [{"id": "eva", "name": "Eva", "memberships": [{"from": date(2025, 1, 1)}]}]
    if issue:  # a person without affiliation: "Notice" in the check
        persons.append({"id": "zoe", "name": "Zoe"})
    (team / "people.yaml").write_text(
        yaml.safe_dump({"people": persons if people else []}), encoding="utf-8"
    )
    return team


@pytest.fixture
def brackets(data_dir: Path, tmp_path: Path) -> Path:
    """Demo data whose path, names and sprint IDs look like Rich markup."""
    root = tmp_path / f"da[x]ten{BS}[red]"
    data_dir.rename(root)
    team = root / "demo"
    replace(team / "team.yaml", "name: Demo-Team", "name: '[/x] Team'")
    people = team / "people.yaml"
    replace(people, "name: Anna", "name: 'Eva [x]'")
    replace(people, "name: Ben", "name: 'Ben [/x]'")
    replace(people, "name: Cem", "name: 'Cem [red]'")
    replace(people, "name: Dana", f"name: 'Dana{BS}'")  # last: stands before the closing tag
    products = team / "products.yaml"
    replace(products, "name: Webshop", "name: 'Shop [/x]'")
    replace(products, "name: Mobile App", "name: 'App [x]'")
    replace(products, "name: Kundenportal", f"name: 'Portal [red]{BS}'")
    replace(products, "po: Alex", "po: 'Alex [x]'")
    replace(products, "po: Bea", "po: 'Bea [/x]'")
    sprints = team / "sprints"
    for old, new in (("2026.20", "[x]"), ("2026.21", f"[red]{BS}")):
        file = sprints / f"{old}.yaml"
        replace(file, f"id: '{old}'", f"id: '{new}'")
        file.rename(sprints / f"{new}.yaml")
    # A finding in the sprint file: check messages show file names and text with brackets.
    replace(sprints / f"[red]{BS}.yaml", "absences:\n", "absences:\n  '[/x]': 1\n")
    return root


# --- _plain and _plain_end ---------------------------------------------------------------

VALUES = [
    "Eva",
    "Eva\\",
    "Eva\\\\",
    "C:\\",
    "[x]",
    "[/x]",
    "[red]",
    "[x]\\",
    "\\[x]",
    "\\\\[x]",
    "\\\\\\[x]\\",
    "a[x][/x]b",
    "a\\[1]",
    "a\\\\[1]",
    "D:\\Projekte\\[2024]\\teams",
    "[1] [web] [de|en]",
    "Name [/x] \\ [y",
    "",
]


@pytest.mark.parametrize("value", VALUES)
def test_plain_is_shown_literally_without_a_following_tag(value: str):
    assert Text.from_markup(_plain(value)).plain == value
    assert Text.from_markup(f"{_plain(value)} (x)").plain == f"{value} (x)"


@pytest.mark.parametrize("value", VALUES)
def test_plain_end_keeps_the_closing_tag_a_tag(value: str):
    text = Text.from_markup(f"[red]{_plain_end(value)}[/red]")
    assert text.plain == value
    # The closing tag took effect: the style covers exactly the value.
    assert [(s.start, s.end, str(s.style)) for s in text.spans] == [(0, len(value), "red")]


def test_trailing_backslash_is_not_doubled_without_a_tag():
    assert _plain("Eva\\") == "Eva\\"
    assert _plain("C:\\") == "C:\\"
    assert _plain("[x]\\") == "\\[x]\\"
    # Backslashes before a tag are doubled as in Rich (+ one that escapes the tag).
    assert _plain("\\[x]") == "\\\\\\[x]"
    assert _plain_end("Eva\\") == "Eva\\\\"
    assert _plain_end("Eva\\\\") == "Eva\\\\\\\\"


def test_backslash_before_a_bracket_that_is_no_tag_is_kept():
    """Rich turns every "\\[" into a "[": without a tag behind it a backslash was lost
    (Windows path with the folder "[2024]")."""
    assert _plain("a\\[1]") == "a\\\\[1]"
    assert _plain("[1]") == "[1]"  # without a backslash everything stays as it is
    assert Text.from_markup(_plain("D:\\Projekte\\[2024]\\teams")).plain == (
        "D:\\Projekte\\[2024]\\teams"
    )


def test_plain_is_literal_for_all_short_strings():
    """All strings up to length 5 from the characters Rich treats specially."""
    import itertools

    alphabet = ["\\", "[", "]", "x", "/", "A", " ", "#"]
    for size in range(6):
        for chars in itertools.product(alphabet, repeat=size):
            value = "".join(chars)
            assert Text.from_markup(_plain(value)).plain == value, repr(value)
            assert Text.from_markup(f"[red]{_plain_end(value)}[/red]").plain == value, repr(value)


def test_translation_markup_is_kept_around_placeholders():
    """[bold], [red] and [dim] of the translation stay markup, the values in them are text."""
    for language in ("de", "en"):
        i18n.set_language(language)
        try:
            text = Text.from_markup(
                i18n.t(
                    "Next: [bold]{command}[/bold]",
                    command=_plain_end("sprintforecast people [x]\\"),
                )
            )
        finally:
            i18n.set_language(None)
        assert text.plain.endswith("sprintforecast people [x]\\")
        bold = [s for s in text.spans if str(s.style) == "bold"]
        assert len(bold) == 1
        assert text.plain[bold[0].start : bold[0].end] == "sprintforecast people [x]\\"


# --- Commands on the data with brackets ------------------------------------------------

NAMES = ["[/x] Team", "Eva [x]", "Ben [/x]", "Cem [red]", f"Dana{BS}"]
PRODUCTS = ["Shop [/x]", "App [x]", f"Portal [red]{BS}"]
SPRINTS = ["[x]", f"[red]{BS}"]
ABSENCES = "0\n" * 4
BLANK = "\n" * 60  # Enter accepts the suggestion each time


@pytest.mark.parametrize(
    ("args", "input", "expected", "code"),
    [
        pytest.param(
            ["forecast", "demo", "--history", "30"], None, ["[/x] Team", *SPRINTS], 0, id="forecast"
        ),
        pytest.param(
            ["forecast", "demo", "--explain", f"[red]{BS}"],
            None,
            [f"Rechenweg Sprint [red]{BS}"],
            0,
            id="forecast-rechenweg",
        ),
        pytest.param(
            ["forecast", "demo", "--explain", "[/x]"],
            None,
            ["Sprint [/x] nicht in der Prognose."],
            1,
            id="forecast-rechenweg-unbekannt",
        ),
        pytest.param(
            ["analysis", "demo"], None, ["Bandbreite [/x] Team", *SPRINTS], 0, id="analyse"
        ),
        pytest.param(
            ["sprints", "demo"],
            None,
            [
                "Sprintkalender [/x] Team",
                *SPRINTS,
                f"sprints/[red]{BS}.yaml: Fehltage für unbekannte Person '[/x]'",
            ],
            1,
            id="sprints",
        ),
        pytest.param(
            ["sprints", "demo", "--end", "[/x]=2026-10-29"],
            None,
            ["--end [/x]=2026-10-29: erwartet SPRINT=JJJJ-MM-TT"],
            1,
            id="sprints-ende",
        ),
        pytest.param(
            ["sprints", "demo", "--end", f"[red]{BS}=2026-10-01"],
            None,
            [f"[red]{BS}"],
            1,
            id="sprints-ende-fehler",
        ),
        pytest.param(["people", "demo"], "q\n", NAMES[1:], 0, id="personen"),
        pytest.param(["capacity", "demo"], None, NAMES[1:], 0, id="kapazitaet"),
        pytest.param(
            ["capacity", "demo", "[x]"],
            None,
            ["Kapazität Sprint [x]", *NAMES[1:]],
            0,
            id="kap-id",
        ),
        pytest.param(
            ["products", "demo"], None, [*PRODUCTS, "Alex [x]", "Bea [/x]"], 0, id="produkte"
        ),
        pytest.param(
            ["products", "demo", f"[red]{BS}", "--preplanning"],
            BLANK,
            [f"Produkte Sprint [red]{BS}", *PRODUCTS, "App [x] – ", f"Portal [red]{BS} – "],
            0,
            id="produkte-vorplanung",
        ),
        pytest.param(
            ["product-list", "demo"],
            "q\n",
            [*PRODUCTS, "Alex [x]", "Bea [/x]"],
            0,
            id="produktliste",
        ),
        pytest.param(
            ["product-list", "demo"],
            "e\nunbekannt\nq\n",
            [f"Produkte: Shop [/x], App [x], Portal [red]{BS}", "Produkt nicht gefunden."],
            0,
            id="produktliste-abgeben",
        ),
        pytest.param(
            ["absences", "demo", f"[red]{BS}"],
            ABSENCES,
            [
                f"Sprint [red]{BS}: 14.10.2026",
                *(f"{name} (" for name in NAMES[1:]),
                f"Prognose Sprint [red]{BS}",
                f"Kapazität Sprint [red]{BS} (14.10. – 28.10.2026)",
                "Gespeichert: ",
                f"Fehler sprints/[red]{BS}.yaml: Fehltage für unbekannte Person '[/x]'",
            ],
            0,
            id="fehltage",
        ),
        pytest.param(
            ["planning", "demo", f"[red]{BS}"],
            "y\n" + ABSENCES + BLANK,
            [
                f"Planning [red]{BS} – Schritt 1: Fehltage",
                f"Planning [red]{BS} – Schritt 2: Forecast PLAN und Einplanung",
                f"Planning [red]{BS} – Schritt 3: Commitment",
                f"Produkte Sprint [red]{BS}",
                f"Portal [red]{BS} – Planning (PT)",
                f"Prognose Sprint [red]{BS}",
                "Gespeichert: ",
                f"Fehler sprints/[red]{BS}.yaml: Fehltage für unbekannte Person '[/x]'",
            ],
            0,
            id="planning",
        ),
        pytest.param(
            ["review", "demo", f"[red]{BS}"],
            "\ny\n" + BLANK,
            [
                f"Review Sprint [red]{BS} (14.10. – 28.10.2026)",
                f"Produkte Sprint [red]{BS}",
                f"Portal [red]{BS} – Erledigt (PT)",
                "Gespeichert: ",
                f"Fehler sprints/[red]{BS}.yaml: Fehltage für unbekannte Person '[/x]'",
            ],
            0,
            id="review",
        ),
        pytest.param(
            ["report", "demo"],
            None,
            [f"da[x]ten{BS}[red]{SEP}demo{SEP}FORECAST.md"],
            0,
            id="bericht",
        ),
        pytest.param(
            ["report"], None, [f"da[x]ten{BS}[red]{SEP}demo{SEP}FORECAST.md"], 0, id="bericht-alle"
        ),
        pytest.param(
            ["check"],
            None,
            [
                "demo",
                f"Fehler sprints/[red]{BS}.yaml: Fehltage für unbekannte Person '[/x]'",
            ],
            1,
            id="pruefen",
        ),
    ],
)
def test_values_with_markup_look_are_shown_literally(
    brackets: Path, args: list[str], input: str | None, expected: list[str], code: int
):
    result = run(brackets, *args, input=input)
    check(result, *expected, code=code)


def test_people_new_person_and_selection(brackets: Path):
    """Select box, new person and check lines after saving with names that look like markup."""
    people = brackets / "demo" / "people.yaml"
    replace(people, "people:\n", "people:\n- id: '[x]'\n  name: Zoe\n")
    result = run(
        brackets,
        "people",
        "demo",
        input="f\nEva\n2026-12-01\n0.5\nn\nNeu [/x]\n[/x]\n2026-11-01\n1\nq\n",
    )
    check(
        result,
        f"Personen: Eva [x], Ben [/x], Cem [red], Dana{BS}\n",
        "people.yaml: neu-x: Region '[/X]' gehört nicht zum Land DE",
        "Gespeichert: ",  # the rest is saved; the invalid new person is refused at once
    )
    assert "Neu [/x]" not in people.read_text(encoding="utf-8")


def test_people_region_with_markup_look(brackets: Path):
    replace(brackets / "demo" / "people.yaml", "region: BY", "region: '[/x]'")
    result = run(brackets, "people", "demo", input="q\n")
    check(result, "Cem [red]", "[/x]")


def test_commit_message_lines_with_markup_look(brackets: Path):
    """Check lines and tag hint of _maybe_commit also appear without markup with --commit."""
    result = run(brackets, "absences", "demo", f"[red]{BS}", "--commit", input=ABSENCES)
    check(
        result,
        f"Fehler sprints/[red]{BS}.yaml: Fehltage für unbekannte Person '[/x]'",
        "Nicht committet – bitte zuerst die Fehler beheben.",
        code=1,
    )


def test_names_in_error_lines_with_markup_look(data_dir: Path):
    teams = {
        "a[x]": dict(products=False),
        f"b[red]{BS}": dict(people=False),
        "c[x]": {},
        f"d[x]{BS}": {},
        f"e[x]{BS}": dict(issue=True),
    }
    for key, kwargs in teams.items():
        write_team(data_dir, key, **kwargs)
    result = run(data_dir, "products", "a[x]")
    check(result, "Einschalten mit: sprintforecast settings a[x]", code=1)
    result = run(data_dir, "products", "c[x]")
    check(result, "Zuerst: sprintforecast product-list c[x]", code=1)
    result = run(data_dir, "product-list", "a[x]")
    check(result, "Einschalten mit: sprintforecast settings a[x]", code=1)
    result = run(data_dir, "absences", f"b[red]{BS}")
    check(result, f"Zuerst: sprintforecast people b[red]{BS}", code=1)
    result = run(data_dir, "forecast", "c[x]")
    check(result, "Sprint-Forecast Klein", "sprintforecast absences c[x] <SPRINT>")
    result = run(data_dir, "check")
    check(result, "a[x]", f"b[red]{BS}", "c[x]", f"✔ d[x]{BS}\n", "✔ demo\n", code=result.exit_code)
    assert f"\ne[x]{BS}\n  Hinweis people.yaml:" in result.output


def test_sprint_panel_names_the_region_with_markup_look(
    brackets: Path, monkeypatch: pytest.MonkeyPatch
):
    """The holidays in the sprint panel name the team's region."""
    replace(brackets / "demo" / "team.yaml", "region: NW", "region: '[x]'")
    monkeypatch.setattr(cli, "holiday_name", lambda d, region, country: "Feiertag" * (d.day == 20))
    result = run(brackets, "absences", "demo", f"[red]{BS}", input=ABSENCES)
    check(result, "davon Feiertage ([x]): 20.10. Feiertag")


def test_init_with_a_key_that_looks_like_markup(brackets: Path, monkeypatch: pytest.MonkeyPatch):
    """New keys are limited to a–z, digits, "-" and "_"; the messages do not depend on this check
    anyway."""
    monkeypatch.setattr(cli, "team_key_problem", lambda key: None)
    key = f"neu[x]{BS}"
    result = run(brackets, "init", key, input=INIT_ANSWERS.format(bs=BS))
    check(
        result,
        f"Neues Team {key} anlegen.",
        f"mit sprintforecast settings {key} änderbar",
        f"Weiter mit: sprintforecast people {key}\n",
    )


def test_fte_change_note_names_people_with_markup_look(brackets: Path):
    """The approximation for an FTE change names the people in the table caption."""
    result = run(brackets, "capacity", "demo", "2026.11")
    check(result, "(Ben [/x]).")


def test_commit_line_with_tag_with_markup_look(brackets: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(cli, "commit", lambda paths, message, tag: "abc1234")
    result = run(brackets, "review", "demo", "[x]", "--commit", input="\ny\n" + BLANK)
    check(result, "Committet (abc1234), Tag demo/[x].")


def test_empty_data_dir_ending_in_a_backslash(tmp_path: Path):
    """The folder is right before the closing tag of the error message."""
    root = tmp_path / f"leer[x]{BS}"
    root.mkdir()
    result = run(root, "check")
    check(result, f"Keine Teams gefunden unter {root}", code=1)
    assert f"leer[x]{BS}\n" in result.output


def test_sprint_id_with_brackets(data_dir: Path):
    new_dir = data_dir / "neu"
    new_dir.mkdir()
    team = {
        "name": "Neu",
        "unit": "PT",
        "sprint": {"length_days": 14, "first": {"id": "[x]", "start": date(2026, 10, 7)}},
    }
    person = {"id": "eva", "name": "Eva", "memberships": [{"from": date(2025, 1, 1)}]}
    people = {"people": [person]}
    (new_dir / "team.yaml").write_text(yaml.safe_dump(team), encoding="utf-8")
    (new_dir / "people.yaml").write_text(yaml.safe_dump(people), encoding="utf-8")

    for args in (["sprints", "neu"], ["forecast", "neu"]):
        result = run(data_dir, *args)
        assert result.exit_code == 0, result.output
        assert "[x]" in result.output

    result = run(data_dir, "absences", "neu", "[/x]")
    assert result.exit_code == 1
    assert "Sprint [/x] liegt nicht in der Sprintfolge des Teams." in result.output
    result = run(data_dir, "forecast", "neu", "--explain", "[/x]")
    assert result.exit_code == 1
    assert "Sprint [/x] nicht in der Prognose." in result.output


def test_unknown_team_with_brackets(data_dir: Path):
    for team in ("[x]", "[/x]"):
        result = run(data_dir, "forecast", team)
        assert result.exit_code == 1, result.output
        assert f"Team '{team}' nicht gefunden" in result.output


def test_check_messages_with_brackets(data_dir: Path):
    demo = data_dir / "demo"
    replace(demo / "people.yaml", "people:\n", "people:\n- id: '[x]'\n  name: Zoe\n")
    sprint = demo / "sprints" / "2026.21.yaml"
    replace(sprint, "absences:\n", "absences:\n  '[/x]': 1\n")

    result = run(data_dir, "check")
    assert result.exit_code == 1
    assert "people.yaml: [x]: keine Zugehörigkeit" in result.output
    assert "Fehltage für unbekannte Person '[/x]'" in result.output


# --- init and settings: guided input ---------------------------------------------------

# Inputs of "init" after the name: first sprint, unit … country, region (invalid, then empty) …
INIT_ANSWERS = (
    "Neu [/x]{bs}\n"  # display name
    + "\n2026-10-07\n2026.20\n"  # first sprint: numbering, start, ID
    + "\n" * 6  # unit, products, PO, production, tickets, country
    + "[/x]\n\n"  # region: message "Unknown region code", then empty
    + "\n" * 20
)


def test_init_with_markup_look(brackets: Path):
    result = run(brackets, "init", "neu", input=INIT_ANSWERS.format(bs=BS))
    check(
        result,
        "Neues Team neu anlegen.",
        "sprintforecast settings neu",
        "Unbekannter Regionscode: [/X]",
        f"Angelegt: {brackets}{SEP}neu{SEP}team.yaml",
        "Weiter mit: sprintforecast people neu",
    )
    assert yaml.safe_load((brackets / "neu" / "team.yaml").read_text())["name"] == f"Neu [/x]{BS}"


def test_settings_with_markup_look(brackets: Path):
    result = run(
        brackets,
        "settings",
        "demo",
        input=f"Neu [x]{BS}\n" + "\n" * 6 + "[/x]\n\n" + "\n" * 20 + "y\n",
    )
    check(
        result,
        "Einstellungen [/x] Team",
        "Unbekannter Regionscode: [/X]",
        "Änderungen",
        "[/x] Team",
        f"Neu [x]{BS}",
        f"Gespeichert: {brackets}{SEP}demo{SEP}team.yaml",
    )


# --- Paths ---------------------------------------------------------------------------


def test_path_with_brackets_and_backslashes_in_messages(brackets: Path):
    """_saved, "Created" and report show the path with "[x]", "[red]" and a backslash."""
    shown = f"da[x]ten{BS}[red]"
    result = run(brackets, "absences", "demo", "2026.23", input=ABSENCES)
    check(result, f"Gespeichert: {brackets}{SEP}demo{SEP}sprints{SEP}2026.23.yaml", shown)
    result = run(brackets, "init", "neu", input=INIT_ANSWERS.format(bs=BS))
    check(result, f"Angelegt: {brackets}{SEP}neu{SEP}team.yaml", shown)
    result = run(brackets, "report", "demo")
    check(result, f"{brackets}{SEP}demo{SEP}FORECAST.md")


def test_path_with_brackets_and_backslashes_for_data_folder(tmp_path: Path):
    """Without an argument ``data-dir`` shows the remembered and the used folder. If it ends in a
    backslash (drive root "C:\\"), it appears once."""
    saved = tmp_path / f"alt[x]{BS}"
    used = tmp_path / f"neu[red]{BS}"
    saved.mkdir()
    used.mkdir()
    save_data_dir(saved)
    result = runner.invoke(app, ["data-dir"], env={DATA_ENV: str(used)})
    check(
        result,
        f"Gemerkt: {saved}\n",
        f"Verwendet (ohne --data): {used}\n",
    )
    result = runner.invoke(app, ["data-dir"], env={DATA_ENV: ""})
    check(result, f"Gemerkt: {saved}\n")


def test_path_with_brackets_and_backslashes_for_missing_folder(data_dir: Path):
    folder = Path(r"C:\daten\[y]")
    result = run(data_dir, "data-dir", str(folder))
    check(result, f"Ordner nicht gefunden: {folder}", code=1)


# --- fixed messages with square brackets -----------------------------------------------


@pytest.mark.parametrize("language", ["de", "en"])
def test_web_without_streamlit_names_the_extra(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, language: str
):
    """The extra "[web]" in the install command is not markup."""
    import importlib.util

    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a: None if name == "streamlit" else real(name, *a),
    )
    monkeypatch.setenv(i18n.LANG_ENV, language)
    i18n.set_language(None)
    try:
        result = run(data_dir, "web")
    finally:
        i18n.set_language(None)
    expected = 'uv tool install "sprintforecast[web] @ git+…"'
    check(result, expected, "uv sync --extra web", code=1)


def test_help_shows_square_brackets_of_the_commands(data_dir: Path):
    result = run(data_dir, "help", "commands")
    check(result, "sprintforecast language [de|en]")


# --- Messages from helper functions that can only be reached with mocks -----------------


def test_analyse_completion_with_markup_look(brackets: Path, monkeypatch: pytest.MonkeyPatch):
    real = analysis.completion

    def completion(*args, **kwargs):
        return dataclasses.replace(
            real(*args, **kwargs),
            p50="[x]",
            p85=None,
            sprints=["[/x]", f"[red]{BS}"],
            trend_capacity_sprints=["[x]", "[/x]", "[red]", "[b]", f"[c]{BS}"],
        )

    monkeypatch.setattr(analysis, "completion", completion)
    result = run(brackets, "analysis", "demo", "--remaining", "20")
    check(
        result,
        "in 50 % der Simulationen bis [x], in 85 % bis später als [red]",
        "Ohne Personenliste gerechnet mit Ø Kapazität: [x], [/x], [red], [b] …",
    )
    monkeypatch.setattr(
        analysis,
        "completion",
        lambda *a, **k: dataclasses.replace(
            real(*a, **k), p50=None, p85=f"[x]{BS}", trend_capacity_sprints=["[x]", f"[red]{BS}"]
        ),
    )
    result = run(brackets, "analysis", "demo", "--remaining", "20")
    check(result, f"bis [x]{BS} (", f"Kapazität: [x], [red]{BS}\n")


def test_auto_update_notices_with_markup_look(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    class Auto:
        def start(self):
            return self

        def finish(self, report):
            report(f"Fertig [/x]{BS}")

    registered = []
    monkeypatch.setattr(updater, "startup_notices", lambda: [f"Hinweis [/x] [red]{BS}"])
    monkeypatch.setattr(updater, "AutoUpdate", Auto)
    monkeypatch.setattr("atexit.register", lambda fn, *args: registered.append((fn, args)))
    cli._auto_update()
    ((finish, args),) = registered
    finish(*args)
    err = capsys.readouterr().err
    assert f"Hinweis [/x] [red]{BS}\n" in err
    assert f"Fertig [/x]{BS}\n" in err
    for tag in CLOSERS:
        assert tag not in err


def check_result(**fields):
    base = {
        "current": "1.0",
        "latest": "2.0",
        "available": True,
        "error": None,
        "installation": updater.Installation(repo="r[x]", ref="main", pinned=False),
    }
    return SimpleNamespace(**(base | fields))


def test_update_error_with_markup_look(data_dir: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(updater, "check", lambda force=False: check_result(error=f"[/x]{BS}"))
    result = run(data_dir, "update", "--check")
    check(result, f"Prüfung fehlgeschlagen: [/x]{BS}\n", code=1)


def test_shortcut_with_markup_look(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    paths = [tmp_path / f"a[x]{BS}", tmp_path / "b[x]"]
    monkeypatch.setattr(shortcuts, "create", lambda: paths)
    result = runner.invoke(app, ["shortcut"])
    check(result, f"Angelegt: {paths[0]}\n", f"Angelegt: {paths[1]}\n")

    def failing():
        raise RuntimeError(f"Kein Programm [/x]{BS}")

    monkeypatch.setattr(shortcuts, "create", failing)
    result = runner.invoke(app, ["shortcut"])
    check(result, f"Kein Programm [/x]{BS}\n", code=1)


def test_language_error_with_markup_look(monkeypatch: pytest.MonkeyPatch):
    from sprintforecast.config import SettingsError

    def failing(code: str):
        raise SettingsError(f"Einstellungen [/x] [red]{BS}")

    monkeypatch.setattr(cli, "save_language", failing)
    result = runner.invoke(app, ["language", "en"])
    check(result, f"Einstellungen [/x] [red]{BS}\n", code=1)


def test_open_app_window_messages_with_markup_look(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    from sprintforecast.launcher import Browser
    from sprintforecast.launcher import Kind as BrowserKind

    server = SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(cli, "wait_until_ready", lambda url, server: True)
    monkeypatch.setattr(cli, "adopt", lambda process: None)
    monkeypatch.setattr(cli, "browser_command", lambda found, url: ["x"])
    monkeypatch.setattr(cli.subprocess, "Popen", lambda cmd: SimpleNamespace(poll=lambda: 0))
    seen = iter(
        [
            FileNotFoundError(f"Browser [/x]{BS}"),
            Browser(kind=BrowserKind.APP, name=f"Edge [red]{BS}", path="/x"),
        ]
    )

    def find(explicit):
        item = next(seen)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(cli, "find_browser", find)
    cli._open_app_window("http://localhost:1", server, f"[/x]{BS}")
    out = capsys.readouterr().out
    assert f"Browser [/x]{BS} – suche automatisch.\n" in out
    assert f"Öffne Edge [red]{BS} als App-Fenster" in out
    monkeypatch.setattr(
        cli,
        "find_browser",
        lambda explicit: Browser(kind=BrowserKind.WINDOW, name=f"Fox [x]{BS}", path="/x"),
    )
    cli._open_app_window("http://localhost:1", server, None)
    assert f"öffne Fox [x]{BS} (neues Fenster)" in capsys.readouterr().out


@pytest.mark.usefixtures("english")
def test_english_translations_keep_their_markup(brackets: Path):
    """The English templates with [bold] around a placeholder also stay markup."""
    result = run(brackets, "init", "neu", input=INIT_ANSWERS.format(bs=BS))
    check(result, "Create new team neu.", f"Created: {brackets}{SEP}neu{SEP}team.yaml", "Next: ")
    result = run(brackets, "absences", "demo", f"[red]{BS}", input=ABSENCES)
    check(result, f"Sprint [red]{BS}: ", "Saved: ")
    result = run(brackets, "review", "demo", f"[red]{BS}", input="\ny\n" + BLANK)
    check(result, f"Review Sprint [red]{BS} (", "Capacity according to people list")


def test_emoji_shortcodes_in_names_stay_text(data_dir: Path):
    replace(data_dir / "demo" / "people.yaml", "name: Cem", "name: ':smile: Cem'")
    result = run(data_dir, "people", "demo", input="q\n")
    check(result, ":smile: Cem")
    assert "😄" not in result.output
