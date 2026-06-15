@echo off
cd /d "%~dp0"
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8

echo Instalando dependencias...
python -m pip install -r requirements.txt -q
if errorlevel 1 (
    echo Falha ao instalar dependencias. Verifique se o Python esta instalado.
    pause
    exit /b 1
)

echo.
echo Iniciando servidor em http://127.0.0.1:5002
echo Pressione Ctrl+C para parar.
echo.
python fiat_server.py
pause
