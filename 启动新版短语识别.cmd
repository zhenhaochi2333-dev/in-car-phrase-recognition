@echo off
setlocal
set "ROOT=%~dp0"
if not exist "%ROOT%.venv\Scripts\pythonw.exe" (
  echo Project runtime was not found.
  echo Run scripts\setup.ps1 first, then double-click this file again.
  pause
  exit /b 1
)
set "PYTHONPATH=%ROOT%app"
"%ROOT%.venv\Scripts\python.exe" -c "import sys; sys.exit(sys.version_info < (3, 11))"
if errorlevel 1 (
  echo Python 3.11 or newer is required. Run scripts\setup.ps1 with a compatible Python.
  pause
  exit /b 1
)
start "" /D "%ROOT%" "%ROOT%.venv\Scripts\pythonw.exe" -m phrase_lab
