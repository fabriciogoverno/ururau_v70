@echo off
title Ururau v70c - Painel
cd /d "%~dp0"

echo.
echo ============================================================
echo   URURAU v70c - Iniciando painel grafico
echo ============================================================
echo.

if not exist "venv\Scripts\activate.bat" (
    echo [ERRO] Ambiente virtual nao encontrado.
    echo Execute INSTALAR.bat primeiro.
    goto fim
)

call venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERRO] Falha ao ativar o ambiente virtual.
    goto fim
)
echo [OK] venv ativado.

if not exist ".env" (
    echo [ERRO] Arquivo .env nao encontrado.
    echo Execute INSTALAR.bat ou copie .env.exemplo para .env.
    goto fim
)
echo [OK] .env encontrado.

if not exist imagens mkdir imagens
if not exist prints  mkdir prints
if not exist logs    mkdir logs

echo.
echo [INFO] Iniciando painel com console visivel para diagnostico.
echo Se algo der errado, o erro fica visivel aqui abaixo.
echo Veja tambem: logs\painel_inicializacao.log
echo ============================================================
echo.

python ururau_painel.py

echo.
echo ============================================================
echo Painel encerrou. Codigo de saida: %errorlevel%
echo ============================================================

:fim
echo.
echo Pressione qualquer tecla para fechar esta janela...
pause >nul
