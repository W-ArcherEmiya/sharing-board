@echo off
setlocal
chcp 65001 >nul
title Sharing Board Launcher

for /f "tokens=1,2,3 delims=|" %%a in ('python launch_config.py') do (
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

echo [1/3] 安装依赖...
python -m pip install -r requirements.txt >nul 2>&1
if %errorlevel% neq 0 (
    echo    依赖安装失败，请确认 Python 已安装且可用。
    pause
    exit /b 1
) else (
    echo    依赖安装完成。
)

set NEED_CERT=0
if not exist key.pem set NEED_CERT=1
if not exist cert.pem set NEED_CERT=1

echo.
if "%NEED_CERT%"=="1" (
    echo [2/3] 正在生成局域网 HTTPS 证书...
    python gen_cert.py
    if %errorlevel% neq 0 (
        echo    证书生成失败，请检查 Python 环境。
        pause
        exit /b 1
    )
    echo    证书已生成。
) else (
    echo [2/3] 已检测到现有证书，跳过生成。
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

start "" powershell -NoProfile -Command "Start-Sleep -Seconds 3; Start-Process $env:APP_URL"

python -m uvicorn main:app --host 0.0.0.0 --port 8000 --ssl-keyfile key.pem --ssl-certfile cert.pem

pause
