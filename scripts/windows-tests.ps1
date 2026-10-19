<#
.SYNOPSIS
    Windows checks for sprintforecast with a Markdown report.

.DESCRIPTION
    Checks what only shows up on a real Windows machine and writes the result as a Markdown
    report to the current folder (or -Bericht).

    Automatic:
      App       start the app, close the window, wait; no processes may remain afterwards
      Uv        installation according to "uv tool list"; on request "uv tool upgrade sprintforecast"
      Anmeldung Git login (credential.helper, gh) and "git ls-remote" against your addresses
      Zeilenenden  create a data repository, save, commit, clone; "git diff" must be empty
      Sperre    YAML file with an exclusive lock: message instead of a crash?
      Symlink   may this account create symbolic links?
    Interactive (answer J, N or Enter to skip, plus a note):
      Interaktiv  network disconnected, protected branch, visuals

    The script changes no user settings (no "git config", no persistent environment
    variables, no registry). All test data lives in a temp folder that is deleted at the end.
    The app itself creates its usual files under %APPDATA%\sprintforecast on start-up
    (app.log, possibly settings.json); that is its normal behaviour.

.PARAMETER Bericht
    Path of the report file. Default: sprintforecast-windows-bericht-YYYYMMDD-HHMM.md in the
    current folder.

.PARAMETER Nur
    Run only these checks, comma-separated (App, Uv, Anmeldung, Zeilenenden, Sperre, Symlink,
    Interaktiv). With -File a list is passed as a single string; hence a string.

.PARAMETER HttpsUrl
    https address of your data repository for the login check (without credentials in the
    address). Asked for if not given.

.PARAMETER SshUrl
    SSH address of your data repository (git@host:organisation/repository.git). Asked for if
    not given.

.PARAMETER WartezeitSekunden
    How long to wait after closing the app window before checking (default 20).

.PARAMETER OhneRueckfragen
    Require no input: prompts and interactive checks are skipped.

.PARAMETER MitAutoUpdate
    Start the app under test with the configured self-update. Default: off
    (SPRINTFORECAST_AUTOUPDATE=aus only for the started process) so that the process check is
    not disturbed by an update.

.PARAMETER PythonExe
    Python of the sprintforecast installation. Default: the one of the uv tool installation.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows-tests.ps1

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows-tests.ps1 -Nur Zeilenenden,Symlink
#>
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingWriteHost', '', Justification = 'Interactive script with console output')]
[CmdletBinding()]
param(
    [string]$Bericht = '',
    [string]$Nur = '',
    [string]$HttpsUrl = '',
    [string]$SshUrl = '',
    [ValidateRange(1, 600)]
    [int]$WartezeitSekunden = 20,
    [switch]$OhneRueckfragen,
    [switch]$MitAutoUpdate,
    [string]$PythonExe = ''
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$KnownChecks = @('App', 'Uv', 'Anmeldung', 'Zeilenenden', 'Sperre', 'Symlink', 'Interaktiv')
$Selected = @(([string]$Nur -split '[,;\s]+') | Where-Object { $_ })
foreach ($name in $Selected) {
    if ($KnownChecks -notcontains $name) {
        throw ('Unbekannte Prüfung "{0}". Möglich: {1}' -f $name, ($KnownChecks -join ', '))
    }
}

$script:OnWindows = ($env:OS -eq 'Windows_NT')
$script:Sections = New-Object System.Collections.Generic.List[object]
$script:TempRoot = ''
$script:SavedEnv = @{}
$script:Locks = New-Object System.Collections.Generic.List[object]
$script:Leftover = @{}
$script:ReportWritten = $false
$script:Notes = ''
$script:Context = [ordered]@{}
$script:Git = ''
$script:Uv = ''
$script:Gh = ''
$script:Sf = ''
$script:SfApp = ''
$script:Py = ''
$script:SnippetCount = 0

# ------------------------------------------------------------------------------------------
# Ausgabe
# ------------------------------------------------------------------------------------------

$script:StatusColor = @{ 'OK' = 'Green'; 'FEHLER' = 'Red'; 'HINWEIS' = 'Yellow'; 'ÜBERSPRUNGEN' = 'DarkGray' }

function Write-Line {
    param([string]$Text = '', [string]$Color = 'Gray')
    Write-Host $Text -ForegroundColor $Color
}

function Protect-Text {
    # Entfernt Zugangsdaten und den persönlichen Profilordner aus Text für den Bericht.
    param([string]$Text)
    if ([string]::IsNullOrEmpty($Text)) { return '' }
    $out = $Text
    $out = [regex]::Replace($out, '(gh[pousr]_|github_pat_)[A-Za-z0-9_]+', '***')
    $out = [regex]::Replace($out, '(?<=://)[^/@\s]+@', '***@')
    $profileDir = if ($script:OnWindows) { $env:USERPROFILE } else { $env:HOME }
    if (-not [string]::IsNullOrEmpty($profileDir)) {
        # Git und uv geben Pfade oft mit Schrägstrichen aus.
        foreach ($variant in @($profileDir, $profileDir.Replace('\', '/'))) {
            $out = [regex]::Replace($out, [regex]::Escape($variant), '%USERPROFILE%', 'IgnoreCase')
        }
    }
    return $out
}

# ------------------------------------------------------------------------------------------
# Abschnitte und Bericht
# ------------------------------------------------------------------------------------------

function Open-Section {
    param([string]$Id, [string]$Title)
    $section = [pscustomobject]@{
        Id      = $Id
        Title   = $Title
        Status  = 'ÜBERSPRUNGEN'
        Summary = ''
        Lines   = New-Object System.Collections.Generic.List[string]
    }
    $script:Sections.Add($section)
    Write-Line ''
    Write-Line ('=== {0} ===' -f $Title) 'Cyan'
    return $section
}

function Add-Text {
    param($Section, [string]$Text)
    $Section.Lines.Add((Protect-Text $Text))
    $Section.Lines.Add('')
}

function Add-Block {
    param($Section, [string]$Caption, [string]$Text)
    $body = (Protect-Text $Text).TrimEnd()
    if ($body.Length -gt 6000) { $body = $body.Substring(0, 6000) + "`n… (gekürzt)" }
    $body = $body.Replace('```', "'''")
    if ($Caption) { $Section.Lines.Add('**' + (Protect-Text $Caption) + '**') }
    $Section.Lines.Add('```text')
    $Section.Lines.Add($(if ($body) { $body } else { '(leer)' }))
    $Section.Lines.Add('```')
    $Section.Lines.Add('')
}

function Complete-Section {
    param($Section, [string]$Status, [string]$Summary)
    $Section.Status = $Status
    $Section.Summary = Protect-Text $Summary
    $color = $script:StatusColor[$Status]
    Write-Line ('{0}: {1}' -f $Status, $Section.Summary) $color
}

function Invoke-Check {
    # Führt eine Prüfung aus; ein Ausnahmefehler beendet nur diese Prüfung, nicht das Skript.
    param([string]$Id, [string]$Title, [scriptblock]$Body)
    if ($Selected.Count -gt 0 -and ($Selected -notcontains $Id)) { return }
    $section = Open-Section -Id $Id -Title $Title
    try {
        & $Body $section
    } catch {
        $message = $_.Exception.Message
        Add-Block $section 'Unerwarteter Fehler im Skript' ($message + "`n" + $_.ScriptStackTrace)
        Complete-Section $section 'FEHLER' ('Prüfung abgebrochen: ' + $message)
    }
}

function Write-Report {
    param([string]$Path)
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.AppendLine('# sprintforecast – Windows-Prüfbericht')
    [void]$sb.AppendLine()
    [void]$sb.AppendLine('| | |')
    [void]$sb.AppendLine('|---|---|')
    foreach ($key in $script:Context.Keys) {
        $value = (Protect-Text ([string]$script:Context[$key])).Replace('|', '\|').Replace("`n", ' ')
        [void]$sb.AppendLine(('| {0} | {1} |' -f $key, $value))
    }
    [void]$sb.AppendLine()
    [void]$sb.AppendLine('## Ergebnis')
    [void]$sb.AppendLine()
    [void]$sb.AppendLine('| Prüfung | Ergebnis | Kurz |')
    [void]$sb.AppendLine('|---|---|---|')
    foreach ($s in $script:Sections) {
        [void]$sb.AppendLine(('| {0} | {1} | {2} |' -f $s.Title, $s.Status, $s.Summary.Replace('|', '\|').Replace("`n", ' ')))
    }
    [void]$sb.AppendLine()
    foreach ($s in $script:Sections) {
        [void]$sb.AppendLine(('## {0} – {1}' -f $s.Title, $s.Status))
        [void]$sb.AppendLine()
        [void]$sb.AppendLine($s.Summary)
        [void]$sb.AppendLine()
        foreach ($line in $s.Lines) { [void]$sb.AppendLine($line) }
    }
    if ($script:Notes) {
        [void]$sb.AppendLine('## Notizen')
        [void]$sb.AppendLine()
        [void]$sb.AppendLine((Protect-Text $script:Notes))
    }
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($Path, $sb.ToString(), $encoding)
    $script:ReportWritten = $true
}

# ------------------------------------------------------------------------------------------
# Werkzeuge: Programme, Prozesse, Umgebung, Temp
# ------------------------------------------------------------------------------------------

function Find-Tool {
    param([string]$Name)
    $found = Get-Command -Name $Name -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($found) { return [string]$found.Source }
    return ''
}

function ConvertTo-ArgumentString {
    # Windows-Kommandozeile aus einzelnen Argumenten (Regeln von CommandLineToArgvW).
    param([string[]]$Arguments)
    $parts = @()
    foreach ($a in $Arguments) {
        if ($a -eq '') {
            $parts += '""'
        } elseif ($a -notmatch '[\s"]') {
            $parts += $a
        } else {
            $quoted = [regex]::Replace($a, '(\\*)"', '$1$1\"')
            $quoted = [regex]::Replace($quoted, '(\\+)$', '$1$1')
            $parts += ('"' + $quoted + '"')
        }
    }
    return ($parts -join ' ')
}

function Close-ProcessTree {
    param([int]$ProcessId)
    if ($script:OnWindows) {
        $children = @(Get-CimInstance -ClassName Win32_Process -Filter ('ParentProcessId = {0}' -f $ProcessId) -ErrorAction SilentlyContinue)
        foreach ($c in $children) { Close-ProcessTree -ProcessId ([int]$c.ProcessId) }
    }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Invoke-Native {
    # Startet ein Programm ohne Fenster, liest Ausgabe und Fehlerausgabe getrennt (UTF-8) und
    # bricht nach TimeoutSeconds ab. Eingaben werden nie verlangt (Standardeingabe ist zu).
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory = '',
        [hashtable]$Environment = @{},
        [int]$TimeoutSeconds = 120,
        [string]$InputText = ''
    )
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    $psi.Arguments = ConvertTo-ArgumentString $Arguments
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.RedirectStandardInput = $true
    $psi.CreateNoWindow = $true
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
    if ($WorkingDirectory) { $psi.WorkingDirectory = $WorkingDirectory }
    $psi.EnvironmentVariables['PYTHONUTF8'] = '1'
    # Jeder Aufruf der CLI könnte sonst nach seinem Ende die echte Installation aktualisieren.
    if (-not $MitAutoUpdate) { $psi.EnvironmentVariables['SPRINTFORECAST_AUTOUPDATE'] = 'aus' }
    foreach ($key in $Environment.Keys) { $psi.EnvironmentVariables[[string]$key] = [string]$Environment[$key] }

    $result = [pscustomobject]@{ ExitCode = -1; Output = ''; Error = ''; TimedOut = $false; Seconds = 0.0 }
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    try {
        [void]$process.Start()
    } catch {
        $result.Error = 'Start fehlgeschlagen: ' + $_.Exception.Message
        return $result
    }
    $outTask = $process.StandardOutput.ReadToEndAsync()
    $errTask = $process.StandardError.ReadToEndAsync()
    try {
        if ($InputText) { $process.StandardInput.Write($InputText) }
        $process.StandardInput.Close()
    } catch {
        Write-Verbose 'Standardeingabe schon geschlossen.'
    }
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        $result.TimedOut = $true
        Close-ProcessTree -ProcessId $process.Id
        [void]$process.WaitForExit(5000)
    } else {
        $process.WaitForExit()  # leert die asynchronen Ausgabepuffer
    }
    $watch.Stop()
    $result.Seconds = [math]::Round($watch.Elapsed.TotalSeconds, 1)
    if ($process.HasExited) { $result.ExitCode = $process.ExitCode }
    if ($outTask.Wait(5000)) { $result.Output = $outTask.Result }
    if ($errTask.Wait(5000)) { $result.Error = $errTask.Result }
    $process.Dispose()
    return $result
}

function Format-Native {
    param($Result)
    $text = ''
    if ($Result.Output) { $text += $Result.Output.TrimEnd() }
    if ($Result.Error) { $text += $(if ($text) { "`n" } else { '' }) + $Result.Error.TrimEnd() }
    if ($Result.TimedOut) { $text += "`n(abgebrochen nach Zeitüberschreitung)" }
    return ($text + "`n(Exitcode " + $Result.ExitCode + ', ' + $Result.Seconds + ' s)')
}

function Invoke-Git {
    param([string]$Directory, [string[]]$Arguments, [hashtable]$Environment = @{}, [int]$TimeoutSeconds = 120)
    $gitEnv = @{ GIT_TERMINAL_PROMPT = '0' }
    foreach ($key in $Environment.Keys) { $gitEnv[$key] = $Environment[$key] }
    $full = @()
    if ($Directory) { $full += @('-C', $Directory) }
    $full += $Arguments
    return Invoke-Native -FilePath $script:Git -Arguments $full -Environment $gitEnv -TimeoutSeconds $TimeoutSeconds
}

function Invoke-Sf {
    param([string[]]$Arguments, [int]$TimeoutSeconds = 120)
    return Invoke-Native -FilePath $script:Sf -Arguments $Arguments -TimeoutSeconds $TimeoutSeconds
}

function Invoke-Python {
    # Führt ein kleines Python-Programm mit dem Python der Installation aus (isolierter Modus,
    # UTF-8), damit die Prüfung dieselben Funktionen nutzt wie die App.
    param([string]$Code, [string[]]$Arguments = @(), [int]$TimeoutSeconds = 120)
    $script:SnippetCount++
    $dir = Join-Path (Get-TempRoot) 'skripte'
    [void][IO.Directory]::CreateDirectory($dir)
    $file = Join-Path $dir ('pruefung{0}.py' -f $script:SnippetCount)
    [IO.File]::WriteAllText($file, $Code, (New-Object System.Text.UTF8Encoding($false)))
    return Invoke-Native -FilePath $script:Py -Arguments (@('-I', '-X', 'utf8', $file) + $Arguments) -TimeoutSeconds $TimeoutSeconds
}

function Get-TempRoot {
    if (-not $script:TempRoot) {
        $name = 'sprintforecast-wintest-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
        $script:TempRoot = Join-Path ([IO.Path]::GetTempPath()) $name
        [void][IO.Directory]::CreateDirectory($script:TempRoot)
    }
    return $script:TempRoot
}

function Save-ProcessEnv {
    param([string[]]$Names)
    foreach ($n in $Names) {
        if (-not $script:SavedEnv.ContainsKey($n)) {
            $script:SavedEnv[$n] = [Environment]::GetEnvironmentVariable($n, 'Process')
        }
    }
}

function Restore-ProcessEnv {
    foreach ($n in @($script:SavedEnv.Keys)) {
        [Environment]::SetEnvironmentVariable($n, $script:SavedEnv[$n], 'Process')
    }
    $script:SavedEnv = @{}
}

function Wait-Until {
    param([scriptblock]$Condition, [int]$TimeoutSeconds, [int]$PollMilliseconds = 500)
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    while ($watch.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        if (& $Condition) { return $true }
        Start-Sleep -Milliseconds $PollMilliseconds
    }
    return $false
}

function Read-Answer {
    # Frage mit J, N oder Enter (überspringen) und optionaler Notiz.
    param([string]$Question)
    while ($true) {
        $raw = Read-Host ($Question + ' [J/N, Enter = überspringen]')
        $answer = ([string]$raw).Trim().ToLowerInvariant()
        if ($answer -in @('j', 'ja', 'y', 'yes')) { $status = 'OK'; break }
        if ($answer -in @('n', 'nein', 'no')) { $status = 'FEHLER'; break }
        if ($answer -in @('', 's')) { $status = 'ÜBERSPRUNGEN'; break }
        Write-Line 'Bitte J, N oder Enter eingeben.' 'Yellow'
    }
    $note = ''
    if ($status -ne 'ÜBERSPRUNGEN') { $note = ([string](Read-Host 'Notiz (optional, Enter = keine)')).Trim() }
    return [pscustomobject]@{ Status = $status; Note = $note }
}

function Test-Interactive {
    return (-not $OhneRueckfragen) -and [Environment]::UserInteractive
}

# ------------------------------------------------------------------------------------------
# Prozesse von sprintforecast (nur Windows)
# ------------------------------------------------------------------------------------------

function Get-SfKind {
    # Ordnet einen Prozess der App zu (leer = gehört nicht dazu): Starter, Python, Browser mit dem
    # eigenen Profil (unter ...\sprintforecast\browser-profil), uv-Aktualisierung.
    param([string]$Name, [string]$CommandLine)
    if ($Name -ieq 'sprintforecast-app.exe') { return 'Starter' }
    if ($Name -ieq 'sprintforecast.exe') { return 'Befehlszeile' }
    if ($Name -match '^pythonw?\.exe$' -and $CommandLine -match 'sprintforecast') {
        return $(if ($CommandLine -match 'streamlit') { 'Server (Streamlit)' } else { 'Python' })
    }
    # Der Pfad kann Leerzeichen enthalten; dann steht das Anführungszeichen vor "--user-data-dir".
    if ($CommandLine -match 'user-data-dir="?[^"]*sprintforecast') { return 'Browser (App-Fenster)' }
    if ($Name -ieq 'uv.exe' -and $CommandLine -match 'sprintforecast') { return 'Aktualisierung (uv)' }
    return ''
}

function Get-SfProcess {
    # Alles, was zur App gehört (siehe Get-SfKind).
    $all = @(Get-CimInstance -ClassName Win32_Process -ErrorAction Stop)
    $found = @()
    foreach ($p in $all) {
        $name = [string]$p.Name
        $cmd = [string]$p.CommandLine
        $kind = Get-SfKind -Name $name -CommandLine $cmd
        if ($kind) {
            $found += [pscustomobject]@{
                Id          = [int]$p.ProcessId
                ParentId    = [int]$p.ParentProcessId
                Name        = $name
                Kind        = $kind
                CommandLine = $cmd
                Created     = [string]$p.CreationDate
            }
        }
    }
    return $found
}

function Get-ProcessCreated {
    # Startzeit eines Prozesses (Win32_Process); leer, wenn es ihn nicht (mehr) gibt.
    param([int]$ProcessId)
    $found = @(Get-CimInstance -ClassName Win32_Process -Filter ('ProcessId = {0}' -f $ProcessId) -ErrorAction SilentlyContinue)
    if ($found.Count -eq 0) { return '' }
    return ([string]$found[0].CreationDate)
}

function Add-Leftover {
    # Merkt einen gestarteten Prozess mit seiner Startzeit: Aufgeräumt wird später nur, was noch
    # derselbe Prozess ist (die Nummer könnte inzwischen jemand anderem gehören).
    param($Process)
    if (-not $script:Leftover.ContainsKey($Process.Id)) {
        $script:Leftover[$Process.Id] = [string]$Process.Created
    }
}

function Format-ProcessTable {
    param($Processes)
    $rows = @($Processes)
    if ($rows.Count -eq 0) { return '(keine)' }
    $lines = @()
    foreach ($p in ($rows | Sort-Object -Property Id)) {
        $cmd = $p.CommandLine
        if ($cmd.Length -gt 150) { $cmd = $cmd.Substring(0, 150) + '…' }
        $lines += ('{0,6} (Eltern {1,6})  {2,-22} {3}  {4}' -f $p.Id, $p.ParentId, $p.Name, $p.Kind, $cmd)
    }
    return ($lines -join "`n")
}

# ------------------------------------------------------------------------------------------
# Testdaten
# ------------------------------------------------------------------------------------------

$script:CodeDemoRepo = @'
import sys
from datetime import date
from pathlib import Path

from sprintforecast.git import init_data_repository
from sprintforecast.model import Membership, Person, Team
from sprintforecast.storage import Repository

teams = init_data_repository(Path(sys.argv[1]))
repo = Repository(teams)
team = Team(key="demo", name="DEMO")
team.sprint.first_id = "2026.1"
team.sprint.first_start = date(2026, 1, 5)
repo.save_team(team)
people = [
    Person(id="anna", name="Anna Übung", memberships=[Membership(start=date(2026, 1, 1), fte=1.0)])
]
repo.save_people("demo", people)
print(teams)
'@

$script:CodeResave = @'
import sys
from pathlib import Path

from sprintforecast.storage import Repository

repo = Repository(Path(sys.argv[1]))
data = repo.load(sys.argv[2])
repo.save_team(data.team)
repo.save_people(sys.argv[2], data.people)
print("gespeichert")
'@

$script:CodeLockedSave = @'
import json
import sys
from pathlib import Path

from sprintforecast.model import Team
from sprintforecast.storage import Repository

repo = Repository(Path(sys.argv[1]))
try:
    repo.save_team(Team(key=sys.argv[2], name="geändert"))
    print(json.dumps({"ok": True}))
except BaseException as e:
    print(json.dumps({"ok": False, "type": type(e).__name__, "message": str(e)}))
'@

function Initialize-DemoRepository {
    # Legt mit dem Code der App ein Daten-Repository mit einem Team an; liefert den Teams-Ordner.
    param([string]$Path)
    $r = Invoke-Python -Code $script:CodeDemoRepo -Arguments @($Path)
    if ($r.ExitCode -ne 0) { throw ('Testdaten konnten nicht angelegt werden: ' + (Format-Native $r)) }
    return ($r.Output.Trim())
}

# ------------------------------------------------------------------------------------------
# Kontext (Versionen)
# ------------------------------------------------------------------------------------------

function Initialize-Context {
    $script:Git = Find-Tool 'git'
    $script:Uv = Find-Tool 'uv'
    $script:Gh = Find-Tool 'gh'
    $script:Sf = Find-Tool 'sprintforecast'
    $script:SfApp = Find-Tool 'sprintforecast-app'

    $script:Context['Datum'] = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss zzz')
    if ($script:OnWindows) {
        try {
            $os = Get-CimInstance -ClassName Win32_OperatingSystem
            $script:Context['Windows'] = '{0} {1} (Build {2}), {3}' -f $os.Caption, $os.Version, $os.BuildNumber, $os.OSArchitecture
        } catch {
            $script:Context['Windows'] = [Environment]::OSVersion.VersionString
        }
    } else {
        $script:Context['Windows'] = 'KEIN Windows: ' + [Environment]::OSVersion.VersionString + ' (nur Trockenlauf)'
    }
    $edition = if ($PSVersionTable.ContainsKey('PSEdition')) { $PSVersionTable.PSEdition } else { 'Desktop' }
    $script:Context['PowerShell'] = '{0} ({1})' -f $PSVersionTable.PSVersion, $edition
    $script:Context['Konto'] = $(if ($script:OnWindows) { 'Administrator: ' + (Test-Administrator) } else { 'nicht Windows' })

    if ($script:Git) {
        $r = Invoke-Native -FilePath $script:Git -Arguments @('--version') -TimeoutSeconds 20
        $script:Context['git'] = $r.Output.Trim()
    } else {
        $script:Context['git'] = 'NICHT GEFUNDEN'
    }
    if ($script:Uv) {
        $r = Invoke-Native -FilePath $script:Uv -Arguments @('--version') -TimeoutSeconds 20
        $script:Context['uv'] = $r.Output.Trim()
        if (-not $PythonExe) {
            $d = Invoke-Native -FilePath $script:Uv -Arguments @('tool', 'dir') -TimeoutSeconds 20
            if ($d.ExitCode -eq 0) {
                $toolDir = Join-Path $d.Output.Trim() 'sprintforecast'
                foreach ($rel in @('Scripts\python.exe', 'bin/python')) {
                    $candidate = Join-Path $toolDir $rel
                    if (Test-Path -LiteralPath $candidate) { $script:Py = $candidate; break }
                }
            }
        }
    } else {
        $script:Context['uv'] = 'NICHT GEFUNDEN'
    }
    if ($PythonExe) { $script:Py = $PythonExe }
    $script:Context['Python der App'] = $(if ($script:Py) { $script:Py } else { 'nicht gefunden (Prüfungen mit Python werden übersprungen; -PythonExe angeben)' })

    if ($script:Sf) {
        $r = Invoke-Sf @('--version') 60
        $script:Context['sprintforecast'] = $(if ($r.ExitCode -eq 0) { $r.Output.Trim() } else { 'Fehler: ' + (Format-Native $r) })
        $script:Context['Befehl'] = $script:Sf
    } else {
        $script:Context['sprintforecast'] = 'NICHT GEFUNDEN (Befehl sprintforecast fehlt im PATH)'
    }
    $script:Context['Starter'] = $(if ($script:SfApp) { $script:SfApp } else { 'sprintforecast-app nicht gefunden' })
    $script:Context['Aufruf'] = ('Nur={0}; HttpsUrl={1}; SshUrl={2}; Wartezeit={3} s; OhneRueckfragen={4}' -f (
            $(if ($Selected.Count) { $Selected -join ',' } else { 'alle' }),
            $(if ($HttpsUrl) { 'angegeben' } else { '-' }),
            $(if ($SshUrl) { 'angegeben' } else { '-' }),
            $WartezeitSekunden, [bool]$OhneRueckfragen))
}

function Test-Administrator {
    try {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $principal = New-Object Security.Principal.WindowsPrincipal($identity)
        return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch {
        return $false
    }
}

function Get-LogTail {
    param([string]$Path, [int]$Lines = 40)
    if (-not (Test-Path -LiteralPath $Path)) { return ('(nicht vorhanden: ' + $Path + ')') }
    $item = Get-Item -LiteralPath $Path
    $content = @(Get-Content -LiteralPath $Path -Encoding UTF8 -Tail $Lines)
    return ('{0}  (geändert {1}, {2} Bytes)' -f $Path, $item.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'), $item.Length) + "`n" + ($content -join "`n")
}

function Get-ConfigDir {
    if ($script:OnWindows -and $env:APPDATA) { return (Join-Path $env:APPDATA 'sprintforecast') }
    $base = if ($env:XDG_CONFIG_HOME) { $env:XDG_CONFIG_HOME } else { Join-Path $env:HOME '.config' }
    return (Join-Path $base 'sprintforecast')
}

# ------------------------------------------------------------------------------------------
# Prüfung 1: App starten und beenden
# ------------------------------------------------------------------------------------------

function Test-AppEnde {
    param($Section)
    if (-not $script:OnWindows) {
        Complete-Section $Section 'ÜBERSPRUNGEN' 'Nur unter Windows (Prozessliste über Win32_Process).'
        return
    }
    $launcher = $script:SfApp
    $launchArgs = @()
    if (-not $launcher -and $script:Sf) {
        $launcher = $script:Sf
        $launchArgs = @('web', '--app')
    }
    if (-not $launcher) {
        Complete-Section $Section 'ÜBERSPRUNGEN' 'Weder sprintforecast-app noch sprintforecast im PATH.'
        return
    }

    # Läuft die App schon, wären die Ergebnisse nicht zuzuordnen.
    $baseline = @(Get-SfProcess)
    $attempt = 0
    while ($baseline.Count -gt 0 -and $attempt -lt 3) {
        Add-Block $Section 'Schon vor dem Start laufende Prozesse' (Format-ProcessTable $baseline)
        if (-not (Test-Interactive)) {
            Complete-Section $Section 'ÜBERSPRUNGEN' 'sprintforecast läuft bereits; bitte alle Fenster schließen und neu starten.'
            return
        }
        Write-Line 'sprintforecast läuft bereits. Bitte alle App-Fenster schließen.' 'Yellow'
        [void](Read-Host 'Danach Enter drücken (Strg+C bricht ab)')
        $baseline = @(Get-SfProcess)
        $attempt++
    }
    if ($baseline.Count -gt 0) {
        Complete-Section $Section 'ÜBERSPRUNGEN' 'sprintforecast lief weiter; Prüfung nicht aussagekräftig.'
        return
    }

    Save-ProcessEnv @('SPRINTFORECAST_DATA', 'SPRINTFORECAST_AUTOUPDATE')
    $dataNote = 'Datenordner der App: ihr gemerkter Ordner (kein Python gefunden, keine Testdaten).'
    if ($script:Py) {
        $teams = Initialize-DemoRepository (Join-Path (Get-TempRoot) 'app-daten')
        $env:SPRINTFORECAST_DATA = $teams
        $dataNote = 'Datenordner der App: temporäres Daten-Repository mit dem Team "demo" (SPRINTFORECAST_DATA nur für diesen Start).'
    }
    if (-not $MitAutoUpdate) { $env:SPRINTFORECAST_AUTOUPDATE = 'aus' }
    Add-Text $Section ('Start mit: `' + (Split-Path -Leaf $launcher) + ' ' + ($launchArgs -join ' ') + '`. ' + $dataNote + $(if (-not $MitAutoUpdate) { ' Selbstaktualisierung nur für diesen Start aus.' } else { '' }))

    $sp = @{ FilePath = $launcher; PassThru = $true }
    if ($launchArgs.Count -gt 0) { $sp['ArgumentList'] = $launchArgs; $sp['WindowStyle'] = 'Minimized' }
    $started = Start-Process @sp
    Write-Line ('Gestartet (PID {0}); warte auf Server und Fenster …' -f $started.Id)

    Add-Leftover ([pscustomobject]@{ Id = [int]$started.Id; Created = (Get-ProcessCreated -ProcessId $started.Id) })
    # Alles, was zur App gehört, sofort merken: Bricht jemand ab, räumt das Skript es auf.
    $serverUp = Wait-Until -TimeoutSeconds 90 -Condition {
        $now = @(Get-SfProcess)
        foreach ($p in $now) { Add-Leftover $p }
        @($now | Where-Object { $_.Kind -like 'Server*' }).Count -gt 0
    }
    # Chromium-Browser (Edge, Chrome, …) mit eigenem Profil; bei Firefox oder dem Standardbrowser
    # gibt es keinen solchen Prozess.
    $windowUp = $serverUp -and (Wait-Until -TimeoutSeconds 30 -Condition {
            $now = @(Get-SfProcess)
            foreach ($p in $now) { Add-Leftover $p }
            @($now | Where-Object { $_.Kind -like 'Browser*' }).Count -gt 0
        })
    Restore-ProcessEnv
    $running = @(Get-SfProcess)
    foreach ($p in $running) { Add-Leftover $p }
    if ($serverUp -and -not $windowUp) {
        Add-Text $Section 'Es wurde kein Browser mit eigenem Profil erkannt (Firefox, Standardbrowser oder ein Browser ohne Profilordner). Das Fenster muss von Hand geschlossen werden.'
    }
    Add-Block $Section 'Prozesse bei geöffnetem Fenster' (Format-ProcessTable $running)
    $log = Join-Path (Get-ConfigDir) 'app.log'

    if (-not $serverUp) {
        Add-Block $Section 'app.log' (Get-LogTail $log)
        Complete-Section $Section 'FEHLER' 'Der Server war nach 90 s nicht da (siehe app.log).'
        return
    }

    # Erreichbarkeit des Servers
    $server = @($running | Where-Object { $_.Kind -like 'Server*' } | Select-Object -First 1)
    if ($server.Count -gt 0 -and $server[0].CommandLine -match '--server\.port\s+(\d+)') {
        $port = $Matches[1]
        try {
            $reply = Invoke-WebRequest -Uri ('http://localhost:{0}/_stcore/health' -f $port) -UseBasicParsing -TimeoutSec 10
            Add-Text $Section ('Server auf Port {0} antwortet: `{1}`.' -f $port, ([string]$reply.Content).Trim())
        } catch {
            Add-Text $Section ('Server auf Port {0} antwortet nicht: {1}' -f $port, $_.Exception.Message)
        }
    }
    # Das Fenster muss länger als 5 s offen gewesen sein (cli._HANDOFF_SECONDS), sonst deutet der
    # Starter das Schließen als Übergabe an eine laufende Instanz.
    Start-Sleep -Seconds 8

    # Fenster schließen wie mit dem Schließen-Knopf (WM_CLOSE). „Geschlossen“ heißt: Das Fenster
    # ist weg (Prozess beendet oder kein Fensterhandle mehr). Bleiben Browserprozesse zurück, ist
    # das gerade das, was die Prüfung danach misst.
    $windowClosed = $false
    $closedBy = ''
    $browserMain = @(Get-SfProcess | Where-Object {
            $_.Kind -like 'Browser*' -and $_.CommandLine -match '--app=' -and $_.CommandLine -notmatch '--type='
        } | Select-Object -First 1)
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    if ($browserMain.Count -gt 0) {
        $mainId = [int]$browserMain[0].Id
        $proc = Get-Process -Id $mainId -ErrorAction SilentlyContinue
        if ($proc -and $proc.MainWindowHandle -ne 0) {
            [void]$proc.CloseMainWindow()
            $windowClosed = Wait-Until -TimeoutSeconds 15 -Condition {
                $current = Get-Process -Id $mainId -ErrorAction SilentlyContinue
                (-not $current) -or ($current.MainWindowHandle -eq 0)
            }
            if ($windowClosed) { $closedBy = 'Skript' }
        }
    }
    if (-not $windowClosed -and (Test-Interactive)) {
        if ($browserMain.Count -eq 0) {
            Write-Line 'Es wurde kein Fenster mit eigenem Browserprofil erkannt (Firefox oder Standardbrowser?).' 'Yellow'
        } else {
            Write-Line 'Das Fenster ließ sich nicht automatisch schließen.' 'Yellow'
        }
        Write-Line 'Bitte das App-Fenster jetzt mit dem Schließen-Knopf (X) schließen.' 'Yellow'
        [void](Read-Host 'Danach Enter drücken')
        $watch.Restart()
        $windowClosed = $true
        $closedBy = 'Hand'
    }
    if (-not $windowClosed) {
        Complete-Section $Section 'HINWEIS' 'Das Fenster ließ sich ohne Rückfragen nicht schließen; das Ende der App wurde nicht geprüft.'
        return
    }
    Add-Text $Section $(if ($closedBy -eq 'Skript') { 'Das Fenster wurde per Skript geschlossen (CloseMainWindow, wie der Schließen-Knopf).' } else { 'Das Fenster wurde von Hand geschlossen.' })

    # Warten und beobachten, wann welcher Prozess endet. Gezählt wird alles, was zur App gehört,
    # auch später Gestartetes (z. B. eine Aktualisierung mit uv); vorher lief nichts.
    $seen = @{}
    foreach ($p in $running) { $seen[$p.Id] = $p }
    $endedAfter = @{}
    $now = @()
    $atDeadline = $null
    $extra = 40
    while ($true) {
        $now = @(Get-SfProcess)
        $nowIds = @($now | ForEach-Object { $_.Id })
        foreach ($p in $now) { if (-not $seen.ContainsKey($p.Id)) { $seen[$p.Id] = $p } }
        foreach ($id in @($seen.Keys)) {
            if (-not $endedAfter.ContainsKey($id) -and ($nowIds -notcontains $id)) {
                $endedAfter[$id] = [math]::Round($watch.Elapsed.TotalSeconds, 1)
            }
        }
        if ($null -eq $atDeadline -and $watch.Elapsed.TotalSeconds -ge $WartezeitSekunden) { $atDeadline = $now }
        if ($now.Count -eq 0) { break }
        # Nach der Wartezeit nur noch beobachten (höchstens 40 s), wann die Nachzügler enden.
        if ($watch.Elapsed.TotalSeconds -ge ($WartezeitSekunden + $extra)) { break }
        Start-Sleep -Seconds 1
    }
    if ($null -eq $atDeadline) { $atDeadline = @() }
    $atDeadline = @($atDeadline)

    $timeline = @()
    foreach ($p in ($seen.Values | Sort-Object -Property Id)) {
        $when = 'LÄUFT NOCH'
        if ($endedAfter.ContainsKey($p.Id)) {
            $secs = $endedAfter[$p.Id]
            $when = $(if ($secs -le $WartezeitSekunden) { 'beendet nach ' + $secs + ' s' } else { 'erst nach ' + $secs + ' s beendet (später als die Wartezeit)' })
        }
        $timeline += ('{0,6}  {1,-22} {2,-22} {3}' -f $p.Id, $p.Name, $p.Kind, $when)
    }
    Add-Block $Section ('Ende der Prozesse (Wartezeit {0} s)' -f $WartezeitSekunden) ($timeline -join "`n")
    Add-Block $Section 'app.log (dieser Start)' (Get-LogTail $log 60)
    Add-Block $Section 'update.log (letzte Zeilen)' (Get-LogTail (Join-Path (Get-ConfigDir) 'update.log') 30)

    if ($atDeadline.Count -eq 0) {
        Complete-Section $Section 'OK' ('Alle {0} Prozesse waren {1} s nach dem Schließen beendet.' -f $seen.Count, $WartezeitSekunden)
    } else {
        $names = ($atDeadline | ForEach-Object { '{0} ({1})' -f $_.Name, $_.Kind }) -join ', '
        Complete-Section $Section 'FEHLER' ('{0} Prozess(e) liefen {1} s nach dem Schließen noch: {2}' -f $atDeadline.Count, $WartezeitSekunden, $names)
    }
}

# ------------------------------------------------------------------------------------------
# Prüfung 2: uv tool
# ------------------------------------------------------------------------------------------

function Test-UvTool {
    param($Section)
    if (-not $script:Uv) {
        Complete-Section $Section 'ÜBERSPRUNGEN' 'uv nicht gefunden.'
        return
    }
    $list = Invoke-Native -FilePath $script:Uv -Arguments @('tool', 'list') -TimeoutSeconds 60
    Add-Block $Section 'uv tool list' (Format-Native $list)
    $paths = Invoke-Native -FilePath $script:Uv -Arguments @('tool', 'list', '--show-paths') -TimeoutSeconds 60
    if ($paths.ExitCode -eq 0) { Add-Block $Section 'uv tool list --show-paths' (Format-Native $paths) }

    $installed = ''
    $match = [regex]::Match($list.Output, '(?m)^sprintforecast\s+v?(\S+)')
    if ($match.Success) { $installed = $match.Groups[1].Value }
    if (-not $installed) {
        Complete-Section $Section 'HINWEIS' 'sprintforecast ist nicht als uv-Tool installiert (Selbstaktualisierung wirkt dann nicht).'
        return
    }

    if (-not (Test-Interactive)) {
        Complete-Section $Section 'OK' ('uv-Tool sprintforecast v{0} installiert; Aktualisierung nicht ausgeführt.' -f $installed)
        return
    }
    $answer = Read-Host 'uv tool upgrade --reinstall sprintforecast jetzt ausführen (so aktualisiert die App)? Sie muss geschlossen sein. [j/N]'
    if (([string]$answer).Trim().ToLowerInvariant() -notin @('j', 'ja', 'y', 'yes')) {
        Complete-Section $Section 'OK' ('uv-Tool sprintforecast v{0} installiert; Aktualisierung auf Wunsch nicht ausgeführt.' -f $installed)
        return
    }
    if ($script:OnWindows) {
        $busy = @(Get-SfProcess)
        if ($busy.Count -gt 0) {
            Add-Block $Section 'Laufende Prozesse' (Format-ProcessTable $busy)
            Complete-Section $Section 'HINWEIS' 'Aktualisierung nicht ausgeführt: sprintforecast läuft noch (Windows sperrt die Dateien).'
            return
        }
    }
    $up = Invoke-Native -FilePath $script:Uv -Arguments @('tool', 'upgrade', '--reinstall', 'sprintforecast') -TimeoutSeconds 600
    Add-Block $Section 'uv tool upgrade --reinstall sprintforecast' (Format-Native $up)
    $after = Invoke-Native -FilePath $script:Uv -Arguments @('tool', 'list') -TimeoutSeconds 60
    Add-Block $Section 'uv tool list (danach)' (Format-Native $after)
    Add-Block $Section 'update.log (letzte Zeilen)' (Get-LogTail (Join-Path (Get-ConfigDir) 'update.log') 30)
    if ($up.ExitCode -eq 0) {
        Complete-Section $Section 'OK' 'uv tool upgrade --reinstall lief ohne Fehler.'
    } else {
        Complete-Section $Section 'FEHLER' ('uv tool upgrade --reinstall endete mit Exitcode {0} (bei "os error 32" hielt noch ein Prozess Dateien offen).' -f $up.ExitCode)
    }
}

# ------------------------------------------------------------------------------------------
# Prüfung 3: Anmeldung
# ------------------------------------------------------------------------------------------

function Read-RemoteUrl {
    param([string]$Given, [string]$Prompt, [string]$Kind)
    $url = $Given
    if (-not $url -and (Test-Interactive)) { $url = ([string](Read-Host $Prompt)).Trim() }
    if (-not $url) { return '' }
    if ($url -match '^https?://[^/@\s]+@') {
        Write-Line 'Die Adresse enthält Zugangsdaten und wird nicht verwendet (Token gehören nicht in die Adresse).' 'Yellow'
        return ''
    }
    if ($Kind -eq 'https' -and $url -notmatch '^https?://') {
        Write-Line 'Das ist keine https-Adresse und wird für diesen Test übersprungen.' 'Yellow'
        return ''
    }
    if ($Kind -eq 'ssh' -and $url -notmatch '^(ssh://|[^/\s:@]+@[^/\s:]+:)') {
        Write-Line 'Das ist keine SSH-Adresse (z. B. git@github.com:Organisation/Repository.git) und wird übersprungen.' 'Yellow'
        return ''
    }
    return $url
}

function Test-Anmeldung {
    param($Section)
    if (-not $script:Git) {
        Complete-Section $Section 'ÜBERSPRUNGEN' 'git nicht gefunden.'
        return
    }
    $helpers = Invoke-Git -Directory '' -Arguments @('config', '--show-origin', '--get-regexp', '^credential\.') -TimeoutSeconds 30
    Add-Block $Section 'git config --show-origin (credential.*)' $(if ($helpers.ExitCode -eq 0) { $helpers.Output } else { '(nichts gesetzt, Exitcode ' + $helpers.ExitCode + ')' })
    $helperSet = ($helpers.ExitCode -eq 0 -and $helpers.Output -match 'credential\.([^\s=]*\.)?helper')
    $gcm = Invoke-Git -Directory '' -Arguments @('credential-manager', '--version') -TimeoutSeconds 30
    Add-Block $Section 'git credential-manager --version' (Format-Native $gcm)

    if ($script:Gh) {
        $gh = Invoke-Native -FilePath $script:Gh -Arguments @('auth', 'status') -TimeoutSeconds 30
        Add-Block $Section 'gh auth status' (Format-Native $gh)
    } else {
        Add-Text $Section '`gh` (GitHub CLI) ist nicht installiert.'
    }
    $ssh = Find-Tool 'ssh'
    if ($ssh) {
        $v = Invoke-Native -FilePath $ssh -Arguments @('-V') -TimeoutSeconds 15
        Add-Block $Section 'ssh -V' (Format-Native $v)
        $agent = Find-Tool 'ssh-add'
        if ($agent) {
            $keys = Invoke-Native -FilePath $agent -Arguments @('-l') -TimeoutSeconds 15
            Add-Block $Section 'ssh-add -l (Schlüssel im Agenten)' (Format-Native $keys)
        }
    } else {
        Add-Text $Section '`ssh` ist nicht installiert.'
    }

    $https = Read-RemoteUrl $HttpsUrl 'https-Adresse Ihres Daten-Repositorys (Enter = überspringen)' 'https'
    $sshUrl = Read-RemoteUrl $SshUrl 'SSH-Adresse Ihres Daten-Repositorys (Enter = überspringen)' 'ssh'
    $failed = @()
    $passed = @()
    foreach ($entry in @(@('https', $https), @('SSH', $sshUrl))) {
        $label = $entry[0]
        $url = $entry[1]
        if (-not $url) { continue }
        $r = Invoke-Git -Directory '' -Arguments @('ls-remote', '--symref', '--', $url, 'HEAD') -TimeoutSeconds 90
        Add-Block $Section ('git ls-remote ({0}) {1}' -f $label, $url) (Format-Native $r)
        if ($r.TimedOut -and $label -eq 'SSH') {
            Add-Text $Section 'Zeitüberschreitung bei SSH: Vermutlich wartete SSH auf eine Eingabe, die dieses Skript nicht stellen kann (Passwortsatz des Schlüssels, Bestätigung des Servers beim ersten Verbinden). Einmal von Hand `ssh -T <benutzer>@<server>` ausführen und bestätigen, dann das Skript wiederholen.'
        }
        if ($r.ExitCode -eq 0) { $passed += $label } else { $failed += $label }
    }
    $summary = if ($failed.Count -gt 0) {
        'git ls-remote scheiterte für: ' + ($failed -join ', ') + '.'
    } elseif ($passed.Count -gt 0) {
        'git ls-remote gelang für: ' + ($passed -join ', ') + '.'
    } else {
        'Keine Adresse geprüft; nur die Einrichtung wurde angezeigt.'
    }
    $summary += $(if ($helperSet) { ' credential.helper ist gesetzt.' } else { ' credential.helper ist NICHT gesetzt.' })
    if ($failed.Count -gt 0) { Complete-Section $Section 'FEHLER' $summary }
    elseif ($passed.Count -eq 0 -or -not $helperSet) { Complete-Section $Section 'HINWEIS' $summary }
    else { Complete-Section $Section 'OK' $summary }
}

# ------------------------------------------------------------------------------------------
# Prüfung 4: Zeilenenden
# ------------------------------------------------------------------------------------------

function Test-Zeilenenden {
    param($Section)
    if (-not $script:Git -or -not $script:Py -or -not $script:Sf) {
        Complete-Section $Section 'ÜBERSPRUNGEN' 'git, sprintforecast oder das Python der Installation fehlt.'
        return
    }
    $base = Join-Path (Get-TempRoot) 'zeilenenden'
    $origin = Join-Path $base 'daten'
    $teams = Initialize-DemoRepository $origin
    $sprints = Invoke-Sf @('--data', $teams, '--as-of', '2026-03-02', 'sprints', 'demo', '--create') 120
    Add-Block $Section 'sprintforecast sprints demo --anlegen' (Format-Native $sprints)
    $identity = @{
        GIT_AUTHOR_NAME = 'sprintforecast Windows-Test'; GIT_AUTHOR_EMAIL = 'test@example.invalid'
        GIT_COMMITTER_NAME = 'sprintforecast Windows-Test'; GIT_COMMITTER_EMAIL = 'test@example.invalid'
    }
    [void](Invoke-Git -Directory $origin -Arguments @('add', '-A'))
    $commit = Invoke-Git -Directory $origin -Arguments @('-c', 'commit.gpgsign=false', 'commit', '-q', '--no-verify', '-m', 'Testdaten') -Environment $identity
    Add-Block $Section 'git commit im Daten-Repository' (Format-Native $commit)
    if ($commit.ExitCode -ne 0) {
        Complete-Section $Section 'FEHLER' 'Das Testrepository konnte nicht committet werden.'
        return
    }

    $ownConfig = Invoke-Git -Directory '' -Arguments @('config', '--show-origin', '--get-all', 'core.autocrlf')
    $ownEol = Invoke-Git -Directory '' -Arguments @('config', '--show-origin', '--get-all', 'core.eol')
    Add-Block $Section 'Ihre Einstellung: core.autocrlf' $(if ($ownConfig.ExitCode -eq 0) { $ownConfig.Output } else { '(nicht gesetzt)' })
    Add-Block $Section 'Ihre Einstellung: core.eol' $(if ($ownEol.ExitCode -eq 0) { $ownEol.Output } else { '(nicht gesetzt)' })

    $variants = @(
        @{ Name = 'Ihre Einstellung'; Args = @(); Dir = 'klon-eigene' },
        @{ Name = 'core.autocrlf=true'; Args = @('-c', 'core.autocrlf=true'); Dir = 'klon-crlf' },
        @{ Name = 'core.autocrlf=false'; Args = @('-c', 'core.autocrlf=false'); Dir = 'klon-lf' }
    )
    $problems = @()
    foreach ($v in $variants) {
        $clone = Join-Path $base $v.Dir
        $name = $v.Name
        # "-c" hinter "clone" speichert die Einstellung im Klon (davor gälte sie nur für den Klonvorgang).
        $r = Invoke-Git -Directory '' -Arguments (@('clone', '-q') + @($v.Args) + @('--', $origin, $clone)) -Environment $identity
        if ($r.ExitCode -ne 0) {
            Add-Block $Section ('Klonen ({0})' -f $name) (Format-Native $r)
            $problems += ('{0}: Klonen scheiterte' -f $name)
            continue
        }
        $cloneTeams = Join-Path $clone 'teams'
        $teamFile = Join-Path (Join-Path $cloneTeams 'demo') 'team.yaml'
        $bytes = [IO.File]::ReadAllBytes($teamFile)
        $crlf = 0
        for ($i = 1; $i -lt $bytes.Length; $i++) { if ($bytes[$i] -eq 10 -and $bytes[$i - 1] -eq 13) { $crlf++ } }

        $status1 = Invoke-Git -Directory $clone -Arguments @('status', '--porcelain')
        $diff1 = Invoke-Git -Directory $clone -Arguments @('diff', '--exit-code', '--stat')
        $check = Invoke-Sf @('--data', $cloneTeams, 'check') 120
        $resave = Invoke-Python -Code $script:CodeResave -Arguments @($cloneTeams, 'demo')
        $status2 = Invoke-Git -Directory $clone -Arguments @('status', '--porcelain')
        $diff2 = Invoke-Git -Directory $clone -Arguments @('diff', '--exit-code', '--stat')
        $eol = Invoke-Git -Directory $clone -Arguments @('ls-files', '--eol')

        $lines = @()
        $lines += ('team.yaml im Arbeitsordner: {0} Zeilen mit CRLF' -f $crlf)
        $lines += ('Nach dem Klonen: git status --porcelain: {0}; git diff Exitcode {1}' -f $(if ($status1.Output.Trim()) { 'NICHT LEER' } else { 'leer' }), $diff1.ExitCode)
        $lines += ('sprintforecast check: Exitcode {0}' -f $check.ExitCode)
        $lines += ('Erneut speichern: Exitcode {0}' -f $resave.ExitCode)
        $lines += ('Danach: git status --porcelain: {0}; git diff Exitcode {1}' -f $(if ($status2.Output.Trim()) { 'NICHT LEER' } else { 'leer' }), $diff2.ExitCode)
        $lines += ''
        $lines += 'git ls-files --eol:'
        $lines += $eol.Output.TrimEnd()
        if ($status1.Output.Trim()) { $lines += ''; $lines += 'git status (nach dem Klonen):'; $lines += $status1.Output.TrimEnd() }
        if ($status2.Output.Trim()) { $lines += ''; $lines += 'git status (nach erneutem Speichern):'; $lines += $status2.Output.TrimEnd() }
        if ($diff2.Output.Trim()) { $lines += ''; $lines += 'git diff (nach erneutem Speichern):'; $lines += $diff2.Output.TrimEnd() }
        if ($check.ExitCode -ne 0) { $lines += ''; $lines += 'pruefen:'; $lines += (Format-Native $check) }
        if ($resave.ExitCode -ne 0) { $lines += ''; $lines += 'Speichern:'; $lines += (Format-Native $resave) }
        Add-Block $Section ('Klon mit {0}' -f $name) ($lines -join "`n")

        if ($status1.Output.Trim() -or $diff1.ExitCode -ne 0) { $problems += ('{0}: Änderungen direkt nach dem Klonen' -f $name) }
        if ($check.ExitCode -ne 0) { $problems += ('{0}: pruefen meldet Fehler' -f $name) }
        if ($resave.ExitCode -ne 0) { $problems += ('{0}: Speichern scheitert' -f $name) }
        if ($status2.Output.Trim() -or $diff2.ExitCode -ne 0) { $problems += ('{0}: Änderungen nach erneutem Speichern' -f $name) }
    }
    if ($problems.Count -eq 0) {
        Complete-Section $Section 'OK' 'Alle Klone sind sauber (git diff leer, pruefen und erneutes Speichern ohne Änderung).'
    } else {
        Complete-Section $Section 'FEHLER' ($problems -join '; ')
    }
}

# ------------------------------------------------------------------------------------------
# Prüfung 5: gesperrte Datei
# ------------------------------------------------------------------------------------------

function Test-Sperre {
    param($Section)
    if (-not $script:Py) {
        Complete-Section $Section 'ÜBERSPRUNGEN' 'Python der Installation nicht gefunden.'
        return
    }
    if (-not $script:OnWindows) {
        Add-Text $Section 'Hinweis: Auf Nicht-Windows-Systemen sperrt .NET nur beratend; das Ergebnis ist hier nicht aussagekräftig.'
    }
    $teams = Initialize-DemoRepository (Join-Path (Get-TempRoot) 'sperre')
    $file = Join-Path (Join-Path $teams 'demo') 'team.yaml'
    $before = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash
    $worst = 'OK'
    $notes = @()
    foreach ($mode in @('None', 'Read')) {
        $stream = [IO.File]::Open($file, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]$mode)
        $script:Locks.Add($stream)
        try {
            $r = Invoke-Python -Code $script:CodeLockedSave -Arguments @($teams, 'demo')
        } finally {
            $stream.Dispose()
            [void]$script:Locks.Remove($stream)
        }
        $after = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash
        $leftovers = @(Get-ChildItem -LiteralPath (Split-Path -Parent $file) -Filter '*.tmp' -ErrorAction SilentlyContinue)
        $outcome = $null
        $json = ($r.Output.Trim() -split "`n" | Select-Object -Last 1)
        try { $outcome = $json | ConvertFrom-Json } catch { $outcome = $null }
        $lines = @()
        $lines += ('Sperre FileShare.{0}: ' -f $mode)
        if ($null -eq $outcome) {
            $lines += ('Unerwartete Ausgabe: ' + (Format-Native $r))
            $verdict = 'FEHLER'
        } elseif ($outcome.ok) {
            $lines += 'Speichern gelang trotz Sperre (Windows ließ das Ersetzen zu).'
            $verdict = 'OK'
        } else {
            $lines += ('Speichern scheiterte mit {0}: {1}' -f $outcome.type, $outcome.message)
            $verdict = 'FEHLER'  # unerwartete Art von Fehler
            if ($outcome.type -in @('PermissionError', 'OSError')) { $verdict = 'HINWEIS' }
            if ($outcome.type -in @('DataError', 'ConflictError', 'GitError')) { $verdict = 'OK' }
        }
        $lines += ('Datei unverändert: {0}' -f $(if ($before -eq $after -or ($null -ne $outcome -and $outcome.ok)) { 'ja' } else { 'NEIN' }))
        $lines += ('Zwischendateien (*.tmp) übrig: {0}' -f $leftovers.Count)
        Add-Block $Section ('Speichern bei Sperre FileShare.{0}' -f $mode) ($lines -join "`n")
        if ($null -ne $outcome -and -not $outcome.ok -and $before -ne $after) { $verdict = 'FEHLER' }
        if ($leftovers.Count -gt 0) { $verdict = 'FEHLER' }
        if ($verdict -eq 'FEHLER') { $worst = 'FEHLER' }
        elseif ($verdict -eq 'HINWEIS' -and $worst -ne 'FEHLER') { $worst = 'HINWEIS' }
        if ($null -ne $outcome -and -not $outcome.ok) { $notes += ('{0}: {1}' -f $mode, $outcome.type) }
        $before = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash
    }
    switch ($worst) {
        'OK' { Complete-Section $Section 'OK' 'Gesperrte Datei: keine Datenverluste, keine Zwischendateien.' }
        'HINWEIS' { Complete-Section $Section 'HINWEIS' ('Daten bleiben heil, aber das Speichern endet mit einem rohen Systemfehler (' + ($notes -join ', ') + '); die Oberfläche zeigt dann vermutlich eine Fehlerseite statt einer Meldung.') }
        default { Complete-Section $Section 'FEHLER' 'Gesperrte Datei: Daten verändert oder Zwischendateien übrig (siehe Details).' }
    }
}

# ------------------------------------------------------------------------------------------
# Prüfung 6: Symlink-Recht
# ------------------------------------------------------------------------------------------

function New-SymbolicLinkProbe {
    # Legt eine symbolische Verknüpfung an. Windows PowerShell 5.1 verlangt für New-Item auch im
    # Entwicklermodus Administratorrechte; "mklink" (cmd) nicht. Darum zuerst mklink, dann New-Item.
    param([string]$Link, [string]$Target)
    $messages = @()
    if ($script:OnWindows -and $env:ComSpec) {
        $r = Invoke-Native -FilePath $env:ComSpec -Arguments @('/c', 'mklink', $Link, $Target) -TimeoutSeconds 30
        if ($r.ExitCode -eq 0 -and (Test-Path -LiteralPath $Link)) {
            return [pscustomobject]@{ Ok = $true; Method = 'mklink'; Message = '' }
        }
        $messages += ('mklink: ' + (Format-Native $r))
    }
    try {
        [void](New-Item -ItemType SymbolicLink -Path $Link -Target $Target -ErrorAction Stop)
        return [pscustomobject]@{ Ok = $true; Method = 'New-Item'; Message = '' }
    } catch {
        $messages += ('New-Item: ' + $_.Exception.Message)
    }
    return [pscustomobject]@{ Ok = $false; Method = ''; Message = ($messages -join "`n") }
}

function Test-Symlink {
    param($Section)
    $dir = Join-Path (Get-TempRoot) 'symlink'
    [void][IO.Directory]::CreateDirectory($dir)
    $target = Join-Path $dir 'ziel.txt'
    $link = Join-Path $dir 'verweis.txt'
    [IO.File]::WriteAllText($target, 'x')
    $admin = if ($script:OnWindows) { Test-Administrator } else { 'n/a' }
    $developerMode = 'unbekannt'
    if ($script:OnWindows) {
        try {
            $key = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock'
            $value = (Get-ItemProperty -Path $key -Name AllowDevelopmentWithoutDevLicense -ErrorAction Stop).AllowDevelopmentWithoutDevLicense
            $developerMode = $(if ($value -eq 1) { 'an' } else { 'aus' })
        } catch {
            $developerMode = 'nicht gesetzt'
        }
    }
    Add-Text $Section ('Administrator: {0}; Entwicklermodus: {1}' -f $admin, $developerMode)
    $probe = New-SymbolicLinkProbe -Link $link -Target $target
    if ($probe.Ok) {
        $isLink = $false
        try { $isLink = ((Get-Item -LiteralPath $link -Force).LinkType -eq 'SymbolicLink') } catch { $isLink = $false }
        if ($isLink) {
            Complete-Section $Section 'OK' ('Symbolische Verknüpfungen dürfen angelegt werden ({0}); der Symlink-Test der Entwicklung läuft.' -f $probe.Method)
        } else {
            Complete-Section $Section 'HINWEIS' 'Verknüpfung angelegt, aber nicht als SymbolicLink erkannt.'
        }
    } else {
        Add-Block $Section 'Fehlermeldungen' $probe.Message
        Complete-Section $Section 'HINWEIS' 'Kein Recht für symbolische Verknüpfungen (normal ohne Administrator/Entwicklermodus). Die App braucht es nicht; nur ein Test der Entwicklung wird dann übersprungen bzw. scheitert.'
    }
}

# ------------------------------------------------------------------------------------------
# Prüfung 7: Interaktiv
# ------------------------------------------------------------------------------------------

function Test-Interaktiv {
    param($Section)
    if (-not (Test-Interactive)) {
        Complete-Section $Section 'ÜBERSPRUNGEN' 'Ohne Rückfragen gestartet.'
        return
    }
    $items = @(
        @{
            Id = 'netz'; Title = 'Netz getrennt'
            Do = 'Trennen Sie das Netzwerk (WLAN aus oder Flugmodus). Öffnen Sie die App mit Ihrem echten Daten-Repository (Starter oder Verknüpfung) und lösen Sie dort Abgleichen bzw. Hochladen aus. Schließen Sie die App danach und verbinden Sie das Netz wieder, bevor Sie hier weitermachen.'
            Ask = 'Erscheint eine verständliche Meldung (keine Fehlerseite, kein Traceback), und lässt sich die App danach weiter bedienen?'
        },
        @{
            Id = 'branch'; Title = 'Geschützter Branch'
            Do = 'Besser in einem Test-Repository: Speichern Sie in der App eine kleine Änderung in einem Repository mit geschütztem Branch (z. B. main) und laden Sie sie hoch. In einem echten Repository bleibt die Änderung als Commit zurück.'
            Ask = 'Nennt die Meldung den Grund (Branch geschützt oder keine Schreibrechte) und den nächsten Schritt, und bleibt Ihre lokale Änderung erhalten?'
        },
        @{ Id = 'start'; Title = 'Optik: Startseite'; Do = 'Öffnen Sie die Startseite.'; Ask = 'Drei Aufgaben-Kacheln, jede führt zur passenden Seite, Text gut lesbar?' },
        @{ Id = 'leiste'; Title = 'Optik: Schrittleiste'; Do = 'Öffnen Sie nacheinander Fehltage, PO-Vorplanung, Planning und Review.'; Ask = 'Vier gleich hohe Schritte (bei Teams ohne Produkte drei), aktiver Schritt klar erkennbar, Erledigt-Haken verständlich, kein Umbruch im schmalen Fenster?' },
        @{ Id = 'tabellen'; Title = 'Optik: Tabellen und Kennzahlen'; Do = 'Sehen Sie sich Forecast, Planning und Produkte an.'; Ask = 'Keine "None"-Zellen (statt dessen "–"), Kennzahlen und Kapazität nicht abgeschnitten?' },
        @{ Id = 'maske'; Title = 'Optik: Server-Maske'; Do = 'Öffnen Sie die Seite Datenordner und die Maske für die Server-Adresse.'; Ask = 'Knöpfe nebeneinander, Meldungen bei falscher Adresse verständlich?' },
        @{ Id = 'konflikt'; Title = 'Optik: Konfliktseite'; Do = 'Falls ein Konflikt vorliegt oder erzeugt wurde: öffnen Sie "Konflikte lösen".'; Ask = 'Ist verständlich, was passiert ist und was Sie tun können?' },
        @{ Id = 'whatif'; Title = 'Optik: Was-wäre-wenn und Historie'; Do = 'Öffnen Sie Was-wäre-wenn und die Prognosen-Historie.'; Ask = 'Übersichtlich und verständlich?' },
        @{ Id = 'kalender'; Title = 'Optik: Kalendertexte und Rechenweg'; Do = 'Öffnen Sie den Sprintkalender und den Rechenweg der Kapazität.'; Ask = 'Texte nach Arbeitswoche verständlich, Rechenweg nachvollziehbar?' },
        @{ Id = 'englisch'; Title = 'Optik: englische Oberfläche'; Do = 'Stellen Sie die Sprache in der Seitenleiste (Sprache / Language) auf Englisch und sehen Sie sich die Seiten an. Danach wieder auf Deutsch stellen: Die Wahl bleibt in den Einstellungen gespeichert.'; Ask = 'Alles übersetzt, keine deutschen Reste, Layout nicht gebrochen?' }
    )
    $worst = 'OK'
    $answered = 0
    $rows = @()
    foreach ($item in $items) {
        Write-Line ''
        Write-Line ('-- {0} --' -f $item.Title) 'Cyan'
        Write-Line $item.Do
        $a = Read-Answer $item.Ask
        $rows += ('| {0} | {1} | {2} |' -f $item.Title, $a.Status, (Protect-Text $a.Note).Replace('|', '\|'))
        if ($a.Status -ne 'ÜBERSPRUNGEN') { $answered++ }
        if ($a.Status -eq 'FEHLER') { $worst = 'FEHLER' }
    }
    $Section.Lines.Add('| Frage | Antwort | Notiz |')
    $Section.Lines.Add('|---|---|---|')
    foreach ($row in $rows) { $Section.Lines.Add($row) }
    $Section.Lines.Add('')
    if ($answered -eq 0) { Complete-Section $Section 'ÜBERSPRUNGEN' 'Keine Frage beantwortet.' }
    elseif ($worst -eq 'FEHLER') { Complete-Section $Section 'FEHLER' 'Mindestens eine Antwort war Nein (siehe Tabelle).' }
    else { Complete-Section $Section 'OK' ('{0} von {1} Fragen mit Ja beantwortet.' -f $answered, $items.Count) }
}

# ------------------------------------------------------------------------------------------
# Aufräumen
# ------------------------------------------------------------------------------------------

function Clear-TestData {
    foreach ($stream in $script:Locks.ToArray()) {
        try { $stream.Dispose() } catch { Write-Verbose 'Sperre schon freigegeben.' }
    }
    $script:Locks.Clear()
    if ($script:OnWindows) {
        foreach ($id in @($script:Leftover.Keys)) {
            $created = Get-ProcessCreated -ProcessId $id
            if ($created -and $created -eq $script:Leftover[$id]) {
                Write-Line ('Beende übrig gebliebenen Prozess {0}.' -f $id) 'Yellow'
                Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
            }
        }
    }
    Restore-ProcessEnv
    if ($script:TempRoot -and (Test-Path -LiteralPath $script:TempRoot)) {
        for ($try = 1; $try -le 5; $try++) {
            try {
                Remove-Item -LiteralPath $script:TempRoot -Recurse -Force -ErrorAction Stop
                break
            } catch {
                Start-Sleep -Milliseconds (500 * $try)
            }
        }
        if (Test-Path -LiteralPath $script:TempRoot) {
            Write-Line ('Temp-Ordner konnte nicht gelöscht werden: {0}' -f $script:TempRoot) 'Yellow'
        }
    }
}

# ------------------------------------------------------------------------------------------
# Ablauf
# ------------------------------------------------------------------------------------------

# Zum Testen einzelner Funktionen: ". .\scripts\windows-tests.ps1" lädt nur die Funktionen.
if ($MyInvocation.InvocationName -eq '.') { return }

function Resolve-ReportPath {
    # Vollständiger Pfad (ein relativer gilt zum aktuellen Ordner von PowerShell, nicht des
    # Prozesses) und eine Schreibprobe vorab: Ein Fehler soll vor den Prüfungen auffallen, nicht
    # erst danach den Bericht kosten. Ist der Ort nicht beschreibbar, dient der Temp-Ordner.
    param([string]$Path)
    $here = (Get-Location).ProviderPath
    if (-not $Path) { $Path = 'sprintforecast-windows-bericht-{0}.md' -f (Get-Date -Format 'yyyyMMdd-HHmm') }
    if (-not [IO.Path]::IsPathRooted($Path)) { $Path = Join-Path $here $Path }
    $Path = [IO.Path]::GetFullPath($Path)
    try {
        [IO.File]::WriteAllText($Path, '')
        return $Path
    } catch {
        $fallback = Join-Path ([IO.Path]::GetTempPath()) ([IO.Path]::GetFileName($Path))
        Write-Line ('Der Bericht kann nicht nach {0} geschrieben werden ({1}); er landet in {2}.' -f $Path, $_.Exception.Message, $fallback) 'Yellow'
        return $fallback
    }
}

$Bericht = Resolve-ReportPath -Path $Bericht

try {
    Write-Line 'sprintforecast – Windows-Prüfung' 'Cyan'
    Write-Line 'Testdaten liegen in einem Temp-Ordner und werden am Ende gelöscht.'
    Initialize-Context
    foreach ($key in $script:Context.Keys) { Write-Line ('{0,-16} {1}' -f $key, (Protect-Text ([string]$script:Context[$key]))) }

    Invoke-Check 'App' '1. App starten und beenden' { param($s) Test-AppEnde $s }
    Invoke-Check 'Uv' '2. Installation (uv tool)' { param($s) Test-UvTool $s }
    Invoke-Check 'Anmeldung' '3. Anmeldung (Git)' { param($s) Test-Anmeldung $s }
    Invoke-Check 'Zeilenenden' '4. Zeilenenden' { param($s) Test-Zeilenenden $s }
    Invoke-Check 'Sperre' '5. Gesperrte Datei' { param($s) Test-Sperre $s }
    Invoke-Check 'Symlink' '6. Symlink-Recht' { param($s) Test-Symlink $s }
    Invoke-Check 'Interaktiv' '7. Interaktive Prüfungen' { param($s) Test-Interaktiv $s }

    if (Test-Interactive) {
        $script:Notes = ([string](Read-Host 'Weitere Notiz für den Bericht (Enter = keine)')).Trim()
    }
} finally {
    try { Clear-TestData } catch { Write-Line ('Aufräumen: ' + $_.Exception.Message) 'Yellow' }
    if ($script:Sections.Count -eq 0) {
        Remove-Item -LiteralPath $Bericht -ErrorAction SilentlyContinue  # nur die Schreibprobe lag da
    }
    if (-not $script:ReportWritten -and $script:Sections.Count -gt 0) {
        try {
            Write-Report -Path $Bericht
            Write-Line ''
            Write-Line 'Zusammenfassung' 'Cyan'
            foreach ($s in $script:Sections) { Write-Line ('{0,-34} {1}' -f $s.Title, $s.Status) $script:StatusColor[$s.Status] }
            Write-Line ''
            Write-Line ('Bericht: {0}' -f $Bericht) 'Green'
            Write-Line 'Bitte diese Datei zurückgeben (sie enthält keine Zugangsdaten; Profilordner sind ersetzt).'
        } catch {
            Write-Line ('Bericht konnte nicht geschrieben werden: ' + $_.Exception.Message) 'Red'
        }
    }
}
