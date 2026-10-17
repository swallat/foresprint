# SPDX-License-Identifier: EUPL-1.2
"""Datenordner anlegen, klonen und merken: Dateien, fehlende Rechte und kaputte Einstellungen
kommen als Klartext statt als rohe Ausnahme (ohne Oberfläche; die Seite: test_web_datenordner)."""

import errno
from pathlib import Path

import pytest

from sprintforecast import config, storage
from sprintforecast import git as gitmod
from sprintforecast.git import GitError

ADDRESS = "https://example.org/team/daten.git"


def fail_on(monkeypatch: pytest.MonkeyPatch, method: str, target: Path, error: OSError) -> None:
    """``Path.<method>`` scheitert für ``target`` mit ``error``. Kein echtes Rechte-Tricksen:
    Das lässt sich unter Windows genauso nachstellen."""
    real = getattr(Path, method)

    def failing(self, *args, **kwargs):
        if self == target:
            raise error
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, method, failing)


@pytest.fixture
def a_file(tmp_path: Path) -> Path:
    file = tmp_path / "datei.txt"
    file.write_text("x", encoding="utf-8")
    return file


def test_folder_problems_have_their_own_title():
    assert gitmod.title_for("folder") != gitmod.title_for("unbekannt")


# --- Pfad zeigt auf eine Datei ----------------------------------------------------------------


def test_init_refuses_a_file(a_file: Path):
    with pytest.raises(GitError) as info:
        gitmod.init_data_repository(a_file)
    assert info.value.kind == "folder"
    assert f"{a_file} ist eine Datei" in str(info.value)
    assert a_file.read_text(encoding="utf-8") == "x"


def test_clone_refuses_a_file(a_file: Path):
    with pytest.raises(GitError) as info:
        gitmod.clone_repository(ADDRESS, a_file)
    assert info.value.kind == "folder"
    assert f"{a_file} ist eine Datei" in str(info.value)
    assert a_file.read_text(encoding="utf-8") == "x"


@pytest.mark.parametrize(
    "action",
    [
        lambda path: gitmod.init_data_repository(path),
        lambda path: gitmod.clone_repository(ADDRESS, path),
    ],
    ids=["anlegen", "klonen"],
)
def test_a_file_in_the_way_of_the_path_is_a_problem_not_an_exception(a_file: Path, action):
    with pytest.raises(GitError) as info:
        action(a_file / "unter")
    assert info.value.kind == "folder"
    assert isinstance(info.value.__cause__, OSError)


# --- Keine Rechte, Pfad unbrauchbar -----------------------------------------------------------


def test_init_names_missing_rights(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "neu"
    fail_on(monkeypatch, "mkdir", target, PermissionError(errno.EACCES, "Permission denied"))
    with pytest.raises(GitError) as info:
        gitmod.init_data_repository(target)
    assert info.value.kind == "folder"
    assert f"Keine Zugriffsrechte für {target}" in str(info.value)
    assert isinstance(info.value.__cause__, PermissionError)


def test_init_names_the_reason_of_other_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "neu"
    fail_on(monkeypatch, "mkdir", target, OSError(errno.ENOSPC, "No space left on device"))
    with pytest.raises(GitError) as info:
        gitmod.init_data_repository(target)
    assert info.value.kind == "folder"
    assert f"{target} lässt sich nicht anlegen (No space left on device)" in str(info.value)


def test_init_names_missing_rights_for_files_in_the_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    target = tmp_path / "neu"
    fail_on(
        monkeypatch, "write_text", target / ".gitignore", PermissionError(errno.EACCES, "denied")
    )
    with pytest.raises(GitError) as info:
        gitmod.init_data_repository(target)
    assert info.value.kind == "folder" and "Keine Zugriffsrechte" in str(info.value)


def test_clone_names_missing_rights_for_the_parent_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    target = tmp_path / "gesperrt" / "klon"
    fail_on(monkeypatch, "mkdir", target.parent, PermissionError(errno.EACCES, "Permission denied"))
    with pytest.raises(GitError) as info:
        gitmod.clone_repository(ADDRESS, target)
    assert info.value.kind == "folder"
    assert f"Keine Zugriffsrechte für {target}" in str(info.value)


def test_clone_names_a_target_that_cannot_be_listed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    target = tmp_path / "ziel"
    target.mkdir()
    fail_on(monkeypatch, "iterdir", target, PermissionError(errno.EACCES, "Permission denied"))
    with pytest.raises(GitError) as info:
        gitmod.clone_repository(ADDRESS, target)
    assert info.value.kind == "folder" and "Keine Zugriffsrechte" in str(info.value)


def test_clone_into_a_non_empty_folder_keeps_its_message(tmp_path: Path):
    target = tmp_path / "ziel"
    target.mkdir()
    (target / "da.txt").write_text("x", encoding="utf-8")
    with pytest.raises(GitError) as info:
        gitmod.clone_repository(ADDRESS, target)
    assert str(info.value) == f"{target} ist nicht leer"


# --- Gemerkter Datenordner in den Einstellungen -----------------------------------------------


@pytest.mark.parametrize("value", [5, 1.5, True, ["/irgendwo"], {"a": 1}, None, ""])
def test_saved_data_dir_ignores_values_that_are_not_a_path_text(value):
    config.update(data_dir=value)
    assert storage.saved_data_dir() is None


def test_saved_data_dir_still_returns_a_saved_folder(tmp_path: Path):
    config.update(data_dir=str(tmp_path))
    assert storage.saved_data_dir() == tmp_path


def test_default_data_dir_survives_a_damaged_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv(storage.DATA_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    config.update(data_dir=["/irgendwo"])
    assert storage.default_data_dir() == Path(".")
