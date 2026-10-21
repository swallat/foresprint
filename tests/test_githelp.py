# SPDX-License-Identifier: EUPL-1.2
"""The help page "Collaboration (Git)" explains the error cases the app distinguishes."""

import pytest

from foresprint.git import classify, title_for
from foresprint.guide import GIT_HELP
from foresprint.i18n import t


def entry(title: str) -> str:
    """Text of the help entry with this heading (exactly one)."""
    texts = [t(text) for head, text in GIT_HELP if t(head) == title]
    assert len(texts) == 1, title
    return " ".join(texts[0].split())


def test_help_titles_are_unique():
    titles = [t(title) for title, _ in GIT_HELP]
    assert len(titles) == len(set(titles))


@pytest.mark.parametrize("kind", ["not_writable", "unsafe_directory", "not_found", "certificate"])
def test_help_entry_carries_the_title_the_app_shows(kind: str):
    """Whoever looks up the heading of an error message in the help finds it there."""
    assert entry(title_for(kind))


def test_help_explains_the_missing_repository():
    text = entry(title_for("not_found"))
    assert "statt „Server nicht erreichbar“" in text and "VPN" in text
    assert "umbenanntes" in text and "Server (Remote)" in text
    # A disconnected drive remains "Server not reachable" (the sentence at the end).
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
    assert "safe.directory" not in text  # the app never recommends a setting


def test_help_explains_the_unwritable_folder():
    text = entry(title_for("not_writable"))
    assert "Schreibrechte" in text and "schreibgeschützt" in text and ".git" in text
    assert "Betreuung des Rechners" in text


def test_help_explains_the_orphaned_lock_file():
    text = entry("Gesperrte Datei")
    assert "index.lock" in text and "Absturz" in text and "Betreuung" in text
    assert "nicht selbst" in text  # the app never removes the lock file
    # The case "Data file not writable while merging" is also explained there.
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
    assert "zuerst committen" not in text  # that does not work on a state without a branch


def test_the_help_page_matches_the_hints_of_the_app():
    """The app's fingerprint notice and the help page say the same: do not confirm via the app,
    but with an SSH or Git program or via https."""
    hint = classify(
        "Host key verification failed.\nfatal: Could not read from remote repository.",
        url="git@example.org:team/daten.git",
    ).hint
    assert "Fingerabdruck" in hint and "https-Adresse" in hint
    assert "SSH- oder Git-Programm" in entry("SSH-Server noch nicht bekannt (Fingerabdruck)")
