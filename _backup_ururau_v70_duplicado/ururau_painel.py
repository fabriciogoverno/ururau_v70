"""
ururau_painel.py - Ponto de entrada do painel editorial Ururau v70c.

Inicializa configuracoes, banco de dados, cliente OpenAI e lanca a GUI.

v63: Tratamento robusto de erros + log em arquivo para diagnosticar
quando o painel fecha sozinho. Se algo falhar, o erro vai aparecer no
console E em logs/painel_inicializacao.log.
"""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path
from datetime import datetime

# Garante que o diretorio do projeto esteja no PYTHONPATH
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def _log_arquivo(msg: str):
    """Loga em arquivo (mesmo se o console fechar)."""
    try:
        log_dir = BASE_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_dir / "painel_inicializacao.log", "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def _imprimir(msg: str):
    """Imprime no console e loga em arquivo."""
    print(msg, flush=True)
    _log_arquivo(msg)


def _erro_fatal(titulo: str, detalhes: str):
    """
    Mostra erro fatal em messagebox (se tk disponivel) e console.
    Garante que o usuario VEJA o erro mesmo se o console fechar.
    """
    _imprimir(f"\n{'='*60}\n[ERRO FATAL] {titulo}\n{'='*60}\n{detalhes}\n")
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            f"Ururau v70c - {titulo}",
            f"{titulo}\n\n{detalhes}\n\n"
            f"Mais detalhes em: logs/painel_inicializacao.log",
        )
        root.destroy()
    except Exception as _e:
        _imprimir(f"[AVISO] Nao foi possivel mostrar messagebox: {_e}")


def main():
    _imprimir("=" * 60)
    _imprimir(f"URURAU v70c - Iniciando painel ({datetime.now().isoformat(timespec='seconds')})")
    _imprimir(f"Diretorio: {BASE_DIR}")
    _imprimir(f"Python: {sys.version}")
    _imprimir(f"Executavel: {sys.executable}")
    _imprimir("=" * 60)

    # Carrega .env
    try:
        from dotenv import load_dotenv
        load_dotenv(BASE_DIR / ".env", override=True)
        _imprimir("[OK] .env carregado")
    except ImportError:
        _erro_fatal(
            "Dependencia ausente: python-dotenv",
            "A biblioteca 'python-dotenv' nao esta instalada.\n\n"
            "Execute INSTALAR.bat para instalar todas as dependencias.",
        )
        sys.exit(2)

    # Imports do pacote
    try:
        from ururau.config.settings import (
            OPENAI_API_KEY,
            MODELO_OPENAI,
            ARQUIVO_DB,
            PASTA_IMAGENS,
            PASTA_PRINTS,
            PASTA_LOGS,
        )
        from ururau.core.database import get_db
        _imprimir("[OK] Modulos do pacote importados")
    except ImportError as e:
        _erro_fatal(
            "Falha ao importar modulos do pacote ururau",
            f"Erro: {e}\n\nStack:\n{traceback.format_exc()}\n\n"
            "Possiveis causas:\n"
            "1. Voce nao esta executando do diretorio do projeto.\n"
            "2. Dependencias nao foram instaladas - rode INSTALAR.bat.\n"
            "3. Algum arquivo .py do pacote esta corrompido.",
        )
        sys.exit(3)
    except Exception as e:
        _erro_fatal(
            "Erro inesperado ao importar settings",
            f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}",
        )
        sys.exit(4)

    # Cria pastas
    try:
        for pasta in (PASTA_IMAGENS, PASTA_PRINTS, PASTA_LOGS):
            Path(pasta).mkdir(parents=True, exist_ok=True)
        _imprimir("[OK] Pastas criadas")
    except Exception as e:
        _imprimir(f"[AVISO] Falha ao criar pastas: {e}")

    # Banco de dados
    try:
        db = get_db(ARQUIVO_DB)
        _imprimir(f"[OK] Banco de dados aberto: {ARQUIVO_DB}")
    except Exception as e:
        _erro_fatal(
            "Falha ao abrir banco de dados",
            f"Arquivo: {ARQUIVO_DB}\n{type(e).__name__}: {e}\n\n{traceback.format_exc()}",
        )
        sys.exit(5)

    # Cliente OpenAI
    client = None
    if not OPENAI_API_KEY:
        _imprimir("[AVISO] OPENAI_API_KEY nao definida no .env - IA desativada.")
    else:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=OPENAI_API_KEY)
            _imprimir(f"[OK] Cliente OpenAI criado (modelo: {MODELO_OPENAI})")
        except ImportError:
            _imprimir("[AVISO] Biblioteca 'openai' nao instalada. IA desativada.")
        except Exception as e:
            _imprimir(f"[AVISO] Falha ao criar cliente OpenAI: {e}")

    # Lanca a interface grafica
    try:
        _imprimir("[INFO] Importando UI...")
        from ururau.ui.painel import PainelUrurau
        _imprimir("[INFO] Construindo PainelUrurau...")
        app = PainelUrurau(db=db, client=client, modelo=MODELO_OPENAI)
        _imprimir("[OK] Painel construido. Entrando no mainloop()...")
        app.mainloop()
        _imprimir("[INFO] Painel encerrado normalmente.")
    except Exception as e:
        _erro_fatal(
            "Falha ao construir/abrir o painel",
            f"{type(e).__name__}: {e}\n\nStack completo:\n{traceback.format_exc()}",
        )
        sys.exit(6)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        _erro_fatal(
            "Erro nao tratado em main()",
            f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}",
        )
        sys.exit(99)
