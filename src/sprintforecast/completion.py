# SPDX-License-Identifier: EUPL-1.2
"""Shell completion (bash, zsh, fish, PowerShell): scripts and dynamic values.

Typer's own completion (``--install-completion``) starts the program on every Tab, so the
completers here import nothing heavy: no YAML parsing, only a look at the folder names.
"""

from __future__ import annotations

import re
import sys
from enum import StrEnum
from pathlib import Path

import click


class Shell(StrEnum):
    BASH = "bash"
    ZSH = "zsh"
    FISH = "fish"
    POWERSHELL = "powershell"


def prog_name() -> str:
    """Name the program was started with (``sprintforecast``, ``foresprint``, ...)."""
    return Path(sys.argv[0]).stem or "sprintforecast"


def complete_var(prog: str) -> str:
    """Environment variable through which the script asks for completions (as in Typer)."""
    return "_{}_COMPLETE".format(prog.replace("-", "_").upper())


def script(shell: Shell, prog: str) -> str:
    """The completion script of ``shell`` for the command ``prog``."""
    from typer._completion_shared import get_completion_script

    return get_completion_script(prog_name=prog, complete_var=complete_var(prog), shell=shell.value)


def _data_dir(ctx: click.Context) -> Path:
    from sprintforecast.storage import default_data_dir

    given = ctx.find_root().params.get("data")
    return Path(given) if given else default_data_dir()


def _natural(sprint_id: str) -> list[tuple[int, str]]:
    """Sort key: 2026.9 before 2026.10."""
    return [
        (int(part), "") if part.isdigit() else (0, part) for part in re.split(r"(\d+)", sprint_id)
    ]


def team_names(ctx: click.Context, incomplete: str) -> list[str]:
    """Teams of the data folder (``--data`` already typed, else the usual folder)."""
    try:
        root = _data_dir(ctx)
        found = sorted(p.parent.name for p in root.glob("*/team.yaml"))
    except OSError:
        return []
    return [name for name in found if name.startswith(incomplete)]


def sprint_ids(ctx: click.Context, incomplete: str) -> list[str]:
    """Sprint IDs of the team typed before (the file names in ``<team>/sprints``)."""
    team = ctx.params.get("team")
    if not team:
        return []
    try:
        folder = _data_dir(ctx) / team / "sprints"
        found = sorted((p.stem for p in folder.glob("*.yaml")), key=_natural)
    except OSError:
        return []
    return [name for name in found if name.startswith(incomplete)]
