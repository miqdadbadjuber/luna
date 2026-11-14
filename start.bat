@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Luna is not installed yet. Run install.ps1 first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m luna.start
rem Keep the window open on an error, so a double-click shows the message.
if errorlevel 1 pause
