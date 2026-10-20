# SPDX-License-Identifier: EUPL-1.2
from types import SimpleNamespace

import pytest
import typer
from typer.testing import CliRunner

from foresprint import plugins
from foresprint.plugins import Plugin, WebPage


class FakeEntryPoint:
    def __init__(self, name: str, value: object):
        self.name, self._value = name, value

    def load(self) -> object:
        if isinstance(self._value, Exception):
            raise self._value
        return self._value


@pytest.fixture
def fake_plugins(monkeypatch: pytest.MonkeyPatch):
    def install(*eps: FakeEntryPoint) -> None:
        monkeypatch.setattr(plugins, "entry_points", lambda group: list(eps))
        plugins.load_plugins.cache_clear()

    yield install
    plugins.load_plugins.cache_clear()


def test_load_plugins_skips_broken_ones(fake_plugins, capsys: pytest.CaptureFixture):
    page = WebPage("demo_import", "Demo-Import", ":material/upload:", render=lambda repo: None)
    good = Plugin("gut", web_pages=[page])
    fake_plugins(
        FakeEntryPoint("gut", good),
        FakeEntryPoint("kaputt", ImportError("fehlt")),
        FakeEntryPoint("falsch", SimpleNamespace()),
    )
    assert plugins.load_plugins() == (good,)
    assert plugins.web_pages() == [page]
    err = capsys.readouterr().err
    assert "'kaputt' konnte nicht geladen werden" in err
    assert "'falsch' ist kein" in err


def test_plugin_registers_cli_command():
    app = typer.Typer()

    @app.command()
    def basis() -> None:
        pass

    def register(target: typer.Typer) -> None:
        @target.command("demo-import")
        def demo_import() -> None:
            typer.echo("importiert")

    Plugin("demo", register_cli=register).register_cli(app)
    assert CliRunner().invoke(app, ["demo-import"]).output == "importiert\n"


def test_import_sprints_keeps_existing_team(tmp_path):
    from datetime import date

    from foresprint.model import Sprint, Team
    from foresprint.storage import Repository, import_sprints

    repo = Repository(tmp_path)
    sprint = Sprint("2026.1", date(2026, 1, 7), date(2026, 1, 21), velocity=10)
    paths = import_sprints(repo, Team(key="t", name="Neu"), [sprint])
    assert [p.name for p in paths] == ["team.yaml", "people.yaml", "2026.1.yaml"]
    repo.save_team(Team(key="t", name="Geändert"))
    paths = import_sprints(repo, Team(key="t", name="Import"), [sprint])
    assert [p.name for p in paths] == ["2026.1.yaml"]
    assert repo.load("t").team.name == "Geändert"


def test_load_plugins_reads_both_groups_and_the_new_group_wins(
    fake_plugins, monkeypatch: pytest.MonkeyPatch
):
    old_only, shared_old, shared_new = Plugin("alt"), Plugin("geteilt-alt"), Plugin("geteilt-neu")
    by_group = {
        plugins.ENTRY_POINT_GROUP: [FakeEntryPoint("geteilt", shared_new)],
        plugins.LEGACY_ENTRY_POINT_GROUP: [
            FakeEntryPoint("alt", old_only),
            FakeEntryPoint("geteilt", shared_old),
        ],
    }
    fake_plugins()
    monkeypatch.setattr(plugins, "entry_points", lambda group: by_group[group])
    plugins.load_plugins.cache_clear()
    loaded = plugins.load_plugins()
    assert shared_new in loaded and old_only in loaded and shared_old not in loaded
