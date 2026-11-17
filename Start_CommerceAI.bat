@echo off
setlocal EnableExtensions
title CommerceAI
pushd "%~dp0"
if errorlevel 1 goto :folder_error

where py.exe >nul 2>nul
if errorlevel 1 goto :python_fallback
py -3 -c "import sys; raise SystemExit(sys.version_info < (3, 10))" >nul 2>nul
if errorlevel 1 goto :python_fallback
py -3 run.py --open
if errorlevel 1 goto :start_error
goto :done

:python_fallback
python -c "import sys; raise SystemExit(sys.version_info < (3, 10))" >nul 2>nul
if errorlevel 1 (
    echo Install Python 3.10 or newer with the Windows Python launcher or add Python to PATH.
    goto :start_error
)
python run.py --open
if errorlevel 1 goto :start_error
goto :done

:start_error
echo Check the error above. See README.md for setup and another port.
pause
popd
exit /b 1

:done
popd
exit /b 0

:folder_error
echo Could not open the launcher folder. Extract the complete project first.
pause
exit /b 1
