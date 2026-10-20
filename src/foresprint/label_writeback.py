# SPDX-License-Identifier: EUPL-1.2
"""Write-back of the earmarks as Jira labels (docs/design/ticket-planning.md, section 6.6).

An earmark of the tool becomes the label ``planned_for_<sprint_id>`` on the ticket; an old
``planned_for_*`` label that does not match goes. :func:`plan_label_writes` only compares and
writes nothing (the preview); :func:`apply_label_writes` does the one thing the tool ever
writes to Jira and only for the changes of the plan. Precedence: Jira sprint field > earmark of
the tool > label, so a ticket in a real sprint gets no label and loses a stale one."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from foresprint.i18n import t
from foresprint.model import Preplan, Ticket
from foresprint.sources import SourceError, label_sprints, planned_label


@dataclass
class LabelWrite:
    key: str
    title: str = ""
    add: list[str] = field(default_factory=list)
    remove: list[str] = field(default_factory=list)


@dataclass
class LabelPlan:
    writes: list[LabelWrite] = field(default_factory=list)
    # Tickets whose label cannot be written (translated texts).
    warnings: list[str] = field(default_factory=list)


def wanted_label(ticket: Ticket, preplan: Preplan) -> str | None:
    """The label the ticket should carry: its earmark, unless it is done or in a real sprint."""
    if ticket.done or ticket.in_sprint is not None:
        return None
    earmark = preplan.earmark_for(ticket.key)
    return planned_label(earmark.sprint) if earmark is not None else None


def plan_label_writes(tickets: list[Ticket], preplan: Preplan) -> LabelPlan:
    """The label changes that make the tracker match the earmarks; only changes are listed.
    Done tickets are left alone."""
    plan = LabelPlan()
    for ticket in tickets:
        if ticket.done:
            continue
        wanted = wanted_label(ticket, preplan)
        if wanted is not None and any(c.isspace() for c in wanted):
            plan.warnings.append(
                t(
                    (
                        'Ticket {key}: the label "{label}" contains spaces, which Jira does '
                        "not allow – change the sprint id or plan without a label"
                    ),
                    key=ticket.key,
                    label=wanted,
                )
            )
            continue
        present = [planned_label(s) for s in label_sprints(ticket.labels)]
        remove = [x for x in present if x != wanted]
        add = [wanted] if wanted is not None and wanted not in present else []
        if add or remove:
            plan.writes.append(LabelWrite(ticket.key, ticket.title, add, remove))
    return plan


def apply_label_writes(source: Any, plan: LabelPlan) -> int:
    """Sends the planned changes one ticket at a time and returns how many were written. The
    first failure stops the run (``SourceError``); what was written before stays, and the
    next run starts from the then current labels."""
    done = 0
    for write in plan.writes:
        try:
            source.set_labels(write.key, write.add, write.remove)
        except SourceError as e:
            raise SourceError(
                t(
                    "Ticket {key}: {error} – {done} of {total} changes written",
                    key=write.key,
                    error=str(e),
                    done=done,
                    total=len(plan.writes),
                )
            ) from e
        done += 1
    return done
