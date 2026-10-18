# SPDX-License-Identifier: EUPL-1.2
"""Änderungsansicht „Was hat sich geändert?“ im Git-Bereich (AppTest, echte Git-Repositories)."""

import subprocess
from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest

from sprintforecast import diff
from sprintforecast.git import GitError, invalidate_status
from sprintforecast.storage import DATA_ENV, STICHTAG_ENV

APP = Path(__file__).parent.parent / "src" / "sprintforecast" / "web" / "app.py"
SPRINT = Path("teams") / "demo" / "sprints" / "2026.20.yaml"
TITLE = "Was hat sich geändert?"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def start(data_dir: Path, monkeypatch) -> AppTest:
    monkeypatch.setenv(DATA_ENV, str(data_dir))
    monkeypatch.setenv(STICHTAG_ENV, "2026-10-15")
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.run()
    assert not at.exception, at.exception
    return at


def view(at: AppTest) -> str:
    """Alles, was die Ansicht als Markdown oder Beschriftung ausgibt."""
    return "\n".join([m.value for m in at.sidebar.markdown] + [c.value for c in at.sidebar.caption])


def commit_extra(root: Path, name: str, text: str) -> Path:
    file = root / "teams" / name
    file.write_text(text, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "extra")
    invalidate_status()
    return file


def test_changed_value_is_shown_with_before_and_after(repo, data_dir: Path, monkeypatch):
    file = repo / SPRINT
    file.write_text(file.read_text().replace("velocity: 9.75", "velocity: 7.0"))
    invalidate_status()
    at = start(data_dir, monkeypatch)
    assert TITLE in view(at)
    assert "`demo/sprints/2026.20.yaml` – geändert" in view(at)
    (frame,) = [d.value for d in at.sidebar.dataframe]
    assert list(frame.columns) == ["Wert", "Vorher", "Nachher"]
    row = frame[frame["Wert"].str.endswith("velocity")].iloc[0]
    assert (row["Vorher"], row["Nachher"]) == ("9.75", "7.0")


def test_no_view_without_changes(repo, data_dir: Path, monkeypatch):
    at = start(data_dir, monkeypatch)
    assert TITLE not in view(at)


def test_new_deleted_and_unreadable_files(repo, data_dir: Path, monkeypatch):
    (data_dir / "neu.yaml").write_text("a: 1\n", encoding="utf-8")
    (data_dir / "bericht.xlsx").write_bytes(b"PK\x03\x04")
    (repo / SPRINT).unlink()
    invalidate_status()
    at = start(data_dir, monkeypatch)
    text = view(at)
    assert "`neu.yaml` – neu" in text
    assert "`bericht.xlsx` – neu" in text
    assert "`demo/sprints/2026.20.yaml` – gelöscht" in text
    assert text.count("keine Wertansicht") == 1  # nur die Excel-Datei
    assert len(at.sidebar.dataframe) == 0  # neu und gelöscht: nur die Art


def test_foreign_text_is_never_rendered_as_markdown(repo, data_dir: Path, monkeypatch):
    evil = "[Klick](http://evil.example) **fett** www.evil.example"
    file = commit_extra(repo, "**fett**.yaml", "wert: alt\n")
    file.write_text(f"wert: '{evil}'\n", encoding="utf-8")
    invalidate_status()
    at = start(data_dir, monkeypatch)
    # Der Dateiname steht als Code, der Wert nur in der Tabelle (kein Markdown, keine Beschriftung).
    assert "`**fett**.yaml` – geändert" in view(at)
    assert evil not in view(at)
    (frame,) = [d.value for d in at.sidebar.dataframe]
    assert frame.iloc[0]["Nachher"] == evil


def test_values_are_shortened_and_missing_is_a_dash(repo, data_dir: Path, monkeypatch):
    file = commit_extra(repo, "x.yaml", "weg: 1\n")
    long = list(range(100))
    file.write_text(f"liste: {long}\n", encoding="utf-8")
    invalidate_status()
    at = start(data_dir, monkeypatch)
    (frame,) = [d.value for d in at.sidebar.dataframe]
    rows = {r["Wert"]: r for _, r in frame.iterrows()}
    assert rows["weg"]["Nachher"] == "–" and rows["weg"]["Vorher"] == "1"
    assert rows["liste"]["Vorher"] == "–"
    assert len(rows["liste"]["Nachher"]) == 80 and rows["liste"]["Nachher"].endswith("…")


def test_rows_and_files_are_limited(repo, data_dir: Path, monkeypatch):
    file = commit_extra(repo, "viel.yaml", "".join(f"k{i}: 0\n" for i in range(40)))
    file.write_text("".join(f"k{i}: 1\n" for i in range(40)), encoding="utf-8")
    for i in range(30):
        (data_dir / f"neu{i:02}.txt").write_text("x", encoding="utf-8")
    invalidate_status()
    at = start(data_dir, monkeypatch)
    (frame,) = [d.value for d in at.sidebar.dataframe]
    assert len(frame) == 31 and frame.iloc[-1]["Wert"] == "… und 10 weitere"
    # 31 Dateien (viel.yaml und 30 neue): 25 gezeigt, 6 weitere
    assert "… und 6 weitere" in view(at)
    assert sum(1 for m in at.sidebar.markdown if " – " in m.value) == 25


def test_second_run_reads_nothing_again_until_invalidated(repo, data_dir: Path, monkeypatch):
    file = repo / SPRINT
    file.write_text(file.read_text().replace("velocity: 9.75", "velocity: 7.0"))
    invalidate_status()
    calls: list[Path] = []
    real = diff.file_changes

    def counting(path: Path):
        calls.append(path)
        return real(path)

    monkeypatch.setattr(diff, "file_changes", counting)
    at = start(data_dir, monkeypatch)
    assert len(calls) == 1
    at.run()
    assert len(calls) == 1  # unverändert: aus dem Zwischenspeicher
    invalidate_status()
    at.run()
    assert len(calls) == 2
    file.write_text(file.read_text().replace("velocity: 7.0", "velocity: 6.5"))  # Größe gleich
    at.run()
    assert len(calls) == 3  # Änderungszeit der Arbeitsdatei geändert
    assert any(d.value["Nachher"].eq("6.5").any() for d in at.sidebar.dataframe)


def test_git_error_hides_only_the_view(repo, data_dir: Path, monkeypatch):
    file = repo / SPRINT
    file.write_text(file.read_text().replace("velocity: 9.75", "velocity: 7.0"))
    invalidate_status()

    def broken(path: Path):
        raise GitError("kaputt", kind="unsafe_directory")

    monkeypatch.setattr(diff, "file_changes", broken)
    at = start(data_dir, monkeypatch)
    assert TITLE not in view(at)
    assert "nicht verfügbar" in view(at)
    assert any("1 offene Änderung" in e.label for e in at.sidebar.expander)
    assert any(b.label == "Änderungen committen" for b in at.sidebar.button)
    assert any(i.key == "commit_message" for i in at.sidebar.text_input)
