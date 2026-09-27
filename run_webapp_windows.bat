@echo off
REM Starts the web app at http://localhost:8000 - shows pipeline / imported data
REM if run_pipeline_windows.bat or import_geojson.py has been run, demo data otherwise.
cd /d "%~dp0"
call .venv\Scripts\activate.bat
start "" http://localhost:8000
python -m uvicorn webapp.backend.main:app --reload --port 8000
pause
