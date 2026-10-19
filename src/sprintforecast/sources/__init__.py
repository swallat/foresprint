# SPDX-License-Identifier: EUPL-1.2
"""Ticket sources of the pre-planning (docs/design/ticket-planning.md, section 7).

A source delivers the tickets of the tracker in a neutral form (:class:`RawTicket`); the import
(``ticket_import.py``) turns them into :class:`~sprintforecast.model.Ticket` objects. Step 1 knows
the CSV export of Jira (``sources/csv.py``); a Jira client follows in a later step. This package
is only imported by the import, never by the core."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from sprintforecast.storage import DataError


class SourceError(DataError):
    """A source cannot be read (file missing, column missing, value not a number …)."""


@dataclass
class RawTicket:
    """A ticket as the source delivers it, before sprint resolution and project assignment."""

    key: str
    title: str = ""
    status: str | None = None
    issue_type: str | None = None
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


__all__ = ["RawTicket", "SourceError", "TicketSource"]
