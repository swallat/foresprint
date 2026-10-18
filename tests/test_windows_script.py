# SPDX-License-Identifier: EUPL-1.2
"""Das Windows-Prüfskript (scripts/windows-tests.ps1) wird mit PowerShell 7 auf Syntax und die
plattformunabhängigen Hilfsfunktionen geprüft. Ohne `pwsh` entfallen die Tests; die Windows-
Teile (Prozessliste, Sperren, Fenster) lassen sich nur auf Windows ausführen."""

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "windows-tests.ps1"
PWSH = shutil.which("pwsh")

pytestmark = pytest.mark.skipif(PWSH is None, reason="PowerShell 7 (pwsh) nicht installiert")


def pwsh(command: str, home: str | None = None) -> subprocess.CompletedProcess:
    env = None
    if home is not None:
        import os

        # Unter Windows gilt USERPROFILE als Profilordner, sonst HOME.
        env = os.environ | {"HOME": home, "USERPROFILE": home}
    return subprocess.run(
        [PWSH or "pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        env=env,
    )


def test_script_has_a_byte_order_mark_for_windows_powershell():
    """Windows PowerShell 5.1 liest eine Datei ohne BOM als ANSI und verstümmelt die Umlaute."""
    assert SCRIPT.read_bytes().startswith(b"\xef\xbb\xbf")


def test_script_parses_without_errors():
    done = pwsh(
        "$e = $null; $t = $null; "
        f"[void][System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT}', [ref]$t, [ref]$e); "
        "$e | ForEach-Object { '{0}:{1} {2}' -f $_.Extent.StartLineNumber, "
        "$_.Extent.StartColumnNumber, $_.Message }"
    )
    assert done.stdout.strip() == "", done.stdout


def test_script_avoids_powershell_7_only_syntax():
    """Das Skript soll auch unter Windows PowerShell 5.1 laufen."""
    text = SCRIPT.read_text(encoding="utf-8-sig")
    for forbidden in ("??", "?.", "-AsByteStream", "ForEach-Object -Parallel", "&&", "||"):
        assert forbidden not in text.replace("-and", "").replace("-or", ""), forbidden


HELPERS = r"""
. '__SCRIPT__'
$bad = @()
$kinds = @(
  @('sprintforecast-app.exe', '"C:\x\sprintforecast-app.exe"', 'Starter'),
  @('pythonw.exe', '"C:\u\tools\sprintforecast\Scripts\pythonw.exe" -m streamlit run C:\u\app.py --server.port 8501', 'Server (Streamlit)'),
  @('python.exe', 'C:\u\tools\sprintforecast\Scripts\python.exe snippet.py', 'Python'),
  @('msedge.exe', '"C:\Edge\msedge.exe" --app=http://localhost:8501 "--user-data-dir=C:\Users\Max Muster\AppData\Local\sprintforecast\browser-profil"', 'Browser (App-Fenster)'),
  @('msedge.exe', 'msedge.exe --type=renderer --user-data-dir="C:\Users\Max Muster\AppData\Local\sprintforecast\browser-profil" --lang=de', 'Browser (App-Fenster)'),
  @('msedge.exe', 'msedge.exe --user-data-dir="C:\Users\x\AppData\Local\Microsoft\Edge\User Data"', ''),
  @('python.exe', 'C:\Python314\python.exe C:\work\other.py', ''),
  @('uv.exe', 'uv tool upgrade --reinstall sprintforecast', 'Aktualisierung (uv)'),
  @('uv.exe', 'uv pip install foo', ''),
  @('powershell.exe', 'powershell -File C:\sprintforecast\scripts\windows-tests.ps1', '')
)
foreach ($c in $kinds) {
  $k = Get-SfKind -Name $c[0] -CommandLine $c[1]
  if ($k -ne $c[2]) { $bad += ('Get-SfKind {0}: {1} statt {2}' -f $c[0], $k, $c[2]) }
}
$args1 = ConvertTo-ArgumentString @('a b', 'c"d', '', 'e\', 'f g\')
if ($args1 -ne '"a b" "c\"d" "" e\ "f g\\"') { $bad += ('ConvertTo-ArgumentString: ' + $args1) }
$p1 = Protect-Text 'Token ghp_abcDEF123 und https://nutzer:geheim@server.example/x.git'
if ($p1 -match 'abcDEF123|geheim') { $bad += ('Protect-Text zeigt Zugangsdaten: ' + $p1) }
$p2 = Protect-Text ($env:HOME + '/Dokumente und ' + $env:HOME)
if ($p2 -match [regex]::Escape($env:HOME)) { $bad += ('Protect-Text zeigt den Profilordner: ' + $p2) }
if ($bad.Count -eq 0) { 'OK' } else { $bad }
"""


def test_helper_functions_classify_and_protect():
    done = pwsh(HELPERS.replace("__SCRIPT__", str(SCRIPT)), home="/home/tester")
    assert done.stdout.strip() == "OK", done.stdout + done.stderr
