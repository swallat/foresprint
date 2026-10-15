# Installiert sprintforecast (inkl. Weboberfläche) unter Windows.
#
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/swallat/sprint-forecast/main/install.ps1 | iex"
#
# Erneut ausführen = aktualisieren. Das Skript fragt nach Plugins und merkt sich die Auswahl.
# Ohne Rückfrage (vorher setzen):
#   $env:SPRINTFORECAST_WITH = "besitzer/repo; name @ git+https://…"   Plugins ("" = keine)
#   $env:SPRINTFORECAST_REF = "…"                                      Branch oder Tag statt main
$ErrorActionPreference = "Stop"

$ref = if ($env:SPRINTFORECAST_REF) { $env:SPRINTFORECAST_REF } else { "main" }
$kind = if ($ref -match '^v\d') { "tags" } else { "heads" }
$core = "sprintforecast[web] @ https://github.com/swallat/sprint-forecast/archive/refs/$kind/$ref.zip"
$pluginFile = Join-Path $env:APPDATA "sprintforecast\plugins.txt"

function Expand-Plugin([string]$item) {
    # „besitzer/repo“ → git+https://github.com/besitzer/repo; alles andere unverändert
    if ($item -match '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') { return "git+https://github.com/$item" }
    return $item
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "==> uv wird installiert (https://docs.astral.sh/uv/)"
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$HOME\.local\bin;$env:Path"
}

$saved = if (Test-Path $pluginFile) { (Get-Content $pluginFile -Raw).Trim() } else { "" }
if (Test-Path Env:SPRINTFORECAST_WITH) {
    $plugins = $env:SPRINTFORECAST_WITH
} elseif ([Environment]::UserInteractive -and -not [Console]::IsInputRedirected) {
    Write-Host ""
    Write-Host "Plugins installieren? Mehrere mit ';' trennen, z. B.:"
    Write-Host "  besitzer/repo   oder   name @ git+https://…"
    $prompt = if ($saved) { "Plugins [Enter = beibehalten: $saved | - = keine]" } else { "Plugins [Enter = keine]" }
    $answer = (Read-Host $prompt).Trim()
    $plugins = switch ($answer) { "" { $saved } "-" { "" } default { $answer } }
} else {
    $plugins = $saved
}

$items = @($plugins.Split(";") | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$arguments = @("tool", "install", "--force", "--reinstall", "--python", "3.15")
if ($items.Count -gt 0) {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Für Plugins aus Git-Repositories wird Git benötigt: winget install Git.Git"
    }
    Write-Host "==> mit Plugins: $($items -join '; ')"
    foreach ($item in $items) { $arguments += @("--with", (Expand-Plugin $item)) }
    # Die Quelle des Kerns kommt aus dem Plugin ([tool.uv.sources]) – sonst „conflicting URLs“.
    $arguments += "sprintforecast[web]"
} else {
    $arguments += $core
}

Write-Host "==> sprintforecast wird installiert (Python 3.15 wird bei Bedarf geladen)"
& uv @arguments
if ($LASTEXITCODE -ne 0) { throw "Installation fehlgeschlagen (Exit-Code $LASTEXITCODE)" }
# Kein Umleiten von stderr: in Windows PowerShell 5.1 würde das mit "Stop" zum Abbruch führen.
try { & uv tool update-shell | Out-Null } catch { }

# Auswahl für das nächste Aktualisieren merken
if ($items.Count -gt 0) {
    New-Item -ItemType Directory -Force -Path (Split-Path $pluginFile) | Out-Null
    Set-Content -Path $pluginFile -Value ($items -join "; ") -Encoding UTF8
} elseif (Test-Path $pluginFile) {
    Remove-Item $pluginFile
}

$bin = (& uv tool dir --bin).Trim()
Write-Host ""
Write-Host "Fertig: sprintforecast $(& (Join-Path $bin 'sprintforecast.exe') --version)"
Write-Host "Neues PowerShell-Fenster öffnen, dann z. B.:"
Write-Host "  cd `"$HOME\sprint-daten`"; sprintforecast web --app"
