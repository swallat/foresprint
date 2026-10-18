# SPDX-License-Identifier: EUPL-1.2
"""Texte, die andere bestimmen (Autor und Betreff von Commits, Tags, Branches, Server-Adresse,
Werte im Konflikt), erscheinen in der Oberfläche als Code und nie als Markdown: Links, Bilder und
Formatierung aus fremden Texten würden sonst dargestellt (AppTest, echte Repositories)."""

import re
from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest
from test_web_k3_anbindung import foreign_history, sidebar_text
from test_web_sync import SPRINT, git, main_button, open_history, press, start

from sprintforecast.git import invalidate_status

TEAM = Path("teams") / "demo" / "team.yaml"

SUBJECT = "[Klick](http://example.org) **fett**"
AUTHOR = "![x](http://example.org/x.png)"
LINK = "www.evil.example/anmelden"  # als Markdown ein Link, als Git-Name erlaubt
TICKS = "a`www.evil.example/x`b"  # ein Backtick beendet sonst den Code-Span

# Teile der Texte oben: Sie dürfen nur innerhalb von Code-Spans vorkommen.
TRACES = ("Klick", "fett", "example.org", "x.png", "evil")


def outside_code(text: str) -> str:
    """Der Text ohne Code-Spans: Nur was dort steht, deutet Markdown."""
    return re.sub(r"(`+).+?\1", "", text)


def assert_only_code(text: str) -> None:
    outside = outside_code(text)
    assert not [trace for trace in TRACES if trace in outside], outside


def markdown(at: AppTest) -> str:
    return "\n".join(e.value for e in at.sidebar.markdown)


def tag_messages(at: AppTest) -> list[str]:
    return [s.value for s in at.success if s.value.startswith("Tag ")]


def commit_of_bob(bob: Path) -> None:
    sprint = bob / SPRINT
    sprint.write_text(
        sprint.read_text(encoding="utf-8").replace("velocity: 9.75", "velocity: 8"),
        encoding="utf-8",
    )
    git(bob, "commit", "-qam", SUBJECT, f"--author={AUTHOR} <bob@example.org>")
    git(bob, "push", "-q")


def test_commits_of_others_are_shown_as_code(shared, data_dir: Path, monkeypatch):
    _root, bob, _server = shared
    commit_of_bob(bob)
    at = start(data_dir, monkeypatch)

    press(at, "Stand prüfen")  # „Neu von anderen“ in der Seitenleiste, noch nicht übernommen
    assert f"`{AUTHOR}`" in markdown(at) and f"`{SUBJECT}`" in markdown(at)
    assert_only_code(markdown(at))

    press(at, "Speichern und teilen")  # dieselbe Liste nach dem Übernehmen
    assert any("von anderen übernommen" in s.value for s in at.sidebar.success)
    assert f"`{AUTHOR}`" in markdown(at) and f"`{SUBJECT}`" in markdown(at)
    assert_only_code(markdown(at))


def test_tags_of_others_are_shown_as_code_in_the_table(shared, data_dir: Path, monkeypatch):
    root, bob, _server = shared
    git(bob, "tag", "-a", LINK, "-m", SUBJECT)
    git(bob, "push", "-q", "origin", LINK)
    git(root, "fetch", "-q", "--tags")
    at = open_history(start(data_dir, monkeypatch))
    [table] = [t.value for t in at.table]
    # st.table deutet Markdown in allen Zellen, auch im Index.
    assert list(table.index) == [f"`{LINK}`"]
    assert list(table["Nachricht"]) == [f"`{SUBJECT}`"]


def test_tag_names_in_messages_are_shown_as_code(shared, data_dir: Path, monkeypatch):
    root, _bob, _server = shared
    at = open_history(start(data_dir, monkeypatch))

    at.text_input[0].set_value(LINK)
    main_button(at, "Tag setzen").click().run()
    assert not at.exception, at.exception
    assert tag_messages(at) == [f"Tag `{LINK}` gesetzt und geteilt."]

    at.checkbox(key=f"tag-confirm-{LINK}").check().run()
    main_button(at, "Tag löschen").click().run()
    assert not at.exception, at.exception
    assert tag_messages(at) == [f"Tag `{LINK}` gelöscht."]

    git(root, "tag", LINK)  # nur lokal: lässt sich zum Server übertragen
    main_button(at, "Mit dem Server abgleichen").click().run()
    main_button(at, "Zum Server übertragen").click().run()
    assert not at.exception, at.exception
    assert tag_messages(at) == [f"Tag `{LINK}` zum Server übertragen."]


def test_branch_and_upstream_names_are_shown_as_code(shared, data_dir: Path, monkeypatch):
    root, _bob, _server = shared
    git(root, "push", "-q", "origin", f"main:{LINK}")
    git(root, "checkout", "-q", "-b", TICKS, "--track", f"origin/{LINK}")
    invalidate_status()
    at = start(data_dir, monkeypatch)
    assert f"Branch ``{TICKS}``" in markdown(at)
    assert f"synchron mit `origin/{LINK}`" in "\n".join(c.value for c in at.sidebar.caption)
    assert_only_code(markdown(at) + "\n" + "\n".join(c.value for c in at.sidebar.caption))


def test_branch_after_reattaching_is_shown_as_code(shared, data_dir: Path, monkeypatch):
    root, _bob, _server = shared
    git(root, "checkout", "-q", "-b", LINK)
    git(root, "push", "-q", "origin", LINK)
    git(root, "remote", "set-head", "origin", LINK)  # der Hauptbranch laut Server
    git(root, "checkout", "-q", "--detach")
    invalidate_status()
    at = start(data_dir, monkeypatch)
    at.sidebar.button(key="git-reattach").click().run()
    assert not at.exception, at.exception
    flash = [s.value for s in at.success if "Zurück auf den Branch" in s.value]
    assert flash == [f"Zurück auf den Branch `{LINK}`."]


def test_server_and_branch_of_foreign_history_are_shown_as_code(
    shared, data_dir: Path, monkeypatch
):
    root, _bob, server = shared
    git(root, "checkout", "-q", "-b", LINK)
    git(root, "push", "-q", "-u", "origin", LINK)
    foreign_history(server)
    git(server, "branch", "-f", LINK, "main")  # auch dort die Historie ohne gemeinsamen Ursprung
    at = start(data_dir, monkeypatch)
    at.sidebar.button(key="git-sync").click().run()
    assert not at.exception, at.exception
    text = sidebar_text(at)
    assert "Server hat eine andere Historie" in text
    assert f"(`{server}`, Branch `{LINK}`)" in text
    assert_only_code(text)


def test_values_of_a_conflict_are_shown_as_code(shared, data_dir: Path, monkeypatch):
    root, bob, _server = shared
    theirs = bob / TEAM
    theirs.write_text(
        theirs.read_text(encoding="utf-8").replace("name: Demo-Team", f"name: '{SUBJECT}'"),
        encoding="utf-8",
    )
    git(bob, "commit", "-qam", "Name")
    git(bob, "push", "-q")
    mine = root / TEAM
    mine.write_text(
        mine.read_text(encoding="utf-8").replace("name: Demo-Team", f"name: '{AUTHOR}'"),
        encoding="utf-8",
    )
    invalidate_status()
    at = start(data_dir, monkeypatch)
    press(at, "Speichern und teilen")
    assert [h.value for h in at.header] == ["Konflikte lösen"]
    options = at.radio(key="conf-0-0").options
    assert options == [f"Meine Änderung: `'{AUTHOR}'`", f"Andere Änderung: `'{SUBJECT}'`"]
    for option in options:
        assert_only_code(option)
