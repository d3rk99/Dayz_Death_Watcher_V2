@echo off
setlocal
set VENV_DIR=.venv

if not exist %VENV_DIR% (
  echo Virtual environment not found. Run setup_env.bat first.
  exit /b 1
)

call %VENV_DIR%\Scripts\activate
python -m src.gui
endlocal
