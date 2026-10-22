# Uninstalls Foresprint on Windows, including the installation under the old name
# "sprintforecast". Your data is never deleted.
#
#   powershell -ExecutionPolicy ByPass -c "& ([scriptblock]::Create((irm https://raw.githubusercontent.com/swallat/foresprint/main/uninstall.ps1))) -DryRun"
#
# Removed, under both names (foresprint and sprintforecast):
#   - the uv tool with its commands (foresprint.exe, foresprint-app.exe, sprintforecast.exe, ...)
#   - the shortcuts on the desktop and in the Start menu
#   - the cache folder with the browser profile of the app window
# Kept: the team data folder, the Jira token in the Credential Manager, Git credentials and the
# settings folders (%APPDATA%\foresprint and %APPDATA%\sprintforecast: data folder, plugin
# selection). A later installation finds the settings again.
#
# Parameters:
#   -DryRun          change nothing, only list
#   -Force           do not ask
#   -RemoveConfig    also remove the settings folders (data folder choice, plugin selection)
#
# Close the app first: Windows locks running programs. Running it again is harmless.
param(
    [switch]$DryRun,
    [switch]$Force,
    [switch]$RemoveConfig
)
$ErrorActionPreference = "Stop"

$names = "foresprint", "sprintforecast"
$apps = "Foresprint", "Sprint-Forecast"
$actions = New-Object System.Collections.Generic.List[object]
function Add-Action($kind, $path) { $actions.Add([pscustomobject]@{ Kind = $kind; Path = $path }) }

# 1. uv tool (removes its commands with it)
$localBin = Join-Path $HOME ".local\bin"
if (-not (Get-Command uv -ErrorAction SilentlyContinue) -and (Test-Path (Join-Path $localBin "uv.exe"))) {
    $env:Path = "$localBin;$env:Path"
}
if (Get-Command uv -ErrorAction SilentlyContinue) {
    # uv writes warnings to stderr; under "Stop" Windows PowerShell 5.1 would abort on them.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { $tools = (& uv tool list 2>&1 | ForEach-Object { "$_" }) -join "`n" } finally { $ErrorActionPreference = $previous }
    foreach ($name in $names) {
        if ($tools -match "(?m)^$name ") { Add-Action "tool" $name }
    }
} elseif ((Test-Path (Join-Path $localBin "sprintforecast.exe")) -or (Test-Path (Join-Path $localBin "foresprint.exe"))) {
    Write-Host "Warning: uv not found, so the commands in $localBin cannot be removed; install uv or run 'uv tool uninstall foresprint'."
}

# 1b. the program of install.ps1 
$programDir = if ($env:FORESPRINT_BIN) { $env:FORESPRINT_BIN } elseif ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA "Programs\foresprint" } else { $null }
if ($programDir -and (Test-Path -LiteralPath (Join-Path $programDir "foresprint.exe"))) {
    Add-Action "file" (Join-Path $programDir "foresprint.exe")
    if (Test-Path -LiteralPath (Join-Path $programDir "foresprint.exe.old")) { Add-Action "file" (Join-Path $programDir "foresprint.exe.old") }
}

# 2. shortcuts on the desktop and in the Start menu; only if they start one of our programs
$shell = New-Object -ComObject WScript.Shell
foreach ($folder in "Desktop", "Programs") {
    $base = [Environment]::GetFolderPath($folder)
    if (-not $base) { continue }
    foreach ($app in $apps) {
        $link = Join-Path $base "$app.lnk"
        if ((Test-Path -LiteralPath $link) -and $shell.CreateShortcut($link).TargetPath -match "(foresprint|sprintforecast)") {
            Add-Action "file" $link
        }
    }
}

# 3. cache: browser profile of the app window and the logo (recreated on demand)
if ($env:LOCALAPPDATA) {
    foreach ($name in $names) {
        $cache = Join-Path $env:LOCALAPPDATA $name
        if (Test-Path -LiteralPath $cache) { Add-Action "dir" $cache }
    }
}

# 4. settings: only on request
if ($RemoveConfig -and $env:APPDATA) {
    foreach ($name in $names) {
        $config = Join-Path $env:APPDATA $name
        if (Test-Path -LiteralPath $config) { Add-Action "dir" $config }
    }
}

if ($actions.Count -eq 0) {
    Write-Host "Nothing to remove: no installation of foresprint or sprintforecast found."
    return
}

Write-Host "Found:"
foreach ($a in $actions) {
    switch ($a.Kind) {
        "tool" { Write-Host "  uv tool        $($a.Path) (uv tool uninstall)" }
        "file" { Write-Host "  remove         $($a.Path)" }
        "dir" { Write-Host "  remove folder  $($a.Path)" }
    }
}
Write-Host "Kept: team data folder, Jira token in the Credential Manager, Git credentials."
if (-not $RemoveConfig) { Write-Host "Kept: settings folders (add -RemoveConfig to remove them)." }

if ($DryRun) {
    Write-Host "Dry run: nothing changed."
    return
}

if (-not $Force) {
    if ([Console]::IsInputRedirected) {
        throw "No terminal for the confirmation; use -Force or -DryRun."
    }
    $answer = Read-Host "Proceed? [y/N]"
    if ($answer -notmatch '^(y|yes|j|ja)$') { Write-Host "Cancelled."; return }
}

foreach ($a in $actions) {
    if ($a.Kind -eq "tool") {
        # uv reports on stderr; keep Windows PowerShell 5.1 from treating that as an error.
        $ErrorActionPreference = "Continue"
        try { & uv tool uninstall $a.Path 2>&1 | ForEach-Object { Write-Host "$_" } } finally { $ErrorActionPreference = "Stop" }
        if ($LASTEXITCODE -ne 0) { throw "uv tool uninstall failed (exit code $LASTEXITCODE); close the app and run again." }
        Write-Host "uv tool $($a.Path) removed"
    } else {
        Remove-Item -LiteralPath $a.Path -Recurse -Force
        Write-Host "removed $($a.Path)"
    }
}
Write-Host "Done."
