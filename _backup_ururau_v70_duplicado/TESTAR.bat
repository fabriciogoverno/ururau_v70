@echo off
chcp 65001 >nul
title Ururau v62 - Suite de Testes
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ============================================================
echo   URURAU v62 - SUITE COMPLETA DE TESTES (76 testes)
echo ============================================================
echo.

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

set TOTAL_FAIL=0

echo --- 1/4: test_config_e_extracao.py (27 testes) ---
python tests\test_config_e_extracao.py
if errorlevel 1 set /a TOTAL_FAIL+=1
echo.

echo --- 2/4: test_agente_editorial.py (7 secoes) ---
python tests\test_agente_editorial.py
if errorlevel 1 set /a TOTAL_FAIL+=1
echo.

echo --- 3/4: test_fluxo_producao.py (30 testes) ---
python tests\test_fluxo_producao.py
if errorlevel 1 set /a TOTAL_FAIL+=1
echo.

echo --- 4/4: test_revisao_workflow.py (12 testes) ---
python tests\test_revisao_workflow.py
if errorlevel 1 set /a TOTAL_FAIL+=1
echo.

echo ============================================================
if !TOTAL_FAIL!==0 (
    echo   RESULTADO: TODOS OS 76 TESTES PASSARAM
) else (
    echo   RESULTADO: !TOTAL_FAIL! suite^(s^) com falha
)
echo ============================================================
echo.
pause
endlocal
