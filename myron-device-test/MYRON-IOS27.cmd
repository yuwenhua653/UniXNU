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
echo Myron iOS27 - exact run 43165530177
echo.
echo 1. Verify original ZIP and extract package
echo 2. Recovery: check current GPT and back up Android boot [READ ONLY]
echo 3. Recovery: install unixnu root and verify every chunk [WRITES UNIXNU]
echo 4. Bootloader fastboot: flash startup probe and reboot [WRITES BOOT]
echo 5. Bootloader fastboot: restore saved Android boot and reboot
echo 6. Verify extracted package [READ ONLY]
echo Q. Quit
echo.
echo Read README-CN.txt first. Keep state folder and original Android backup.
choice /C 123456Q /N /M "Select: "
if errorlevel 7 exit /b 0
if errorlevel 6 (call :run verify & goto menu)
if errorlevel 5 (call :run restore & goto menu)
if errorlevel 4 (call :run start & goto menu)
if errorlevel 3 (call :run install & goto menu)
if errorlevel 2 (call :run prepare & goto menu)
if errorlevel 1 (call :run unpack & goto menu)
goto menu
:run
%MYRON_PY% "%~dp0myron_device_test.py" %1
if errorlevel 1 echo STOPPED. Read the error and keep state. Do not skip checks.
pause
exit /b
:python_error
echo Install Python 3.11 or newer and enable PATH, then reopen this file.
pause
exit /b 1
