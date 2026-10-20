# SPDX-License-Identifier: EUPL-1.2
"""Application settings (theme): stored in the user settings, not in the team data."""

from pathlib import Path

import pytest

from sprintforecast import appsettings, config

APP = Path(__file__).parent.parent / "src" / "sprintforecast" / "web" / "app.py"


def test_theme_defaults_to_system():
    assert appsettings.theme() == "system"
    assert appsettings.theme_options()["theme.base"] is None


@pytest.mark.parametrize("code", ["light", "dark"])
def test_saved_theme_is_read_and_sets_the_base(code):
    appsettings.save_theme(code)
    assert appsettings.theme() == code
    assert config.load()["theme"] == code
    assert appsettings.theme_options()["theme.base"] == code


def test_theme_keeps_other_settings():
    config.update(language="de")
    appsettings.save_theme("dark")
    assert config.load() == {"language": "de", "theme": "dark"}


def test_unknown_theme_is_rejected_and_ignored():
    with pytest.raises(ValueError):
        appsettings.save_theme("pink")
    config.update(theme="pink")
    assert appsettings.theme() == "system"


def test_page_saves_theme_and_applies_it(data_dir, monkeypatch):
    from streamlit import config as st_config
    from streamlit.testing.v1 import AppTest

    from sprintforecast.storage import DATA_ENV

    monkeypatch.setenv(DATA_ENV, str(data_dir))
    app = AppTest.from_file(str(APP), default_timeout=30)
    app.run()
    app.switch_page("page_scripts/app_settings.py").run()
    assert not app.exception, app.exception
    assert app.radio(key="theme").value == "system"
    app.radio(key="theme").set_value("dark").run()
    assert not app.exception, app.exception
    assert appsettings.theme() == "dark"
    assert st_config.get_option("theme.base") == "dark"
    app.radio(key="theme").set_value("system").run()
    assert st_config.get_option("theme.base") is None
