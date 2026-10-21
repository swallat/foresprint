# SPDX-License-Identifier: EUPL-1.2
"""Demo data with the ticket pre-planning switched on (shared by the ticket tests)."""

from pathlib import Path

import yaml

from foresprint.storage import Repository


def enable(data_dir: Path, projects: bool = True) -> None:
    team = data_dir / "demo"
    doc = yaml.safe_load((team / "team.yaml").read_text(encoding="utf-8"))
    doc["features"]["tickets"] = True
    doc["tracker"] = {
        "kind": "csv",
        "fields": {"estimate": "Story Points", "remaining": "Remaining", "epic": "Epic Link"},
        "refined_label": "Refined",
    }
    (team / "team.yaml").write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    if projects:
        (team / "projects.yaml").write_text(
            yaml.safe_dump(
                {
                    "schema": 1,
                    "projects": [
                        {
                            "id": "payment", "name": "Payment", "product": "webshop",
                            "target": "2027-03-31", "match": {"epic": ["ABC-100"]},
                        },
                        {
                            "id": "migration", "name": "Migration", "product": "webshop",
                            "target": "2026-11-30", "match": {"epic": ["ABC-200"]},
                        },
                    ],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )  # fmt: skip


def seed(data_dir: Path) -> None:
    """Tickets small enough for the budget of the demo team (3 per sprint and product)."""
    from foresprint.model import EstimateSource, Ticket

    refined, rough = EstimateSource.REFINED, EstimateSource.ROUGH

    def ticket(key: str, project: str, size: float | None, source=refined, **kw) -> Ticket:
        return Ticket(
            key=key, title=f"Title of {key}", project=project, estimate=size, remaining=None,
            estimate_source=source if size is not None else EstimateSource.NONE, rank=key, **kw,
        )  # fmt: skip

    Repository(data_dir).save_tickets(
        "demo",
        [
            ticket("T-1", "payment", 2),
            ticket("T-2", "payment", 2, rough),
            ticket("T-3", "payment", 1, rough),
            ticket("T-4", "migration", 3),
            ticket("T-5", "migration", 2, rough, depends_on=["T-4"]),
            ticket("T-6", "payment", None),
            ticket("T-7", "payment", 1, in_sprint="2026.22"),
        ],
        None,
        "seed",
    )
