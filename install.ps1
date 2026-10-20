# Installs foresprint (including the web UI and the extras excel and jira) on Windows.
#
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/swallat/foresprint/main/install.ps1 | iex"
#
# Running it again updates. The script asks for plugins and remembers the choice.
# Without prompting (set beforehand):
#   $env:FORESPRINT_WITH = "owner/repo; name @ git+https://…"   plugins ("" = none)
#   $env:FORESPRINT_REF = "…"                                      branch or tag instead of main
#   $env:FORESPRINT_NO_SHORTCUT = "1"                              do not create a launcher
#   $env:FORESPRINT_COMPLETION = "1"                               set up Tab completion
# The former names SPRINTFORECAST_WITH, _REF, _NO_SHORTCUT and _COMPLETION still work.
$ErrorActionPreference = "Stop"

# Old variable names: use them when the new one is not set.
foreach ($name in "WITH", "REF", "NO_SHORTCUT", "COMPLETION") {
    if (-not (Test-Path "Env:FORESPRINT_$name") -and (Test-Path "Env:SPRINTFORECAST_$name")) {
        Set-Item "Env:FORESPRINT_$name" (Get-Item "Env:SPRINTFORECAST_$name").Value
    }
}

$ref = if ($env:FORESPRINT_REF) { $env:FORESPRINT_REF } else { "main" }
$kind = if ($ref -match '^v\d') { "tags" } else { "heads" }
$core = "foresprint[web,excel,jira] @ https://github.com/swallat/foresprint/archive/refs/$kind/$ref.zip"
$pluginFile = Join-Path $env:APPDATA "foresprint\plugins.txt"
$legacyPluginFile = Join-Path $env:APPDATA "sprintforecast\plugins.txt"  # before the rename

function Expand-Plugin([string]$item) {
    # "owner/repo" -> git+https://github.com/owner/repo; everything else unchanged
    if ($item -match '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') { return "git+https://github.com/$item" }
    return $item
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "==> installing uv (https://docs.astral.sh/uv/)"
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$HOME\.local\bin;$env:Path"
}

$saved = if (Test-Path $pluginFile) { (Get-Content $pluginFile -Raw).Trim() } elseif (Test-Path $legacyPluginFile) { (Get-Content $legacyPluginFile -Raw).Trim() } else { "" }
if (Test-Path Env:FORESPRINT_WITH) {
    $plugins = $env:FORESPRINT_WITH
} elseif ([Environment]::UserInteractive -and -not [Console]::IsInputRedirected) {
    Write-Host ""
    Write-Host "Install plugins? Separate several with ';', e.g.:"
    Write-Host "  owner/repo   or   name @ git+https://…"
    $prompt = if ($saved) { "Plugins [Enter = keep: $saved | - = none]" } else { "Plugins [Enter = none]" }
    $answer = (Read-Host $prompt).Trim()
    $plugins = switch ($answer) { "" { $saved } "-" { "" } default { $answer } }
} else {
    $plugins = $saved
}

$items = @($plugins.Split(";") | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$arguments = @("tool", "install", "--force", "--reinstall", "--python", "3.14")
if ($items.Count -gt 0) {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Plugins from Git repositories require Git: winget install Git.Git"
    }
    Write-Host "==> with plugins: $($items -join '; ')"
    foreach ($item in $items) { $arguments += @("--with", (Expand-Plugin $item)) }
    # The core's source comes from the plugin ([tool.uv.sources]); otherwise "conflicting URLs".
    $arguments += "foresprint[web,excel,jira]"
} else {
    $arguments += $core
}

Write-Host "==> installing foresprint with the extras web, excel and jira (Python 3.14 is downloaded if needed)"
& uv @arguments
if ($LASTEXITCODE -ne 0) { throw "Installation failed (exit code $LASTEXITCODE)" }
# No stderr redirection: in Windows PowerShell 5.1 that would abort under "Stop".
try { & uv tool update-shell | Out-Null } catch { }
# The environment of the uv tool from before the rename is no longer needed (the commands
# sprintforecast and sprintforecast-app now belong to the new tool; "uv tool uninstall" would remove them).
$oldTool = Join-Path (& uv tool dir).Trim() "sprintforecast"
if (Test-Path (Join-Path $oldTool "uv-receipt.toml")) { Remove-Item -Recurse -Force $oldTool }

# Remember the choice for the next update
if ($items.Count -gt 0) {
    New-Item -ItemType Directory -Force -Path (Split-Path $pluginFile) | Out-Null
    Set-Content -Path $pluginFile -Value ($items -join "; ") -Encoding UTF8
} elseif (Test-Path $pluginFile) {
    Remove-Item $pluginFile
    if (Test-Path $legacyPluginFile) { Remove-Item $legacyPluginFile }
}

$bin = (& uv tool dir --bin).Trim()
# Double-click launcher (disable with $env:FORESPRINT_NO_SHORTCUT = "1")
if (-not $env:FORESPRINT_NO_SHORTCUT) {
    try { & (Join-Path $bin 'foresprint.exe') shortcut } catch { Write-Host "Note: launcher not created." }
}
# Tab completion in PowerShell (opt in with $env:FORESPRINT_COMPLETION = "1")
if ($env:FORESPRINT_COMPLETION) {
    try { & (Join-Path $bin 'foresprint.exe') --install-completion } catch { Write-Host "Note: Tab completion not set up." }
} else {
    Write-Host "Tab completion (optional): foresprint --install-completion"
}
# Git is optional for the installation, but needed to save, share and view the history of data
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Host "Note: Git was not found in the PATH. The app runs without it, but committing, sharing with"
    Write-Host "the team, the history and cloning the data repository need Git (no administrator rights"
    Write-Host "required; see the Git section in docs/installation.md)."
}
Write-Host ""
Write-Host "Done: foresprint $(& (Join-Path $bin 'foresprint.exe') --version)"
Write-Host "Start by double-clicking 'Foresprint' (desktop/Start menu) or, in a new PowerShell window, e.g.:"
Write-Host "  cd `"$HOME\sprint-daten`"; foresprint web"
