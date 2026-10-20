# SPDX-License-Identifier: EUPL-1.2
"""UI for the backend fixes (K3): foreign history, notices, tags, renames, settings errors,
"Use without Git" and test gaps (AppTest)."""

import subprocess
from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest
from test_web_k3_ui import (
    APP,
    diverge,
    git,
    goto,
    main_button,
    open_merge,
    sidebar_button,
    start,
    tag_box,
)

from sprintforecast import config
from sprintforecast.config import SettingsError
from sprintforecast.git import invalidate_status
from sprintforecast.storage import DATA_ENV, STICHTAG_ENV, Repository

BROKEN = SettingsError("Die Einstellungen konnten nicht gespeichert werden (x): Zugriff verweigert")


def sidebar_text(at: AppTest) -> str:
    groups = (
        at.sidebar.markdown,
        at.sidebar.error,
        at.sidebar.warning,
        at.sidebar.info,
        at.sidebar.success,
        at.sidebar.caption,
    )
    return "\n".join(e.value for group in groups for e in group)


def any_error(at: AppTest, text: str) -> bool:
    return any(text in e.value for e in [*at.error, *at.sidebar.error])


def foreign_history(server: Path) -> None:
    """The server receives a history without a common origin (wrong repository)."""
    other = server.parent / "fremd"
    other.mkdir()
    git(other, "init", "-q", "-b", "main")
    (other / "code.py").write_text("print()\n")
    git(other, "add", "-A")
    git(other, "commit", "-qm", "Fremder Code")
    git(other, "push", "-qf", str(server), "main")


# --- U1: foreign history ----------------------------------------------------------------


def test_unrelated_histories_ask_for_explicit_confirmation(shared, data_dir, monkeypatch):
    _, _, server = shared
    foreign_history(server)
    at = start(data_dir, monkeypatch)
    sidebar_button(at, "Speichern und teilen").click().run()
    assert not at.exception, at.exception
    text = sidebar_text(at)
    assert "Server hat eine andere Historie" in text
    assert "falsches Repository" in text
    assert str(server) in text and "main" in text
    # The right way out of a wrong address is the form under "Data folder".
    assert "Server (Remote)" in text
    assert [p.proto.label for p in at.sidebar.get("page_link")] == ["Server-Adresse ändern"]
    assert at.sidebar.button(key="unrelated-go").disabled  # nothing works without confirmation
    # Ticking the box triggers a new run; the dialog stays.
    at.sidebar.checkbox(key="unrelated-confirm").check().run()
    assert not at.sidebar.button(key="unrelated-go").disabled
    at.sidebar.checkbox(key="unrelated-confirm").uncheck().run()
    assert at.sidebar.button(key="unrelated-go").disabled
    assert "Fremder Code" in git(server, "log", "--format=%s", "main")  # unchanged
    assert "Start" not in git(server, "log", "--format=%s", "main")


def test_unrelated_histories_cancel_changes_nothing(shared, data_dir, monkeypatch):
    _, _, server = shared
    foreign_history(server)
    before = git(server, "rev-parse", "main")
    at = start(data_dir, monkeypatch)
    sidebar_button(at, "Speichern und teilen").click().run()
    at.sidebar.button(key="unrelated-cancel").click().run()
    assert not at.exception, at.exception
    assert "Server hat eine andere Historie" not in sidebar_text(at)
    assert not [b for b in at.sidebar.button if b.key == "unrelated-go"]
    assert git(server, "rev-parse", "main") == before


def test_unrelated_histories_confirmed_merges_both(shared, data_dir, monkeypatch):
    _, _, server = shared
    foreign_history(server)
    at = start(data_dir, monkeypatch)
    sidebar_button(at, "Speichern und teilen").click().run()
    at.sidebar.checkbox(key="unrelated-confirm").check().run()
    at.sidebar.button(key="unrelated-go").click().run()
    assert not at.exception, at.exception
    log = git(server, "log", "--format=%s", "main")
    assert "Fremder Code" in log and "Start" in log
    assert "Server hat eine andere Historie" not in sidebar_text(at)
    assert not at.sidebar.error


def test_existing_tag_blocks_commit_with_explanation(
    repo: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    git(repo, "tag", "demo/2026.20")
    invalidate_status()
    (repo / "teams" / "demo" / "sprints" / "2026.20.yaml").write_text("velocity: 1\n", "utf-8")
    at = start(data_dir, monkeypatch)
    at.session_state["pending_tags"] = ["demo/2026.20"]
    at.run()
    sidebar_button(at, "Änderungen committen").click().run()
    assert not at.exception, at.exception
    errors = " ".join(e.value for e in at.sidebar.error)
    assert "Tag-Name ist schon vergeben" in errors
    assert "anderen Namen" in errors


# --- U2: notices despite success --------------------------------------------------------


def test_sync_notes_are_shown(shared, data_dir, monkeypatch):
    root, _, _ = shared
    git(root, "tag", "-a", "demo/alt", "-m", "alt")
    (root / "hinweis.txt").write_text("x\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "Weiter")
    invalidate_status()
    at = start(data_dir, monkeypatch)
    at.session_state["pending_tags"] = ["demo/alt"]  # points to a different commit than HEAD
    at.run()
    sidebar_button(at, "Speichern und teilen").click().run()
    assert not at.exception, at.exception
    notes = " ".join(e.value for e in [*at.sidebar.warning, *at.sidebar.info])
    assert "zeigt auf einen anderen Commit" in notes and "demo/alt" in notes


# --- U3: tags with partial failures ----------------------------------------------------


def tag_setup(shared) -> Path:
    """Local: nurlokal, both (uploaded), anders; only on the server: nurserver."""
    root, bob, server = shared
    git(root, "tag", "-a", "nurlokal", "-m", "x")
    git(root, "tag", "-a", "beide", "-m", "x")
    git(root, "push", "-q", "origin", "beide")
    git(root, "tag", "-a", "anders", "-m", "x")
    (bob / "bob.txt").write_text("b\n")
    git(bob, "add", "-A")
    git(bob, "commit", "-qm", "Bob")
    git(bob, "tag", "-a", "anders", "-m", "x")
    git(bob, "tag", "-a", "nurserver", "-m", "x")
    git(bob, "push", "-q", "origin", "anders", "nurserver")
    invalidate_status()
    return server


def tag_rows(at: AppTest) -> dict[str, str]:
    frame = at.table[0].value
    return {name.strip("`"): row["Server"] for name, row in frame.iterrows()}  # names as code


def test_tag_list_shows_status_after_server_check(shared, data_dir, monkeypatch):
    tag_setup(shared)
    at = goto(start(data_dir, monkeypatch), "verlauf")
    assert set(tag_rows(at)) == {"nurlokal", "beide", "anders"}
    assert not any(tag_rows(at).values())  # no claim without a sync
    main_button(at, "Mit dem Server abgleichen").click().run()
    assert not at.exception, at.exception
    rows = tag_rows(at)
    assert rows["nurlokal"] == "nur lokal"
    assert rows["nurserver"] == "nur auf dem Server"
    assert rows["anders"] == "unterschiedlich"
    assert rows["beide"] == "auf dem Server"


def test_failed_server_check_without_local_tags_is_not_reported_as_no_tags(
    shared, data_dir, monkeypatch
):
    """Without local tags and with an unreachable server, "No tags yet" must not stand alone."""
    root, _, _ = shared
    git(root, "remote", "set-url", "origin", str(root / "gibt-es-nicht"))
    invalidate_status()
    at = goto(start(data_dir, monkeypatch), "verlauf")
    main_button(at, "Mit dem Server abgleichen").click().run()
    assert not at.exception, at.exception
    assert any("Der Server konnte nicht abgefragt werden" in w.value for w in at.main.warning)


def test_local_only_tag_can_be_uploaded(shared, data_dir, monkeypatch):
    _, _, server = shared
    tag_setup(shared)
    at = goto(start(data_dir, monkeypatch), "verlauf")
    assert not [s for s in at.main.selectbox if s.label == "Tag zum Server übertragen"]
    main_button(at, "Mit dem Server abgleichen").click().run()
    box = next(s for s in at.main.selectbox if s.label == "Tag zum Server übertragen")
    assert box.options == ["nurlokal"]
    main_button(at, "Zum Server übertragen").click().run()
    assert not at.exception, at.exception
    assert "nurlokal" in git(server, "tag").split()
    assert any("nurlokal" in s.value for s in at.success)
    assert tag_rows(at)["nurlokal"] == "auf dem Server"  # re-synced after the action


def test_upload_failure_is_explained(shared, data_dir, monkeypatch):
    _, _, server = shared
    tag_setup(shared)
    at = goto(start(data_dir, monkeypatch), "verlauf")
    main_button(at, "Mit dem Server abgleichen").click().run()
    server.rename(server.with_name("weg.git"))
    main_button(at, "Zum Server übertragen").click().run()
    assert not at.exception, at.exception
    assert at.error  # understandable error instead of a traceback


def test_server_only_tag_can_be_deleted_with_per_tag_confirmation(shared, data_dir, monkeypatch):
    _, _, server = shared
    tag_setup(shared)
    at = goto(start(data_dir, monkeypatch), "verlauf")
    main_button(at, "Mit dem Server abgleichen").click().run()
    assert "nurserver" in tag_box(at).options
    tag_box(at).set_value("nurserver").run()
    assert main_button(at, "Tag löschen").disabled
    at.checkbox(key="tag-confirm-nurserver").check().run()
    main_button(at, "Tag löschen").click().run()
    assert not at.exception, at.exception
    assert "nurserver" not in git(server, "tag").split()
    assert "nurserver" not in tag_rows(at)


# --- U4: renames and status values when discarding -------------------------------------


def test_discard_preview_names_renames(repo: Path, data_dir: Path, monkeypatch):
    git(repo, "mv", "teams/demo/people.yaml", "teams/demo/leute.yaml")
    invalidate_status()
    at = goto(start(data_dir, monkeypatch), "verlauf")
    text = "umbenannt: `teams/demo/people.yaml` → `teams/demo/leute.yaml`"
    assert text in " ".join(c.label for c in at.checkbox)
    assert "geändert" not in " ".join(c.label for c in at.checkbox)
    main_button(at, "Alles verwerfen …").click().run()
    assert any(text in w.value for w in at.warning)


def test_lost_status_shows_both_paths_of_a_rename_as_code():
    from sprintforecast.githistory import Lost
    from sprintforecast.web import ui

    renamed = Lost("R", "teams/demo/leute.yaml", orig="teams/demo/people.yaml")
    assert (
        ui._lost_status(renamed) == "umbenannt: `teams/demo/people.yaml` → `teams/demo/leute.yaml`"
    )
    # A path with a backtick does not end the code span (Markdown characters are not interpreted).
    odd = Lost("R", "neu*`x`.yaml", orig="alt _name_.yaml")
    assert ui._lost_status(odd) == "umbenannt: `alt _name_.yaml` → ``neu*`x`.yaml``"
    assert ui._lost_status(Lost("M", "a.yaml")) == "geändert"  # unchanged without a rename


@pytest.mark.parametrize(
    ("status", "name"),
    [
        ("M", "geändert"), ("MM", "geändert"), ("T", "geändert"), ("D", "gelöscht"),
        ("MD", "gelöscht"), ("A", "neu"), ("??", "neu"), ("AM", "neu"),
        ("AD", "neu, danach gelöscht"), ("R", "umbenannt"), ("RM", "umbenannt und geändert"),
        ("RD", "umbenannt, danach gelöscht"), ("C", "kopiert"),
        ("DD", "Konflikt"), ("UU", "Konflikt"), ("AA", "Konflikt"), ("UD", "Konflikt"),
        ("DU", "Konflikt"), ("AU", "Konflikt"), ("UA", "Konflikt"),
    ],
)  # fmt: skip
def test_status_names(status: str, name: str):
    from sprintforecast.web import ui

    assert ui.status_name(status) == name


# --- U5: settings cannot be saved ------------------------------------------------------


def fail_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(**_: object) -> None:
        raise BROKEN

    monkeypatch.setattr(config, "update", broken)


def test_language_change_with_unwritable_settings(
    repo: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    at = start(data_dir, monkeypatch)
    fail_settings(monkeypatch)
    at.sidebar.selectbox(key="language").set_value("en").run()
    assert not at.exception, at.exception
    assert any_error(at, "Zugriff verweigert")
    assert any_error(at, "Sprache wurde nicht geändert")
    assert at.sidebar.selectbox(key="language").value == "de"  # nothing switched


def test_folder_switch_with_unwritable_settings(
    repo: Path, data_dir: Path, second_folder: Path, monkeypatch: pytest.MonkeyPatch
):
    at = start(data_dir, monkeypatch)
    fail_settings(monkeypatch)
    sidebar_button(at, "Wechseln").click().run()
    assert not at.exception, at.exception
    assert any_error(at, "Zugriff verweigert")
    assert any_error(at, "nicht gewechselt")
    assert "zweiter-ordner" not in " ".join(m.value for m in at.sidebar.markdown)


def test_forget_with_unwritable_settings(
    repo: Path, data_dir: Path, second_folder: Path, monkeypatch: pytest.MonkeyPatch
):
    at = goto(start(data_dir, monkeypatch), "datenordner")
    fail_settings(monkeypatch)
    main_button(at, "Entfernen").click().run()
    assert not at.exception, at.exception
    assert any_error(at, "Zugriff verweigert")
    assert any("zweiter-ordner" in m.value for m in at.main.markdown)  # still in the list


def test_choose_folder_with_unwritable_settings(
    repo: Path, data_dir: Path, second_folder: Path, monkeypatch: pytest.MonkeyPatch
):
    at = goto(start(data_dir, monkeypatch), "datenordner")
    fail_settings(monkeypatch)
    at.text_input(key="data-path").set_value(str(second_folder))
    main_button(at, "Übernehmen").click().run()
    assert not at.exception, at.exception
    assert any_error(at, "Zugriff verweigert")
    assert "zweiter-ordner" not in " ".join(m.value for m in at.sidebar.markdown)


# --- U6: "Use without Git" survives a new tab --------------------------------------------


def test_without_git_survives_a_new_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    empty = tmp_path / "leer"
    empty.mkdir()
    at = start(empty, monkeypatch)
    at.session_state["offer-init"] = str(empty)
    at.run()
    main_button(at, "Ohne Git verwenden").click().run()
    assert [h.value for h in at.header] != ["Datenordner"]
    fresh = AppTest.from_file(str(APP), default_timeout=30)  # new tab = new session
    fresh.run()
    assert not fresh.exception, fresh.exception
    assert [h.value for h in fresh.header] != ["Datenordner"]
    assert config.load()["without_git_dirs"] == [str(empty.resolve())]


def test_without_git_choice_is_stored_once(tmp_path: Path):
    from sprintforecast.web import logic

    folder = tmp_path / "a"
    folder.mkdir()
    logic.remember_without_git(folder)
    logic.remember_without_git(folder)
    logic.remember_without_git(tmp_path / "a" / ".." / "a")  # different spelling
    assert config.load()["without_git_dirs"] == [str(folder.resolve())]
    assert logic.is_without_git(folder)
    assert not logic.is_without_git(tmp_path)


def test_without_git_does_nothing_when_settings_cannot_be_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    empty = tmp_path / "leer"
    empty.mkdir()
    at = start(empty, monkeypatch)
    at.session_state["offer-init"] = str(empty)
    at.run()
    fail_settings(monkeypatch)
    main_button(at, "Ohne Git verwenden").click().run()
    assert not at.exception, at.exception
    assert any_error(at, "Zugriff verweigert")
    assert [h.value for h in at.header] == ["Datenordner"]  # unchanged in the setup


def test_without_git_choice_is_taken_back_when_the_switch_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """If the switch fails after remembering, "without Git" is not left half saved."""
    from sprintforecast.web import logic

    empty = tmp_path / "leer"
    empty.mkdir()
    at = start(empty, monkeypatch)
    at.session_state["offer-init"] = str(empty)
    at.run()
    real = config.update

    def only_without_git(**changes: object) -> None:
        if logic.WITHOUT_GIT_KEY not in changes:
            raise BROKEN
        real(**changes)

    monkeypatch.setattr(config, "update", only_without_git)
    main_button(at, "Ohne Git verwenden").click().run()
    assert not at.exception, at.exception
    assert any_error(at, "Zugriff verweigert")
    assert not logic.is_without_git(empty)


def test_unrelated_confirmation_does_not_survive_another_sync(shared, data_dir, monkeypatch):
    _, _, server = shared
    foreign_history(server)
    at = start(data_dir, monkeypatch)
    sidebar_button(at, "Speichern und teilen").click().run()
    at.sidebar.checkbox(key="unrelated-confirm").check().run()
    assert not at.sidebar.button(key="unrelated-go").disabled
    sidebar_button(at, "Speichern und teilen").click().run()
    assert at.sidebar.button(key="unrelated-go").disabled  # confirm again


# --- U7: active folder missing in the switch list, also with a different path ----------------


def test_recent_dirs_exclude_active_folder_via_symlink(data_dir: Path, tmp_path: Path):
    from sprintforecast.web import ui

    link = tmp_path / "verweis"
    try:
        link.symlink_to(data_dir, target_is_directory=True)
    except OSError as e:  # Windows without administrator/developer mode: no symlinks
        if getattr(e, "winerror", None) != 1314:
            raise
        pytest.skip("Kein Recht für symbolische Verknüpfungen")
    config.update(recent_data_dirs=[str(link), str(data_dir / ".." / "teams")])
    assert ui._recent_dirs(Repository(data_dir)) == []
    assert ui._recent_dirs(Repository(link)) == []


# --- U8: test gaps ----------------------------------------------------------------------


def plugin_script() -> None:
    import streamlit as st

    from sprintforecast.plugins import WebPage
    from sprintforecast.web import ui

    ui.run_plugin_page(
        WebPage("demo", "Demo", ":material/upload:", lambda repo: st.write("PLUGIN-INHALT"))
    )


def test_plugin_page_is_locked_with_open_merge(
    repo: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    open_merge(repo)
    monkeypatch.setenv(DATA_ENV, str(data_dir))
    monkeypatch.setenv(STICHTAG_ENV, "2026-10-15")
    at = AppTest.from_function(plugin_script, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    assert [h.value for h in at.header] == ["Konflikte lösen"]
    assert not any("PLUGIN-INHALT" in m.value for m in at.markdown)


def test_plugin_page_renders_without_merge(
    repo: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv(DATA_ENV, str(data_dir))
    at = AppTest.from_function(plugin_script, default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    assert any("PLUGIN-INHALT" in m.value for m in at.markdown)


def test_sidebar_has_no_write_buttons_with_open_merge(shared, data_dir, monkeypatch):
    root, _, _ = shared
    diverge(root)
    subprocess.run(["git", "merge", "andere"], cwd=root, capture_output=True)
    (root / "offen.txt").write_text("offen\n")  # an open change would otherwise be committable
    invalidate_status()
    at = start(data_dir, monkeypatch)
    labels = [b.label for b in at.sidebar.button]
    assert "Zusammenführen abbrechen" in labels
    for forbidden in ("Speichern und teilen", "Änderungen committen"):
        assert forbidden not in labels


def test_new_tab_after_folder_switch_starts_in_new_folder(
    repo: Path, data_dir: Path, second_folder: Path, monkeypatch: pytest.MonkeyPatch
):
    tab1 = start(data_dir, monkeypatch)
    sidebar_button(tab1, "Wechseln").click().run()
    assert "zweiter-ordner" in " ".join(m.value for m in tab1.sidebar.markdown)
    fresh = AppTest.from_file(str(APP), default_timeout=30)  # new tab, environment unchanged
    fresh.run()
    assert not fresh.exception, fresh.exception
    assert "zweiter-ordner" in " ".join(m.value for m in fresh.sidebar.markdown)


@pytest.mark.parametrize("error", [OSError("tot"), RuntimeError("Symlink-Schleife")])
def test_resolved_path_keeps_unresolvable_path(monkeypatch, error: Exception):
    from sprintforecast.web.logic import resolved_path

    def broken(self):
        raise error

    monkeypatch.setattr(Path, "resolve", broken)
    assert resolved_path(Path("x") / "y") == Path("x") / "y"
