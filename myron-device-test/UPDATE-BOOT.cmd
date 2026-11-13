@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set "MYRON_PY=python"
where py >nul 2>nul
if not errorlevel 1 set "MYRON_PY=py -3"
%MYRON_PY% -c "import sys; assert sys.version_info >= (3,11), 'Python 3.11+ required'"
if errorlevel 1 goto python_error
:menu
cls
echo Myron iOS27 Linux/Clang 18 boot comparison - run 43361559288
echo.
echo 1. Verify update, existing Android backup and install receipt [READ ONLY]
echo 2. Bootloader fastboot: update current boot and reboot [WRITES BOOT]
echo 3. Bootloader fastboot: restore saved Android boot and reboot
echo Q. Quit
echo.
echo Keep this menu beside the original package and state directories.
echo Read START-IOS27-LINUX-README-CN.txt. Do not reinstall unixnu for this update.
choice /C 123Q /N /M "Select: "
if errorlevel 4 exit /b 0
if errorlevel 3 (call :run restore & goto menu)
if errorlevel 2 (call :run start & goto menu)
if errorlevel 1 (call :run check & goto menu)
goto menu
:run
%MYRON_PY% "%~dp0boot-update-43361559288\myron_boot_update.py" %1
if errorlevel 1 echo STOPPED. Keep state and read the error. Do not skip checks.
pause
exit /b
:python_error
echo Install Python 3.11 or newer and enable PATH.
pause
exit /b 1
