@echo off
:: v63: Versao alternativa sem console visivel (apenas use APOS confirmar
:: que INICIAR.bat funciona corretamente. Se algo der errado nesta versao,
:: voce nao verá a mensagem de erro - so o log em logs/painel_inicializacao.log).
setlocal
cd /d "%~dp0"

if not exist "venv\Scripts\activate.bat" (
    echo Execute INSTALAR.bat primeiro.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

if not exist ".env" (
    echo Configure o arquivo .env primeiro.
    pause
    exit /b 1
)

if not exist imagens mkdir imagens
if not exist prints  mkdir prints
if not exist logs    mkdir logs

if exist "venv\Scripts\pythonw.exe" (
    start "" "venv\Scripts\pythonw.exe" ururau_painel.py
) else (
    start "" /B python ururau_painel.py
)
endlocal
