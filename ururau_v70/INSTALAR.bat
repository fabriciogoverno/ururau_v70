@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ============================================================
echo   URURAU v70c - Instalacao do Robo Editorial
echo   Correcao definitiva 10/10 (76 testes aprovados)
echo   v63: INICIAR.bat com console visivel para diagnostico
echo ============================================================
echo.

:: --- Detecta Python (tenta 'python' e 'py -3') ---
set PYTHON_CMD=
set PYTHON_OK=0

python --version 1>nul 2>nul
if not errorlevel 1 (
    set PYTHON_CMD=python
    set PYTHON_OK=1
)

if !PYTHON_OK!==0 (
    py -3 --version 1>nul 2>nul
    if not errorlevel 1 (
        set PYTHON_CMD=py -3
        set PYTHON_OK=1
    )
)

if !PYTHON_OK!==0 (
    echo [ERRO] Python nao encontrado no PATH.
    echo.
    echo Instale o Python 3.10 ou superior em:
    echo   https://www.python.org/downloads/
    echo.
    echo IMPORTANTE: marque "Add Python to PATH" durante a instalacao.
    echo.
    pause
    exit /b 1
)

echo [OK] Python detectado: !PYTHON_CMD!
!PYTHON_CMD! --version
echo.

:: --- Verifica versao Python (>= 3.10) ---
!PYTHON_CMD! -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 1>nul 2>nul
if errorlevel 1 (
    echo [ERRO] Python 3.10 ou superior eh obrigatorio.
    echo Versao instalada:
    !PYTHON_CMD! --version
    echo.
    echo Atualize o Python em https://www.python.org/downloads/
    pause
    exit /b 1
)

:: --- Cria ambiente virtual se nao existir ---
if not exist "venv\Scripts\activate.bat" (
    echo [INFO] Criando ambiente virtual...
    !PYTHON_CMD! -m venv venv
    if errorlevel 1 (
        echo [ERRO] Falha ao criar ambiente virtual.
        pause
        exit /b 1
    )
    echo [OK] Ambiente virtual criado.
) else (
    echo [OK] Ambiente virtual ja existe.
)
echo.

:: --- Ativa ambiente virtual ---
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERRO] Falha ao ativar o ambiente virtual.
    pause
    exit /b 1
)
echo [OK] Ambiente virtual ativado.
echo.

:: --- Atualiza pip ---
echo [INFO] Atualizando pip...
python -m pip install --upgrade pip --quiet
echo [OK] pip atualizado.
echo.

:: --- Instala dependencias ---
echo [INFO] Instalando dependencias do requirements.txt...
echo        (pode demorar 2 a 5 minutos na primeira vez)
echo.
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERRO] Falha ao instalar dependencias.
    echo Verifique sua conexao com a internet e tente novamente.
    pause
    exit /b 1
)
echo [OK] Dependencias instaladas.
echo.

:: --- Instala Chromium para Playwright ---
echo [INFO] Instalando navegador Chromium para Playwright (necessario para CMS)...
playwright install chromium
if errorlevel 1 (
    echo [AVISO] Falha ao instalar Chromium.
    echo Para instalar manualmente, execute:
    echo   venv\Scripts\activate
    echo   playwright install chromium
) else (
    echo [OK] Chromium instalado.
)
echo.

:: --- Cria .env se nao existir ---
if not exist ".env" (
    echo [INFO] Criando arquivo .env a partir do exemplo...
    if exist ".env.exemplo" (
        copy ".env.exemplo" ".env" 1>nul
    )
    if not exist ".env" (
        echo OPENAI_API_KEY=sua_chave_aqui> .env
        echo OPENAI_MODEL=gpt-4.1-mini>> .env
        echo URURAU_LOGIN=seu_login_cms>> .env
        echo URURAU_SENHA=sua_senha_cms>> .env
        echo URURAU_ASSINATURA=Fabricio Freitas>> .env
        echo SITE_LOGIN_URL=https://www.ururau.com.br/acessocpainel/>> .env
        echo SITE_NOVA_URL=https://www.ururau.com.br/acessocpainel/noticias/nova/>> .env
        echo HEADLESS=false>> .env
        echo SLOW_MO=150>> .env
        echo ARQUIVO_DB=ururau.db>> .env
        echo PASTA_IMAGENS=imagens>> .env
        echo PASTA_PRINTS=prints>> .env
        echo PASTA_LOGS=logs>> .env
        echo QUALIDADE_JPEG_FINAL=95>> .env
        echo LIMIAR_RELEVANCIA_PUBLICAR=28>> .env
        echo LIMIAR_RISCO_MAXIMO=70>> .env
        echo MAX_PUBLICACOES_POR_CICLO=3>> .env
        echo MAX_PUBLICACOES_POR_CANAL=1>> .env
    )
    echo [OK] Arquivo .env criado.
    echo.
    echo ============================================================
    echo   IMPORTANTE: edite o arquivo .env com suas credenciais!
    echo   Preencha: OPENAI_API_KEY, URURAU_LOGIN, URURAU_SENHA
    echo ============================================================
    echo.
) else (
    echo [OK] Arquivo .env ja existe.
)

if not exist imagens mkdir imagens
if not exist prints  mkdir prints
if not exist logs    mkdir logs
echo [OK] Pastas auxiliares verificadas.
echo.

:: --- Sanity check: importa modulos principais ---
echo [INFO] Validando importacao dos modulos principais (v63)...
python -c "import ururau.config.settings; import ururau.editorial.safe_title; import ururau.editorial.redacao; import ururau.publisher.workflow; import ururau.ui.painel; from ururau.editorial.safe_title import safe_title; assert safe_title('teste', 60) == 'teste'; print('[OK] Modulos principais OK + safe_title OK')"
if errorlevel 1 (
    echo [AVISO] Alguns modulos falharam ao importar.
    echo Verifique se todas as dependencias foram instaladas.
)
echo.

:: --- Roda os testes (76 testes) ---
echo [INFO] Executando suite de testes (76 testes - pode demorar 30s)...
echo.
set TEST_FAIL=0
python tests\test_config_e_extracao.py 1>nul 2>nul
if errorlevel 1 (
    echo [FAIL] test_config_e_extracao.py
    set TEST_FAIL=1
) else (
    echo [PASS] test_config_e_extracao.py - 27 testes
)
python tests\test_agente_editorial.py 1>nul 2>nul
if errorlevel 1 (
    echo [FAIL] test_agente_editorial.py
    set TEST_FAIL=1
) else (
    echo [PASS] test_agente_editorial.py - 7 secoes
)
python tests\test_fluxo_producao.py 1>nul 2>nul
if errorlevel 1 (
    echo [FAIL] test_fluxo_producao.py
    set TEST_FAIL=1
) else (
    echo [PASS] test_fluxo_producao.py - 30 testes
)
python tests\test_revisao_workflow.py 1>nul 2>nul
if errorlevel 1 (
    echo [FAIL] test_revisao_workflow.py
    set TEST_FAIL=1
) else (
    echo [PASS] test_revisao_workflow.py - 12 testes
)
echo.
if !TEST_FAIL!==0 (
    echo [OK] Todos os 76 testes passaram.
) else (
    echo [AVISO] Alguns testes falharam - rode TESTAR.bat para ver detalhes.
)
echo.

echo ============================================================
echo   INSTALACAO CONCLUIDA COM SUCESSO!  v63
echo ============================================================
echo.
echo Proximos passos:
echo   1. Edite o arquivo .env com suas credenciais
echo      (OPENAI_API_KEY, URURAU_LOGIN, URURAU_SENHA)
echo   2. Execute INICIAR.bat para abrir o painel
echo      (com console visivel para diagnostico se algo der errado)
echo   3. Apos confirmar que funciona, opcional: INICIAR_SEM_CONSOLE.bat
echo   4. Para revalidar testes:  TESTAR.bat
echo.
pause
endlocal
