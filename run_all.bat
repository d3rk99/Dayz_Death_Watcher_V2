@echo off
setlocal
set VENV_DIR=.venv

if not exist %VENV_DIR% (
  call setup_env.bat
  if errorlevel 1 exit /b 1
)

call %VENV_DIR%\Scripts\activate
start "DeathWatcher Bot" cmd /k python -m src.bot
start "DeathWatcher GUI" cmd /k python -m src.gui
endlocal
