# Installs sprintforecast (including the web UI) on Windows.
#
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/swallat/sprint-forecast/main/install.ps1 | iex"
#
# Running it again updates. The script asks for plugins and remembers the choice.
# Without prompting (set beforehand):
#   $env:SPRINTFORECAST_WITH = "owner/repo; name @ git+https://…"   plugins ("" = none)
#   $env:SPRINTFORECAST_REF = "…"                                      branch or tag instead of main
#   $env:SPRINTFORECAST_NO_SHORTCUT = "1"                              do not create a launcher
$ErrorActionPreference = "Stop"

$ref = if ($env:SPRINTFORECAST_REF) { $env:SPRINTFORECAST_REF } else { "main" }
$kind = if ($ref -match '^v\d') { "tags" } else { "heads" }
$core = "sprintforecast[web] @ https://github.com/swallat/sprint-forecast/archive/refs/$kind/$ref.zip"
$pluginFile = Join-Path $env:APPDATA "sprintforecast\plugins.txt"

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

$saved = if (Test-Path $pluginFile) { (Get-Content $pluginFile -Raw).Trim() } else { "" }
if (Test-Path Env:SPRINTFORECAST_WITH) {
    $plugins = $env:SPRINTFORECAST_WITH
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
    $arguments += "sprintforecast[web]"
} else {
    $arguments += $core
}

Write-Host "==> installing sprintforecast (Python 3.14 is downloaded if needed)"
& uv @arguments
if ($LASTEXITCODE -ne 0) { throw "Installation failed (exit code $LASTEXITCODE)" }
# No stderr redirection: in Windows PowerShell 5.1 that would abort under "Stop".
try { & uv tool update-shell | Out-Null } catch { }

# Remember the choice for the next update
if ($items.Count -gt 0) {
    New-Item -ItemType Directory -Force -Path (Split-Path $pluginFile) | Out-Null
    Set-Content -Path $pluginFile -Value ($items -join "; ") -Encoding UTF8
} elseif (Test-Path $pluginFile) {
    Remove-Item $pluginFile
}

$bin = (& uv tool dir --bin).Trim()
# Double-click launcher (disable with $env:SPRINTFORECAST_NO_SHORTCUT = "1")
if (-not $env:SPRINTFORECAST_NO_SHORTCUT) {
    try { & (Join-Path $bin 'sprintforecast.exe') shortcut } catch { Write-Host "Note: launcher not created." }
}
Write-Host ""
Write-Host "Done: sprintforecast $(& (Join-Path $bin 'sprintforecast.exe') --version)"
Write-Host "Start by double-clicking 'Sprint-Forecast' (desktop/Start menu) or, in a new PowerShell window, e.g.:"
Write-Host "  cd `"$HOME\sprint-daten`"; sprintforecast web"
