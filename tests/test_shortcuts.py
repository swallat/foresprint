# SPDX-License-Identifier: EUPL-1.2
import os
from pathlib import Path

import pytest

from sprintforecast import shortcuts


@pytest.fixture
def program(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    monkeypatch.setattr(shortcuts, "icon_dir", lambda: tmp_path / "icons")
    monkeypatch.setattr(shortcuts, "app_program", lambda: "/opt/uv/bin/sprintforecast-app")
    return "/opt/uv/bin/sprintforecast-app"


def test_linux_desktop_entries(tmp_path: Path, program: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    (tmp_path / "Desktop").mkdir()
    paths = shortcuts.create(home=tmp_path, platform="linux")
    assert paths == [
        tmp_path / ".local/share/applications/sprintforecast.desktop",
        tmp_path / "Desktop/sprintforecast.desktop",
    ]
    entry = paths[0].read_text()
    assert f'Exec="{program}"' in entry and "Terminal=false" in entry
    icon = Path(next(x for x in entry.splitlines() if x.startswith("Icon="))[5:])
    assert icon.read_bytes().startswith(b"\x89PNG")
    assert os.access(paths[1], os.X_OK)


def test_mac_bundle_and_alias(tmp_path: Path, program: str):
    (tmp_path / "Desktop").mkdir()
    bundle, alias = shortcuts.create(home=tmp_path, platform="darwin")
    starter = bundle / "Contents/MacOS/Sprint-Forecast"
    assert f'exec "{program}"' in starter.read_text()
    assert os.access(starter, os.X_OK)
    assert alias.is_symlink() and alias.resolve() == bundle.resolve()
    shortcuts.create(home=tmp_path, platform="darwin")  # erneut: ersetzt den Alias


def test_windows_script():
    script = shortcuts.windows_script("C:\\Users\\O'Neil\\sf-app.exe", "C:\\Users\\O'Neil")
    assert "GetFolderPath('Desktop')" in script and "GetFolderPath('Programs')" in script
    assert "$link.TargetPath = 'C:\\Users\\O''Neil\\sf-app.exe'" in script


def test_missing_program(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(shortcuts, "app_program", lambda: None)
    with pytest.raises(RuntimeError, match="nicht gefunden"):
        shortcuts.create(home=tmp_path, platform="linux")


def test_windows_script_icon():
    script = shortcuts.windows_script("C:\\sf-app.exe", "C:\\", "C:\\x\\sprintforecast.ico")
    assert "$link.IconLocation = 'C:\\x\\sprintforecast.ico'" in script
    assert "IconLocation" not in shortcuts.windows_script("C:\\sf-app.exe", "C:\\")


def test_icon_formats(tmp_path: Path):
    from sprintforecast.icon import write_icon

    assert write_icon(tmp_path, "png").read_bytes().startswith(b"\x89PNG")
    assert write_icon(tmp_path, "ico").read_bytes()[:6] == b"\x00\x00\x01\x00\x01\x00"
    assert write_icon(tmp_path, "icns").read_bytes()[:4] == b"icns"
