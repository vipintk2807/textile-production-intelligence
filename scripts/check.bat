@echo off
REM Run every quality check. Each command's result is printed; failures stop the script.
cd /d "%~dp0\.."
call .venv\Scripts\activate.bat
python -m pytest || exit /b 1
ruff check . || exit /b 1
python manage.py check || exit /b 1
python manage.py makemigrations --check --dry-run || exit /b 1
echo.
echo All checks passed.
