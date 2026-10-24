<#
.SYNOPSIS
    Windows smoke test for the installed foresprint.exe, with a text report.

.DESCRIPTION
    Checks what only shows up on a real Windows machine: version and help output, console
    subsystem, a check/forecast run on the demo team, the window starting and closing again,
    and the start log. Prints OK / FEHLER per step and writes the same lines to a report file.

    Nothing outside a temp folder is changed. The app writes its usual files (start.log under
    %LOCALAPPDATA%\Foresprint\logs, settings under %APPDATA%) when it starts.

.PARAMETER Exe
    Path of foresprint.exe. Default: the one on the PATH, else the install folder
    (%LOCALAPPDATA%\Programs\foresprint).

.PARAMETER Branch
    Branch of the repository from which the demo team is downloaded (default v1).

.PARAMETER Report
    Report file (default foresprint-smoke-YYYYMMDD-HHMM.txt in the current folder).

.PARAMETER SkipWindow
    Skip the window test (for sessions without a desktop).

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows-smoke.ps1
#>
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingWriteHost', '', Justification = 'Console script')]
param(
    [string]$Exe,
    [string]$Branch = "v1",
    [string]$Report,
    [switch]$SkipWindow
)
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"
if (-not $Report) { $Report = Join-Path (Get-Location) ("foresprint-smoke-{0:yyyyMMdd-HHmm}.txt" -f (Get-Date)) }
$lines = New-Object System.Collections.Generic.List[string]
$failed = 0

function Add-Result([string]$Step, [bool]$Ok, [string]$Note = "") {
    $state = if ($Ok) { "OK    " } else { "FEHLER" }
    if (-not $Ok) { $script:failed++ }
    $line = "$state $Step"
    if ($Note) { $line += " - $Note" }
    $script:lines.Add($line)
    Write-Host $line -ForegroundColor $(if ($Ok) { "Green" } else { "Red" })
}

function Invoke-Fs([string[]]$Arguments) {
    $out = & $script:Exe @Arguments 2>&1 | Out-String
    [pscustomobject]@{ Code = $LASTEXITCODE; Text = $out.Trim() }
}

if (-not $Exe) {
    $cmd = Get-Command foresprint -ErrorAction SilentlyContinue
    $Exe = if ($cmd) { $cmd.Source } else { Join-Path $env:LOCALAPPDATA "Programs\foresprint\foresprint.exe" }
}
$lines.Add("foresprint Windows smoke test, {0:yyyy-MM-dd HH:mm}" -f (Get-Date))
$lines.Add("Windows: " + [Environment]::OSVersion.VersionString + ", PowerShell " + $PSVersionTable.PSVersion)
$lines.Add("Exe: $Exe")
if (-not (Test-Path $Exe)) {
    Add-Result "Programm gefunden" $false "nicht gefunden; mit -Exe <Pfad> angeben"
    $lines | Set-Content $Report -Encoding UTF8
    exit 1
}
Add-Result "Programm gefunden" $true

# 1 version and help print text on the console
$v = Invoke-Fs @("--version")
Add-Result "--version" (($v.Code -eq 0) -and ($v.Text -match '\d+\.\d+\.\d+')) "Exit $($v.Code): $($v.Text)"
$h = Invoke-Fs @("--help")
Add-Result "--help" (($h.Code -eq 0) -and ($h.Text.Length -gt 100)) "Exit $($h.Code), $($h.Text.Length) Zeichen"

# 2 console subsystem (3), otherwise Windows prints nothing in a terminal
try {
    $bytes = [IO.File]::ReadAllBytes($Exe)
    $pe = [BitConverter]::ToInt32($bytes, 0x3C)
    $subsystem = [BitConverter]::ToUInt16($bytes, $pe + 24 + 68)
    Add-Result "PE-Subsystem Konsole" ($subsystem -eq 3) "Wert $subsystem"
} catch { Add-Result "PE-Subsystem Konsole" $false $_.Exception.Message }

# 3 demo team from the repository, then check / forecast / report
$tmp = Join-Path ([IO.Path]::GetTempPath()) ("foresprint-smoke-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
    $zip = Join-Path $tmp "repo.zip"
    Invoke-WebRequest "https://github.com/swallat/foresprint/archive/refs/heads/$Branch.zip" -OutFile $zip
    Expand-Archive $zip -DestinationPath (Join-Path $tmp "src") -Force
    $teams = Get-ChildItem (Join-Path $tmp "src") -Directory | Select-Object -First 1 | ForEach-Object { Join-Path $_.FullName "examples\teams" }
    Add-Result "Demo-Team geladen" (Test-Path (Join-Path $teams "demo\team.yaml")) $teams
    $data = Join-Path $tmp "teams"
    Copy-Item $teams $data -Recurse
    $c = Invoke-Fs @("--data", $data, "check")
    Add-Result "check (Demo)" ($c.Code -eq 0) "Exit $($c.Code): $(($c.Text -split "`n" | Select-Object -Last 2) -join ' | ')"
    $f = Invoke-Fs @("--data", $data, "forecast", "demo")
    Add-Result "forecast (Demo)" (($f.Code -eq 0) -and ($f.Text.Length -gt 50)) "Exit $($f.Code), $($f.Text.Length) Zeichen"
    $p = Invoke-Fs @("--data", $data, "people", "demo")
    Add-Result "people (Demo), Umlaute lesbar" (($p.Code -eq 0) -and ($p.Text -notmatch '[�]|Ã')) "Exit $($p.Code)"
} catch {
    Add-Result "Demo-Team und Befehle" $false $_.Exception.Message
}

# 4 window starts, comes to the front and closes without leftover processes
if ($SkipWindow) {
    $lines.Add("UEBERSPRUNGEN Fenster-Test (-SkipWindow)")
} else {
    $log = Join-Path $env:LOCALAPPDATA "Foresprint\logs\start.log"
    $logBefore = if (Test-Path $log) { (Get-Item $log).Length } else { 0 }
    $proc = Start-Process $Exe -PassThru
    $hasWindow = $false
    for ($i = 0; $i -lt 30 -and -not $hasWindow; $i++) {
        Start-Sleep -Seconds 1
        $any = Get-Process -Name foresprint -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 }
        $hasWindow = [bool]$any
    }
    Add-Result "Fenster erscheint (max. 30 s)" $hasWindow
    Get-Process -Name foresprint -ErrorAction SilentlyContinue | ForEach-Object { [void]$_.CloseMainWindow() }
    Start-Sleep -Seconds 10
    $left = @(Get-Process -Name foresprint, msedgewebview2 -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*foresprint*" })
    if ($left.Count -gt 0) {
        $left | Stop-Process -Force -ErrorAction SilentlyContinue
        Add-Result "Prozesse nach Schliessen beendet" $false "$($left.Count) uebrig (beendet)"
    } else {
        Add-Result "Prozesse nach Schliessen beendet" $true
    }
    if (Test-Path $log) {
        $new = (Get-Item $log).Length - $logBefore
        Add-Result "start.log geschrieben" ($new -gt 0) $log
        $lines.Add("--- start.log (letzte 8 Zeilen) ---")
        Get-Content $log -Tail 8 | ForEach-Object { $lines.Add($_) }
    } else {
        Add-Result "start.log geschrieben" $false "Datei fehlt: $log"
    }
}

Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
$lines.Add("")
$lines.Add("Ergebnis: $failed Fehler")
$lines | Set-Content $Report -Encoding UTF8
Write-Host ""
Write-Host "Ergebnis: $failed Fehler. Bericht: $Report" -ForegroundColor $(if ($failed) { "Red" } else { "Green" })
exit ([int]($failed -gt 0))
