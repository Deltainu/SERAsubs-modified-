@echo off
title SERAsubs
cd /d "%~dp0"

rem The only file a user needs to run. Checks that the runtime is present,
rem runs the first-time setup if needed, then starts the app from app\.

rem the runtime is not in the repository, so tell the two cases apart:
rem source checkout without a runtime, or a release that was extracted wrong
if not exist "python\python.exe" (
    echo.
    echo   SERAsubs can't find its python folder.
    echo.
    if exist "tools\make_release.py" (
        echo   This looks like the source code from GitHub, which doesn't
        echo   include the python runtime.
        echo.
        echo   Download SERAsubs-x.x.zip from the Releases page instead, or
        echo   run it yourself with your own python:  python app\serasubs.py
    ) else (
        echo   This usually means the zip wasn't extracted properly. Right click
        echo   it and use "Extract All", don't drag the files out of the window.
    )
    echo.
    pause
    exit /b 1
)

rem any argument re-runs the setup with those options, then starts as normal
if not "%~1"=="" goto setup

rem if the engine imports, setup has already been done
python\python.exe -c "import faster_whisper" >nul 2>&1
if not errorlevel 1 goto start

:setup
python\python.exe app\install.py %*
if errorlevel 1 (
    echo.
    echo   Setup didn't finish. The lines above say why.
    echo.
    pause
    exit /b 1
)

:start
python\python.exe app\serasubs.py
if errorlevel 1 pause
