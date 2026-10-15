# Installiert sprintforecast (inkl. Weboberfläche) unter Windows.
#
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/swallat/sprint-forecast/main/install.ps1 | iex"
#
# Erneut ausführen = aktualisieren. Optional (vorher setzen):
#   $env:SPRINTFORECAST_WITH = "name @ git+https://…"  zusätzliche Pakete (Plugins), mehrere mit
#                                                      ";" getrennt; das Plugin muss die Quelle des
#                                                      Kerns in [tool.uv.sources] festlegen (braucht Git)
#   $env:SPRINTFORECAST_REF = "…"                      Branch oder Tag statt main
$ErrorActionPreference = "Stop"

$ref = if ($env:SPRINTFORECAST_REF) { $env:SPRINTFORECAST_REF } else { "main" }
$kind = if ($ref -match '^v\d') { "tags" } else { "heads" }
$core = "sprintforecast[web] @ https://github.com/swallat/sprint-forecast/archive/refs/$kind/$ref.zip"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "==> uv wird installiert (https://docs.astral.sh/uv/)"
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$HOME\.local\bin;$env:Path"
}

$arguments = @("tool", "install", "--force", "--reinstall", "--python", "3.15")
if ($env:SPRINTFORECAST_WITH) {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Für Plugins aus Git-Repositories wird Git benötigt: winget install Git.Git"
    }
    Write-Host "==> mit Plugins: $env:SPRINTFORECAST_WITH"
    # Die Quelle des Kerns kommt aus dem Plugin ([tool.uv.sources]) – sonst „conflicting URLs“.
    $arguments += "sprintforecast[web]"
    foreach ($spec in $env:SPRINTFORECAST_WITH.Split(";")) {
        if ($spec.Trim()) { $arguments += @("--with", $spec.Trim()) }
    }
} else {
    $arguments += $core
}

Write-Host "==> sprintforecast wird installiert (Python 3.15 wird bei Bedarf geladen)"
& uv @arguments
if ($LASTEXITCODE -ne 0) { throw "Installation fehlgeschlagen (Exit-Code $LASTEXITCODE)" }
# Kein Umleiten von stderr: in Windows PowerShell 5.1 würde das mit "Stop" zum Abbruch führen.
try { & uv tool update-shell | Out-Null } catch { }

$bin = (& uv tool dir --bin).Trim()
Write-Host ""
Write-Host "Fertig: sprintforecast $(& (Join-Path $bin 'sprintforecast.exe') --version)"
Write-Host "Neues PowerShell-Fenster öffnen, dann z. B.:"
Write-Host "  cd `"$HOME\sprint-daten`"; sprintforecast web --app"
