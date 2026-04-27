"""
ururau_monitor.py — Robô de monitoramento 24h do Ururau.

Executa em loop contínuo:
  - Coleta pautas de RSS + Google News
  - Seleciona as melhores por score editorial
  - Redigir, revisar e salvar como rascunho no banco
  - Opcionalmente publica diretamente no CMS (modo --publicar)

Uso:
    python ururau_monitor.py
    python ururau_monitor.py --publicar       # publica no CMS também
    python ururau_monitor.py --intervalo 900  # ciclo a cada 15 minutos
    python ururau_monitor.py --max-hora 2     # máx 2 por hora

Ctrl+C para parar com segurança.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# ── Garante que o diretório do projeto esteja no PYTHONPATH ──────────────────
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# ── Carrega .env antes de qualquer import do pacote ──────────────────────────
from dotenv import load_dotenv
load_dotenv(BASE_DIR / ".env", override=True)


def _criar_pastas():
    from ururau.config.settings import PASTA_IMAGENS, PASTA_PRINTS, PASTA_LOGS
    for pasta in (PASTA_IMAGENS, PASTA_PRINTS, PASTA_LOGS):
        Path(pasta).mkdir(parents=True, exist_ok=True)


def _criar_client_openai():
    from ururau.config.settings import OPENAI_API_KEY
    if not OPENAI_API_KEY:
        print("[MONITOR] OPENAI_API_KEY não definida. IA desativada — abortando.")
        sys.exit(1)
    try:
        from openai import OpenAI
        return OpenAI(api_key=OPENAI_API_KEY)
    except ImportError:
        print("[MONITOR] Biblioteca 'openai' não instalada.")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Robô de monitoramento editorial Ururau 24h")
    parser.add_argument("--publicar", action="store_true",
                        help="Publica diretamente no CMS além de salvar como rascunho")
    parser.add_argument("--intervalo", type=int, default=None,
                        help="Intervalo entre ciclos em segundos (padrão: .env ou 1800)")
    parser.add_argument("--max-hora", type=int, default=None,
                        help="Máx. publicações por hora (padrão: .env ou 4)")
    parser.add_argument("--ciclo-unico", action="store_true",
                        help="Executa um único ciclo e sai (útil para testes)")
    args = parser.parse_args()

    _criar_pastas()

    from ururau.config.settings import (
        ARQUIVO_DB, MODELO_OPENAI,
        INTERVALO_ENTRE_CICLOS_SEGUNDOS,
        MAX_PUBLICACOES_MONITORAMENTO_POR_HORA,
    )
    from ururau.core.database import get_db
    from ururau.publisher.monitor import MonitorRobo

    db     = get_db(ARQUIVO_DB)
    client = _criar_client_openai()

    intervalo   = args.intervalo or INTERVALO_ENTRE_CICLOS_SEGUNDOS
    max_hora    = args.max_hora  or MAX_PUBLICACOES_MONITORAMENTO_POR_HORA
    publicar    = args.publicar

    print(f"""
╔══════════════════════════════════════════════════╗
║       URURAU — ROBÔ DE MONITORAMENTO 24h         ║
╠══════════════════════════════════════════════════╣
║  Intervalo : {intervalo}s ({intervalo//60}min)
║  Max/hora  : {max_hora} matérias
║  CMS       : {'PUBLICAR DIRETAMENTE' if publicar else 'APENAS RASCUNHO (local)'}
║  Ctrl+C    : parar com segurança
╚══════════════════════════════════════════════════╝
""")

    robo = MonitorRobo(
        db=db,
        client=client,
        modelo=MODELO_OPENAI,
        intervalo_segundos=intervalo,
        max_por_hora=max_hora,
        publicar_no_cms=publicar,
    )

    if args.ciclo_unico:
        print("[MONITOR] Modo ciclo único...")
        robo._executar_ciclo(1)
        return

    try:
        robo.iniciar()
    except KeyboardInterrupt:
        print("\n[MONITOR] Interrompido pelo usuário.")
        robo.parar()


if __name__ == "__main__":
    main()
