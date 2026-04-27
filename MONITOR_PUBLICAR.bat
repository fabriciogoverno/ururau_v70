@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Ururau v70 - Monitor 24h COM PUBLICACAO no CMS

echo.
echo ============================================================
echo   URURAU v70 - MONITOR 24h + PUBLICACAO no CMS
echo ============================================================
echo.
echo   ATENCAO: Este modo PUBLICA DIRETAMENTE no CMS.
echo   Certifique-se de que URURAU_PUBLICACAO_REAL_CONFIRMADA=SIM no .env
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

:: --- Verifica se publicacao esta confirmada no .env ---
python -c "
import os, sys
from dotenv import load_dotenv
load_dotenv()
conf = os.getenv('URURAU_PUBLICACAO_REAL_CONFIRMADA', 'NAO').upper()
if conf not in ('SIM', 'YES', '1', 'TRUE'):
    print('[BLOQUEIO] URURAU_PUBLICACAO_REAL_CONFIRMADA nao esta ativada no .env.')
    print('           Para publicar de verdade, defina URURAU_PUBLICACAO_REAL_CONFIRMADA=SIM')
    sys.exit(1)
" || (
    echo.
    echo [ERRO] Publicacao bloqueada por seguranca.
    echo         Edite .env e defina URURAU_PUBLICACAO_REAL_CONFIRMADA=SIM
    pause
    exit /b 1
)

:: --- Executa monitor com publicacao no CMS ---
echo [INFO] Iniciando monitor 24h em modo PUBLICACAO DIRETA...
echo [INFO] Verifique os logs em /logs para acompanhar.
echo.
python ururau_monitor.py --cms

echo.
echo ============================================================
echo   Monitor finalizado.
echo ============================================================
pause
