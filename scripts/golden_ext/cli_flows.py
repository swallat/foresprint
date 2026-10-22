# SPDX-License-Identifier: EUPL-1.2
"""Golden references of the interactive commands (init, settings, people, ...): each scenario runs
the Python command line on a copy of the demo team with typed answers and records the exit code
and the files the command wrote. The Go test replays the scenarios and compares the files byte
for byte. Texts on the screen are not compared (Python draws panels and tables, Go prints plain
text); the order and meaning of the questions are, because the typed answers must end up in the
same files."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from typer.testing import CliRunner

from foresprint.cli import app
from foresprint.settings import FIRST_SPRINT_KEYS, applicable

ROOT = Path(__file__).resolve().parents[2]
AS_OF = "2026-03-10"


def _answers(has_sprints: bool, given: dict[str, str]) -> str:
    """Input for init (has_sprints False) or settings: one line per question in the order the
    command asks; ``given`` has the answers by key, everything else accepts the default."""
    keys = [s.key for s in applicable(has_sprints=has_sprints)]
    if not has_sprints:  # init asks name, the first sprint keys, then the rest
        keys = [
            "name",
            *FIRST_SPRINT_KEYS,
            *[k for k in keys if k != "name" and k not in FIRST_SPRINT_KEYS],
        ]
    return "".join(given.get(k, "") + "\n" for k in keys)


SCENARIOS: list[dict] = [
    {
        "name": "init-defaults",
        "args": ["init", "team-zeta"],
        "input": _answers(
            False,
            {
                "name": "Team Zeta",
                "sprint.numbering": "yearly",
                "sprint.first_start": "2026-03-02",
                "sprint.first_id": "2026.5",
            },
        ),
    },
    {
        "name": "init-changed",
        "args": ["init", "team-eta"],
        "input": _answers(
            False,
            {
                "name": "Team Eta",
                "unit": "SP",
                "features.products": "on",
                "capacity.country": "AT",
                "capacity.overhead_share": "10%",
                "sprint.length_days": "21",
                "sprint.numbering": "sequential",
                "sprint.first_start": "2026-03-02",
                "sprint.first_id": "12",
                "forecast.reference_capacity": "55,5",
                "forecast.trend_mode": "linear",
                "forecast.roadmap_share": "70",
            },
        ),
    },
    {
        "name": "init-id-mismatch",
        "args": ["init", "team-theta"],
        "input": "Team Theta\nsequential\n2026-03-02\n2026.15\n15\n" + "\n" * 40,
    },
    {
        "name": "init-invalid-then-valid",
        "args": ["init", "team-iota"],
        "input": "\nyearly\nnot a date\n2026-03-02\n\n2026.9\n" + "\n" * 40,
    },
    {"name": "init-existing", "args": ["init", "demo"], "input": ""},
    {"name": "init-bad-key", "args": ["init", "Bad Key"], "input": ""},
    {
        "name": "settings-change",
        "args": ["settings", "demo"],
        "input": _answers(
            True,
            {
                "unit": "SP",
                "capacity.country": "DE",
                "capacity.region": "BY",
                "forecast.window": "6",
            },
        )
        + "y\n",
    },
    {
        "name": "settings-nothing",
        "args": ["settings", "demo"],
        "input": _answers(True, {}),
    },
    {
        "name": "settings-declined",
        "args": ["settings", "demo"],
        "input": _answers(True, {"name": "Renamed"}) + "n\n",
    },
    {"name": "people-nothing", "args": ["people", "demo"], "input": "q\n"},
    {
        "name": "people-new",
        "args": ["people", "demo"],
        "input": "n\nZoë Test\nby\n2026-04-01\n0,5\nq\n",
    },
    {
        "name": "people-new-duplicate-then-valid",
        "args": ["people", "demo"],
        "input": "n\n\nn\nanna\nn\nMax\n\n\n0\n1\nq\n",
    },
    {
        "name": "people-change-fte",
        "args": ["people", "demo"],
        "input": "x\nf\nnobody\nan\n2026-04-01\n0,6\nq\n",
    },
    {
        "name": "people-change-fte-too-early",
        "args": ["people", "demo"],
        "input": "f\nanna\n2025-01-01\nq\n",
    },
    {"name": "people-leave", "args": ["people", "demo"], "input": "a\ncem\n2026-06-30\nq\n"},
    {"name": "people-former", "args": ["people", "demo", "--former"], "input": "q\n"},
    {"name": "absences-next", "args": ["absences", "demo"], "input": "1\n0\n0,5\n2\n0\ny\n"},
    {
        "name": "absences-keep-capacity",
        "args": ["absences", "demo"],
        "input": "0\n0\n0\n0\n0\nn\n",
    },
    {
        "name": "absences-sprint-clamped",
        "args": ["absences", "demo", "2026.9"],
        "input": "abc\n99\n-1\n1,5\n\n\n\n\n\n\n",
    },
    {"name": "absences-unknown-sprint", "args": ["absences", "demo", "1999.1"], "input": ""},
    {
        "name": "settings-invalid-then-valid",
        "args": ["settings", "demo"],
        "input": _answers(True, {"forecast.window": "abc\n0\n7"}) + "\n",
    },
]


def _snapshot(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def run_scenario(scenario: dict) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        data = base / "data"
        shutil.copytree(ROOT / "examples" / "teams", data)
        before = _snapshot(data)
        config = base / "config"
        config.mkdir()
        saved = {k: os.environ.get(k) for k in ("XDG_CONFIG_HOME", "HOME", "FORESPRINT_LANG")}
        os.environ.update(
            {"XDG_CONFIG_HOME": str(config), "HOME": str(base), "FORESPRINT_LANG": "en"}
        )
        try:
            runner = CliRunner(env={"COLUMNS": "200"})
            result = runner.invoke(
                app,
                ["--data", str(data), "--as-of", AS_OF, *scenario["args"]],
                input=scenario["input"],
            )
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        after = _snapshot(data)
        files = {k: v for k, v in after.items() if before.get(k) != v}
        return {
            "args": scenario["args"],
            "input": scenario["input"],
            "exit_code": result.exit_code,
            "files": files,
        }


def generate(ctx) -> None:
    for scenario in SCENARIOS:
        ctx.write(f"cliflows/{scenario['name']}.json", ctx.dump_json(run_scenario(scenario)))
