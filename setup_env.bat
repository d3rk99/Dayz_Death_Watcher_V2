@echo off
setlocal
set VENV_DIR=.venv
set PYTHON_EXE=

for /f "delims=" %%i in ('where python 2^>nul') do if not defined PYTHON_EXE set PYTHON_EXE=%%i
if not defined PYTHON_EXE (
  for /f "delims=" %%i in ('where py 2^>nul') do if not defined PYTHON_EXE set PYTHON_EXE=%%i
)

if not defined PYTHON_EXE (
  echo Python not found. Attempting to install via winget...
  where winget >nul 2>&1
  if errorlevel 1 (
    echo winget is not available. Please install Python manually from https://www.python.org/downloads/.
    exit /b 1
  )
  winget install -e --id Python.Python.3.11
  for /f "delims=" %%i in ('where python 2^>nul') do if not defined PYTHON_EXE set PYTHON_EXE=%%i
  if not defined PYTHON_EXE (
    for /f "delims=" %%i in ('where py 2^>nul') do if not defined PYTHON_EXE set PYTHON_EXE=%%i
  )
  if not defined PYTHON_EXE (
    echo Python installation completed, but it is not yet available in PATH.
    echo Please restart your terminal and re-run setup_env.bat.
    exit /b 1
  )
)

if not exist %VENV_DIR% (
  "%PYTHON_EXE%" -m venv %VENV_DIR%
)

call %VENV_DIR%\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt

echo Environment ready.
endlocal
