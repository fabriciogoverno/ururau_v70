@echo off
chcp 65001 >nul
title Ururau v62 - Monitor 24h COM PUBLICACAO no CMS
setlocal
cd /d "%~dp0"

echo.
echo ============================================================
echo   URURAU v62 - MONITOR 24h + PUBLICACAO no CMS
echo ============================================================
echo.

:: --- Verifica venv ---
if not exist "venv\Scripts\activate.bat" (
    echo [ERRO] Ambiente virtual nao encontrado.
    echo Execute INSTALAR.bat primeiro.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERRO] Falha ao ativar venv.
    pause
    exit /b 1
)

if not exist ".env" (
    echo [ERRO] .env nao encontrado. Execute I