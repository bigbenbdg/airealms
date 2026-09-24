@echo off
setlocal
cd /d "%~dp0"
title AI Realms Server

set "PYTHON=python"
if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON=%~dp0.venv\Scripts\python.exe"

echo Starting AI Realms server at http://localhost:8765
"%PYTHON%" -m uvicorn app.main:app --app-dir backend --reload --port 8765 %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo AI Realms server exited with error code %EXIT_CODE%.
  pause
)

exit /b %EXIT_CODE%
