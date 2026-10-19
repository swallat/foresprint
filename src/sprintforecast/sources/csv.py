# SPDX-License-Identifier: EUPL-1.2
"""CSV export of Jira as a ticket source (docs/design/ticket-planning.md, section 7.2).

Reads the standard export of the advanced Jira search ("all fields"). Column names follow the
Jira export in English or German; custom fields appear as "Custom field (<name>)" or
"Benutzerdefiniertes Feld (<name>)" with the display names from ``tracker.fields``. Jira repeats
a header for multi-value fields (Labels, Sprint, Component/s, issue links): each occurrence is
one value."""

from __future__ import annotations

import csv
import io
import math
from pathlib import Path

from sprintforecast.i18n import t
from sprintforecast.model import TrackerFields
from sprintforecast.sources import RawTicket, SourceError

# Jira's standard column names, English and German.
HEADERS: dict[str, tuple[str, ...]] = {
    "key": ("Issue key", "Vorgangsschlüssel"),
    "title": ("Summary", "Zusammenfassung"),
    "status": ("Status",),
    "issue_type": ("Issue Type", "Vorgangstyp"),
    "labels": ("Labels", "Stichwörter"),
    "components": ("Component/s", "Komponente/n"),
    "sprint": ("Sprint",),
    "rank": ("Custom field (Rank)", "Benutzerdefiniertes Feld (Rang)", "Rank", "Rang"),
    "resolution": ("Resolution", "Lösung"),
    # Inward link of the type "Blocks" = "is blocked by": the tickets that must be finished first.
    "blocked_by": ("Inward issue link (Blocks)", "Eingehende Vorgangsverknüpfung (Blocks)"),
    # Epic without a configured field name: the parent of the issue.
    "parent": ("Parent", "Übergeordnet"),
}
# Columns without which the file is useless; the others are optional.
REQUIRED = ("key", "title", "estimate")


def custom_field_headers(name: str) -> tuple[str, ...]:
    """The headers under which a custom field with this display name appears in the export."""
    return (f"Custom field ({name})", f"Benutzerdefiniertes Feld ({name})", name)


def _norm(header: str) -> str:
    return header.strip().casefold()


def sniff_delimiter(header_line: str) -> str:
    """``;`` when the header line contains more semicolons than commas, else ``,``."""
    return ";" if header_line.count(";") > header_line.count(",") else ","


def parse_number(value: str) -> float | None:
    """A number with decimal point or decimal comma; empty = None; other text raises."""
    text = value.strip()
    if not text:
        return None
    if "," in text:
        if "." in text:
            # Both present: the last one is the decimal separator, the other groups thousands.
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", "")
        else:
            text = text.replace(",", ".")
    number = float(text)
    if not math.isfinite(number):
        raise ValueError(f"not a finite number: {value!r}")
    return number


class CsvSource:
    """Tickets from a CSV export of Jira."""

    kind = "csv"

    def __init__(self, path: Path, fields: TrackerFields) -> None:
        self.path = Path(path)
        self.fields = fields

    @property
    def name(self) -> str:
        """Name of the source as stored in tickets.yaml."""
        return self.path.name

    def headers(self) -> dict[str, tuple[str, ...]]:
        """Accepted headers per column, including the configured custom fields."""
        wanted = dict(HEADERS)
        if self.fields.estimate:
            wanted["estimate"] = custom_field_headers(self.fields.estimate)
        if self.fields.remaining:
            wanted["remaining"] = custom_field_headers(self.fields.remaining)
        if self.fields.epic:
            wanted["epic"] = custom_field_headers(self.fields.epic)
        else:
            wanted["epic"] = wanted.pop("parent")
        return wanted

    def fetch(self) -> list[RawTicket]:
        text = self._read()
        first_line = text.split("\n", 1)[0]
        # strict: a quote that never closes is an error instead of swallowing the rest of the
        # file into one cell.
        reader = csv.reader(io.StringIO(text), delimiter=sniff_delimiter(first_line), strict=True)
        try:
            header = next(reader)
        except StopIteration:
            raise SourceError(t("{path}: Die Datei ist leer", path=self.path)) from None
        except csv.Error as e:
            raise self._csv_error(e, 1) from e
        columns = self._columns(header)
        tickets = []
        while True:
            start = reader.line_num + 1
            try:
                row = next(reader)
            except StopIteration:
                break
            except csv.Error as e:
                raise self._csv_error(e, start) from e
            if not any(cell.strip() for cell in row):
                continue
            tickets.append(self._ticket(row, columns, reader.line_num))
        return tickets

    def _csv_error(self, error: csv.Error, line: int) -> SourceError:
        return SourceError(
            t(
                "{path}, Zeile {line}: Die Datei ist keine gültige CSV-Datei ({error})",
                path=self.path,
                line=line,
                error=error,
            )
        )

    def _read(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as e:
            raise SourceError(
                t("{path}: Die Datei ist nicht UTF-8-kodiert ({error})", path=self.path, error=e)
            ) from e
        except OSError as e:
            raise SourceError(
                t("{path}: Datei nicht lesbar: {error}", path=self.path, error=e.strerror or e)
            ) from e

    def _columns(self, header: list[str]) -> dict[str, list[int]]:
        """Column indexes per field (several for repeated headers); missing required columns
        raise with the headers that would have been accepted."""
        if not self.fields.estimate:
            raise SourceError(
                t(
                    "{path}: Der Feldname der Schätzung ist nicht eingestellt "
                    "(tracker.fields.estimate in team.yaml)",
                    path=self.path,
                )
            )
        wanted = self.headers()
        positions: dict[str, list[int]] = {}
        for index, cell in enumerate(header):
            name = _norm(cell)
            for field_name, aliases in wanted.items():
                if any(_norm(alias) == name for alias in aliases):
                    positions.setdefault(field_name, []).append(index)
        missing = [name for name in REQUIRED if name not in positions]
        if missing:
            raise SourceError(
                "\n".join(
                    t(
                        "{path}: Spalte fehlt – erwartet {names}",
                        path=self.path,
                        names=" / ".join(f"„{alias}“" for alias in wanted[name]),
                    )
                    for name in missing
                )
            )
        return positions

    def _ticket(self, row: list[str], columns: dict[str, list[int]], line: int) -> RawTicket:
        def values(name: str) -> list[str]:
            found = [row[i].strip() for i in columns.get(name, []) if i < len(row)]
            return [v for v in found if v]

        def single(name: str) -> str | None:
            found = values(name)
            return found[0] if found else None

        def number(name: str) -> float | None:
            found = values(name)
            if not found:
                return None
            column = self.headers()[name][0]
            try:
                value = parse_number(found[0])
            except ValueError:
                raise SourceError(
                    t(
                        "{path}, Zeile {line}: '{value}' in Spalte „{column}“ ist keine Zahl",
                        path=self.path,
                        line=line,
                        value=found[0],
                        column=column,
                    )
                ) from None
            if value == 0:
                value = 0.0  # "-0" is stored as 0
            if value is not None and value < 0:
                raise SourceError(
                    t(
                        "{path}, Zeile {line}: '{value}' in Spalte „{column}“ ist negativ",
                        path=self.path,
                        line=line,
                        value=found[0],
                        column=column,
                    )
                )
            return value

        key = single("key")
        if key is None:
            raise SourceError(t("{path}, Zeile {line}: Schlüssel fehlt", path=self.path, line=line))
        sprints = values("sprint")
        return RawTicket(
            key=key,
            title=" ".join((single("title") or "").split()),
            status=single("status"),
            issue_type=single("issue_type"),
            estimate=number("estimate"),
            remaining=number("remaining"),
            # Jira lists the sprints of a ticket chronologically: the last one is the current.
            sprint_name=sprints[-1] if sprints else None,
            rank=single("rank"),
            epic=single("epic"),
            labels=list(dict.fromkeys(values("labels"))),
            components=list(dict.fromkeys(values("components"))),
            blocked_by=list(dict.fromkeys(values("blocked_by"))),
            resolved=bool(values("resolution")),
        )
