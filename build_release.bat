@echo off
chcp 65001 >nul
title 达尔文 — 构建发布包

echo ══════════════════════════════════════════════════
echo   🧬 达尔文 — 构建发布包
echo ══════════════════════════════════════════════════
echo.

set "SRC_DIR=%~dp0"
set "BUILD_DIR=%SRC_DIR%dist\darwin"
set "PYTHON_VERSION=3.12.8"
set "PYTHON_URL=https://www.python.org/ftp/python/%PYTHON_VERSION%/python-%PYTHON_VERSION%-embed-amd64.zip"
set "GET_PIP_URL=https://bootstrap.pypa.io/get-pip.py"
set "PYTHONUTF8=1"

:: Clean previous build
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
mkdir "%BUILD_DIR%"

echo [1/5] 下载 Python %PYTHON_VERSION% 嵌入式版本...
mkdir "%BUILD_DIR%\python"
curl -L -o "%BUILD_DIR%\python\python.zip" "%PYTHON_URL%"
powershell -Command "Expand-Archive -Path '%BUILD_DIR%\python\python.zip' -DestinationPath '%BUILD_DIR%\python' -Force"
del "%BUILD_DIR%\python\python.zip"

:: Enable site-packages
powershell -Command "(Get-Content '%BUILD_DIR%\python\python312._pth') -replace '#import site','import site' | Set-Content '%BUILD_DIR%\python\python312._pth'"

echo [2/5] 安装 pip...
curl -L -o "%BUILD_DIR%\python\get-pip.py" "%GET_PIP_URL%"
"%BUILD_DIR%\python\python.exe" "%BUILD_DIR%\python\get-pip.py" --no-warn-script-location -q
del "%BUILD_DIR%\python\get-pip.py"

echo [3/5] 安装项目依赖...
"%BUILD_DIR%\python\python.exe" -m pip install -r "%SRC_DIR%requirements.txt" --no-warn-script-location -q

echo [4/5] 复制项目文件...
:: Copy Python source files
for %%f in (app.py audit.py config.py data_io.py hill_climb.py llm.py models.py priority.py prompts.py ratchet.py room.py rubric.py task_manager.py task_worker.py ui_helpers.py zmeng_api.py launcher.py) do (
    copy "%SRC_DIR%%%f" "%BUILD_DIR%\%%f" >nul
)

:: Copy pages
mkdir "%BUILD_DIR%\pages"
copy "%SRC_DIR%pages\*.py" "%BUILD_DIR%\pages\" >nul

:: Copy config and scripts
copy "%SRC_DIR%config.example.json" "%BUILD_DIR%\config.example.json" >nul
copy "%SRC_DIR%config.json" "%BUILD_DIR%\config.json" >nul 2>nul
copy "%SRC_DIR%requirements.txt" "%BUILD_DIR%\requirements.txt" >nul
copy "%SRC_DIR%start.bat" "%BUILD_DIR%\start.bat" >nul
copy "%SRC_DIR%install.bat" "%BUILD_DIR%\install.bat" >nul

:: Copy .streamlit config
mkdir "%BUILD_DIR%\.streamlit"
copy "%SRC_DIR%.streamlit\config.toml" "%BUILD_DIR%\.streamlit\config.toml" >nul

:: Copy data (rooms with all results)
echo [5/5] 复制数据文件...
xcopy "%SRC_DIR%data\rooms" "%BUILD_DIR%\data\rooms\" /E /I /Q >nul
if exist "%SRC_DIR%data\weight_config.json" copy "%SRC_DIR%data\weight_config.json" "%BUILD_DIR%\data\weight_config.json" >nul
if exist "%SRC_DIR%data\.auth" copy "%SRC_DIR%data\.auth" "%BUILD_DIR%\data\.auth" >nul
mkdir "%BUILD_DIR%\data\tasks" 2>nul

echo.
echo ══════════════════════════════════════════════════
echo   ✅ 构建完成！
echo   发布包位置: %BUILD_DIR%
echo.
echo   分发方式：
echo   1. 将 dist\darwin 文件夹压缩为 zip
echo   2. 目标机器解压后双击 start.bat 即可运行
echo ══════════════════════════════════════════════════
echo.

:: Calculate size
for /f "tokens=3" %%a in ('dir "%BUILD_DIR%" /s /-c ^| findstr "个文件"') do set SIZE=%%a
echo   总大小: 约 %SIZE% 字节

pause
