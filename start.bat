@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Luna is not installed yet. Run install.ps1 first.
  exit /b 1
)
".venv\Scripts\python.exe" -m luna.start
