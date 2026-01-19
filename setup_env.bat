@echo off
setlocal
set VENV_DIR=.venv

where python >nul 2>nul
if errorlevel 1 (
  echo Python not found. Attempting to install via winget...
  where winget >nul 2>nul
  if errorlevel 1 (
    echo winget not found. Please install Python 3.11+ manually.
    exit /b 1
  )
  winget install --id Python.Python.3.11 -e
)

if not exist %VENV_DIR% (
  python -m venv %VENV_DIR%
)

call %VENV_DIR%\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt

echo Environment ready.
endlocal
