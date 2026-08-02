@echo off
setlocal
chcp 65001 >nul
title Sharing Board Launcher

set "PYTHON_CMD="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=py -3"

if "%PYTHON_CMD%"=="" (
    python --version >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=python"
)

if "%PYTHON_CMD%"=="" (
    echo 未找到 Python，请先安装 Python 3.10 或更高版本。
    pause
    exit /b 1
)

for /f "tokens=1,2,3 delims=|" %%a in ('%PYTHON_CMD% launch_config.py') do (
    set HOST_IP=%%a
    set ROOM_CODE=%%b
    set ROOM_PASSWORD=%%c
)

if "%HOST_IP%"=="" set HOST_IP=localhost
if "%ROOM_CODE%"=="" set ROOM_CODE=demoRoom
if "%ROOM_PASSWORD%"=="" set ROOM_PASSWORD=demoPass123

set "APP_URL=https://%HOST_IP%:8000/#room=%ROOM_CODE%&password=%ROOM_PASSWORD%&host=1"

echo ========================================================
echo   Sharing Board 正在检查运行环境...
echo ========================================================
echo.

set "DEPS_HASH_FILE=.deps-installed.sha256"
set "CURRENT_DEPS_HASH="
set "INSTALLED_DEPS_HASH="
set "NEED_DEPS=1"

for /f "delims=" %%h in ('powershell -NoProfile -Command "(Get-FileHash -Algorithm SHA256 'requirements.txt').Hash"') do set "CURRENT_DEPS_HASH=%%h"
if "%CURRENT_DEPS_HASH%"=="" (
    echo [1/3] 依赖清单读取失败，请确认 requirements.txt 存在。
    pause
    exit /b 1
)

if exist "%DEPS_HASH_FILE%" set /p INSTALLED_DEPS_HASH=<"%DEPS_HASH_FILE%"
if /I "%INSTALLED_DEPS_HASH%"=="%CURRENT_DEPS_HASH%" set "NEED_DEPS=0"

echo [1/3] 检查依赖...
if "%NEED_DEPS%"=="1" (
    echo    requirements.txt 首次安装或已变化，正在安装依赖...
    %PYTHON_CMD% -m pip install -r requirements.txt >nul 2>&1
    if errorlevel 1 (
        echo    依赖安装失败，请确认 Python 已安装且可用。
        pause
        exit /b 1
    )
    >"%DEPS_HASH_FILE%" echo %CURRENT_DEPS_HASH%
    echo    依赖安装完成。
) else (
    echo    依赖未变化，跳过安装。
)

set NEED_CERT=0
if not exist key.pem set NEED_CERT=1
if not exist cert.pem set NEED_CERT=1
if "%NEED_CERT%"=="0" (
    %PYTHON_CMD% gen_cert.py --covers "%HOST_IP%" >nul 2>&1
    if errorlevel 1 set NEED_CERT=1
)

echo.
if "%NEED_CERT%"=="1" (
    echo [2/3] 正在生成或更新局域网 HTTPS 证书...
    %PYTHON_CMD% gen_cert.py
    if errorlevel 1 (
        echo    证书生成失败，请检查 Python 环境。
        pause
        exit /b 1
    )
    echo    证书已就绪。
) else (
    echo [2/3] 证书已覆盖当前访问地址，跳过生成。
)

echo.
echo [3/3] 正在启动服务...
echo ========================================================
echo   默认访问地址： https://%HOST_IP%:8000
echo   默认房间号： %ROOM_CODE%
echo   默认密码： %ROOM_PASSWORD%
ipconfig | findstr "IPv4"
echo ========================================================
echo.

start "" powershell -NoProfile -Command "Start-Sleep -Seconds 3; Start-Process -FilePath '%APP_URL%'"

%PYTHON_CMD% -m uvicorn main:app --host 0.0.0.0 --port 8000 --ssl-keyfile key.pem --ssl-certfile cert.pem

pause
