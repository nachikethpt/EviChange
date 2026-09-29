@echo off
REM Starts the web app at http://localhost:8000 - shows pipeline / imported data
REM if run_pipeline_windows.bat or import_geojson.py has been run, demo data otherwise.
cd /d "%~dp0"
if exist .venv312\Scripts\activate.bat (
  call .venv312\Scripts\activate.bat
) else (
  call .venv\Scripts\activate.bat
)
REM Open the browser a few seconds later, once the server is listening
start "" /min cmd /c "timeout /t 5 /nobreak >nul & start "" http://localhost:8000"
python -m uvicorn webapp.backend.main:app --reload --port 8000
pause
