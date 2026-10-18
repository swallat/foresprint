# SPDX-License-Identifier: EUPL-1.2
"""Protokolle der Sprint-Termine (PO-Vorplanung, Planning, Review).

Bei jedem Speichern entsteht eine Markdown-Datei
``<team>/protokolle/<sprint>-<termin>-<Datum>-<Zeit>.md``; ältere Stände bleiben lesbar. Wird
ein Termin hinfällig (z. B. beim Aufheben des Einfrierens), heißt das alte Protokoll danach
``…_obsolet_<Datum>-<Zeit>.md``."""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import re
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import IO

from sprintforecast.git import invalidate_status
from sprintforecast.i18n import t
from sprintforecast.model import Sprint
from sprintforecast.products import Distribution, by_po, measure_label
from sprintforecast.report import fmt
from sprintforecast.storage import (
    FileAccessError,
    Repository,
    _not_readable,
    _not_saved,
    dump_yaml,
    sprint_to_dict,
    write_text,
)

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
    r"(?:-[0-9a-f]{4})?"  # Anfang des Fingerabdrucks, siehe write_protocol_new
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


def _body_of(text: str) -> list[str]:
    """Der Text ohne die Zeile „Stand: …“ (dritte Zeile, mit dem Zeitpunkt)."""
    lines = text.replace("\r\n", "\n").split("\n")
    return lines[:2] + lines[3:]


def _body(path: Path) -> list[str] | None:
    try:
        return _body_of(path.read_text(encoding="utf-8"))
    except OSError, UnicodeDecodeError:
        return None


STATE_MARKER = "<!-- sprintforecast-state: "


def fingerprint(text: str, *documents: dict) -> str:
    """Kurzer Fingerabdruck des gespeicherten Stands: der Text ohne die Zeile „Stand: …“ und alle
    gespeicherten Felder der Sprintdateien (auch die, die das Protokoll nicht darstellt)."""
    digest = hashlib.sha256("\n".join(_body_of(text)).encode("utf-8"))
    for document in documents:
        digest.update(dump_yaml(document).encode("utf-8"))
    return digest.hexdigest()[:16]


def _state_of(path: Path) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError, UnicodeDecodeError:
        return None
    for line in reversed(lines):
        if line.startswith(STATE_MARKER):
            return line[len(STATE_MARKER) :].removesuffix(" -->").strip()
    return None


# Sperre je Sprint und Termin: Suchen des letzten Protokolls, Prüfen auf Unverändertes und Schreiben
# laufen am Stück, damit zwei Sitzungen mit demselben Stand nicht zwei Protokolle erzeugen.
LOCK_WAIT_SECONDS = 10.0


def _lock_file(folder: Path, sprint_id: str, kind: str) -> Path:
    """Sperrdatei außerhalb des Datenordners (nie im Git-Arbeitsverzeichnis): je Protokollordner,
    Sprint und Termin eine."""
    key = hashlib.sha256(f"{folder.resolve()}|{sprint_id}|{kind}".encode()).hexdigest()[:24]
    root = Path(tempfile.gettempdir()) / "sprintforecast-sperren"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{key}.lock"


def _try_lock(handle: IO[bytes]) -> bool:
    """Versucht, die Datei ohne Warten zu sperren (Sperre des Betriebssystems)."""
    try:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False  # belegt (Windows meldet das als PermissionError/EDEADLOCK)
    return True


def _unlock(handle: IO[bytes]) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def _locked(folder: Path, sprint_id: str, kind: str) -> Iterator[None]:
    """Sperrt Protokolle eines Sprints und Termins für andere Sitzungen auf diesem Rechner. Die
    Sperre ist eine Sperre des Betriebssystems auf einer Datei (``flock``/``msvcrt.locking``): Sie
    endet mit dem Prozess von selbst, braucht keine Erkennung verwaister Sperren und keine Uhr. Wer
    wartet, wartet bis ``LOCK_WAIT_SECONDS``. Zwischen Klonen auf verschiedenen Rechnern wirkt sie
    nicht; dort schützt der aus dem Inhalt abgeleitete Dateiname."""
    path = _lock_file(folder, sprint_id, kind)
    try:
        handle = path.open("a+b")
    except OSError as e:
        raise _not_saved(path, e) from e
    try:
        deadline = time.monotonic() + LOCK_WAIT_SECONDS
        while not _try_lock(handle):
            if time.monotonic() >= deadline:
                raise FileAccessError(
                    t(
                        "Eine andere Sitzung schreibt gerade Protokolle dieses Sprints. "
                        "Bitte gleich noch einmal speichern."
                    )
                )
            time.sleep(0.05)
        try:
            yield
        finally:
            with contextlib.suppress(OSError):
                _unlock(handle)
    finally:
        handle.close()


def write_protocol_new(
    repo: Repository,
    team: str,
    sprint_id: str,
    kind: str,
    text: str,
    now: datetime,
    state: str | None = None,
) -> tuple[Path, bool]:
    """Schreibt das Protokoll (LF-Zeilenenden, über eine Zwischendatei) und meldet, ob es neu
    entstand. Mit ``state`` (siehe :func:`fingerprint`) entsteht kein weiteres Protokoll, wenn der
    Stand unverändert ist; ohne ``state`` entscheidet der Text. Gibt es den Namen schon (zwei
    Speicherungen in derselben Sekunde), wird die Sekunde hochgezählt: nichts geht verloren.
    Suchen und Schreiben laufen unter einer Sperre je Sprint und Termin (:func:`_locked`).
    Schreibfehler kommen als :class:`FileAccessError`."""
    folder = _make_folder(repo, team)
    with _locked(folder, sprint_id, kind):
        return _write_locked(repo, team, sprint_id, kind, text, now, state)


def _make_folder(repo: Repository, team: str) -> Path:
    """Legt den Protokollordner an (Fehler als :class:`FileAccessError`)."""
    folder = _folder(repo, team)
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise _not_saved(folder, e) from e
    return folder


def _write_locked(
    repo: Repository,
    team: str,
    sprint_id: str,
    kind: str,
    text: str,
    now: datetime,
    state: str | None,
) -> tuple[Path, bool]:
    """Rumpf von :func:`write_protocol_new`. Der Aufrufer hält die Sperre (:func:`_locked`); die
    Sperre des Betriebssystems ist nicht wiedereintrittsfähig, hier darf sie nicht erneut betreten
    werden."""
    folder = _folder(repo, team)
    latest = next(
        (
            p
            for _, k, obsolete, p in list_protocols(repo, team, sprint_id)
            if k == kind and not obsolete
        ),
        None,
    )
    if latest is not None:
        same = _state_of(latest) == state if state is not None else _body(latest) == _body_of(text)
        if same:
            return latest, False  # nichts hat sich geändert: kein weiteres, gleiches Protokoll
    if state is not None:
        text = text.rstrip("\n") + f"\n\n{STATE_MARKER}{state} -->\n"
    # Ein Bestandteil des Namens aus dem Inhalt: Zwei Klone, die in derselben Sekunde
    # Verschiedenes speichern, erzeugen so nie denselben Dateinamen (sonst Konflikt beim
    # Zusammenführen).
    tag = (state or hashlib.sha256(text.encode("utf-8")).hexdigest())[:4]
    stamp = now
    while (path := folder / f"{sprint_id}-{kind}-{stamp:{STAMP}}-{tag}.md").exists():
        stamp += timedelta(seconds=1)
    write_text(path, text, newline="\n")  # Zwischendatei, dann ersetzen: nie halb gelesen
    invalidate_status()  # eine neue Datei ist eine offene Änderung, auch ohne geänderte YAML
    return path, True


def write_protocol(
    repo: Repository,
    team: str,
    sprint_id: str,
    kind: str,
    text: str,
    now: datetime,
    state: str | None = None,
) -> Path:
    """Wie :func:`write_protocol_new`, liefert nur die Datei."""
    return write_protocol_new(repo, team, sprint_id, kind, text, now, state)[0]


def _persisted(repo: Repository, team: str, sprint: Sprint) -> dict:
    """Die Sprintdatei so, wie ``save_sprint`` sie schreibt – mit festgelegtem Stand der Fehltage
    (``save_sprint`` legt ihn beim Speichern fest; sonst wichen Fingerabdruck und Datei ab)."""
    copy = dataclasses.replace(sprint)
    if copy.absence_state is None:
        copy.absence_state = repo._pinned_absence_state(repo.sprint_path(team, sprint.id), copy)
    return sprint_to_dict(copy)


def save_with_protocol(
    repo: Repository,
    team: str,
    sprint_id: str,
    kind: str,
    text: str,
    now: datetime,
    sprints: list[Sprint],
    save: Callable[[], list[Path]],
) -> list[Path]:
    """Schreibt erst das Protokoll, dann ``save`` (die Sprintdateien). Ist das Protokoll nicht
    schreibbar, bleibt die Sprintdatei unverändert; scheitert ``save``, wird das eben geschriebene
    Protokoll wieder entfernt – beides gelingt oder keines. Die Sperre (:func:`_locked`) gilt über
    Protokoll, ``save`` und Rückbau: Eine zweite Sitzung mit demselben Stand übernimmt das
    Protokoll erst, wenn die erste gespeichert hat, und nie eines, das die erste gleich wieder
    löscht. ``save`` läuft also unter der Sperre und darf sie nicht selbst betreten (sie ist nicht
    wiedereintrittsfähig)."""
    state = fingerprint(text, *(_persisted(repo, team, s) for s in sprints))
    folder = _make_folder(repo, team)
    with _locked(folder, sprint_id, kind):
        path, created = _write_locked(repo, team, sprint_id, kind, text, now, state)
        try:
            return save()
        except BaseException:
            if created:
                # Scheitert auch der Rückbau (z. B. gesperrte Datei), zählt der ursprüngliche
                # Fehler.
                with contextlib.suppress(OSError):
                    path.unlink(missing_ok=True)
                invalidate_status()
            raise


def list_protocols(
    repo: Repository, team: str, sprint_id: str
) -> list[tuple[datetime, str, bool, Path]]:
    """Die Protokolle eines Sprints als (Zeitpunkt, Termin, obsolet, Datei), neueste zuerst."""
    folder = _folder(repo, team)
    found: list[tuple[datetime, str, bool, Path]] = []
    try:
        entries = list(folder.iterdir()) if folder.is_dir() else []
    except OSError as e:
        raise _not_readable(folder, e) from e
    for p in entries:
        m = _NAME.match(p.name)
        if m and m["sprint"] == sprint_id and p.is_file():
            try:
                at = datetime.strptime(m["at"], STAMP)
            except ValueError:  # von Hand oder per Sync umbenannt: unmöglicher Zeitpunkt
                continue
            found.append((at, m["kind"], m["obsolete"] is not None, p))
    return sorted(found, key=lambda f: (f[0], f[3].name), reverse=True)


def _undo(renamed: list[Path]) -> None:
    """Macht ``mark_obsolete`` rückgängig (so gut es geht)."""
    for target in renamed:
        original = re.sub(r"_obsolet_\d{8}-\d{6}(?=\.md$)", "", target.name)
        with contextlib.suppress(OSError):
            target.replace(target.with_name(original))
    if renamed:
        invalidate_status()


def mark_obsolete(
    repo: Repository, team: str, sprint_id: str, kind: str, now: datetime
) -> list[Path]:
    """Benennt die gültigen Protokolle des Termins in ``…_obsolet_<Datum>-<Zeit>.md`` um (z. B.
    wenn das Einfrieren des Sprints aufgehoben wird). Liefert die neuen Dateien. Scheitert eine
    Umbenennung, werden die schon umbenannten wieder zurückbenannt (alles oder nichts). Die Sperre
    wird auch dann genommen, wenn es den Ordner noch nicht gibt (er wird angelegt; ein leerer Ordner
    ist harmlos): Eine andere Sitzung kann ihn gleichzeitig anlegen und ein Protokoll schreiben."""
    folder = _make_folder(repo, team)
    with _locked(folder, sprint_id, kind):
        return _mark_obsolete(repo, team, sprint_id, kind, now)


def _mark_obsolete(
    repo: Repository, team: str, sprint_id: str, kind: str, now: datetime
) -> list[Path]:
    renamed: list[Path] = []
    for _, found_kind, obsolete, path in list_protocols(repo, team, sprint_id):
        if found_kind != kind or obsolete:
            continue
        stamp = now
        target = path.with_name(f"{path.stem}_obsolet_{stamp:{STAMP}}.md")
        while target.exists():  # zwei Aufhebungen in derselben Sekunde
            stamp += timedelta(seconds=1)
            target = path.with_name(f"{path.stem}_obsolet_{stamp:{STAMP}}.md")
        try:
            path.replace(target)
        except OSError as e:
            _undo(renamed)
            raise FileAccessError(
                t("{path}: nicht umbenannt ({reason})", path=path, reason=str(e))
            ) from e
        renamed.append(target)
    if renamed:
        invalidate_status()
    return renamed


def obsolete_with_save(
    repo: Repository,
    team: str,
    sprint_id: str,
    kind: str,
    now: datetime,
    save: Callable[[], list[Path]],
) -> list[Path]:
    """Benennt die Protokolle zuerst um und schreibt dann mit ``save`` die Sprintdatei; scheitert
    das Speichern, werden die Protokolle zurückbenannt: beides gelingt oder keines. Die Sperre
    (:func:`_locked`) gilt über Umbenennen, ``save`` und Rückbenennen, damit eine andere Sitzung nie
    einen Zwischenstand sieht (``save`` darf sie nicht selbst betreten). Die Sperre gilt auch, wenn
    es den Protokollordner noch nicht gibt (er wird angelegt): Sonst könnte eine andere Sitzung
    gleichzeitig ein Planning samt Protokoll speichern, das danach gültig bliebe."""
    folder = _make_folder(repo, team)
    with _locked(folder, sprint_id, kind):
        renamed = _mark_obsolete(repo, team, sprint_id, kind, now)
        try:
            return save()
        except BaseException:
            _undo(renamed)
            raise
