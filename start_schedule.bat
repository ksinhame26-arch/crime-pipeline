@echo off
REM Starts the daily schedule on the laptop (keep this window open).
REM Prefect UI with all runs: http://localhost:4200
cd /d "%~dp0"
docker compose up -d
start "" http://localhost:4200
".venv\Scripts\python.exe" etl\etl_pipeline.py
pause
