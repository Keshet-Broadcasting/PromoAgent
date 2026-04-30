@echo off
echo ===================================================
echo Starting Promobot Application
echo ===================================================

echo.
echo [1/2] Starting Backend API (FastAPI) on port 8000...
:: Start the backend in a new command prompt window
:: It checks if a virtual environment exists and activates it before running uvicorn
start "Promobot Backend API" cmd /k "if exist .venv\Scripts\activate.bat (call .venv\Scripts\activate.bat) & uvicorn app.api:app --reload --host 0.0.0.0 --port 8000"

echo.
echo [2/2] Starting Frontend UI (Next.js) on port 3000...
:: Start the frontend in a new command prompt window
start "Promobot Frontend UI" cmd /k "cd promobot-ui & npm run dev"

echo.
echo Both services are starting in separate windows!
echo.
echo - Backend API Docs: http://localhost:8000/docs
echo - Frontend UI:      http://localhost:3000 (or 3001 if 3000 is taken)
echo.
echo You can close this window.
pause
