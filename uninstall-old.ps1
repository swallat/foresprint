# Removes the installation left over from the old name "sprintforecast" on Windows: the uv tool,
# the desktop and Start menu shortcuts and the browser profile cache. User data is never deleted.
#
#   powershell -ExecutionPolicy ByPass -c "& ([scriptblock]::Create((irm https://raw.githubusercontent.com/swallat/foresprint/main/uninstall-old.ps1))) -DryRun"
#
# Parameters:
#   -DryRun             change nothing, only list
#   -Force              do not ask
#   -RemoveOldConfig    also remove the old settings folder, but only after its files were copied
#                       to the new one (default: keep it)
#
# Never touched: the team data folder, the Jira token in the Credential Manager, Git
# credentials, the new foresprint installation. The settings (data folder, plugin selection)
# are copied from %APPDATA%\sprintforecast to %APPDATA%\foresprint unless the file exists there
# already. Running it again is harmless.
param(
    [switch]$DryRun,
    [switch]$Force,
    [switch]$RemoveOldConfig
)
$ErrorActionPreference = "Stop"

$old = "sprintforecast"
$oldApp = "Sprint-Forecast"
$new = "foresprint"
$actions = New-Object System.Collections.Generic.List[object]
function Add-Action($kind, $path) { $actions.Add([pscustomobject]@{ Kind = $kind; Path = $path }) }

# 1. uv tool (removes the commands sprintforecast.exe and sprintforecast-app.exe with it)
if (Get-Command uv -ErrorAction SilentlyContinue) {
    $tools = (& uv tool list 2>$null) -join "`n"
    if ($tools -match "(?m)^$old ") { Add-Action "tool" $old }
}

# 2. shortcuts on the desktop and in the Start menu
foreach ($folder in "Desktop", "Programs") {
    $link = Join-Path ([Environment]::GetFolderPath($folder)) "$oldApp.lnk"
    if (Test-Path -LiteralPath $link) { Add-Action "file" $link }
}

# 3. cache: browser profile of the app window and the logo (recreated on demand)
if ($env:LOCALAPPDATA) {
    $cache = Join-Path $env:LOCALAPPDATA $old
    if (Test-Path -LiteralPath $cache) { Add-Action "dir" $cache }
}

# 4. settings: copy to the new folder, remove the old one only on request
$oldConfig = if ($env:APPDATA) { Join-Path $env:APPDATA $old } else { $null }
$newConfig = if ($env:APPDATA) { Join-Path $env:APPDATA $new } else { $null }
if ($oldConfig -and (Test-Path -LiteralPath $oldConfig)) {
    foreach ($name in "settings.json", "plugins", "plugins.txt") {
        if ((Test-Path -LiteralPath (Join-Path $oldConfig $name)) -and
            -not (Test-Path -LiteralPath (Join-Path $newConfig $name))) {
            Add-Action "copy" (Join-Path $oldConfig $name)
        }
    }
    if ($RemoveOldConfig) { Add-Action "dir" $oldConfig }
}

if ($actions.Count -eq 0) {
    Write-Host "Nothing to remove: no installation under the old name '$old' found."
    return
}

Write-Host "Found under the old name '$old':"
foreach ($a in $actions) {
    switch ($a.Kind) {
        "tool" { Write-Host "  uv tool        $($a.Path) (uv tool uninstall)" }
        "file" { Write-Host "  remove         $($a.Path)" }
        "dir" { Write-Host "  remove folder  $($a.Path)" }
        "copy" { Write-Host "  copy settings  $($a.Path) -> $newConfig\" }
    }
}
Write-Host "Kept: team data folder, Jira token in the Credential Manager, Git credentials."
if (-not $RemoveOldConfig -and $oldConfig -and (Test-Path -LiteralPath $oldConfig)) {
    Write-Host "Kept: $oldConfig (add -RemoveOldConfig to remove it after copying)."
}

if ($DryRun) {
    Write-Host "Dry run: nothing changed."
    return
}

if (-not $Force) {
    if ([Console]::IsInputRedirected) {
        Write-Host "No terminal for the confirmation; use -Force or -DryRun."
        exit 1
    }
    $answer = Read-Host "Proceed? [y/N]"
    if ($answer -notmatch '^(y|yes|j|ja)$') { Write-Host "Cancelled."; return }
}

# Copy first so that a removal of the old folder never loses settings.
foreach ($a in $actions | Where-Object Kind -eq "copy") {
    New-Item -ItemType Directory -Force -Path $newConfig | Out-Null
    Copy-Item -LiteralPath $a.Path -Destination $newConfig
    Write-Host "copied $($a.Path) -> $newConfig\"
}
foreach ($a in $actions | Where-Object Kind -ne "copy") {
    switch ($a.Kind) {
        "tool" {
            & uv tool uninstall $a.Path
            if ($LASTEXITCODE -ne 0) { throw "uv tool uninstall failed (exit code $LASTEXITCODE)" }
            Write-Host "uv tool $($a.Path) removed"
        }
        default {
            Remove-Item -LiteralPath $a.Path -Recurse -Force
            Write-Host "removed $($a.Path)"
        }
    }
}
Write-Host "Done."
