@echo off
chcp 65001 >nul
title 达尔文 — 安装依赖

echo ══════════════════════════════════════════════════
echo   🧬 达尔文 — 安装运行环境
echo ══════════════════════════════════════════════════
echo.

set "APP_DIR=%~dp0"
set "PYTHON_DIR=%APP_DIR%python"
set "PYTHON=%PYTHON_DIR%\python.exe"
set "PIP=%PYTHON_DIR%\Scripts\pip.exe"
set "PYTHONUTF8=1"
set "PYTHON_VERSION=3.12.8"
set "PYTHON_URL=https://www.python.org/ftp/python/%PYTHON_VERSION%/python-%PYTHON_VERSION%-embed-amd64.zip"
set "GET_PIP_URL=https://bootstrap.pypa.io/get-pip.py"

:: Step 1: Download embedded Python if not exists
if exist "%PYTHON%" (
    echo [✓] Python 已存在，跳过下载。
    goto :install_deps
)

echo [1/3] 下载 Python %PYTHON_VERSION% 嵌入式版本...
if not exist "%PYTHON_DIR%" mkdir "%PYTHON_DIR%"

:: Try curl first, then PowerShell
where curl >nul 2>&1
if %errorlevel%==0 (
    curl -L -o "%PYTHON_DIR%\python.zip" "%PYTHON_URL%"
) else (
    powershell -Command "Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%PYTHON_DIR%\python.zip'"
)

if not exist "%PYTHON_DIR%\python.zip" (
    echo [错误] 下载 Python 失败。请检查网络连接。
    pause
    exit /b 1
)

echo [1/3] 解压 Python...
powershell -Command "Expand-Archive -Path '%PYTHON_DIR%\python.zip' -DestinationPath '%PYTHON_DIR%' -Force"
del "%PYTHON_DIR%\python.zip"

:: Enable pip in embedded Python (uncomment import site in python312._pth)
powershell -Command "(Get-Content '%PYTHON_DIR%\python312._pth') -replace '#import site','import site' | Set-Content '%PYTHON_DIR%\python312._pth'"

:: Install pip
echo [2/3] 安装 pip...
if exist "%APP_DIR%get-pip.py" (
    "%PYTHON%" "%APP_DIR%get-pip.py" --no-warn-script-location
) else (
    where curl >nul 2>&1
    if %errorlevel%==0 (
        curl -L -o "%PYTHON_DIR%\get-pip.py" "%GET_PIP_URL%"
    ) else (
        powershell -Command "Invoke-WebRequest -Uri '%GET_PIP_URL%' -OutFile '%PYTHON_DIR%\get-pip.py'"
    )
    "%PYTHON%" "%PYTHON_DIR%\get-pip.py" --no-warn-script-location
    del "%PYTHON_DIR%\get-pip.py"
)

:install_deps
echo [3/3] 安装项目依赖（首次较慢，请耐心等待）...
"%PYTHON%" -m pip install -r "%APP_DIR%requirements.txt" --no-warn-script-location -q

if %errorlevel% neq 0 (
    echo [错误] 依赖安装失败。请检查网络连接后重试。
    pause
    exit /b 1
)

:: Create config.json if not exists
if not exist "%APP_DIR%config.json" (
    if exist "%APP_DIR%config.example.json" (
        copy "%APP_DIR%config.example.json" "%APP_DIR%config.json" >nul
        echo.
        echo [提示] 已创建 config.json，请编辑填入 API Keys。
    )
)

echo.
echo ══════════════════════════════════════════════════
echo   ✅ 安装完成！
echo   双击 start.bat 启动达尔文。
echo ══════════════════════════════════════════════════
echo.
pause
