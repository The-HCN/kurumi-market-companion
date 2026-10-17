@echo off
cd /d "%~dp0"
where pythonw.exe >nul 2>&1
if not errorlevel 1 (
    start "" pythonw.exe "%~dp0app.py"
    exit /b
)
python app.py
if errorlevel 1 pause
