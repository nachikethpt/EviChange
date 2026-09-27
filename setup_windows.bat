@echo off
REM Run this once. Creates one shared Python environment for the whole project
REM (web app + multi-agent pipeline + tests).
cd /d "%~dp0"
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt -r requirements-dev.txt
echo.
echo Setup done. Next: double-click run_pipeline_windows.bat, then run_webapp_windows.bat.
echo Earth Engine (Phase 5-6): pip install -r requirements-ee.txt, then see scripts\ee_smoke_test.py
pause
