# SPDX-License-Identifier: EUPL-1.2
"""Protokolle der Sprint-Termine (PO-Vorplanung, Planning, Review).

Bei jedem Speichern entsteht eine Markdown-Datei
``<team>/protokolle/<sprint>-<termin>-<Datum>-<Zeit>.md``; ältere Stände bleiben lesbar. Wird
ein Termin hinfällig (z. B. beim Aufheben des Einfrierens), heißt das alte Protokoll danach
``…_obsolet_<Datum>-<Zeit>.md``."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from sprintforecast.i18n import t
from sprintforecast.products import Distribution, by_po, measure_label
from sprintforecast.report import fmt
from sprintforecast.storage import FileAccessError, Repository, write_text

PROTOCOL_DIR = "protokolle"
STAMP = "%Y%m%d-%H%M%S"
PREPLANNING, PLANNING, REVIEW = "vorplanung", "planning", "review"
KINDS = (PREPLANNING, PLANNING, REVIEW)
# Spalten der Produkttabelle je Termin.
KIND_MEASURES = {
    PREPLANNING: ("standard", "preplanned"),
    PLANNING: ("standard", "preplanned", "planned"),
    REVIEW: ("planned", "done"),
}
_NAME = re.compile(
    r"^(?P<sprint>.+)-(?P<kind>vorplanung|planning|review)-(?P<at>\d{8}-\d{6})"
    r"(?:_obsolet_(?P<obsolete>\d{8}-\d{6}))?\.md$"
)


def _cell(text: str | None) -> str:
    """Text für eine Markdown-Zelle oder -Zeile (Trennstriche und Zeilenwechsel neutralisieren)."""
    return " ".join((text or "").replace("|", "\\|").split())


def kind_title(kind: str) -> str:
    return {
        PREPLANNING: t("PO-Vorplanung"),
        PLANNING: t("Sprint Planning"),
        REVIEW: t("Sprint Review"),
    }[kind]


def render_protocol(
    kind: str,
    team: str,
    sprint_id: str,
    *,
    now: datetime,
    facts: list[tuple[str, str]],
    d: Distribution | None = None,
    notes: list[tuple[str, list[str]]] | None = None,
    comment: str = "",
    show_po: bool = True,
) -> str:
    """Markdown-Text eines Termins: Kopf, Kennzahlen (``facts``), Abschnitte (``notes``) und –
    mit ``d`` – die Verteilung je Produkt (und je PO)."""
    lines = [
        f"# {kind_title(kind)} {_cell(team)} – {t('Sprint {id}', id=sprint_id)}",
        "",
        t("Stand: {at}", at=f"{now:%d.%m.%Y %H:%M}"),
        "",
    ]
    lines += [f"- {label}: {_cell(value)}" for label, value in facts]
    if comment.strip():
        lines += ["", f"**{t('Kommentar')}:** {_cell(comment)}"]
    for title, items in notes or []:
        if items:
            lines += ["", f"## {title}", ""] + [f"- {_cell(i)}" for i in items]
    measures = KIND_MEASURES[kind]
    if d is not None and d.rows:
        header = [t("Produkt"), *(["PO"] if show_po else [])]
        header += [measure_label(m) for m in measures]
        lines += ["", f"## {t('Je Produkt')}", ""]
        lines += ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        for r in d.rows:
            if not (r.active or any(r.value(m) is not None for m in measures)):
                continue
            cells = [_cell(r.product.name), *([_cell(r.product.po)] if show_po else [])]
            cells += [fmt(r.value(m), 2) for m in measures]
            lines.append("| " + " | ".join(cells) + " |")
        if show_po and (po_rows := by_po(d)):
            header = ["PO", *(measure_label(m) for m in measures)]
            lines += ["", f"## {t('Je PO')}", "", "| " + " | ".join(header) + " |"]
            lines.append("|" + "---|" * len(header))
            for po, totals in po_rows:
                cells = [_cell(po), *(fmt(totals[m], 2) for m in measures)]
                lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def _folder(repo: Repository, team: str) -> Path:
    return repo.team_dir(team) / PROTOCOL_DIR


def write_protocol(
    repo: Repository, team: str, sprint_id: str, kind: str, text: str, now: datetime
) -> Path:
    """Schreibt das Protokoll (LF-Zeilenenden, über eine Zwischendatei)."""
    path = _folder(repo, team) / f"{sprint_id}-{kind}-{now:{STAMP}}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text(path, text, newline="\n")
    return path


def list_protocols(
    repo: Repository, team: str, sprint_id: str
) -> list[tuple[datetime, str, bool, Path]]:
    """Die Protokolle eines Sprints als (Zeitpunkt, Termin, obsolet, Datei), neueste zuerst."""
    folder = _folder(repo, team)
    found: list[tuple[datetime, str, bool, Path]] = []
    if folder.is_dir():
        for p in folder.iterdir():
            m = _NAME.match(p.name)
            if m and m["sprint"] == sprint_id and p.is_file():
                at = datetime.strptime(m["at"], STAMP)
                found.append((at, m["kind"], m["obsolete"] is not None, p))
    return sorted(found, key=lambda f: (f[0], f[3].name), reverse=True)


def mark_obsolete(
    repo: Repository, team: str, sprint_id: str, kind: str, now: datetime
) -> list[Path]:
    """Benennt die gültigen Protokolle des Termins in ``…_obsolet_<Datum>-<Zeit>.md`` um (z. B.
    wenn das Einfrieren des Sprints aufgehoben wird). Liefert die neuen Dateien."""
    renamed: list[Path] = []
    for _, found_kind, obsolete, path in list_protocols(repo, team, sprint_id):
        if found_kind != kind or obsolete:
            continue
        target = path.with_name(f"{path.stem}_obsolet_{now:{STAMP}}.md")
        try:
            path.replace(target)
        except OSError as e:
            raise FileAccessError(
                t("{path}: nicht umbenannt ({reason})", path=path, reason=str(e))
            ) from e
        renamed.append(target)
    return renamed
