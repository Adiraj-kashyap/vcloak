@echo off
REM run_vcloak.bat - start the V-cloak backend and open the web app in the browser.
REM
REM   run_vcloak.bat            demo: dev key, in-memory SQLite store, V-cloak/baseline switch
REM   run_vcloak.bat pg         same, but on the development PostgreSQL (scripts\pgdev.py up first)
REM
REM Dev mode uses the fixed public development key and listens on 127.0.0.1 only: a throw-away demo,
REM never real data. The CUDA kernels run on the remote runner (ai\GPU_RUNNER.md); locally the
REM numpy backend serves the same semantics, so no timing shown here is a performance result.

setlocal
cd /d "%~dp0"

set "PORT=8000"
set "PY=.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo [setup] No .venv found - running setup\bootstrap.ps1 once...
    powershell -NoProfile -ExecutionPolicy Bypass -File "setup\bootstrap.ps1"
    if not exist "%PY%" (
        echo [error] setup did not create .venv. See START_HERE.md.
        pause
        exit /b 1
    )
)

set "STORE=--store sqlite"
if /i "%~1"=="pg" (
    echo [db] Starting the development PostgreSQL...
    "%PY%" scripts\pgdev.py up
    if errorlevel 1 (
        echo [error] could not start PostgreSQL. Run without "pg" for the SQLite demo.
        pause
        exit /b 1
    )
    set "STORE=--store pg"
)

echo [dashboard] Regenerating web\data\dashboard.json from the metrics index...
"%PY%" tasks.py dashboard
if errorlevel 1 echo [warn] dashboard export failed - the page will show the last committed data.

echo.
echo  V-cloak is starting on http://127.0.0.1:%PORT%/app/
echo  Close this window or press Ctrl+C to stop.
echo.

REM open the browser a few seconds after the server starts
start "" /b powershell -NoProfile -Command "Start-Sleep -Seconds 4; Start-Process 'http://127.0.0.1:%PORT%/app/'"

"%PY%" -m vcloak.cli serve --dev --compare --sessions --window-s 5 %STORE% --port %PORT%

echo.
echo V-cloak stopped.
pause
endlocal
