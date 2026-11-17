# Builds the Windows app and installer:
#   dist\Audio Assembler\                 the app folder (also usable without installing)
#   dist\AudioAssembler-<ver>-Setup.exe   the installer
# Usage (from the project folder):  powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1 [-SkipTests]
param([switch]$SkipTests)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Python environment missing. Run: python -m venv .venv; .venv\Scripts\pip install -e .[gui,dev] pyinstaller" }

$version = & $py -c "import audio_assembler; print(audio_assembler.__version__)"
Write-Host "Building Audio Assembler $version"

if (-not (Test-Path "vendor\ffmpeg\ffmpeg.exe")) { & $py packaging\get_ffmpeg.py; if ($LASTEXITCODE) { throw "ffmpeg download failed" } }

if (-not $SkipTests) {
    & $py -m pytest -q
    if ($LASTEXITCODE) { throw "Tests failed - not building." }
}

& $py -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging\audio_assembler.spec
if ($LASTEXITCODE) { throw "PyInstaller failed" }

$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 not found. Install it with: winget install JRSoftware.InnoSetup" }
& $iscc /Q "/DAppVersion=$version" packaging\installer.iss
if ($LASTEXITCODE) { throw "Inno Setup failed" }

Get-Item "dist\AudioAssembler-$version-Setup.exe" | Select-Object Name, @{n="MB"; e={[math]::Round($_.Length / 1MB, 1)}}
