@echo off
chcp 65001 >nul
title 安全剪贴板启动器
echo ========================================================
echo   正在检查运行环境，请稍候...
echo ========================================================
echo.

:: 1. 自动尝试安装缺失的库 (如果已安装会跳过)
echo [1/3] 正在检查并安装依赖库...
pip install fastapi uvicorn websockets cryptography jinja2 >nul 2>&1
if %errorlevel% neq 0 (
    echo    警告: 自动安装失败，请确保你安装了 Python 并勾选了 "Add to PATH"
) else (
    echo    依赖库检查完成。
)

:: 2. 自动检查并生成证书 (解决 OpenSSL 问题)
if not exist key.pem (
    echo.
    echo [2/3] 证书不存在，正在通过 Python 生成...
    :: 这里调用我们之前写的 gen_cert.py，如果没有该文件，下面会创建一个临时的
    if not exist gen_cert.py (
        echo    正在创建临时证书生成脚本...
        (
        echo from cryptography import x509
        echo from cryptography.x509.oid import NameOID
        echo from cryptography.hazmat.primitives import hashes
        echo from cryptography.hazmat.primitives.asymmetric import rsa
        echo from cryptography.hazmat.primitives import serialization
        echo import datetime
        echo def generate_self_signed_cert^(:^):
        echo     key = rsa.generate_private_key^(public_exponent=65537, key_size=2048^)
        echo     subject = issuer = x509.Name^([x509.NameAttribute^(NameOID.COMMON_NAME, u"localhost"^)^]^)
        echo     cert = x509.CertificateBuilder^(:^).subject_name^(subject^).issuer_name^(issuer^).public_key^(key.public_key^(:^)^).serial_number^(x509.random_serial_number^(:^)^).not_valid_before^(datetime.datetime.utcnow^(:^)^).not_valid_after^(datetime.datetime.utcnow^(:^) + datetime.timedelta^(days=365^)^).sign^(key, hashes.SHA256^(:^)^)
        echo     with open^("key.pem", "wb"^) as f: f.write^(key.private_bytes^(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption^(:^)^)^)
        echo     with open^("cert.pem", "wb"^) as f: f.write^(cert.public_bytes^(serialization.Encoding.PEM^)^)
        echo if __name__ == "__main__": generate_self_signed_cert^(:^)
        ) > gen_cert_temp.py
        python gen_cert_temp.py
        del gen_cert_temp.py
    ) else (
        python gen_cert.py
    )
    echo    证书生成完毕！
) else (
    echo [2/3] 证书已存在，跳过生成。
)

:: 3. 启动服务 (解决 uvicorn 找不到的问题)
echo.
echo [3/3] 正在启动服务...
echo.
echo ========================================================
echo   本机 IP 地址 (请在手机输入 https://IP:8000)
ipconfig | findstr "IPv4"
echo ========================================================
echo.

:: 关键修改：使用 "python -m uvicorn" 而不是直接 "uvicorn"
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --ssl-keyfile key.pem --ssl-certfile cert.pem

pause