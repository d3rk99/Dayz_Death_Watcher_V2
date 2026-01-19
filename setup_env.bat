@echo off
setlocal
set VENV_DIR=.venv
set "PYTHON_CMD="
set "PYTHON_ARGS="

for /f "delims=" %%i in ('where python 2^>nul') do if not defined PYTHON_CMD set "PYTHON_CMD=%%i"
if defined PYTHON_CMD (
  "%PYTHON_CMD%" -c "import sys" >nul 2>&1
  if errorlevel 1 set "PYTHON_CMD="
)

if not defined PYTHON_CMD (
  where py >nul 2>&1
  if not errorlevel 1 (
    set "PYTHON_CMD=py"
    set "PYTHON_ARGS=-3"
    %PYTHON_CMD% %PYTHON_ARGS% -c "import sys" >nul 2>&1
    if errorlevel 1 (
      set "PYTHON_CMD="
      set "PYTHON_ARGS="
    )
  )
)

if not defined PYTHON_CMD (
  echo Python not found. Attempting to install via winget...
  where winget >nul 2>&1
  if errorlevel 1 (
    echo winget is not available. Please install Python manually from https://www.python.org/downloads/.
    exit /b 1
  )
  winget install -e --id Python.Python.3.11
  set "PYTHON_CMD="
  for /f "delims=" %%i in ('where python 2^>nul') do if not defined PYTHON_CMD set "PYTHON_CMD=%%i"
  if defined PYTHON_CMD (
    "%PYTHON_CMD%" -c "import sys" >nul 2>&1
    if errorlevel 1 set "PYTHON_CMD="
  )
  if not defined PYTHON_CMD (
    where py >nul 2>&1
    if not errorlevel 1 (
      set "PYTHON_CMD=py"
      set "PYTHON_ARGS=-3"
      %PYTHON_CMD% %PYTHON_ARGS% -c "import sys" >nul 2>&1
      if errorlevel 1 (
        set "PYTHON_CMD="
        set "PYTHON_ARGS="
      )
    )
  )
  if not defined PYTHON_CMD (
    echo Python installation completed, but it is not yet available in PATH.
    echo Please restart your terminal and re-run setup_env.bat.
    exit /b 1
  )
)

if not exist %VENV_DIR% (
  %PYTHON_CMD% %PYTHON_ARGS% -m venv %VENV_DIR%
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
  echo Virtual environment setup failed. Please rerun setup_env.bat.
  exit /b 1
)

call %VENV_DIR%\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo Environment ready.
endlocal
