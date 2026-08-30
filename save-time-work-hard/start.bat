@echo off
rem ============================================================
rem  Save time, Work hard - shared server
rem  Run this on the PC that hosts the app. Other PCs on the same
rem  network open the address printed below in their browser.
rem  For this PC only:  set HOST=127.0.0.1  before running.
rem ============================================================
setlocal
cd /d "%~dp0"
if "%HOST%"=="" set HOST=0.0.0.0
if "%PORT%"=="" set PORT=8000

rem ---- find Python (python, or the py launcher)
set PY=
python --version >nul 2>&1 && set PY=python
if not defined PY py -3 --version >nul 2>&1 && set PY=py -3
if not defined PY (
  echo Python 3.10+ is not installed. Install it from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during setup.
  goto :error
)

rem ---- Python environment (rebuilt if missing or copied from another PC)
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -c "import sys" >nul 2>&1 || (
    echo Repairing the Python environment...
    rmdir /s /q .venv
  )
)
if not exist .venv\Scripts\python.exe (
  echo Creating the Python environment...
  %PY% -m venv .venv || goto :error
)
.venv\Scripts\python.exe -m pip install -q --disable-pip-version-check -r backend\requirements.txt || goto :error

rem ---- web interface (needs Node.js only if it was never built)
if not exist frontend\dist\index.html (
  where npm >nul 2>&1 || (
    echo The web interface is not built and Node.js is missing.
    echo Install Node.js 18+ from https://nodejs.org/ or copy the frontend\dist folder from a built copy.
    goto :error
  )
  echo Building the web interface...
  pushd frontend
  call npm install || goto :error
  call npm run build || goto :error
  popd
)

rem ---- firewall: allow other PCs to reach the port (asks for admin rights once)
if not "%HOST%"=="127.0.0.1" (
  netsh advfirewall firewall show rule name=SaveTimeWorkHard >nul 2>&1 || (
    echo Allowing port %PORT% through Windows Firewall - approve the Windows prompt...
    powershell -NoProfile -Command "Start-Process netsh -Verb RunAs -Wait -ArgumentList 'advfirewall firewall add rule name=SaveTimeWorkHard dir=in action=allow protocol=TCP localport=%PORT% profile=private,domain'"
  )
)

echo.
echo ============================================================
echo  Save time, Work hard is running.
echo  On this PC:     http://127.0.0.1:%PORT%
if not "%HOST%"=="127.0.0.1" (
  echo  On other PCs:
  powershell -NoProfile -Command "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | ForEach-Object { '                 http://' + $_.IPAddress + ':%PORT%' }"
)
echo  Keep this window open. Close it to stop the app.
echo ============================================================
echo.

start "" http://127.0.0.1:%PORT%
cd backend
..\.venv\Scripts\python.exe -m uvicorn main:app --host %HOST% --port %PORT%
goto :eof

:error
echo.
echo Setup failed. See the messages above.
pause
exit /b 1
