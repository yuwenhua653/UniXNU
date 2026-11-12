@echo off
setlocal
cd /d "%~dp0"
set "MYRON_PY=python"
where py >nul 2>nul
if not errorlevel 1 set "MYRON_PY=py -3"
%MYRON_PY% "%~dp0merge_parts.py"
pause
