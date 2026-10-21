# SPDX-License-Identifier: EUPL-1.2
"""Golden references of the ticket pre-planning (``foresprint.preplan``) on altered copies of the
synthetic team ``tickets-products``: dependency cycles, an ended tracker sprint, earmarks, a
dependency gap, the budget basis ``plan``, rough factor, priorities, no products, tickets far
beyond the horizon and a project that is already late.

Written like ``golden_ext/validate.py``: per case only the changed files below
``golden/inputs/preplan/<case>/`` (and the deleted ones) plus ``golden/expected/preplan/cases.json``
with the export of ``golden.export_preplan``. The Go port is ``go/internal/preplan``."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import yaml

BASE = "tickets-products"
TODAY = date(2026, 7, 8)

Files = dict[str, str]
Edit = Callable[[Files], None]


def dump(obj: Any) -> str:
    return yaml.safe_dump(obj, sort_keys=False, allow_unicode=True, width=100)


def Y(path: str, fn: Callable[[Any], None]) -> Edit:
    def run(files: Files) -> None:
        obj = yaml.safe_load(files[path])
        fn(obj)
        files[path] = dump(obj)

    return run


def ticket(key: str, **fields: Any) -> Edit:
    def run(d: dict) -> None:
        for t in d["tickets"]:
            if t["key"] == key:
                t.update(fields)
                return
        raise KeyError(key)

    return Y("tickets.yaml", run)


def team(**fields: Any) -> Edit:
    def run(d: dict) -> None:
        for dotted, value in fields.items():
            *parents, last = dotted.split("__")
            node = d
            for p in parents:
                node = node.setdefault(p, {})
            node[last] = value

    return Y("team.yaml", run)


def project(pid: str, **fields: Any) -> Edit:
    def run(d: dict) -> None:
        for p in d["projects"]:
            if p["id"] == pid:
                p.update(fields)
                return
        raise KeyError(pid)

    return Y("projects.yaml", run)


def earmarks(*pairs: tuple[str, str]) -> Edit:
    return Y("preplan.yaml", lambda d: d.update(earmarks=[{"ticket": t, "sprint": s} for t, s in pairs]))


CASES: list[tuple[str, list[Edit]]] = [
    ("cycle", [ticket("W-1", depends_on=["W-2"])]),
    ("cycle-chain", [ticket("W-1", depends_on=["W-2"]), ticket("W-14", depends_on=["W-1"])]),
    ("ended-tracker-sprint", [ticket("W-12", in_sprint="2026.3"), ticket("W-14", in_sprint="2026.7")]),
    ("tracker-sprint-far", [ticket("W-12", in_sprint="2031.1"), ticket("W-14", in_sprint="9999.9")]),
    ("earmarks", [earmarks(("W-4", "2026.9"), ("W-3", "2026.8"), ("W-5", "2026.2"), ("L-1", "2027.20"))]),
    ("dependency-gap", [team(tracker__dependency_gap=2)]),
    ("basis-plan", [team(tracker__budget_basis="plan")]),
    ("basis-roadmap", [team(tracker__budget_basis="roadmap_share", forecast__roadmap_share=0.5)]),
    ("rough-factor", [team(tracker__rough_factor=2.5)]),
    ("priorities", [team(tracker__priority_order=["Normal", "High"]), ticket("W-3", priority="Blocker")]),
    ("products-off", [team(features__products=False)]),
    ("project-late", [project("shop", target="2026-07-10"), project("pay", target="2026-06-01")]),
    ("too-large", [ticket("W-3", estimate=99), ticket("W-14", estimate=0)]),
    ("shop-no-target", [project("shop", target=None), project("legacy", target="2030-01-01")]),
]


def read_tree(folder: Path) -> Files:
    return {p.relative_to(folder).as_posix(): p.read_text(encoding="utf-8") for p in sorted(folder.rglob("*.yaml"))}


def generate(ctx) -> None:
    import tempfile

    import golden
    from foresprint.storage import DataError, Repository, clear_team_cache

    source = next(c for c in ctx.resolved if c.name == BASE)
    original = read_tree(Path(source.root) / source.team)
    out = []
    for name, edits in CASES:
        files = dict(original)
        for edit in edits:
            edit(files)
        changed = {p: t for p, t in files.items() if original.get(p) != t}
        target = ctx.out / "inputs" / "preplan" / name
        for path, text in changed.items():
            dest = target / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text, encoding="utf-8", newline="")
        entry: dict[str, Any] = {
            "name": name,
            "base": BASE,
            "team": source.team,
            "today": TODAY,
            "overrides": sorted(changed),
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "t"
            folder = root / source.team
            for path, text in files.items():
                dest = folder / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(text, encoding="utf-8", newline="")
            clear_team_cache()
            try:
                data = Repository(root).load(source.team)
            except DataError as err:
                entry["load_error"] = str(err).replace(str(root), "<data>")
            else:
                entry["preplan"] = golden.export_preplan(data, TODAY)
        out.append(entry)
    ctx.write("preplan/cases.json", ctx.dump_json(ctx.jsonable({"cases": out})))
