# SPDX-License-Identifier: EUPL-1.2
"""The "Data folder" page: special cases of path input and errors when creating and cloning
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
    """The errors in the main area (the sidebar reports missing Git on its own)."""
    return "\n".join(e.value for e in at.main.error)


def enter_address(at: AppTest, value: str) -> None:
    """Only with the address is "Clone" enabled: a run in between."""
    next(e for e in at.text_input if e.label == "Adresse").set_value(value).run()


def technical(at: AppTest) -> str:
    """Content of the collapsible "Technical message"."""
    return "\n".join(c.value for c in at.code)


# --- User shortcut (~) ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "button"),
    [("data-path", "data-choose"), ("data-new", "data-create"), ("data-clone", "data-clone-go")],
)
def test_unknown_user_folder_is_explained_and_the_button_stays_locked(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, key: str, button: str
):
    """If the home folder cannot be determined, ``Path.expanduser`` raises a ``RuntimeError``
    (on Linux for ``~name`` of an unknown user, on Windows only rarely; hence
    simulated). ``Path.home()`` stays untouched."""
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


# --- Create a new data repository -------------------------------------------------------------


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
    assert f"`{file}` ist eine Datei, kein Ordner" in errors(at)
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
    assert f"Keine Zugriffsrechte für `{target}`" in errors(at)
    assert not target.exists()


def test_create_in_a_folder_that_cannot_be_listed_names_the_problem(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """The folder exists but is not readable: no traceback in the "not empty" check."""
    target = tmp_path / "gesperrt"
    target.mkdir()
    denied = PermissionError(errno.EACCES, "Permission denied")
    fail_on(monkeypatch, "iterdir", target, denied)
    fail_on(monkeypatch, "mkdir", target, denied)
    at = datenordner(data_dir, monkeypatch)
    at.text_input(key="data-new").set_value(str(target))
    at.button(key="data-create").click().run()
    assert not at.exception, at.exception
    assert f"Keine Zugriffsrechte für `{target}`" in errors(at)


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


# --- Clone a repository -----------------------------------------------------------------------


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
    assert errors(at).count("fehlt oder wurde abgelehnt") == 1  # heading only once
    assert "terminal prompts disabled" in technical(at)  # message from Git: collapsible
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
    assert f"`{file}` ist eine Datei, kein Ordner" in errors(at)


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


# --- Folder without access, empty fields, notices when cloning ---------------------------------


def test_choose_a_folder_without_access_names_the_problem(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """The folder exists but git does not start in it (no access): a message instead of the error
    page."""
    from sprintforecast.web import ui

    real = ui.git_root

    def refuse(path):
        if Path(path) == tmp_path:  # only the chosen folder; the sidebar asks too
            raise PermissionError(errno.EACCES, "Permission denied")
        return real(path)

    at = datenordner(data_dir, monkeypatch)
    monkeypatch.setattr(ui, "git_root", refuse)
    at.text_input(key="data-path").set_value(str(tmp_path))
    at.button(key="data-choose").click().run()
    assert not at.exception, at.exception
    assert "Ordner nicht nutzbar" in errors(at)
    assert f"Keine Zugriffsrechte für `{tmp_path}`" in errors(at)


def test_choose_a_folder_that_cannot_be_listed_names_the_problem(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from sprintforecast.web import ui

    real = ui.teams_dir

    def refuse(path):
        if Path(path) == tmp_path:
            raise PermissionError(errno.EACCES, "Permission denied")
        return real(path)

    at = datenordner(data_dir, monkeypatch)
    monkeypatch.setattr(ui, "git_root", lambda path: path)
    monkeypatch.setattr(ui, "teams_dir", refuse)
    at.text_input(key="data-path").set_value(str(tmp_path))
    at.button(key="data-choose").click().run()
    assert not at.exception, at.exception
    assert f"Keine Zugriffsrechte für `{tmp_path}`" in errors(at)


@pytest.mark.parametrize(
    ("key", "button"),
    [("data-path", "data-choose"), ("data-new", "data-create"), ("data-clone", "data-clone-go")],
)
def test_an_empty_path_field_does_not_mean_the_working_folder(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, key: str, button: str
):
    at = datenordner(data_dir, monkeypatch)
    enter_address(at, "https://example.org/team/daten.git")
    at.text_input(key=key).set_value("   ").run()
    assert not at.exception, at.exception
    assert at.button(key=button).disabled


@pytest.mark.parametrize(
    ("kind", "expected", "unwanted"),
    [
        ("offline", "noch einmal „Klonen“ wählen", "Speichern und teilen"),
        ("not_found", "oder beim Betreiber des Servers nachfragen", "Server (Remote)"),
    ],
)
def test_clone_errors_give_hints_that_fit_cloning(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind, expected, unwanted
):
    from sprintforecast.git import GitError, hint_for
    from sprintforecast.web import ui

    def failing(url, path):
        raise GitError("fatal: unable to access", kind, hint_for(kind))

    at = datenordner(data_dir, monkeypatch)
    monkeypatch.setattr(ui, "clone_repository", failing)
    enter_address(at, "https://example.org/team/daten.git")
    at.text_input(key="data-clone").set_value(str(tmp_path / "klon")).run()
    at.button(key="data-clone-go").click().run()
    assert not at.exception, at.exception
    assert expected in errors(at)
    assert unwanted not in errors(at)


def test_clone_into_a_non_empty_folder_says_folder_not_git(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    target = tmp_path / "ziel"
    target.mkdir()
    (target / "datei.txt").write_text("x", encoding="utf-8")
    at = datenordner(data_dir, monkeypatch)
    enter_address(at, "https://example.org/team/daten.git")
    at.text_input(key="data-clone").set_value(str(target)).run()
    at.button(key="data-clone-go").click().run()
    assert "Ordner nicht nutzbar" in errors(at)
    assert f"`{target}` ist nicht leer" in errors(at)


def test_create_here_after_choosing_a_folder_without_git_shows_the_problem_with_its_title(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from sprintforecast.git import GitError
    from sprintforecast.web import ui

    def failing(path, teams_folder=True):
        raise GitError("kaputt", "folder")

    at = datenordner(data_dir, monkeypatch)
    monkeypatch.setattr(ui, "init_data_repository", failing)
    at.session_state["offer-init"] = str(tmp_path)
    at.run()
    at.button(key="data-init-here").click().run()
    assert not at.exception, at.exception
    assert "Ordner nicht nutzbar" in errors(at)


def test_create_in_a_folder_that_is_writable_but_cannot_be_listed_creates_nothing(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """Whether the folder is empty cannot be determined: the "not empty" check must not be
    silently skipped and put a repository into a full folder."""
    target = tmp_path / "voll"
    target.mkdir()
    (target / "datei.txt").write_text("x", encoding="utf-8")
    fail_on(monkeypatch, "iterdir", target, PermissionError(errno.EACCES, "Permission denied"))
    at = datenordner(data_dir, monkeypatch)
    at.text_input(key="data-new").set_value(str(target))
    at.button(key="data-create").click().run()
    assert not at.exception, at.exception
    assert f"Keine Zugriffsrechte für `{target}`" in errors(at)
    assert not (target / ".git").exists()
