# SPDX-License-Identifier: EUPL-1.2
"""Seite „Datenordner“: Sonderfälle der Pfadeingabe und Fehler beim Anlegen und Klonen
(AppTest)."""

import errno
from pathlib import Path

import pytest
from gitrepos import Denying, serve
from test_datenordner import fail_on

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest
from test_web_k3_ui import goto, start


def datenordner(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    return goto(start(data_dir, monkeypatch), "datenordner")


def errors(at: AppTest) -> str:
    """Die Fehler im Hauptbereich (die Seitenleiste meldet fehlendes Git von sich aus)."""
    return "\n".join(e.value for e in at.main.error)


def enter_address(at: AppTest, value: str) -> None:
    """Erst mit der Adresse wird „Klonen“ freigegeben: ein Durchlauf dazwischen."""
    next(e for e in at.text_input if e.label == "Adresse").set_value(value).run()


def technical(at: AppTest) -> str:
    """Inhalt der aufklappbaren „Technischen Meldung“."""
    return "\n".join(c.value for c in at.code)


# --- Benutzerkürzel (~) -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "button"),
    [("data-path", "data-choose"), ("data-new", "data-create"), ("data-clone", "data-clone-go")],
)
def test_unknown_user_folder_is_explained_and_the_button_stays_locked(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, key: str, button: str
):
    """Ist der Benutzerordner nicht zu ermitteln, wirft ``Path.expanduser`` einen
    ``RuntimeError`` (unter Linux für ``~name`` eines unbekannten Benutzers, unter Windows nur
    selten; deshalb nachgestellt). ``Path.home()`` bleibt unberührt."""
    real = Path.expanduser

    def expanduser(self):
        if str(self).startswith("~gibtesnicht"):
            raise RuntimeError("Could not determine home directory.")
        return real(self)

    monkeypatch.setattr(Path, "expanduser", expanduser)
    at = datenordner(data_dir, monkeypatch)
    enter_address(at, "https://example.org/team/daten.git")
    at.text_input(key=key).set_value("~gibtesnicht/daten").run()
    assert not at.exception, at.exception
    assert errors(at).count("Benutzerordner unbekannt") == 1
    assert "`~gibtesnicht/daten`" in errors(at)
    assert at.button(key=button).disabled


def test_a_user_shortcut_that_works_is_still_expanded(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    def expanduser(self):
        return tmp_path.joinpath(*self.parts[1:]) if self.parts[:1] == ("~",) else self

    monkeypatch.setattr(Path, "expanduser", expanduser)
    at = datenordner(data_dir, monkeypatch)
    at.text_input(key="data-path").set_value("~/fehlt")
    at.button(key="data-choose").click().run()
    assert not at.exception, at.exception
    assert "Benutzerordner unbekannt" not in errors(at)
    assert f"Ordner nicht gefunden: {tmp_path / 'fehlt'}" in errors(at)


# --- Neues Daten-Repository anlegen -----------------------------------------------------------


def test_create_on_a_file_names_the_problem(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    file = tmp_path / "datei.txt"
    file.write_text("x", encoding="utf-8")
    at = datenordner(data_dir, monkeypatch)
    at.text_input(key="data-new").set_value(str(file))
    at.button(key="data-create").click().run()
    assert not at.exception, at.exception
    assert "Ordner nicht nutzbar" in errors(at)
    assert f"{file} ist eine Datei, kein Ordner" in errors(at)
    assert file.read_text(encoding="utf-8") == "x"


def test_create_without_rights_names_the_problem(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    target = tmp_path / "gesperrt"
    fail_on(monkeypatch, "mkdir", target, PermissionError(errno.EACCES, "Permission denied"))
    at = datenordner(data_dir, monkeypatch)
    at.text_input(key="data-new").set_value(str(target))
    at.button(key="data-create").click().run()
    assert not at.exception, at.exception
    assert "Ordner nicht nutzbar" in errors(at)
    assert f"Keine Zugriffsrechte für {target}" in errors(at)
    assert not target.exists()


def test_create_in_a_folder_that_cannot_be_listed_names_the_problem(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """Der Ordner ist da, aber nicht lesbar: kein Traceback bei der Prüfung „nicht leer“."""
    target = tmp_path / "gesperrt"
    target.mkdir()
    denied = PermissionError(errno.EACCES, "Permission denied")
    fail_on(monkeypatch, "iterdir", target, denied)
    fail_on(monkeypatch, "mkdir", target, denied)
    at = datenordner(data_dir, monkeypatch)
    at.text_input(key="data-new").set_value(str(target))
    at.button(key="data-create").click().run()
    assert not at.exception, at.exception
    assert f"Keine Zugriffsrechte für {target}" in errors(at)


def test_create_without_git_shows_how_to_install_it(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    at = datenordner(data_dir, monkeypatch)
    at.text_input(key="data-new").set_value(str(tmp_path / "neu"))
    monkeypatch.setenv("PATH", "")
    at.button(key="data-create").click().run()
    assert not at.exception, at.exception
    assert "Git ist nicht installiert" in errors(at)
    assert "Git installieren (Windows:" in errors(at)


# --- Repository klonen ------------------------------------------------------------------------


@pytest.mark.usefixtures("no_login_prompt")
def test_clone_with_missing_login_explains_the_steps(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    with serve(Denying) as port:
        at = datenordner(data_dir, monkeypatch)
        enter_address(at, f"http://127.0.0.1:{port}/r.git")
        at.text_input(key="data-clone").set_value(str(tmp_path / "ziel"))
        at.button(key="data-clone-go").click().run()
    assert not at.exception, at.exception
    assert "Anmeldung fehlt oder wurde abgelehnt" in errors(at)
    assert "Zugangstoken" in errors(at) and "gh auth setup-git" in errors(at)
    assert errors(at).count("fehlt oder wurde abgelehnt") == 1  # Überschrift nur einmal
    assert "terminal prompts disabled" in technical(at)  # Meldung von Git: aufklappbar
    assert "terminal prompts disabled" not in errors(at)


def test_clone_without_git_shows_how_to_install_it(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    at = datenordner(data_dir, monkeypatch)
    enter_address(at, "https://example.org/team/daten.git")
    at.text_input(key="data-clone").set_value(str(tmp_path / "ziel"))
    monkeypatch.setenv("PATH", "")
    at.button(key="data-clone-go").click().run()
    assert not at.exception, at.exception
    assert "Git ist nicht installiert" in errors(at)
    assert "Git installieren (Windows:" in errors(at)


def test_clone_onto_a_file_names_the_problem(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    file = tmp_path / "datei.txt"
    file.write_text("x", encoding="utf-8")
    at = datenordner(data_dir, monkeypatch)
    enter_address(at, "https://example.org/team/daten.git")
    at.text_input(key="data-clone").set_value(str(file))
    at.button(key="data-clone-go").click().run()
    assert not at.exception, at.exception
    assert "Ordner nicht nutzbar" in errors(at)
    assert f"{file} ist eine Datei, kein Ordner" in errors(at)


def test_clone_keeps_the_title_of_a_bad_address(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    at = datenordner(data_dir, monkeypatch)
    enter_address(at, "github.com/team/daten")
    at.text_input(key="data-clone").set_value(str(tmp_path / "ziel"))
    at.button(key="data-clone-go").click().run()
    assert not at.exception, at.exception
    assert errors(at).count("Ungültige Adresse") == 1
    assert "Das Format wird nicht erkannt" in errors(at)
