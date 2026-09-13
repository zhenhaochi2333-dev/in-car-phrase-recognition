param(
    [switch]$Direct,
    [string]$Python
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

function Get-PythonVersion([string]$Path) {
    try {
        $value = & $Path -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
        if ($LASTEXITCODE -ne 0) { return $null }
        return [version]$value.Trim()
    } catch {
        return $null
    }
}

$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $venvPython) {
    $venvVersion = Get-PythonVersion $venvPython
    if ($null -eq $venvVersion -or $venvVersion -lt [version]'3.11') {
        throw "现有 .venv 使用的 Python 版本不兼容（需要 Python 3.11 或更新版本）。请删除项目目录中的 .venv 后重试。"
    }
} else {
    if ([string]::IsNullOrWhiteSpace($Python)) {
        $candidate = Get-Command python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -eq $candidate) {
            throw "未找到 Python。请安装 Python 3.11+，或用 -Python 指定解释器路径。"
        }
        $Python = $candidate.Source
    }
    if (-not (Test-Path -LiteralPath $Python)) {
        throw "找不到指定的 Python：$Python"
    }
    $version = Get-PythonVersion $Python
    if ($null -eq $version -or $version -lt [version]'3.11') {
        throw "项目依赖需要 Python 3.11 或更新版本；当前解释器版本不兼容。可使用：.\scripts\setup.ps1 -Python 'C:\路径\python.exe'"
    }
    & $Python -m venv --system-site-packages .venv
    if ($LASTEXITCODE -ne 0) { throw '无法创建项目虚拟环境' }
}
if ($Direct) {
    & $venvPython scripts/install_dependencies.py --direct
} else {
    & $venvPython scripts/install_dependencies.py
}
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败' }
& $venvPython scripts/build_native.py
if ($LASTEXITCODE -ne 0) { throw 'C++ 编译失败' }
& $venvPython scripts/download_model.py
if ($LASTEXITCODE -ne 0) { throw '模型下载失败' }
Write-Output '初始化完成。未启动应用、麦克风、语音合成或扬声器。'
