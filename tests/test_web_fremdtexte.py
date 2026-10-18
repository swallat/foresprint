# SPDX-License-Identifier: EUPL-1.2
"""Texte, die andere bestimmen (Autor und Betreff von Commits, Tags, Branches, Server-Adresse,
Werte im Konflikt), erscheinen in der Oberfläche als Code und nie als Markdown: Links, Bilder und
Formatierung aus fremden Texten würden sonst dargestellt (AppTest, echte Repositories)."""

import re
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest
from test_web_datenordner import datenordner, enter_address
from test_web_datenordner import errors as main_errors
from test_web_k3_anbindung import foreign_history, sidebar_text
from test_web_sync import SPRINT, git, main_button, open_history, press, start

from sprintforecast.git import classify, invalidate_status
from sprintforecast.web import ui

TEAM = Path("teams") / "demo" / "team.yaml"

SUBJECT = "[Klick](http://example.org) **fett**"
AUTHOR = "![x](http://example.org/x.png)"
LINK = "www.evil.example/anmelden"  # als Markdown ein Link, als Git-Name erlaubt
TICKS = "a`www.evil.example/x`b"  # ein Backtick beendet sonst den Code-Span

# Teile der Texte oben: Sie dürfen nur innerhalb von Code-Spans vorkommen.
TRACES = ("Klick", "fett", "example.org", "x.png", "evil")

# Texte, die ein Code-Span nur mit Abstand oder gar nicht umschließen kann bzw. nicht zerlegen darf:
# Betreff, Autor und Tag-Nachricht mit Backtick; Emoji-Folge mit Zero-Width-Joiner (U+200D);
# persischer Name mit Zero-Width-Non-Joiner (U+200C).
FAMILY = "Familie \U0001f468\u200d\U0001f469\u200d\U0001f467"
PERSIAN = "\u0645\u06cc\u200c\u062e\u0648\u0627\u0647\u0645"
CODE_CASES = [  # Betreff, Autor, Betreff als Code, Autor als Code
    ("Fix `foo`", "Bo`b", "`` Fix `foo` ``", "``Bo`b``"),
    (FAMILY, PERSIAN, f"`{FAMILY}`", f"`{PERSIAN}`"),
]


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


def commit_of_bob(bob: Path, subject: str = SUBJECT, author: str = AUTHOR) -> None:
    sprint = bob / SPRINT
    sprint.write_text(
        sprint.read_text(encoding="utf-8").replace("velocity: 9.75", "velocity: 8"),
        encoding="utf-8",
    )
    git(bob, "commit", "-qam", subject, f"--author={author} <bob@example.org>")
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


@pytest.mark.parametrize(("subject", "author", "shown_subject", "shown_author"), CODE_CASES)
def test_commits_of_others_keep_backticks_and_joiners(
    shared, data_dir: Path, monkeypatch, subject, author, shown_subject, shown_author
):
    """Ein Backtick im Betreff („Fix `foo`“) beendet keinen Code-Span; Emoji-Folgen und Namen mit
    Joiner bleiben, wie sie sind."""
    _root, bob, _server = shared
    commit_of_bob(bob, subject, author)
    at = start(data_dir, monkeypatch)
    expected = f"{shown_author}: {shown_subject}"

    press(at, "Stand prüfen")
    assert expected in markdown(at)
    press(at, "Speichern und teilen")
    assert expected in markdown(at)


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


@pytest.mark.parametrize(
    ("message", "shown"), [("Fix `foo`", "`` Fix `foo` ``"), (FAMILY, f"`{FAMILY}`")]
)
def test_tags_of_others_keep_backticks_and_joiners_in_the_table(
    shared, data_dir: Path, monkeypatch, message, shown
):
    root, bob, _server = shared
    git(bob, "tag", "-a", TICKS, "-m", message)
    git(bob, "push", "-q", "origin", TICKS)
    git(root, "fetch", "-q", "--tags")
    at = open_history(start(data_dir, monkeypatch))
    [table] = [t.value for t in at.table]
    assert list(table.index) == [f"``{TICKS}``"]
    assert list(table["Nachricht"]) == [shown]


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


def conflict_on_the_team_name(root: Path, bob: Path, mine: str, theirs: str) -> None:
    """Beide ändern den Namen des Teams, Bob hat schon geteilt."""
    other = bob / TEAM
    other.write_text(
        other.read_text(encoding="utf-8").replace("name: Demo-Team", f"name: '{theirs}'"),
        encoding="utf-8",
    )
    git(bob, "commit", "-qam", "Name")
    git(bob, "push", "-q")
    own = root / TEAM
    own.write_text(
        own.read_text(encoding="utf-8").replace("name: Demo-Team", f"name: '{mine}'"),
        encoding="utf-8",
    )
    invalidate_status()


def test_values_of_a_conflict_are_shown_as_code(shared, data_dir: Path, monkeypatch):
    root, bob, _server = shared
    conflict_on_the_team_name(root, bob, mine=AUTHOR, theirs=SUBJECT)
    at = start(data_dir, monkeypatch)
    press(at, "Speichern und teilen")
    assert [h.value for h in at.header] == ["Konflikte lösen"]
    options = at.radio(key="conf-0-0").options
    assert options == [f"Meine Änderung: `'{AUTHOR}'`", f"Andere Änderung: `'{SUBJECT}'`"]
    for option in options:
        assert_only_code(option)


def test_values_of_a_conflict_keep_backticks_and_joiners(shared, data_dir: Path, monkeypatch):
    root, bob, _server = shared
    conflict_on_the_team_name(root, bob, mine="Bo`b", theirs=FAMILY)
    at = start(data_dir, monkeypatch)
    press(at, "Speichern und teilen")
    assert at.radio(key="conf-0-0").options == [
        "Meine Änderung: ``Bo`b``",
        f"Andere Änderung: `{FAMILY}`",
    ]


def test_files_and_keys_of_a_conflict_are_shown_as_code(shared, data_dir: Path, monkeypatch):
    """Dateinamen wie ``__notiz__.txt`` würden als Markdown fett bzw. kursiv; ein Backtick im
    Schlüssel beendete den Code-Span der Beschriftung. Das Zusammenführen läuft hier außerhalb der
    App (etwa mit einem Git-Programm): Dann ist auch die Datei zu sehen, die sich von selbst mischt
    (``__auto__.yaml``)."""
    root, bob, _server = shared
    note, auto = Path("teams/demo/__notiz__.txt"), Path("teams/demo/__auto__.yaml")
    (root / note).write_text("eins\n", encoding="utf-8")
    (root / auto).write_text("a: 1\nb: 2\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "Basis")
    git(root, "push", "-q")
    git(bob, "pull", "-q", "--ff-only")
    for person, text, a, b in ((bob, "bob", 3, 2), (root, "alice", 1, 4)):
        (person / note).write_text(f"{text}\n", encoding="utf-8")  # nur als Ganzes entscheidbar
        (person / auto).write_text(f"a: {a}\nb: {b}\n", encoding="utf-8")  # lässt sich mischen
        with (person / SPRINT).open("a", encoding="utf-8") as file:
            file.write(f"notiz`x: {text}\n")  # beide ergänzen den Schlüssel unterschiedlich
        git(person, "add", "-A")
        git(person, "commit", "-qm", text)
    git(bob, "push", "-q")
    git(root, "fetch", "-q")
    merge = subprocess.run(
        ["git", "merge", "--no-edit", "origin/main"], cwd=root, capture_output=True
    )
    assert merge.returncode != 0  # Konflikte: das Zusammenführen bleibt offen
    invalidate_status()
    at = start(data_dir, monkeypatch)
    assert [h.value for h in at.header] == ["Konflikte lösen"]
    assert "**`teams/demo/__notiz__.txt`**" in [m.value for m in at.markdown]
    assert "`teams/demo/__auto__.yaml`: wird automatisch zusammengeführt" in [
        c.value for c in at.caption
    ]
    assert "``notiz`x``" in [radio.label for radio in at.radio]


def test_files_in_the_list_of_changes_are_shown_as_code(shared, data_dir: Path, monkeypatch):
    """Die Beschriftung eines Kästchens und die Warnung deuten Markdown: ``__notiz__.txt`` würde
    zu „notiz“ in Fettdruck, ein Backtick im Namen beendete den Code-Span."""
    root, _bob, _server = shared
    (root / "teams" / "__notiz__.txt").write_text("eins\n", encoding="utf-8")
    (root / "teams" / "a`b.txt").write_text("eins\n", encoding="utf-8")
    invalidate_status()
    at = open_history(start(data_dir, monkeypatch))
    assert [c.label for c in at.checkbox] == [
        "`teams/__notiz__.txt` – neu (+1 −0 Zeilen)",
        "``teams/a`b.txt`` – neu (+1 −0 Zeilen)",
    ]
    main_button(at, "Alles verwerfen …").click().run()
    assert not at.exception, at.exception
    [warning] = [w.value for w in at.warning if "geht verloren" in w.value]
    assert "`teams/__notiz__.txt` – neu, +1 −0" in warning
    assert "``teams/a`b.txt`` – neu, +1 −0" in warning


# --- Text von Git und vom Server ---------------------------------------------------------------

HOOK = "[Klick](http://example.org) **fett**"  # was ein Server in seiner Absage schreiben kann


def reject_pushes(server: Path) -> None:
    """Der Server lehnt jedes Hochladen mit einer Zeile voller Markdown ab (pre-receive-Hook)."""
    hook = server / "hooks" / "pre-receive"
    hook.write_text(f"#!/bin/sh\ncat > /dev/null\necho '{HOOK}' >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)


def warnings_of_local_only(at: AppTest) -> list[str]:
    return [w.value for w in at.warning if w.value.startswith("Nur lokal erledigt")]


@pytest.mark.parametrize("action", ["delete", "set"])
def test_rejection_by_the_server_is_shown_as_code(shared, data_dir: Path, monkeypatch, action):
    """Löschen und Setzen eines Tags sind „nur lokal erledigt“, wenn der Server ablehnt. Die
    Warnung nennt den Tag und die Zeilen des Servers: nur als Code."""
    _root, bob, server = shared
    if action == "delete":  # den Tag gibt es nur auf dem Server
        git(bob, "tag", "-a", LINK, "-m", "x")
        git(bob, "push", "-q", "origin", LINK)
    reject_pushes(server)
    at = open_history(start(data_dir, monkeypatch))
    if action == "set":
        at.text_input[0].set_value(LINK)
        main_button(at, "Tag setzen").click().run()
    else:
        main_button(at, "Mit dem Server abgleichen").click().run()
        at.checkbox(key=f"tag-confirm-{LINK}").check().run()
        main_button(at, "Tag löschen").click().run()
    assert not at.exception, at.exception
    [warning] = warnings_of_local_only(at)
    assert warning.startswith("Nur lokal erledigt: `")  # der eigene Text bleibt Fließtext
    assert f"`remote: {HOOK}`" in warning
    assert f"! [remote rejected] {LINK} " in warning and "(pre-receive hook declined)" in warning
    assert_only_code(warning)


def test_rejection_when_uploading_a_tag_shows_the_text_of_the_server_only_as_code(
    shared, data_dir: Path, monkeypatch
):
    """Das Übertragen eines vorhandenen Tags meldet den Fehler (statt „nur lokal“) mit Hinweis;
    die Meldung des Servers steht aufklappbar im Code-Block."""
    root, _bob, server = shared
    git(root, "tag", LINK)
    reject_pushes(server)
    at = open_history(start(data_dir, monkeypatch))
    main_button(at, "Mit dem Server abgleichen").click().run()
    main_button(at, "Zum Server übertragen").click().run()
    assert not at.exception, at.exception
    assert "Server lehnt das Hochladen ab" in "\n".join(e.value for e in at.error)
    assert_only_code("\n".join(e.value for e in at.error))
    assert HOOK in "\n".join(c.value for c in at.code)


def test_a_message_of_git_without_hint_is_shown_as_code(
    data_dir: Path, monkeypatch, tmp_path: Path
):
    """Ohne Hinweis steht die Meldung selbst in der Fehlerbox: Das ist die Ausgabe von Git, mit
    Zeilen des Servers und Namen anderer. Eigene Texte (ohne Hinweis) bleiben Fließtext."""
    clone = ui.clone_repository

    def failing(url, path):
        if path.name != "klon":
            return clone(url, path)
        raise classify(f"fatal: bad ref {LINK}\nremote: {HOOK}   \nremote: ! `tick`")

    at = datenordner(data_dir, monkeypatch)
    monkeypatch.setattr(ui, "clone_repository", failing)
    enter_address(at, "https://example.org/team/daten.git")
    at.text_input(key="data-clone").set_value(str(tmp_path / "klon")).run()
    at.button(key="data-clone-go").click().run()
    assert not at.exception, at.exception
    shown = main_errors(at)
    assert f"`fatal: bad ref {LINK}`  \n`remote: {HOOK}`  \n`` remote: ! `tick` ``" in shown
    assert_only_code(shown)

    at.text_input(key="data-clone").set_value(str(tmp_path)).run()  # nicht leer: eigener Text
    at.button(key="data-clone-go").click().run()
    shown = main_errors(at)
    assert f"`{tmp_path}` ist nicht leer" in shown and "`ist nicht leer" not in shown
