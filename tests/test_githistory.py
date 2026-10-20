# SPDX-License-Identifier: EUPL-1.2
"""Discard, history, restore and tags with real repositories."""

from pathlib import Path

import pytest
from gitrepos import Denying, Person, git, serve

from sprintforecast import git as gitmod
from sprintforecast import githistory, gitsync
from sprintforecast.git import GitError, invalidate_status

A1 = "teams/a/2026.1.yaml"


def test_discard_preview_and_single_file(alice: Person):
    alice.write("a/2026.1.yaml", "velocity: 99\nscope_creep: 1\n")
    alice.write("a/neu.yaml", "x: 1\ny: 2\n")
    (alice.data / "a" / "team.yaml").unlink()
    invalidate_status()
    lost = {item.file: item for item in githistory.discard_preview(alice.data)}
    assert lost[A1].status == "M" and (lost[A1].added, lost[A1].removed) == (1, 1)
    assert lost["teams/a/neu.yaml"].status == "??" and lost["teams/a/neu.yaml"].added == 2
    assert lost["teams/a/team.yaml"].status == "D"

    trash = githistory.discard(alice.data, [A1])
    assert (alice.data / "a" / "2026.1.yaml").read_text() == "velocity: 10\nscope_creep: 1\n"
    assert (alice.data / "a" / "neu.yaml").exists()  # other files untouched
    assert trash and (trash / A1).read_text().startswith("velocity: 99")  # trash


def test_discard_everything_including_new_and_deleted_files(alice: Person):
    alice.write("a/2026.1.yaml", "velocity: 99\n")
    alice.write("a/neu.yaml", "x: 1\n")
    (alice.data / "a" / "team.yaml").unlink()
    git(alice.root, "add", "teams/a/neu.yaml")  # also a new file that is already staged
    invalidate_status()
    githistory.discard(alice.data)
    assert git(alice.root, "status", "--porcelain") == ""
    assert (alice.data / "a" / "team.yaml").exists() and not (
        alice.data / "a" / "neu.yaml"
    ).exists()
    with pytest.raises(GitError, match="Keine Änderungen"):
        githistory.discard(alice.data)


def test_discard_leaves_files_outside_the_data_folder(alice: Person):
    (alice.root / "andere.txt").write_text("x")
    alice.write("a/2026.1.yaml", "velocity: 99\n")
    githistory.discard(alice.data)
    assert (alice.root / "andere.txt").exists()


def test_history_by_team_sprint_and_file(alice: Person, bob: Person):
    alice.write("a/2026.2.yaml", "velocity: 5\n")
    assert alice.sync("Review 2026.2").ok
    bob.sync("holen")
    bob.write("a/2026.1.yaml", "velocity: 11\nscope_creep: 1\n")
    assert bob.sync("Korrektur 2026.1").ok
    team = githistory.history(alice.data, alice.data / "a")
    assert [e.subject for e in team] == ["Review 2026.2", "Start"]
    alice.sync("holen")
    team = githistory.history(alice.data, alice.data / "a")
    assert [e.subject for e in team][:2] == ["Korrektur 2026.1", "Review 2026.2"]
    assert team[0].author == "Bob" and team[1].author == "Alice" and team[0].files == (A1,)
    only = githistory.history(alice.data, alice.data / "a" / "2026.1.yaml")
    assert [e.subject for e in only] == ["Korrektur 2026.1", "Start"]


def test_restore_earlier_state_is_a_change_that_can_be_undone(alice: Person):
    alice.write("a/2026.1.yaml", "velocity: 11\nscope_creep: 1\n")
    assert alice.sync("Korrektur").ok
    alice.write("a/2026.9.yaml", "velocity: 1\n")
    assert alice.sync("Neuer Sprint").ok
    start = githistory.history(alice.data, alice.data / "a")[-1]
    new = githistory.restore_version(alice.data, alice.data / "a", start.rev)
    assert (alice.data / "a" / "2026.1.yaml").read_text() == "velocity: 10\nscope_creep: 1\n"
    assert not (alice.data / "a" / "2026.9.yaml").exists()  # did not exist back then
    assert git(alice.root, "log", "-1", "--format=%s").startswith("Stand von")
    assert git(alice.root, "status", "--porcelain") == ""
    # undo
    githistory.revert_commit(alice.data, new)
    assert (alice.data / "a" / "2026.1.yaml").read_text() == "velocity: 11\nscope_creep: 1\n"
    assert (alice.data / "a" / "2026.9.yaml").exists()
    # and the restore can be shared
    assert alice.sync("teilen").ok


def test_restore_single_file(alice: Person):
    alice.write("a/2026.1.yaml", "velocity: 11\nscope_creep: 1\n")
    assert alice.sync("Korrektur").ok
    alice.write("a/team.yaml", "name: B\n")
    assert alice.sync("Name").ok
    old = githistory.history(alice.data, alice.data / "a" / "2026.1.yaml")[-1]
    githistory.restore_version(alice.data, alice.data / "a" / "2026.1.yaml", old.rev)
    assert (alice.data / "a" / "2026.1.yaml").read_text().startswith("velocity: 10")
    assert (alice.data / "a" / "team.yaml").read_text() == "name: B\n"  # only this file


def test_restore_refuses_with_open_changes_or_no_difference(alice: Person):
    head = githistory.history(alice.data)[0]
    with pytest.raises(GitError, match="bereits genau diesen Stand"):
        githistory.restore_version(alice.data, alice.data / "a", head.rev)
    alice.write("a/2026.1.yaml", "velocity: 99\n")
    with pytest.raises(GitError) as info:
        githistory.restore_version(alice.data, alice.data / "a", head.rev)
    assert info.value.kind == "dirty"
    with pytest.raises(GitError) as info:
        githistory.revert_commit(alice.data, head.rev)
    assert info.value.kind == "dirty"


def test_revert_with_conflict_changes_nothing(alice: Person):
    alice.write("a/2026.1.yaml", "velocity: 11\nscope_creep: 1\n")
    assert alice.sync("Erste").ok
    first = githistory.history(alice.data)[0]
    alice.write("a/2026.1.yaml", "velocity: 12\nscope_creep: 1\n")
    assert alice.sync("Zweite").ok
    with pytest.raises(GitError) as info:
        githistory.revert_commit(alice.data, first.rev)
    assert info.value.kind == "conflict"
    assert gitsync.state(alice.data).unfinished is None
    assert git(alice.root, "status", "--porcelain") == ""


def test_merges_cannot_be_reverted(alice: Person, bob: Person):
    alice.write("a/2026.2.yaml", "velocity: 5\n")
    bob.write("a/2026.3.yaml", "velocity: 7\n")
    assert alice.sync("A").ok and bob.sync("B").ok
    merge = next(e for e in githistory.history(bob.data) if e.merge)
    with pytest.raises(GitError, match="Zusammenführung"):
        githistory.revert_commit(bob.data, merge.rev)


def test_tags_set_later_listed_and_deleted_also_on_server(alice: Person, remote: Path):
    alice.write("a/2026.2.yaml", "velocity: 5\n")
    assert alice.sync("Review 2026.2").ok  # without tag
    first = githistory.history(alice.data)[-1]
    assert githistory.list_tags(alice.data) == []
    assert githistory.set_tag(alice.data, "a/2026.1", first.rev, "Review 2026.1") is None
    tags = githistory.list_tags(alice.data)
    assert [(t.name, t.target, t.subject) for t in tags] == [
        ("a/2026.1", first.short, "Review 2026.1")
    ]
    assert "a/2026.1" in git(remote, "tag")  # set afterwards and uploaded
    with pytest.raises(GitError, match="existiert bereits"):
        githistory.set_tag(alice.data, "a/2026.1")
    with pytest.raises(GitError, match="Ungültiger"):
        githistory.set_tag(alice.data, "ungültig name ~")
    assert githistory.delete_tag(alice.data, "a/2026.1") is None
    assert githistory.list_tags(alice.data) == [] and git(remote, "tag") == ""


def test_tags_with_an_empty_subject_of_the_oldest_tag(
    alice: Person, monkeypatch: pytest.MonkeyPatch
):
    """The list of tags comes from ``for-each-ref``; ``_git`` strips the separator at the end
    of the last line. If the subject of the oldest tag is empty (a tag on a commit without
    a subject), the last field is missing in that line."""
    alice.write("a/2026.2.yaml", "velocity: 5\n")
    git(alice.root, "add", "-A")
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2020-01-01T10:00:00")
    git(alice.root, "commit", "-q", "--allow-empty-message", "-m", "")
    git(alice.root, "tag", "a/leer")  # lightweight: the subject is the commit's
    alice.write("a/2026.3.yaml", "velocity: 6\n")
    git(alice.root, "add", "-A")
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2021-01-01T10:00:00")
    git(alice.root, "commit", "-qm", "Später")
    git(alice.root, "tag", "-a", "a/spaeter", "-m", "Mit Text")
    tags = githistory.list_tags(alice.data)
    assert [(tag.name, tag.subject) for tag in tags] == [("a/spaeter", "Mit Text"), ("a/leer", "")]


def test_a_tag_message_with_a_unicode_line_separator_stays_one_tag(alice: Person):
    """``str.splitlines`` also splits at U+2028 and similar characters: the rest of a subject
    would otherwise show up as a ghost tag that could even be deleted on the server."""
    alice.write("a/2026.2.yaml", "velocity: 5\n")
    git(alice.root, "add", "-A")
    git(alice.root, "commit", "-qm", "Start")
    git(alice.root, "tag", "-a", "a/trenner", "-m", "Release\u2028Notes: wichtig")
    tags = githistory.list_tags(alice.data)
    assert [tag.name for tag in tags] == ["a/trenner"]


@pytest.mark.usefixtures("no_login_prompt")
def test_tag_upload_without_login_is_a_warning_that_names_the_cause(alice: Person):
    """ " "Done locally only" shows the warning without a heading (``GitError.full()``): it names
    the cause itself, because the hint starts right away with the next step."""
    with serve(Denying) as port:
        git(alice.root, "remote", "set-url", "origin", f"http://127.0.0.1:{port}/r.git")
        warning = githistory.set_tag(alice.data, "a/lokal")
    assert warning is not None and warning.kind == "auth"
    text = warning.full()
    assert text.startswith("Anmeldung fehlt oder wurde abgelehnt. ")
    assert text.count("fehlt oder wurde abgelehnt") == 1
    assert "Zugangstoken" in text and text.endswith("Danach noch einmal versuchen.")
    assert [t.name for t in githistory.list_tags(alice.data)] == ["a/lokal"]  # tag stays local


def test_tag_upload_failure_is_a_warning_and_tag_stays(alice: Person, tmp_path: Path):
    """The server is a folder on a drive that is currently missing (no network, no proxy):
    uploading and deleting report "not reachable", the tag stays local."""
    git(alice.root, "remote", "set-url", "origin", str(tmp_path / "getrennt" / "weg.git"))
    warning = githistory.set_tag(alice.data, "a/lokal")
    assert warning and warning.kind == "offline"
    assert [t.name for t in githistory.list_tags(alice.data)] == ["a/lokal"]
    assert githistory.delete_tag(alice.data, "a/lokal").kind == "offline"
    assert githistory.list_tags(alice.data) == []


def test_tag_upload_and_delete_name_the_ssh_login_for_an_ssh_server(
    alice: Person, monkeypatch: pytest.MonkeyPatch
):
    """The server address also drives the classification for tags: SSH instructions instead of
    the help for https (access token)."""
    import subprocess

    git(alice.root, "tag", "-a", "-m", "m", "a/lokal")
    git(alice.root, "remote", "set-url", "origin", "git@example.org:team/daten.git")
    real = gitmod._git_result

    def refused(cwd, *args, **kwargs):
        if args[:1] in {("push",), ("ls-remote",), ("fetch",)}:
            return subprocess.CompletedProcess(
                args, 128, "", "git@example.org: Permission denied (publickey)."
            )
        return real(cwd, *args, **kwargs)

    monkeypatch.setattr(gitmod, "_git_result", refused)
    with pytest.raises(GitError) as caught:
        githistory.upload_tag(alice.data, "a/lokal")
    assert caught.value.kind == "auth" and "ssh-keygen" in caught.value.hint
    assert "Zugangstoken" not in caught.value.hint
    deleted = githistory.delete_tag(alice.data, "a/lokal")
    assert deleted is not None and deleted.kind == "auth" and "ssh-keygen" in deleted.hint


MARKED = "<<<<<<< HEAD\nvelocity: 5\n=======\nvelocity: 7\n>>>>>>> origin/main\n"


def test_restore_refuses_a_state_with_conflict_markers_and_changes_nothing(alice: Person):
    """An earlier shared faulty state (before the check on commit) cannot be restored;
    the current state stays unchanged."""
    alice.write("a/2026.1.yaml", MARKED)
    git(alice.root, "add", "-A")
    git(alice.root, "-c", "core.hooksPath=/dev/null", "commit", "-qm", "kaputt")
    bad = git(alice.root, "rev-parse", "--short", "HEAD")
    alice.write("a/2026.1.yaml", "velocity: 11\nscope_creep: 1\n")
    assert alice.sync("Repariert").ok
    before = git(alice.root, "rev-parse", "HEAD")
    with pytest.raises(GitError) as caught:
        githistory.restore_version(alice.data, alice.data / "a", bad)
    assert caught.value.kind == "conflict"
    assert git(alice.root, "rev-parse", "HEAD") == before
    assert git(alice.root, "status", "--porcelain") == ""
    assert (alice.data / "a" / "2026.1.yaml").read_text().startswith("velocity: 11")


def test_revert_refuses_a_state_with_conflict_markers_and_changes_nothing(alice: Person):
    alice.write("a/2026.1.yaml", MARKED)
    git(alice.root, "add", "-A")
    git(alice.root, "commit", "-qm", "kaputt")
    alice.write("a/2026.1.yaml", "velocity: 11\nscope_creep: 1\n")
    assert alice.sync("Repariert").ok
    repair = git(alice.root, "rev-parse", "--short", "HEAD")
    before = git(alice.root, "rev-parse", "HEAD")
    with pytest.raises(GitError) as caught:
        githistory.revert_commit(alice.data, repair)  # would bring the markers back
    assert caught.value.kind == "conflict"
    assert git(alice.root, "rev-parse", "HEAD") == before
    assert git(alice.root, "status", "--porcelain") == ""
