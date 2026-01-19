@echo off
setlocal
set VENV_DIR=.venv

if not exist %VENV_DIR% (
  echo Virtual environment not found. Running setup_env.bat...
  call setup_env.bat
  if errorlevel 1 (
    exit /b 1
  )
)

call %VENV_DIR%\Scripts\activate
python -m src.bot
endlocal
