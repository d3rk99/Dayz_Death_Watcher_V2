@echo off
setlocal
set VENV_DIR=.venv

if not exist %VENV_DIR% (
  python -m venv %VENV_DIR%
)

call %VENV_DIR%\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt

echo Environment ready.
endlocal
