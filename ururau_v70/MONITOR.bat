@echo off
chcp 65001 >nul
title Ururau v62 - Monitor 24h
setlocal
cd /d "%~dp0"

echo.
echo ============================================================
echo   URURAU v62 - ROBO DE MONITORAMENTO 24h (rascunhos)
echo ============================================================
echo.

:: --- Verifica ambiente virtual ---
if not exist "venv\Scripts\activate.bat" (
    echo [ERRO] Ambiente virtual nao encontrado.
    echo Execute INSTALAR.bat primeiro.
    pause
    exit /b 1
)

:: --- Ativa venv ---
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERRO] Falha ao ativar venv.
    pause
    exit /b 1
)

:: --- V