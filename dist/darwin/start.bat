@echo off
chcp 65001 >nul 2>nul
title Darwin

echo ==================================================
echo   Darwin - TikTok Live Script Optimization
echo ==================================================
echo.

set "APP_DIR=%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

set "PY="
where python >nul 2>&1 && set "PY=python" && goto :found
where python3 >nul 2>&1 && set "PY=python3" && goto :found
where py >nul 2>&1 && set "PY=py" && goto :found
if exist "C:\Python312\python.exe" set "PY=C:\Python312\python.exe" && goto :found
if exist "C:\Python311\python.exe" set "PY=C:\Python311\python.exe" && goto :found
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe" && goto :found
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe" && goto :found

echo [ERROR] Python not found. Install Python 3.10+ and add to PATH.
pause
exit /b 1

:found
echo [OK] Python: %PY%
%PY% --version
echo.

%PY% -c "import streamlit" >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing dependencies...
    %PY% -m pip install -r "%APP_DIR%requirements.txt"
    if %errorlevel% neq 0 (
        echo [ERROR] Install failed. Check network.
        pause
        exit /b 1
    )
    echo [OK] Dependencies installed.
    echo.
)

if not exist "%APP_DIR%config.json" (
    if exist "%APP_DIR%config.example.json" (
        copy "%APP_DIR%config.example.json" "%APP_DIR%config.json" >nul
        echo [INFO] config.json created. Edit API keys and restart.
        notepad "%APP_DIR%config.json"
        pause
        exit /b 0
    )
)

if not exist "%APP_DIR%data\rooms" mkdir "%APP_DIR%data\rooms"
if not exist "%APP_DIR%data\tasks" mkdir "%APP_DIR%data\tasks"

echo ==================================================
echo   Open browser: http://localhost:8501
echo   Close this window to stop.
echo ==================================================
echo.

cd /d "%APP_DIR%"
%PY% -m streamlit run app.py --server.port 8501 --server.headless true --browser.gatherUsageStats false

pause
