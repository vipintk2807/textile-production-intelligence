@echo off
REM One-time setup. Run from the project folder:  scripts\setup.bat
cd /d "%~dp0\.."
where py >nul 2>nul
if errorlevel 1 (
  echo The Python launcher "py" was not found. Install Python 3.12 from https://www.python.org/downloads/
  exit /b 1
)
if not exist .venv (
  py -3.12 -m venv .venv
  if errorlevel 1 exit /b 1
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
if errorlevel 1 exit /b 1
python manage.py migrate
if errorlevel 1 exit /b 1
echo.
echo Setup complete. Start the application with:  scripts\run.bat
