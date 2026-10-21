# SPDX-License-Identifier: EUPL-1.2
"""Golden references of the meeting minutes (``foresprint.protocol``): the Markdown text of the
three meetings (also with product tables taken from the real distribution of the cases), the
section parser, the fingerprint and a scripted sequence of file operations (write, no-change,
two saves in the same second, obsolete, rename, list) with the resulting folder.

Written to ``golden/expected/protocol/``. The Go port is ``go/internal/protocol``."""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from foresprint import protocol
from foresprint.forecast import build_forecast
from foresprint.products import by_po, distribution
from foresprint.storage import Repository, dump_yaml

NOW = datetime(2026, 7, 8, 9, 5)
FACTS = [("Capacity", "40 PT"), ("Commitment", "34 | 35"), ("Note", "two\nlines  here")]
NOTES = [("Decisions", ["first | pipe", "second\nline"]), ("Empty", []), ("Risks", ["x"])]


def distribution_input(d) -> dict[str, Any]:
    """The part of a distribution the minutes use, as the Go renderer gets it."""
    return {
        "rows": [
            {
                "name": r.product.name,
                "po": r.product.po,
                "active": r.active,
                "standard": r.standard,
                "preplanned": r.preplanned,
                "planned": r.planned,
                "done": r.done,
                "production_planned": r.production_planned,
                "production_done": r.production_done,
            }
            for r in d.rows
        ],
        "by_po": [{"po": po, "totals": totals} for po, totals in by_po(d)],
    }


def rendering(ctx) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    plain = [
        {"kind": k, "team": "Team | A", "sprint": "2026.7", "facts": FACTS, "notes": NOTES,
         "comment": c, "show_po": True, "text": protocol.render_protocol(
             k, "Team | A", "2026.7", now=NOW, facts=FACTS, notes=NOTES, comment=c)}
        for k in protocol.KINDS
        for c in ("", "  ", "A comment | with\\nbreaks\\n and   spaces")
    ]  # fmt: skip
    out += plain
    for case in ctx.resolved:
        data = ctx.load(case)
        if not data.products:
            continue
        fc = build_forecast(data, case.today)
        entries = [e for e in fc.entries if e.sprint.products or e in fc.upcoming()][:3]
        for e in entries:
            d = distribution(fc, e)
            for kind in protocol.KINDS:
                for show_po in (True, False):
                    out.append(
                        {
                            "case": case.name, "sprint": e.sprint.id, "kind": kind,
                            "team": data.team.name, "facts": FACTS, "notes": None,
                            "comment": "", "show_po": show_po,
                            "distribution": distribution_input(d),
                            "text": protocol.render_protocol(
                                kind, data.team.name, e.sprint.id, now=NOW, facts=FACTS,
                                d=d, show_po=show_po,
                            ),
                            "planning_lines": protocol.planning_distribution_lines(d, show_po),
                        }
                    )  # fmt: skip
    return out


def planning(ctx) -> list[dict[str, Any]]:
    sections = [
        protocol.PlanningSection("absences", "Absences", ["- anna: 2", "", "- ben: 1"]),
        protocol.PlanningSection("scheduling", "Scheduling", ["Tickets: 12"], recorded=False),
        protocol.PlanningSection("commitment", "Commitment", ["34"]),
    ]
    first = protocol.render_planning_protocol(
        "Team A", "2026.7", now=NOW, facts=FACTS, sections=sections, previous={}
    )
    parts = protocol._section_parts(first)
    later = datetime(2026, 7, 9, 10, 30)
    changed = [
        sections[0],
        sections[1],
        protocol.PlanningSection("commitment", "Commitment", ["35"]),
    ]
    second = protocol.render_planning_protocol(
        "Team A", "2026.7", now=later, facts=FACTS, sections=changed, previous=parts
    )
    return [
        {"text": first, "parts": parts},
        {"text": second, "parts": protocol._section_parts(second), "previous": parts},
        {
            "text": "x\r\n## S\r\n<!-- sprintforecast-section: a -->\r\n_As of_\r\n\r\nl1\r\n\r\n"
            "<!-- sprintforecast-state: abc -->\r\n<!-- sprintforecast-section: b -->\r\nl2\r\n",
            "parts": protocol._section_parts(
                "x\r\n## S\r\n<!-- sprintforecast-section: a -->\r\n_As of_\r\n\r\nl1\r\n\r\n"
                "<!-- sprintforecast-state: abc -->\r\n<!-- sprintforecast-section: b -->\r\nl2\r\n"
            ),
        },
    ]


def fingerprints() -> list[dict[str, Any]]:
    texts = [
        "# T\n\nAs of: 08.07.2026 09:05\n\n- a: 1\n",
        "# T\r\n\r\nAs of: 09.07.2026 10:00\r\n\r\n- a: 1\r\n",
        "# T\n\nAs of: 08.07.2026 09:05\n\n- a: 2\n",
        "",
        "one",
    ]
    docs: list[tuple[dict, ...]] = [
        (),
        ({"id": "2026.7", "velocity": 3.5, "absences": {}},),
        ({"id": "2026.7"}, {"id": "2026.8", "note": "grün ä"}),
    ]
    return [
        {"text": t, "documents": list(doc),
            "documents_yaml": [dump_yaml(d) for d in doc],
         "fingerprint": protocol.fingerprint(t, *doc)}
        for t in texts
        for doc in docs
    ]  # fmt: skip


def scenario() -> dict[str, Any]:
    """Operations in one team folder; ``now`` values are fixed, the lock is not part of it."""
    ops: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as tmp:
        repo = Repository(Path(tmp))
        (Path(tmp) / "t").mkdir()

        def listing() -> list[str]:
            folder = Path(tmp) / "t" / protocol.PROTOCOL_DIR
            return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []

        def at(*a: int) -> datetime:
            return datetime(*a)

        def step(name: str, **kw: Any) -> None:
            ops.append({"op": name, **kw, "folder": listing()})

        def write(sprint: str, kind: str, text: str, now: datetime, state: str | None = None):
            path, created = protocol.write_protocol_new(repo, "t", sprint, kind, text, now, state)
            step(
                "write", sprint=sprint, kind=kind, text=text, now=now, state=state,
                path=path.name, created=created,
                content=path.read_text(encoding="utf-8"),
            )  # fmt: skip

        write("2026.7", "planning", "# P\n\nAs of: x\n\n- a: 1\n", at(2026, 7, 8, 9, 0))
        write(
            "2026.7", "planning", "# P\n\nAs of: y\n\n- a: 1\n", at(2026, 7, 8, 9, 1)
        )  # same body
        write("2026.7", "planning", "# P\n\nAs of: y\n\n- a: 2\n", at(2026, 7, 8, 9, 0))  # same sec
        write("2026.7", "planning", "# P\n\nAs of: y\n\n- a: 3\n", at(2026, 7, 8, 9, 0), "abcd1234")
        write("2026.7", "planning", "# P\n\nAs of: z\n\n- a: 3\n", at(2026, 7, 8, 9, 5), "abcd1234")
        write("2026.7", "planning", "# P\n\nAs of: z\n\n- a: 4\n", at(2026, 7, 8, 9, 6), "ffff0000")
        write("2026.7", "review", "# R\r\n\r\nAs of: z\r\n\r\n- r: 1\r\n", at(2026, 7, 20, 16, 0))
        write("2026.8", "vorplanung", "# V\n\nAs of: z\n\n- v: 1\n", at(2026, 7, 8, 9, 0))
        write("2026.10", "planning", "# P10\n\nAs of: q\n\n", at(2026, 8, 1, 0, 0, 0))

        def listed(sprint: str) -> None:
            rows = protocol.list_protocols(repo, "t", sprint)
            step(
                "list", sprint=sprint,
                found=[[a, k, o, p.name] for a, k, o, p in rows],
            )  # fmt: skip

        listed("2026.7")
        listed("2026.8")
        listed("2026.1")

        moved = protocol.mark_obsolete(repo, "t", "2026.7", "planning", at(2026, 7, 9, 12, 0))
        step("obsolete", sprint="2026.7", kind="planning", now=at(2026, 7, 9, 12, 0),
             renamed=[p.name for p in moved])  # fmt: skip
        listed("2026.7")
        moved = protocol.mark_obsolete(repo, "t", "2026.7", "planning", at(2026, 7, 9, 12, 0))
        step("obsolete", sprint="2026.7", kind="planning", now=at(2026, 7, 9, 12, 0),
             renamed=[p.name for p in moved])  # fmt: skip
        write("2026.7", "planning", "# P\n\nAs of: n\n\n- a: 9\n", at(2026, 7, 10, 8, 0))
        moved = protocol.mark_obsolete(repo, "t", "2026.7", "planning", at(2026, 7, 9, 12, 0))
        step("obsolete", sprint="2026.7", kind="planning", now=at(2026, 7, 9, 12, 0),
             renamed=[p.name for p in moved])  # fmt: skip
        renames = protocol.protocol_renames(repo, "t", [("2026.7", "2026.07"), ("2026.8", "A")])
        step("renames", renames=[[a.name, b.name] for a, b in renames])
        # Names that do not belong or are impossible are ignored.
        folder = Path(tmp) / "t" / protocol.PROTOCOL_DIR
        for name in (
            "2026.7-planning-20261340-250000.md",
            "2026.7-planning-20260101-000000.txt",
            "2026.7-other-20260101-000000.md",
            "2026.7-planning-20260101-000000-ZZZZ.md",
            "2026.7-planning-20260101-000000-abcd_obsolet_20260102-000000.md",
            "2026.7-planning-20260101-000000-abcd_obsolet_20260102-000000.md.bak",
        ):
            (folder / name).write_text("x", encoding="utf-8")
        (folder / "2026.7-review-20260102-000000").mkdir()
        listed("2026.7")
    return {"operations": ops}


def generate(ctx) -> None:
    ctx.write(
        "protocol/cases.json",
        ctx.dump_json(
            ctx.jsonable(
                {
                    "kind_titles": {k: protocol.kind_title(k) for k in protocol.KINDS},
                    "cell": [
                        {"text": s, "cell": protocol._cell(s)}
                        for s in (None, "", "a | b", "line\none", "  many   spaces ", "tab\there")
                    ],
                    "md_item": [{"text": s, "item": protocol.md_item(s)} for s in ("a|b", "x\ny")],
                    "rendering": rendering(ctx),
                    "planning": planning(ctx),
                    "fingerprints": fingerprints(),
                    "scenario": scenario(),
                }
            )
        ),
    )
