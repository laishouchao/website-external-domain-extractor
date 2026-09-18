@echo off
chcp 65001 >nul
title 网站外部域名提取与全深度网站地图系统

echo ========================================================
echo   网站外部域名提取与全深度网站地图系统
echo ========================================================
echo.

set PYTHON_EXE=D:\02_Dev\MiniConda\python.exe
if not exist "%PYTHON_EXE%" (
    set PYTHON_EXE=python
)

echo 正在使用 Python: %PYTHON_EXE%
echo 正在启动 Web 服务，请在浏览器访问: http://localhost:8000
echo.

"%PYTHON_EXE%" run.py

pause
