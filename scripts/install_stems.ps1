$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$PackageSpec = "${RepoRoot}[stems]"

if (-not (Test-Path $Python)) {
    throw "Virtual environment not found. Create it with: py -3.12 -m venv .venv"
}

Write-Host "Installing optional Demucs stem-separation dependencies..."
& $Python -m pip install --upgrade pip
& $Python -m pip install -e $PackageSpec

Write-Host "Checking Demucs import..."
& $Python -c "import demucs; print('Demucs import succeeded')"

Write-Host ""
Write-Host "Stem support is installed. Enable it in this PowerShell session with:"
Write-Host '$env:LASTRADA_STEM_ENABLED = "1"'
Write-Host "Then launch the main Lastrada website with:"
Write-Host ".\.venv\Scripts\python.exe -m streamlit run app.py"
Write-Host ""
Write-Host "The first htdemucs_6s run downloads Demucs model weights."
