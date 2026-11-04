@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Luna is not installed yet. Run install.ps1 first.
  exit /b 1
)
if "%LUNA_PORT%"=="" set LUNA_PORT=8000
echo Opening http://localhost:%LUNA_PORT%. Add your API keys in Settings. Press Ctrl+C to stop.
start "" /b cmd /c "timeout /t 2 >nul & start http://localhost:%LUNA_PORT%"
".venv\Scripts\python.exe" -m uvicorn luna.app:app --host 127.0.0.1 --port "%LUNA_PORT%"
