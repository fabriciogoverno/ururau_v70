"""
ia/logger.py — Log centralizado e rastreável de todas as ações editoriais de IA.

Registra em SQLite (tabela ia_logs) e opcionalmente em arquivo de texto.
Cada entrada contém: ação, timestamp, modelo, contextos usados, entrada,
saída, resultado da auditoria, decisão final, erros, atualização de memória.

Permite auditoria completa de qualquer matéria gerada — quem pediu, o quê
foi enviado, o quê voltou, o quê foi bloqueado e por quê.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

TZ_BR = ZoneInfo("America/Sao_Paulo")
_lock = threading.Lock()

# Arquivo de log texto (opcional, complementar ao banco)
_LOG_FILE = Path("logs/ia_editorial.log")


class IALogger:
    """Logger central para todas as ações editoriais de IA."""

    def __init__(self, caminho_db: str = "ururau.db"):
        self._db_path = Path(caminho_db)
        self._inicializar()

    def _conectar(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _inicializar(self):
        try:
            with _lock:
                conn = self._conectar()
                conn.execute("""
                CREATE TABLE IF NOT EXISTS ia_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    acao TEXT NOT NULL,
                    pauta_uid TEXT DEFAULT '',
                    titulo_pauta TEXT DEFAULT '',
                    canal TEXT DEFAULT '',
                    modo_operacional TEXT DEFAULT 'painel',
                    modelo TEXT DEFAULT '',
                    contextos_usados TEXT DEFAULT '',
                    memoria_carregada INTEGER DEFAULT 0,
                    feedback_carregado INTEGER DEFAULT 0,
                    exemplos_usados INTEGER DEFAULT 0,
                    json_geracao TEXT DEFAULT '',
                    json_auditoria TEXT DEFAULT '',
                    aprovado INTEGER DEFAULT 0,
                    bloqueado INTEGER DEFAULT 1,
                    status_publicacao TEXT DEFAULT 'bloquear',
                    erros TEXT DEFAULT '',
                    violacoes_factuais TEXT DEFAULT '',
                    violacoes_editoriais TEXT DEFAULT '',
                    memoria_atualizada INTEGER DEFAULT 0,
                    tentativas_geracao INTEGER DEFAULT 0,
                    tentativas_auditoria INTEGER DEFAULT 0,
                    log_completo TEXT DEFAULT ''
                )
                """)
                conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ia_logs_ts
                ON ia_logs(timestamp)
                """)
                conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ia_logs_pauta
                ON ia_logs(pauta_uid)
                """)
                conn.commit()
                conn.close()
        except Exception as e:
            print(f"[IALOGGER] Aviso: não foi possível inicializar tabela ia_logs: {e}")

    def _agora(self) -> str:
        return datetime.now(TZ_BR).isoformat(timespec="seconds")

    def _escrever_arquivo(self, linha: str):
        """Escreve linha no arquivo de log texto (cria diretório se necessário)."""
        try:
            _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(linha + "\n")
        except Exception:
            pass

    def registrar(
        self,
        acao: str,
        pauta_uid: str = "",
        titulo_pauta: str = "",
        canal: str = "",
        modo_operacional: str = "painel",
        modelo: str = "",
        contextos_usados: list[str] | None = None,
        memoria_carregada: bool = False,
        feedback_carregado: bool = False,
        exemplos_usados: int = 0,
        json_geracao: dict | None = None,
        json_auditoria: dict | None = None,
        aprovado: bool = False,
        bloqueado: bool = True,
        status_publicacao: str = "bloquear",
        erros: list[str] | None = None,
        violacoes_factuais: list[str] | None = None,
        violacoes_editoriais: list[str] | None = None,
        memoria_atualizada: bool = False,
        tentativas_geracao: int = 0,
        tentativas_auditoria: int = 0,
        log_completo: list[str] | None = None,
    ):
        """Registra entrada de log no banco e no arquivo de texto."""
        ts = self._agora()
        try:
            with _lock:
                conn = self._conectar()
                conn.execute("""
                    INSERT INTO ia_logs (
                        timestamp, acao, pauta_uid, titulo_pauta, canal,
                        modo_operacional, modelo, contextos_usados,
                        memoria_carregada, feedback_carregado, exemplos_usados,
                        json_geracao, json_auditoria,
                        aprovado, bloqueado, status_publicacao,
                        erros, violacoes_factuais, violacoes_editoriais,
                        memoria_atualizada, tentativas_geracao, tentativas_auditoria,
                        log_completo
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    ts, acao, pauta_uid, titulo_pauta[:120], canal,
                    modo_operacional, modelo,
                    json.dumps(contextos_usados or [], ensure_ascii=False),
                    int(memoria_carregada), int(feedback_carregado), exemplos_usados,
                    json.dumps(json_geracao or {}, ensure_ascii=False)[:8000],
                    json.dumps(json_auditoria or {}, ensure_ascii=False)[:8000],
                    int(aprovado), int(bloqueado), status_publicacao,
                    json.dumps(erros or [], ensure_ascii=False),
                    json.dumps(violacoes_factuais or [], ensure_ascii=False),
                    json.dumps(violacoes_editoriais or [], ensure_ascii=False),
                    int(memoria_atualizada),
                    tentativas_geracao, tentativas_auditoria,
                    "\n".join(log_completo or [])[:4000],
                ))
                conn.commit()
                conn.close()
        except Exception as e:
            print(f"[IALOGGER] Erro ao registrar: {e}")

        # Linha resumida no arquivo de texto
        status_str = "OK" if aprovado else "BLOQ"
        erros_str = f" | erros={len(erros or [])}" if erros else ""
        linha = (
            f"[{ts}] {acao.upper()} | {status_str} | {canal} | {modo_operacional} | "
            f"modelo={modelo} | status={status_publicacao}{erros_str} | {titulo_pauta[:60]}"
        )
        self._escrever_arquivo(linha)
        print(linha)

    def registrar_de_resultado(self, resultado, pauta: dict, acao: str = "geracao_completa"):
        """
        Atalho: registra a partir de um ResultadoPipeline.
        """
        from ururau.ia.pipeline import ResultadoPipeline  # import local evita circular
        if not isinstance(resultado, ResultadoPipeline):
            return
        self.registrar(
            acao=acao,
            pauta_uid=pauta.get("_uid") or pauta.get("uid", ""),
            titulo_pauta=pauta.get("titulo_origem", ""),
            canal=pauta.get("canal_forcado") or pauta.get("canal", ""),
            modo_operacional=getattr(resultado, "_modo_operacional", "painel"),
            modelo=resultado.modelo_usado,
            memoria_carregada=True,
            json_geracao=resultado.json_geracao,
            json_auditoria=resultado.json_auditoria,
            aprovado=resultado.aprovado_auditoria,
            bloqueado=resultado.bloqueado,
            status_publicacao=resultado.status_publicacao,
            erros=resultado.todos_erros,
            violacoes_factuais=resultado.violacoes_factuais,
            violacoes_editoriais=resultado.violacoes_editoriais,
            memoria_atualizada=bool(resultado.json_auditoria.get("atualizar_memoria")),
            tentativas_geracao=resultado.tentativas_geracao,
            tentativas_auditoria=resultado.tentativas_auditoria,
            log_completo=resultado.log,
        )

    def listar_recentes(self, limite: int = 20) -> list[dict]:
        """Lista os logs mais recentes."""
        try:
            conn = self._conectar()
            rows = conn.execute(
                "SELECT * FROM ia_logs ORDER BY id DESC LIMIT ?", (limite,)
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def listar_bloqueados(self, limite: int = 50) -> list[dict]:
        """Lista matérias bloqueadas pela auditoria."""
        try:
            conn = self._conectar()
            rows = conn.execute(
                "SELECT * FROM ia_logs WHERE bloqueado=1 ORDER BY id DESC LIMIT ?",
                (limite,)
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception:
            return []


# ── Singleton global ──────────────────────────────────────────────────────────
_logger_inst: Optional[IALogger] = None

def obter_logger(caminho_db: str = "ururau.db") -> IALogger:
    global _logger_inst
    if _logger_inst is None:
        _logger_inst = IALogger(caminho_db)
    return _logger_inst
