@echo off
setlocal EnableExtensions

rem Heat one-click launcher for Windows.
rem The script is intentionally kept outside the Python application so it can
rem be used before opening a terminal or activating an environment manually.

cd /d "%~dp0"
set "PROJECT_DIR=%~dp0"
set "PYTHON_EXE="

if exist "%PROJECT_DIR%.venv\Scripts\python.exe" set "PYTHON_EXE=%PROJECT_DIR%.venv\Scripts\python.exe"
if not defined PYTHON_EXE if exist "%PROJECT_DIR%venv\Scripts\python.exe" set "PYTHON_EXE=%PROJECT_DIR%venv\Scripts\python.exe"
if not defined PYTHON_EXE set "PYTHON_EXE=python"

if not exist "%PROJECT_DIR%run_server.py" (
    echo [ERROR] run_server.py was not found.
    echo Place this script in the Heat project root.
    pause
    exit /b 1
)

"%PYTHON_EXE%" --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] No usable Python environment was found.
    echo Install Python 3.10+ or create a .venv in the project root.
    pause
    exit /b 1
)

for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":8000 .*LISTENING"') do set "PORT_PID=%%p"
if defined PORT_PID (
    echo [INFO] Port 8000 is already in use. Heat may already be running.
    start "" "http://localhost:8000"
    exit /b 0
)

echo [Heat] Starting server...
start "Heat Server" /b "%PYTHON_EXE%" "%PROJECT_DIR%run_server.py"

set "CHECK_COUNT=0"
:wait_for_server
set /a CHECK_COUNT+=1
powershell -NoProfile -ExecutionPolicy Bypass -Command "$client = New-Object Net.Sockets.TcpClient; try { $client.Connect('127.0.0.1',8000); exit 0 } catch { exit 1 } finally { $client.Dispose() }" >nul 2>&1
if not errorlevel 1 (
    echo [Heat] Server is ready: http://localhost:8000
    start "" "http://localhost:8000"
    exit /b 0
)
if %CHECK_COUNT% GEQ 15 (
    echo [ERROR] Server did not start within the expected time.
    echo Run python run_server.py directly to inspect the error.
    pause
    exit /b 1
)
timeout /t 1 /nobreak >nul
goto wait_for_server
