$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    throw "未找到项目运行环境。请先执行：powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1"
}
$version = & $projectPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0 -or [version]$version.Trim() -lt [version]'3.11') {
    throw "项目运行环境需要 Python 3.11 或更新版本。请删除 .venv 后重新执行 scripts/setup.ps1。"
}
$env:PYTHONPATH = Join-Path $PSScriptRoot 'app'
& $projectPython -m phrase_lab
