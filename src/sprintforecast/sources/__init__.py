# SPDX-License-Identifier: EUPL-1.2
"""Ticket sources of the pre-planning (docs/design/ticket-planning.md, section 7).

A source delivers the tickets of the tracker in a neutral form (:class:`RawTicket`); the import
(``ticket_import.py``) turns them into :class:`~sprintforecast.model.Ticket` objects. Step 1 knows
the CSV export of Jira (``sources/csv.py``), step 2 a Jira Data Center client
(``sources/jira.py``, optional extra ``[jira]``). This package is only imported by the import and
the command, never by the core; the concrete sources are imported on demand."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from sprintforecast.i18n import t
from sprintforecast.storage import DataError

if TYPE_CHECKING:  # pragma: no cover
    from sprintforecast.model import TrackerSettings


# The label that marks a ticket as earmarked for a sprint (spec section 6.6).
LABEL_PREFIX = "planned_for_"


def planned_label(sprint_id: str) -> str:
    return LABEL_PREFIX + sprint_id


def label_sprints(labels: list[str]) -> list[str]:
    """Sprint ids of the ``planned_for_<sprint_id>`` labels, in order, without duplicates."""
    return list(
        dict.fromkeys(
            x.removeprefix(LABEL_PREFIX)
            for x in labels
            if x.startswith(LABEL_PREFIX) and len(x) > len(LABEL_PREFIX)
        )
    )


class SourceError(DataError):
    """A source cannot be read (file missing, column missing, value not a number …)."""


@dataclass
class RawTicket:
    """A ticket as the source delivers it, before sprint resolution and project assignment."""

    key: str
    title: str = ""
    status: str | None = None
    issue_type: str | None = None
    priority: str | None = None
    estimate: float | None = None
    remaining: float | None = None
    # The sprint name as the tracker shows it (resolved to a sprint id by the import).
    sprint_name: str | None = None
    rank: str | None = None
    epic: str | None = None
    labels: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    # Keys of tickets that must be finished first (Jira: inward "Blocks" links).
    blocked_by: list[str] = field(default_factory=list)
    # Done according to the tracker (Jira: resolution set).
    resolved: bool = False


class TicketSource(Protocol):
    """Something that delivers tickets: ``kind`` names the tracker kind (``csv``, later
    ``jira``), ``fetch`` reads all tickets or raises :class:`SourceError`."""

    kind: str

    def fetch(self) -> list[RawTicket]: ...


def open_source(
    settings: TrackerSettings,
    path: Path | None = None,
    *,
    token: str | None = None,
    transport: Any = None,
) -> TicketSource:
    """The source for these tracker settings. A ``path`` is a CSV export (also when the tracker
    is Jira: the offline fallback); without one, ``tracker.kind`` decides. Jira needs a token
    (``token``, else the environment or the keychain); ``transport`` is a hook for tests."""
    if path is not None:
        from sprintforecast.sources.csv import CsvSource

        return CsvSource(path, settings.fields)
    if settings.kind == "jira":
        from sprintforecast.sources.jira import JiraSource, jira_token, missing_token_error

        token = token or jira_token(settings.base_url)
        if not token:
            raise missing_token_error()
        return JiraSource(settings, token, transport)
    if settings.kind == "csv":
        raise SourceError(t("The source “csv” needs a file: --import FILE"))
    raise SourceError(t("Unknown ticket source “{kind}” (tracker.kind)", kind=settings.kind))


__all__ = [
    "LABEL_PREFIX",
    "RawTicket",
    "SourceError",
    "TicketSource",
    "label_sprints",
    "open_source",
    "planned_label",
]
