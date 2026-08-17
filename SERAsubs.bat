@echo off
title SERAsubs-modified-
cd /d "%~dp0"

rem The only file a user needs to run. Checks that the runtime is present,
rem runs the first-time setup if needed, then starts the app from app\.

rem the runtime is not in the repository, so tell the two cases apart:
rem source checkout without a runtime, or a release that was extracted wrong
if not exist "python\python.exe" (
    echo.
    echo   SERAsubs-modified- can't find its python folder.
    echo.
    if exist "tools\make_release.py" (
        echo   This looks like the source code from GitHub, which doesn't
        echo   include the python runtime.
        echo.
        echo   Download SERAsubs-modified-x.x.zip from the Releases page instead, or
        echo   run it yourself with your own python:  python app\serasubs.py
    ) else (
        echo   This usually means the zip wasn't extracted properly. Right click
        echo   it and use "Extract All", don't drag the files out of the window.
    )
    echo.
    pause
    exit /b 1
)

rem the app runs under a copy of the runtime named after itself, so the task
rem manager shows SERAsubs rather than a python nobody can place. make_launcher
rem writes the copy and names it, and falls back to a plain copy on its own
set "RUNTIME=python\SERAsubs-modified-.exe"
if not exist "%RUNTIME%" python\python.exe app\make_launcher.py
if not exist "%RUNTIME%" set "RUNTIME=python\python.exe"

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
rem tells the app it may hide this console once its own window is up. started
rem by hand from someone's own terminal, it leaves that terminal alone
set "SERASUBS_LAUNCHER=1"
"%RUNTIME%" app\serasubs.py
if errorlevel 1 pause
