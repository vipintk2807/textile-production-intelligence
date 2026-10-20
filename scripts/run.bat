@echo off
REM Start the local development server (trusted local use only).
cd /d "%~dp0\.."
call .venv\Scripts\activate.bat
python manage.py runserver 127.0.0.1:8000
