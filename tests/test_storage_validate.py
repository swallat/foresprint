# SPDX-License-Identifier: EUPL-1.2
import copy
import shutil
from datetime import date
from pathlib import Path

import pytest

from foresprint.engine import CapacitySource
from foresprint.forecast import build_forecast
from foresprint.storage import DataError, Repository, import_sprints, team_key_problem
from foresprint.validate import Level, check_team

TODAY = date(2026, 10, 15)


def test_roundtrip_keeps_files_stable(data_dir: Path):
    repo = Repository(data_dir)
    data = repo.load("demo")
    before = {p: p.read_text() for p in (data_dir / "demo").rglob("*.yaml")}
    repo.save_team(data.team)
    repo.save_people("demo", data.people)
    for s in data.sprints:
        repo.save_sprint("demo", s)
    after = {p: p.read_text() for p in (data_dir / "demo").rglob("*.yaml")}
    assert before == after


def test_unquoted_sprint_id_gives_helpful_error(data_dir: Path):
    path = data_dir / "demo" / "sprints" / "2026.20.yaml"
    path.write_text(path.read_text().replace("id: '2026.20'", "id: 2026.20"))
    with pytest.raises(DataError, match="Anführungszeichen"):
        Repository(data_dir).load("demo")


@pytest.mark.parametrize("raw", [".nan", ".inf", "-.inf", "1.0e+999", "1" + "0" * 400])
def test_non_finite_number_in_yaml_gives_error(data_dir: Path, raw: str):
    path = data_dir / "demo" / "sprints" / "2026.20.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("velocity: 9.75", f"velocity: {raw}"),
        encoding="utf-8",
    )
    with pytest.raises(DataError, match=r"2026\.20\.yaml: velocity: endliche Zahl erwartet"):
        Repository(data_dir).load("demo")


@pytest.mark.parametrize("raw", [".nan", ".inf", "-.inf"])
@pytest.mark.parametrize(
    ("section", "key"),
    [
        ("forecast", "reference_capacity"),
        ("forecast", "roadmap_share"),
        ("forecast", "window"),
        ("forecast", "horizon"),
        ("forecast", "rounding"),
        ("capacity", "overhead_share"),
        ("capacity", "overhead_days"),
        ("capacity", "rounding"),
        ("capacity", "absence_history"),
        ("sprint", "length_days"),
    ],
)
def test_non_finite_setting_in_team_yaml_gives_error(
    data_dir: Path, section: str, key: str, raw: str
):
    """Also the settings in team.yaml: previously the check reported nothing and the calculation
    crashed (nan) or loading aborted with OverflowError (inf for integers)."""
    import re

    path = data_dir / "demo" / "team.yaml"
    text = path.read_text(encoding="utf-8")
    block = re.search(rf"^{section}:\n(?:[ ]+.*\n)+", text, re.M)
    assert block, section
    if re.search(rf"^  {key}:", block.group(0), re.M):
        changed = re.sub(rf"^(  {key}:).*$", rf"\1 {raw}", block.group(0), flags=re.M)
    else:  # defaults are not in the file: add the line
        changed = block.group(0) + f"  {key}: {raw}\n"
    path.write_text(text.replace(block.group(0), changed), encoding="utf-8")
    with pytest.raises(DataError, match=r"team\.yaml"):
        Repository(data_dir).load("demo")


def test_unknown_team_lists_known_teams(data_dir: Path):
    with pytest.raises(DataError, match="demo"):
        Repository(data_dir).load("gibtsnicht")


def test_demo_data_is_valid(data_dir: Path):
    assert check_team(Repository(data_dir).load("demo"), TODAY) == []


def test_validation_finds_errors_and_warnings(data_dir: Path):
    repo = Repository(data_dir)
    data = repo.load("demo")
    s = data.sprint("2026.20")
    s.absences["niemand"] = 1
    s.absences["anna"] = 20
    s.velocity = None
    s.scope_creep = 30
    data.people[0].memberships[0].fte = 1.5
    issues = check_team(data, TODAY)
    errors = [i.message for i in issues if i.level is Level.ERROR]
    warnings = [i.message for i in issues if i.level is Level.WARNING]
    assert any("unbekannte Person 'niemand'" in m for m in errors)
    assert any("nur 10 Arbeitstage" in m for m in errors)
    assert any("fte 1.5" in m for m in errors)
    assert any("Velocity fehlt" in m for m in warnings)
    assert any("scope_creep 30" in m for m in warnings)


def test_capacity_sources_in_forecast(data_dir: Path):
    fc = build_forecast(Repository(data_dir).load("demo"), TODAY)
    sources = {e.sprint.id: e.result.plan_capacity_source for e in fc.upcoming()}
    assert sources == {
        "2026.21": CapacitySource.PEOPLE,
        "2026.22": CapacitySource.PEOPLE,
        # Absences unknown: calendar and people, absences estimated from history
        "2026.23": CapacitySource.ESTIMATED,
        "2026.24": CapacitySource.ESTIMATED,
    }
    assert fc.current.sprint.id == "2026.21"
    assert all(e.result.plan_capacity_source is CapacitySource.RECORDED for e in fc.history())


def test_apply_planning():
    from datetime import date as d

    from foresprint.forecast import apply_planning
    from foresprint.model import Planning, Sprint

    s = Sprint("x", d(2026, 1, 1), d(2026, 1, 15))
    assert apply_planning(s, None, Planning(carryover=1, backlog=7.5, corrections=[2])) is True
    assert s.commitment == 8.5  # carry-over + backlog, corrections only for the delta
    assert s.planning.total == 6.5
    assert apply_planning(s, 9.0, Planning(backlog=7.5)) is False
    assert s.commitment == 9.0
    assert apply_planning(s, 9.0, Planning()) is False
    assert s.planning is None  # empty cross-check = not recorded


def test_planning_plausibility(data_dir: Path):
    data = Repository(data_dir).load("demo")
    s = data.sprint("2026.21")  # current; demo: carry-over 0.25 + backlog 9.75 = commitment 10
    s.commitment = 12
    messages = [i.message for i in check_team(data, TODAY)]
    assert any("Commitment 12 weicht von Überkipper + Backlog (10)" in m for m in messages)
    s.commitment = 10
    s.planning.corrections = [20]
    messages = [i.message for i in check_team(data, TODAY)]
    assert not any("weicht" in m for m in messages)
    assert any("Korrekturen sind größer" in m for m in messages)
    # completed sprints (e.g. imported history) are not checked
    assert not any("weicht" in i.message for i in check_team(data, date(2027, 1, 1)))


@pytest.mark.parametrize(
    "key",
    ["a", "team-a", "team_a", "t1", "0", "1-team", "a-", "a" * 64, "con1", "comx", "com10", "null"],
)
def test_valid_team_keys(key: str):
    assert team_key_problem(key) is None


@pytest.mark.parametrize(
    "key",
    [
        "",
        "../x", "a/b", "a\\b", "/abs", "C:", "a:b", "..", ".", ".hidden", "a.b",
        " x", "x ", "a b", "a\n", "a\tb", "a\0b",
        "Team-A", "ä", "straße", "１",
        "-x", "_x", "a" * 65,
        "con", "prn", "aux", "nul", "com0", "com1", "com9", "lpt0", "lpt1", "lpt9",
        "CON", "Nul", "con.txt", "COM1.log", "aux.",
    ],
)  # fmt: skip
def test_invalid_team_keys(key: str):
    assert team_key_problem(key)


def test_team_key_problem_names_the_cause():
    assert "Windows" in team_key_problem("con")
    assert "Windows" in team_key_problem("COM1.txt")
    assert team_key_problem("../x").startswith("Kürzel: Kleinbuchstaben a–z (ohne Umlaute)")
    assert team_key_problem("köln") == team_key_problem("../x")  # umlauts are not allowed
    assert team_key_problem("a" * 65) == team_key_problem("../x")


def test_existing_team_with_unusual_name_still_loads(data_dir: Path):
    """Only new keys are checked; older teams (capital letters, dot) run unchanged."""
    shutil.copytree(data_dir / "demo", data_dir / "Alt.Team_X")
    repo = Repository(data_dir)
    assert team_key_problem("Alt.Team_X")
    assert "Alt.Team_X" in repo.teams()
    assert repo.exists("Alt.Team_X")
    assert repo.load("Alt.Team_X").team.key == "Alt.Team_X"


def test_clashing_team_ignores_case(data_dir: Path):
    repo = Repository(data_dir)
    shutil.copytree(data_dir / "demo", data_dir / "Alpha")
    assert repo.clashing_team("Alpha") == "Alpha"  # same name
    assert repo.clashing_team("alpha") == "Alpha"  # only spelled differently
    assert repo.clashing_team("../demo") is None  # no match via a path
    assert repo.clashing_team("beta") is None


@pytest.mark.parametrize("key", ["../out", "con", "Team X", "köln"])
def test_import_refuses_unsuitable_keys_for_new_teams(data_dir: Path, key: str):
    """The entry point for import plugins creates a new team: the key is checked there as well."""
    repo = Repository(data_dir)
    data = repo.load("demo")
    team = copy.deepcopy(data.team)
    team.key = key
    with pytest.raises(DataError, match="Kürzel"):
        import_sprints(repo, team, data.sprints[:1])
    assert sorted(p.name for p in data_dir.parent.iterdir()) == ["teams"]
    assert sorted(p.name for p in data_dir.iterdir()) == ["demo"]


def test_import_into_existing_team_with_unusual_key_still_works(data_dir: Path):
    shutil.copytree(data_dir / "demo", data_dir / "Alt.Team_X")
    repo = Repository(data_dir)
    data = repo.load("Alt.Team_X")
    assert import_sprints(repo, data.team, data.sprints[:1])
