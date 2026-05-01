#requires -Version 5.1
<#
.SYNOPSIS
    Build a portable Windows --onedir bundle of Auryn with PyInstaller.

.DESCRIPTION
    Manual local build script. Runs PyInstaller against
    packaging/windows/Auryn.spec and leaves the result in dist/Auryn/.

    This script must be invoked from an MSYS2 MINGW64 shell (or a
    PowerShell where the MSYS2 MINGW64 bin dir is first on PATH).
    A plain pip-on-Windows environment will not produce a working bundle:
    GTK3 / PyGObject need the MSYS2 GTK runtime to be present at build
    time so the spec can copy it into the bundle.

    No installer is produced. No CI is involved. No code signing.

.PARAMETER MingwPrefix
    Path to the MSYS2 MINGW64 root. Defaults to C:\msys64\mingw64.
    Forwarded to the spec via the AURYN_MINGW_PREFIX env var.

.PARAMETER Clean
    Delete build/ and dist/ before building.

.EXAMPLE
    # From the MSYS2 MINGW64 shell (or equivalent):
    pwsh -File packaging/windows/build.ps1 -Clean
#>
[CmdletBinding()]
param(
    [string]$MingwPrefix = "C:\msys64\mingw64",
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

# Resolve repo root from this script's location.
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Resolve-Path (Join-Path $ScriptDir "..\..")
$SpecFile  = Join-Path $ScriptDir "Auryn.spec"

Write-Host "Auryn Windows packaging (manual --onedir build)" -ForegroundColor Cyan
Write-Host "  repo root   : $RepoRoot"
Write-Host "  spec file   : $SpecFile"
Write-Host "  MINGW64     : $MingwPrefix"
Write-Host ""

if (-not (Test-Path $MingwPrefix)) {
    throw "MSYS2 MINGW64 prefix not found at '$MingwPrefix'. Install MSYS2 and the mingw-w64-x86_64-gtk3 / -python / -python-gobject packages, or pass -MingwPrefix."
}

if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    throw "pyinstaller not found on PATH. Install it inside the MSYS2 MINGW64 shell: pacman -S mingw-w64-x86_64-python-pyinstaller (or pip install pyinstaller into the MINGW64 python)."
}

Push-Location $RepoRoot
try {
    if ($Clean) {
        Write-Host "Cleaning build/ and dist/ ..." -ForegroundColor Yellow
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $RepoRoot "build")
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $RepoRoot "dist")
    }

    # The spec reads this to locate the GTK runtime tree.
    $env:AURYN_MINGW_PREFIX = $MingwPrefix

    Write-Host "Running PyInstaller ..." -ForegroundColor Cyan
    & pyinstaller --noconfirm --clean $SpecFile
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }

    $OutDir = Join-Path $RepoRoot "dist\Auryn"
    if (-not (Test-Path (Join-Path $OutDir "Auryn.exe"))) {
        throw "Build finished but Auryn.exe was not produced in $OutDir."
    }

    Write-Host ""
    Write-Host "Build succeeded." -ForegroundColor Green
    Write-Host "  output  : $OutDir"
    Write-Host "  launch  : $OutDir\Auryn.exe"
    Write-Host ""
    Write-Host "Reminder: this is an experimental, unsigned, manual build."
    Write-Host "Smoke-test it on a clean Windows VM before sharing."
}
finally {
    Pop-Location
}
