# SPDX-License-Identifier: EUPL-1.2
"""Protokolle der Sprint-Termine: schreiben, auflisten, bei Aufheben des Einfrierens obsolet."""

from datetime import datetime
from pathlib import Path

from sprintforecast.protocol import (
    PLANNING,
    PREPLANNING,
    list_protocols,
    mark_obsolete,
    render_protocol,
    write_protocol,
)
from sprintforecast.storage import Repository

NOW = datetime(2026, 10, 16, 14, 43, 5)
LATER = datetime(2026, 10, 20, 9, 0, 0)


def test_render_escapes_table_separators_and_lists_facts():
    text = render_protocol(
        PREPLANNING,
        "Team|A",
        "2026.21",
        now=NOW,
        facts=[("Kapazität", "50,6")],
        comment="Daily\nvom 16.10. | Prognose",
        notes=[("Annahmen", ["a | b"]), ("Leer", [])],
    )
    assert "- Kapazität: 50,6" in text
    assert "Team\\|A" in text and "a \\| b" in text
    assert "Daily vom 16.10. \\| Prognose" in text
    assert "## Leer" not in text


def test_write_list_and_lf_line_endings(tmp_path: Path):
    repo = Repository(tmp_path)
    path = write_protocol(repo, "demo", "2026.21", PREPLANNING, "a\nb\n", NOW)
    assert path.name == "2026.21-vorplanung-20261016-144305.md"
    assert b"\r" not in path.read_bytes()
    write_protocol(repo, "demo", "2026.21", PREPLANNING, "neu\n", LATER)
    write_protocol(repo, "demo", "2026.22", PREPLANNING, "anderer Sprint\n", LATER)
    found = list_protocols(repo, "demo", "2026.21")
    assert [(f[0], f[1], f[2]) for f in found] == [
        (LATER, PREPLANNING, False),
        (NOW, PREPLANNING, False),
    ]


def test_unfreeze_marks_only_the_planning_protocol_obsolete(tmp_path: Path):
    repo = Repository(tmp_path)
    plan = write_protocol(repo, "demo", "2026.21", PLANNING, "x\n", NOW)
    pre = write_protocol(repo, "demo", "2026.21", PREPLANNING, "y\n", NOW)
    renamed = mark_obsolete(repo, "demo", "2026.21", PLANNING, LATER)
    assert [p.name for p in renamed] == [
        "2026.21-planning-20261016-144305_obsolet_20261020-090000.md"
    ]
    assert not plan.exists() and pre.exists() and renamed[0].read_text() == "x\n"
    assert [f[2] for f in list_protocols(repo, "demo", "2026.21") if f[1] == PLANNING] == [True]
    # ein zweites Aufheben benennt Obsoletes nicht noch einmal um
    assert mark_obsolete(repo, "demo", "2026.21", PLANNING, LATER) == []
