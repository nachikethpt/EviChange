@echo off
REM Runs the 6-agent pipeline once and publishes the result to the web app.
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python run_and_publish.py %*
pause
