@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
set "HEAT_PYTHON="
set "HEAT_CONDA="

if exist ".venv\Scripts\python.exe" set "HEAT_PYTHON=%~dp0.venv\Scripts\python.exe"
if not defined HEAT_PYTHON if exist "venv\Scripts\python.exe" set "HEAT_PYTHON=%~dp0venv\Scripts\python.exe"
if defined HEAT_PYTHON goto launch

rem Conda may not be on PATH when launched from Explorer.
if defined CONDA_EXE for %%C in ("%CONDA_EXE%") do if exist "%%~dpC..\condabin\conda.bat" set "HEAT_CONDA=%%~dpC..\condabin\conda.bat"
if not defined HEAT_CONDA for /f "delims=" %%C in ('where conda.bat 2^>nul') do if not defined HEAT_CONDA set "HEAT_CONDA=%%C"
for %%C in ("%USERPROFILE%\miniconda3" "%USERPROFILE%\anaconda3" "%LOCALAPPDATA%\miniconda3" "%LOCALAPPDATA%\anaconda3" "%ProgramData%\miniconda3" "%ProgramData%\anaconda3") do if not defined HEAT_CONDA if exist "%%~C\condabin\conda.bat" set "HEAT_CONDA=%%~C\condabin\conda.bat"
if not defined HEAT_CONDA goto system_python
call "%HEAT_CONDA%" activate heat
if errorlevel 1 goto system_python
set "HEAT_PYTHON=%CONDA_PREFIX%\python.exe"
goto launch

:system_python
echo [INFO] Conda heat is unavailable; checking Python on PATH.
set "HEAT_PYTHON=python"

:launch
"%HEAT_PYTHON%" -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.10+ is required. Selected: "%HEAT_PYTHON%"
    echo Create the environment with: conda env create -f environment.yml
    goto failed
)
if not exist "scripts\launch_heat.py" (
    echo [ERROR] scripts\launch_heat.py is missing. Restore the complete project.
    goto failed
)
rem Keep Python in the foreground so Ctrl+C reaches Uvicorn normally.
"%HEAT_PYTHON%" "scripts\launch_heat.py"
if errorlevel 1 goto failed
exit /b 0

:failed
echo [ERROR] Heat did not start or exited with an error. See the output above.
pause
exit /b 1
