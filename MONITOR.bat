@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Ururau v70 - Monitor 24h Rascunho

echo.
echo ============================================================
echo   URURAU v70 - ROBO DE MONITORAMENTO 24h (rascunhos)
echo ============================================================
echo.

:: --- Verifica ambiente virtual ---
if not exist "venv\Scripts\activate.bat" (
    echo [ERRO] Ambiente virtual nao encontrado.
    echo Execute INSTALAR.bat primeiro.
    pause
    exit /b 1
)

:: --- Verifica .env ---
if not exist ".env" (
    echo [ERRO] .env nao encontrado.
    echo Execute INICIAR.bat primeiro para configurar.
    pause
    exit /b 1
)

:: --- Ativa venv ---
call "venv\Scripts\activate.bat" || (
    echo [ERRO] Falha ao ativar venv.
    pause
    exit /b 1
)

:: --- Cria pasta de logs se nao existir ---
if not exist "logs" mkdir "logs"

:: --- Verifica dependencias criticas ---
python -c "import feedparser" 2>nul || (
    echo [AVISO] feedparser nao instalado. Instalando...
    pip install feedparser -q
)
python -c "import playwright" 2>nul || (
    echo [AVISO] playwright nao instalado. Instalando...
    pip install playwright -q
    python -m playwright install chromium
)

:: --- Executa monitor em modo rascunho (sem publicacao no CMS) ---
echo [INFO] Iniciando monitor 24h em modo RASCUNHO...
echo [INFO] Nenhuma publicacao real sera feita no CMS.
echo.
python ururau_monitor.py --cms-nao

echo.
echo ============================================================
echo   Monitor finalizado.
echo ============================================================
pause
