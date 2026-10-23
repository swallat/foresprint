# Installs foresprint (command line and window in one program) on Windows.
#
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/swallat/foresprint/main/install.ps1 | iex"
#
# Running it again updates. The program also updates itself (foresprint update).
#   $env:FORESPRINT_VERSION = "1.0.0"      install this version instead of the newest one
#   $env:FORESPRINT_BIN = "C:\tools"       folder for the program (default: %LOCALAPPDATA%\Programs\foresprint)
#   $env:FORESPRINT_NO_SHORTCUT = "1"      do not create a launcher
#   $env:FORESPRINT_DOWNLOAD_BASE = "URL"  other place for the release files (tests, mirrors)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$repo = "swallat/foresprint"
$bin = if ($env:FORESPRINT_BIN) { $env:FORESPRINT_BIN } else { Join-Path $env:LOCALAPPDATA "Programs\foresprint" }

$arch = switch ($env:PROCESSOR_ARCHITECTURE) {
    "AMD64" { "amd64" }
    default { throw "unsupported processor $($env:PROCESSOR_ARCHITECTURE)" }
}

$version = $env:FORESPRINT_VERSION
if (-not $version) {
    $latest = Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest"
    $version = $latest.tag_name
}
$version = $version.TrimStart("v")
$name = "foresprint_${version}_windows_${arch}.zip"
$root = if ($env:FORESPRINT_DOWNLOAD_BASE) { $env:FORESPRINT_DOWNLOAD_BASE } else { "https://github.com/$repo/releases/download" }
$base = "$root/v$version"

$tmp = Join-Path ([IO.Path]::GetTempPath()) ("foresprint-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
    Write-Host "==> downloading foresprint $version (windows/$arch)"
    Invoke-WebRequest "$base/$name" -OutFile (Join-Path $tmp $name)
    Invoke-WebRequest "$base/checksums.txt" -OutFile (Join-Path $tmp "checksums.txt")

    $line = Get-Content (Join-Path $tmp "checksums.txt") | Where-Object { $_ -match "\s$([regex]::Escape($name))$" } | Select-Object -First 1
    if (-not $line) { throw "checksums.txt has no sum for $name" }
    $want = ($line -split "\s+")[0]
    $have = (Get-FileHash (Join-Path $tmp $name) -Algorithm SHA256).Hash
    if ($have -ne $want) { throw "checksum of $name does not match; not installing" }

    Expand-Archive (Join-Path $tmp $name) -DestinationPath $tmp -Force
    New-Item -ItemType Directory -Path $bin -Force | Out-Null
    $exe = Join-Path $bin "foresprint.exe"
    if (Test-Path $exe) {
        # A running program cannot be overwritten, but it can be renamed (the update does the same).
        Move-Item $exe "$exe.old" -Force
    }
    Move-Item (Join-Path $tmp "foresprint.exe") $exe -Force
    Remove-Item "$exe.old" -Force -ErrorAction SilentlyContinue
    Write-Host "==> installed $exe"
} finally {
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (($userPath -split ";") -notcontains $bin) {
    [Environment]::SetEnvironmentVariable("Path", "$userPath;$bin", "User")
    $env:Path = "$env:Path;$bin"
    Write-Host "==> added $bin to your PATH (open a new terminal)"
}

if (-not $env:FORESPRINT_NO_SHORTCUT) {
    # A failing launcher must not make the installation look failed: the program is in place.
    # Policies (AppLocker, antivirus) can refuse to start a freshly written, unsigned program.
    try {
        & $exe shortcut
        if ($LASTEXITCODE -ne 0) { throw "foresprint shortcut exited with code $LASTEXITCODE" }
    } catch {
        Write-Warning "could not create the launcher with the program: $($_.Exception.Message)"
        # Fall back to plain Windows shortcuts that only point at the program (it is not started).
        try {
            $shell = New-Object -ComObject WScript.Shell
            foreach ($dir in @([Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs"))) {
                $link = $shell.CreateShortcut((Join-Path $dir "Foresprint.lnk"))
                $link.TargetPath = $exe
                $link.WorkingDirectory = $env:USERPROFILE
                $link.IconLocation = "$exe,0"
                $link.Description = "Foresprint"
                $link.Save()
            }
            Write-Host "==> created the launcher on the desktop and in the Start menu"
            Write-Host "Run 'foresprint shortcut' later to replace it with the regular launcher."
        } catch {
            Write-Warning "could not create the launcher: $($_.Exception.Message)"
            Write-Host "The program is installed. Create the launcher later with: foresprint shortcut"
            Write-Host "If Windows or your antivirus blocks the program, allow $exe and run that command again."
        }
    }
}

Write-Host "Done. Start with the launcher or: foresprint"
Write-Host "The program is not signed. If Windows SmartScreen warns on the first start, choose"
Write-Host "'More info' and then 'Run anyway' (docs/installation.md)."
