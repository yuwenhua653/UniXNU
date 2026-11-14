@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "%~dp0runtime\python.exe" (
  echo Missing runtime. Extract the complete ZIP first.
  pause
  exit /b 1
)
"%~dp0runtime\python.exe" -X utf8 "%~dp0app\fresh_boot.py" menu
if errorlevel 1 pause
