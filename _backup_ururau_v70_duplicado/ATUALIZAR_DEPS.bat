@echo off
setlocal
cd /d "%~dp0"

if not exist "venv\Scripts\activate.bat" (
    echo Ambiente virtual nao encontrado. Execute INSTALAR.bat primeiro.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

echo Atualizando dependencias...
pip install -r requirements.txt --upgrade
if errorlevel 1 (
    echo [ERRO] Falha ao atualizar dependencias.
    pause
    exit /b 1
)

echo.
echo Atualizando navegador Chromium...
playwright install chromium

echo.
echo [OK] Tudo atualizado com sucesso!
pause
endlocal
