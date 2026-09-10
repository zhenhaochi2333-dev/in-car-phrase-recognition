param([switch]$Direct)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    python -m venv --system-site-packages .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create virtual environment' }
}
if ($Direct) {
    & '.\.venv\Scripts\python.exe' scripts/install_dependencies.py --direct
} else {
    & '.\.venv\Scripts\python.exe' scripts/install_dependencies.py
}
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& '.\.venv\Scripts\python.exe' scripts/build_native.py
if ($LASTEXITCODE -ne 0) { throw 'C++ compilation failed' }
& '.\.venv\Scripts\python.exe' scripts/download_model.py
if ($LASTEXITCODE -ne 0) { throw 'Model download failed' }
Write-Output 'Setup complete. No application, microphone, synthesis, or playback was started.'
