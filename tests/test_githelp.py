# SPDX-License-Identifier: EUPL-1.2
"""Die Hilfeseite „Zusammenarbeit (Git)“ erklärt die Fehlerfälle, die die App unterscheidet."""

import pytest

from sprintforecast.git import classify, title_for
from sprintforecast.guide import GIT_HELP
from sprintforecast.i18n import t


def entry(title: str) -> str:
    """Text des Hilfeeintrags mit dieser Überschrift (genau einer)."""
    texts = [t(text) for head, text in GIT_HELP if t(head) == title]
    assert len(texts) == 1, title
    return " ".join(texts[0].split())


def test_help_titles_are_unique():
    titles = [t(title) for title, _ in GIT_HELP]
    assert len(titles) == len(set(titles))


@pytest.mark.parametrize("kind", ["not_writable", "unsafe_directory", "not_found", "certificate"])
def test_help_entry_carries_the_title_the_app_shows(kind: str):
    """Wer die Überschrift einer Fehlermeldung in der Hilfe sucht, findet sie dort wieder."""
    assert entry(title_for(kind))


def test_help_explains_the_missing_repository():
    text = entry(title_for("not_found"))
    assert "statt „Server nicht erreichbar“" in text and "VPN" in text
    assert "umbenanntes" in text and "Server (Remote)" in text
    # Ein getrenntes Laufwerk bleibt „Server nicht erreichbar“ (der Satz am Ende).
    assert "Netzlaufwerk" in text and text.endswith("dagegen „Server nicht erreichbar“.")


def test_help_explains_the_untrusted_certificate():
    text = entry(title_for("certificate"))
    assert "Sicherheitszertifikat" in text and "Firmenzertifikat" in text and "IT" in text
    assert "keine Git-Einstellungen" in text and "nicht anerkannt wird, nicht" in text


def test_help_explains_the_unsafe_folder():
    text = entry(title_for("unsafe_directory"))
    assert "dubious ownership" in text and "anderen Benutzerkonto" in text
    assert "ändert keine Git-Einstellungen" in text and "Betreuung des Rechners" in text
    assert "Ohne Git verwenden" in text and "keinem Git-Repository" in text
    assert "safe.directory" not in text  # die App rät nie zu einer Einstellung


def test_help_explains_the_unwritable_folder():
    text = entry(title_for("not_writable"))
    assert "Schreibrechte" in text and "schreibgeschützt" in text and ".git" in text
    assert "Betreuung des Rechners" in text


def test_help_explains_the_orphaned_lock_file():
    text = entry("Gesperrte Datei")
    assert "index.lock" in text and "Absturz" in text and "Betreuung" in text
    assert "nicht selbst" in text  # die App entfernt die Sperrdatei nie
    # Der Fall „Datendatei beim Zusammenführen nicht schreibbar“ ist dort ebenfalls erklärt.
    assert "Zusammenführen" in text and "Schreibschutz" in text


def test_help_explains_the_ssh_fingerprint():
    text = entry("SSH-Server noch nicht bekannt (Fingerabdruck)")
    assert "Fingerabdruck" in text and "https-Adresse" in text
    assert "Abgleich" in text and "Hochladen" in text and "Klonen" in text


def test_help_explains_back_to_the_branch_with_open_changes():
    text = entry("Unvollständiges Zusammenführen, detached HEAD")
    assert "auf einem Rettungsbranch gesichert, dessen Namen die Meldung nennt" in text
    assert "der Rettungsbranch bleibt bestehen" in text and "ebenfalls dort gesichert" in text
    assert "außerhalb" in text and "Technische Meldung" in text
    assert "verwerfen (sie gehen" not in text
    assert "zuerst committen" not in text  # auf einem Stand ohne Branch geht das nicht


def test_the_help_page_matches_the_hints_of_the_app():
    """Der Fingerabdruck-Hinweis der App und die Hilfeseite sagen dasselbe: nicht per App
    bestätigen, sondern mit einem SSH- oder Git-Programm oder über https."""
    hint = classify(
        "Host key verification failed.\nfatal: Could not read from remote repository.",
        url="git@example.org:team/daten.git",
    ).hint
    assert "Fingerabdruck" in hint and "https-Adresse" in hint
    assert "SSH- oder Git-Programm" in entry("SSH-Server noch nicht bekannt (Fingerabdruck)")
