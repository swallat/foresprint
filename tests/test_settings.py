# SPDX-License-Identifier: EUPL-1.2
from pathlib import Path

import pytest

from sprintforecast.model import Team, TrendMode
from sprintforecast.settings import BY_KEY, SETTINGS, applicable, changes


def test_parse_and_apply():
    team = Team(key="t", name="T")
    BY_KEY["capacity.overhead_share"].set(team, BY_KEY["capacity.overhead_share"].parse("12,5 %"))
    assert team.capacity.overhead_share == pytest.approx(0.125)
    assert BY_KEY["capacity.overhead_share"].display(team) == "12.5"
    BY_KEY["forecast.trend_mode"].set(team, BY_KEY["forecast.trend_mode"].parse("linear"))
    assert team.forecast.trend_mode is TrendMode.LINEAR
    assert BY_KEY["capacity.region"].parse("nw") == "NW"
    assert BY_KEY["capacity.region"].parse("") is None


@pytest.mark.parametrize(
    ("key", "raw", "message"),
    [
        ("forecast.window", "2.5", "ganze Zahl"),
        ("forecast.window", "0", "≥ 1"),
        ("forecast.roadmap_share", "120", "≤ 100"),
        ("unit", "XX", "Erlaubt"),
        ("sprint.first_start", "15.10.2026", "JJJJ-MM-TT"),
        ("name", "", "Bitte einen Wert"),
    ],
)
def test_parse_rejects(key, raw, message):
    with pytest.raises(ValueError, match=message):
        BY_KEY[key].parse(raw)


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf", "1e999"])
@pytest.mark.parametrize(
    "key",
    [
        "forecast.reference_capacity",  # number without an upper limit
        "capacity.overhead_share",  # percent
        "forecast.window",  # integer
    ],
)
def test_parse_rejects_non_finite(key, raw):
    with pytest.raises(ValueError, match="endliche Zahl"):
        BY_KEY[key].parse(raw)


def test_display_roundtrip_for_defaults():
    team = Team(key="t", name="T")
    for s in SETTINGS:
        shown = s.display(team)
        if shown == "" and s.optional:
            continue
        copy = Team(key="t", name="T")
        s.set(copy, s.parse(shown))
        assert s.display(copy) == shown, s.key


def test_applicable_and_changes():
    assert {s.key for s in SETTINGS} - {s.key for s in applicable(True)} == {
        "sprint.first_start",
        "sprint.first_id",
    }
    a, b = Team(key="t", name="T"), Team(key="t", name="T")
    b.forecast.window = 3
    assert [(s.key, old, new) for s, old, new in changes(a, b)] == [("forecast.window", "5", "3")]


@pytest.mark.parametrize("junk", [3, ["de"], {"a": 1}, True, ""])
def test_wrongly_typed_language_in_settings_json_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, junk
):
    import json

    from sprintforecast import i18n

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    for var in ("SPRINTFORECAST_LANG", "LANG", "LC_ALL", "LANGUAGE"):
        monkeypatch.delenv(var, raising=False)
    (tmp_path / "sprintforecast").mkdir()
    (tmp_path / "sprintforecast" / "settings.json").write_text(json.dumps({"language": junk}))
    assert i18n._saved() is None
