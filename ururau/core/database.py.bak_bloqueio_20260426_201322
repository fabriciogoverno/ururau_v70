"""
core/database.py — Persistência SQLite com abstração clara.
Substitui o modelo frágil baseado apenas em JSON local.
Mantém compatibilidade com o histórico JSON existente na migração.

v41+ — sistema de bloqueio permanente por link:
  - Tabela links_bloqueados: registro definitivo de links descartados/publicados
  - Cache em memória (_links_bloqueados_cache): O(1) lookup sem bater no banco
  - Migração automática: backfill de pautas rejeitadas/publicadas existentes
  - Arquivo .ururau_bloqueados.txt: persiste cache entre reinicializações
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

# ── Cache em memória de links bloqueados ──────────────────────────────────────
# Carregado do banco na inicialização. Lookup O(1) sem SQL.
_links_bloqueados_cache: set[str] = set()
_cache_lock = threading.Lock()

def _cache_add(link: str):
    """Adiciona link ao cache em memória de forma thread-safe."""
    if link:
        with _cache_lock:
            _links_bloqueados_cache.add(link.strip())

def _cache_has(link: str) -> bool:
    """Verifica se link está no cache em memória."""
    if not link:
        return False
    with _cache_lock:
        return link.strip() in _links_bloqueados_cache


class Database:
    """Camada de persistência SQLite thread-safe."""

    def __init__(self, caminho_db: str = "ururau.db"):
        self.caminho = Path(caminho_db)
        self._conn: Optional[sqlite3.Connection] = None
        self._inicializar()

    def _conectar(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.caminho), check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _inicializar(self):
        with _lock:
            conn = self._conectar()
            c = conn.cursor()

            # Tabela principal de pautas
            c.execute("""
            CREATE TABLE IF NOT EXISTS pautas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid TEXT UNIQUE NOT NULL,
                titulo_origem TEXT NOT NULL,
                link_origem TEXT NOT NULL,
                fonte_nome TEXT,
                resumo_origem TEXT,
                canal TEXT,
                score_editorial INTEGER DEFAULT 0,
                status TEXT DEFAULT 'captada',
                urgente INTEGER DEFAULT 0,
                captada_em TEXT,
                atualizada_em TEXT,
                dados_json TEXT
            )""")

            # Tabela de matérias geradas
            c.execute("""
            CREATE TABLE IF NOT EXISTS materias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pauta_uid TEXT NOT NULL,
                versao INTEGER DEFAULT 1,
                titulo TEXT,
                titulo_capa TEXT,
                slug TEXT,
                meta_description TEXT,
                subtitulo TEXT,
                legenda TEXT,
                retranca TEXT,
                tags TEXT,
                conteudo TEXT,
                resumo_curto TEXT,
                chamada_social TEXT,
                score_risco INTEGER DEFAULT 0,
                termos_ia TEXT,
                status TEXT DEFAULT 'rascunho',
                gerada_em TEXT,
                dados_json TEXT,
                FOREIGN KEY (pauta_uid) REFERENCES pautas(uid)
            )""")

            # Tabela de imagens
            c.execute("""
            CREATE TABLE IF NOT EXISTS imagens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pauta_uid TEXT NOT NULL,
                caminho_final TEXT,
                caminho_original TEXT,
                url_origem TEXT,
                dimensoes_origem TEXT,
                estrategia TEXT,
                credito TEXT,
                score_imagem REAL DEFAULT 0,
                aprovada INTEGER DEFAULT 0,
                registrada_em TEXT,
                dados_json TEXT,
                FOREIGN KEY (pauta_uid) REFERENCES pautas(uid)
            )""")

            # Tabela de publicações
            c.execute("""
            CREATE TABLE IF NOT EXISTS publicacoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pauta_uid TEXT NOT NULL,
                canal TEXT,
                titulo_publicado TEXT,
                status TEXT DEFAULT 'rascunho',
                tentativa INTEGER DEFAULT 1,
                publicada_em TEXT,
                erro TEXT,
                dados_json TEXT,
                FOREIGN KEY (pauta_uid) REFERENCES pautas(uid)
            )""")

            # Tabela de auditoria
            c.execute("""
            CREATE TABLE IF NOT EXISTS auditoria (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pauta_uid TEXT,
                acao TEXT NOT NULL,
                detalhe TEXT,
                usuario TEXT DEFAULT 'sistema',
                timestamp TEXT,
                sucesso INTEGER DEFAULT 1
            )""")

            # Tabela de histórico legado (compatibilidade)
            c.execute("""
            CREATE TABLE IF NOT EXISTS historico_legado (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo_origem TEXT,
                titulo_publicado TEXT,
                canal TEXT,
                status TEXT DEFAULT 'rascunho',
                publicado_em TEXT,
                dados_json TEXT
            )""")

            # ── Tabela de bloqueio permanente por link ────────────────────────
            # Garante que links descartados ou publicados NUNCA voltem à fila,
            # mesmo que não tenham passado pelo fluxo completo de salvar_pauta.
            c.execute("""
            CREATE TABLE IF NOT EXISTS links_bloqueados (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                link TEXT UNIQUE NOT NULL,
                uid TEXT,
                titulo TEXT,
                motivo TEXT DEFAULT 'descarte',
                bloqueado_em TEXT
            )""")
            # Índice para busca rápida por link
            c.execute("""
            CREATE INDEX IF NOT EXISTS idx_links_bloqueados_link
            ON links_bloqueados(link)
            """)

            conn.commit()

            # ── Migração automática ───────────────────────────────────────────
            # Garante que bancos existentes recebam as novas tabelas/índices
            # mesmo que já tenham sido criados antes dessa versão.
            self._migrar(conn)

            # ── Carrega cache de links bloqueados em memória ──────────────────
            self._carregar_cache_bloqueados(conn)

            conn.close()

    def _migrar(self, conn):
        """
        Aplica migrações incrementais no banco existente.
        Seguro rodar múltiplas vezes — usa IF NOT EXISTS.
        """
        # Migração 1: tabela links_bloqueados (v41+)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS links_bloqueados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            link TEXT UNIQUE NOT NULL,
            uid TEXT,
            titulo TEXT,
            motivo TEXT DEFAULT 'descarte',
            bloqueado_em TEXT
        )""")
        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_links_bloqueados_link
        ON links_bloqueados(link)
        """)

        # Migração 2: popula links_bloqueados a partir de pautas já rejeitadas/publicadas
        # (backfill para quem já tem banco com histórico)
        conn.execute("""
        INSERT OR IGNORE INTO links_bloqueados (link, uid, titulo, motivo, bloqueado_em)
        SELECT link_origem, uid, titulo_origem,
               CASE WHEN status='publicada' THEN 'publicada'
                    WHEN status='excluida' THEN 'excluida_pelo_editor'
                    ELSE 'descarte' END,
               atualizada_em
        FROM pautas
        WHERE status IN ('rejeitada', 'bloqueada', 'publicada', 'excluida')
          AND link_origem IS NOT NULL
          AND link_origem != ''
        """)

        # Migração 4: adiciona coluna revisao_status na tabela materias (v59+)
        try:
            conn.execute("ALTER TABLE materias ADD COLUMN revisao_status TEXT DEFAULT 'pendente'")
        except Exception:
            pass  # já existe
        try:
            conn.execute("ALTER TABLE materias ADD COLUMN approved_by TEXT DEFAULT ''")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE materias ADD COLUMN approved_at TEXT DEFAULT ''")
        except Exception:
            pass

        # Migração 3: corrige data_pub_fonte com fuso errado (+3h) em pautas captadas
        # antes do fix de fuso (v45). Subtrai 3h de qualquer data_pub_fonte que tenha
        # hora >= 03:00, só uma vez (marcador: migração3_fuso_aplicada na tabela meta).
        conn.execute("""
        CREATE TABLE IF NOT EXISTS _meta (
            chave TEXT PRIMARY KEY,
            valor TEXT
        )""")
        ja_migrou = conn.execute(
            "SELECT valor FROM _meta WHERE chave='migr3_fuso_corrigido'"
        ).fetchone()
        if not ja_migrou:
            try:
                import json as _json
                from datetime import datetime as _dt, timedelta as _td
                rows = conn.execute(
                    "SELECT uid, dados_json FROM pautas WHERE dados_json LIKE '%data_pub_fonte%'"
                ).fetchall()
                corrigidos = 0
                for row in rows:
                    try:
                        d = _json.loads(row[0] or "{}")
                        dpf = (d.get("data_pub_fonte") or "").strip()
                        if not dpf:
                            continue
                        # Formato esperado: "DD/MM/YYYY HH:MM"
                        # Se hora >= 3, provavelmente está em UTC — subtrai 3h
                        dt_obj = _dt.strptime(dpf, "%d/%m/%Y %H:%M")
                        if dt_obj.hour >= 3:
                            dt_corr = dt_obj - _td(hours=3)
                            d["data_pub_fonte"] = dt_corr.strftime("%d/%m/%Y %H:%M")
                            conn.execute(
                                "UPDATE pautas SET dados_json=? WHERE uid=?",
                                (_json.dumps(d, ensure_ascii=False, default=str), row["uid"])
                            )
                            corrigidos += 1
                    except Exception:
                        pass
                conn.execute(
                    "INSERT OR REPLACE INTO _meta (chave, valor) VALUES ('migr3_fuso_corrigido', ?)",
                    (str(corrigidos),)
                )
                if corrigidos:
                    print(f"[DB] Migração 3: corrigidos {corrigidos} data_pub_fonte (fuso UTC→BRT)")
            except Exception as e:
                print(f"[DB] Aviso migração 3: {e}")

        conn.commit()

    def _carregar_cache_bloqueados(self, conn):
        """Carrega todos os links bloqueados do banco para o cache em memória."""
        global _links_bloqueados_cache
        try:
            rows = conn.execute(
                "SELECT link FROM links_bloqueados"
            ).fetchall()
            with _cache_lock:
                for row in rows:
                    if row[0]:
                        _links_bloqueados_cache.add(row[0].strip())
            print(f"[DB] Cache de bloqueio carregado: {len(_links_bloqueados_cache)} links")
        except Exception as e:
            print(f"[DB] Aviso ao carregar cache de bloqueio: {e}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _agora(self) -> str:
        return datetime.now(TZ_BR).strftime("%Y-%m-%d %H:%M:%S")

    def _uid_para_pauta(self, link: str, titulo: str) -> str:
        import hashlib
        return hashlib.md5(f"{link}{titulo}".encode()).hexdigest()[:16]

    # ── Pautas ────────────────────────────────────────────────────────────────

    def salvar_pauta(self, pauta: dict) -> str:
        uid = pauta.get("_uid") or self._uid_para_pauta(
            pauta.get("link_origem", ""), pauta.get("titulo_origem", "")
        )
        with _lock:
            conn = self._conectar()
            try:
                # ── Proteção de exclusão: nunca sobrescreve pautas excluídas ──
                # Se a pauta já existe com status='excluida', ignora o INSERT.
                existente = conn.execute(
                    "SELECT status FROM pautas WHERE uid=? LIMIT 1", (uid,)
                ).fetchone()
                if existente and existente["status"] == "excluida":
                    conn.close()
                    return uid   # pauta excluída — não reativa nunca

                conn.execute("""
                INSERT OR REPLACE INTO pautas
                    (uid, titulo_origem, link_origem, fonte_nome, resumo_origem,
                     canal, score_editorial, status, urgente, captada_em, atualizada_em, dados_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    uid,
                    pauta.get("titulo_origem", ""),
                    pauta.get("link_origem", ""),
                    pauta.get("fonte_nome", ""),
                    pauta.get("resumo_origem", "")[:500],
                    pauta.get("canal_forcado", ""),
                    pauta.get("score_editorial", 0),
                    pauta.get("status", "captada"),
                    1 if pauta.get("urgente") else 0,
                    pauta.get("captada_em", self._agora()),
                    self._agora(),
                    json.dumps(pauta, ensure_ascii=False, default=str),
                ))
                conn.commit()
            finally:
                conn.close()
        return uid

    def buscar_pauta(self, uid: str) -> Optional[dict]:
        with _lock:
            conn = self._conectar()
            try:
                row = conn.execute("SELECT * FROM pautas WHERE uid=?", (uid,)).fetchone()
                if row:
                    return dict(row)
                return None
            finally:
                conn.close()

    def atualizar_status_pauta(self, uid: str, status: str):
        with _lock:
            conn = self._conectar()
            try:
                conn.execute("UPDATE pautas SET status=?, atualizada_em=? WHERE uid=?",
                             (status, self._agora(), uid))
                conn.commit()
            finally:
                conn.close()

    def excluir_pauta(self, uid: str, link: str = "", titulo: str = ""):
        """
        Marca a pauta como 'excluida' e bloqueia o link definitivamente.
        A pauta permanece no banco (auditável), mas fica oculta na fila padrão.
        O link entra na tabela links_bloqueados para não reaparecer em coletas futuras.
        """
        self.atualizar_status_pauta(uid, "excluida")
        if link:
            self.bloquear_link(link, uid, titulo, motivo="excluida_pelo_editor")
        self.log_auditoria(uid, "exclusao", "Excluída manualmente pelo editor", sucesso=True)

    def excluir_pautas_em_lote(self, uids_e_dados: list[tuple[str, str, str]]):
        """
        Exclui várias pautas de uma vez.
        uids_e_dados: lista de (uid, link, titulo)
        """
        for uid, link, titulo in uids_e_dados:
            self.excluir_pauta(uid, link, titulo)

    def reativar_pauta(self, uid: str, link: str = ""):
        """
        Reativa uma pauta excluída: volta para 'captada' e remove o link do bloqueio.
        Útil para recuperar pautas excluídas por engano.
        """
        self.atualizar_status_pauta(uid, "captada")
        if link:
            # Remove da tabela de links bloqueados
            with _lock:
                conn = self._conectar()
                try:
                    conn.execute(
                        "DELETE FROM links_bloqueados WHERE link=? AND motivo='excluida_pelo_editor'",
                        (link,)
                    )
                    conn.commit()
                    # Atualiza cache
                    with _cache_lock:
                        _links_bloqueados_cache.discard(link.strip())
                finally:
                    conn.close()
        self.log_auditoria(uid, "reativacao", "Pauta reativada pelo editor", sucesso=True)

    def link_ja_publicado(self, link: str, janela_horas: int = 48) -> bool:
        from datetime import timedelta
        cutoff = (datetime.now(TZ_BR) - timedelta(hours=janela_horas)).strftime("%Y-%m-%d %H:%M:%S")
        with _lock:
            conn = self._conectar()
            try:
                r = conn.execute(
                    "SELECT 1 FROM pautas WHERE link_origem=? AND status='publicada' AND atualizada_em>=?",
                    (link, cutoff)
                ).fetchone()
                return r is not None
            finally:
                conn.close()

    # ── Checagem anti-repetição ───────────────────────────────────────────────

    def pauta_ja_captada(self, link: str, uid: str = "") -> Optional[dict]:
        """
        Verifica se uma pauta com o mesmo link (ou uid) já foi captada.
        Retorna o registro existente ou None.

        Uso: antes de adicionar nova pauta à fila.
        """
        with _lock:
            conn = self._conectar()
            try:
                # Tenta por link primeiro (mais confiável)
                row = conn.execute(
                    "SELECT uid, status, atualizada_em FROM pautas WHERE link_origem=? LIMIT 1",
                    (link,)
                ).fetchone()
                if row:
                    return dict(row)
                # Fallback por uid (hash md5 do link+titulo)
                if uid:
                    row = conn.execute(
                        "SELECT uid, status, atualizada_em FROM pautas WHERE uid=? LIMIT 1",
                        (uid,)
                    ).fetchone()
                    if row:
                        return dict(row)
                return None
            finally:
                conn.close()

    def pauta_foi_descartada(self, link: str, uid: str = "") -> bool:
        """
        Verifica se a pauta foi explicitamente descartada/bloqueada.

        HOTFIX:
        - Não usa mais link_esta_bloqueado() de forma genérica antes de checar status.
        - Se a pauta atual está ativa no banco, não deve ser tratada como descartada
          apenas porque o link aparece na tabela de bloqueio.
        - Links com motivo de publicação ficam para pauta_ja_publicada().
        """
        status_descartados = ("rejeitada", "bloqueada", "excluida")
        status_ativos = ("captada", "triada", "aprovada", "em_redacao", "revisada", "pronta")

        with _lock:
            conn = self._conectar()
            try:
                # 1. Se existe a pauta atual por UID, o status dela manda.
                if uid:
                    row = conn.execute(
                        "SELECT status FROM pautas WHERE uid=? LIMIT 1",
                        (uid,)
                    ).fetchone()
                    if row:
                        status = row["status"]
                        if status in status_descartados:
                            return True
                        if status in status_ativos or status == "publicada":
                            return False

                # 2. Se não achou por UID, consulta por link.
                if link:
                    row = conn.execute(
                        "SELECT status FROM pautas WHERE link_origem=? ORDER BY id DESC LIMIT 1",
                        (link,)
                    ).fetchone()
                    if row:
                        status = row["status"]
                        if status in status_descartados:
                            return True
                        if status in status_ativos or status == "publicada":
                            return False

                    # 3. Só considera descartada se o motivo do bloqueio NÃO for publicação.
                    row = conn.execute(
                        "SELECT motivo FROM links_bloqueados WHERE link=? LIMIT 1",
                        (link.strip(),)
                    ).fetchone()
                    if row:
                        motivo = (row["motivo"] or "").lower()
                        if motivo.startswith("publicad"):
                            return False
                        return True

                return False
            finally:
                conn.close()

    def pauta_ja_publicada(self, link: str, uid: str = "") -> bool:
        """
        Verifica se a pauta já foi publicada no Ururau.

        HOTFIX:
        - Não usa mais link_esta_bloqueado(), porque essa função mistura
          descartadas, excluídas e publicadas.
        - Só retorna True para publicação real:
          1. status='publicada' na tabela pautas;
          2. motivo de bloqueio começando com 'publicad';
          3. registro em publicacoes com status='publicada'.
        """
        with _lock:
            conn = self._conectar()
            try:
                # 1. Status publicado por UID.
                if uid:
                    row = conn.execute(
                        "SELECT status FROM pautas WHERE uid=? LIMIT 1",
                        (uid,)
                    ).fetchone()
                    if row:
                        return row["status"] == "publicada"

                # 2. Status publicado por link.
                if link:
                    row = conn.execute(
                        "SELECT 1 FROM pautas WHERE link_origem=? AND status='publicada' LIMIT 1",
                        (link,)
                    ).fetchone()
                    if row:
                        return True

                    # 3. Link bloqueado por motivo de publicação, não por descarte.
                    row = conn.execute(
                        "SELECT motivo FROM links_bloqueados WHERE link=? LIMIT 1",
                        (link.strip(),)
                    ).fetchone()
                    if row:
                        motivo = (row["motivo"] or "").lower()
                        if motivo.startswith("publicad"):
                            return True

                    # 4. Registro formal em publicacoes.
                    row = conn.execute(
                        "SELECT 1 FROM publicacoes WHERE dados_json LIKE ? AND status='publicada' LIMIT 1",
                        (f'%"{link}"%',)
                    ).fetchone()
                    if row:
                        return True

                return False
            finally:
                conn.close()

    def classificar_pauta(self, link: str, uid: str = "") -> str:
        """
        Retorna o status atual da pauta ou 'nova' se não existir no banco.

        Possíveis retornos:
          'nova'       — nunca foi captada
          'captada'    — está na fila aguardando processamento
          'em_redacao' — está sendo processada agora
          'pronta'     — matéria gerada, aguardando publicação
          'publicada'  — já foi publicada no Ururau
          'rejeitada'  — foi descartada por critérios editoriais
          'bloqueada'  — bloqueada por risco jurídico

        Uso: ponto único de consulta para decisão de fluxo.
        """
        with _lock:
            conn = self._conectar()
            try:
                row = conn.execute(
                    "SELECT status FROM pautas WHERE link_origem=? LIMIT 1",
                    (link,)
                ).fetchone()
                if not row and uid:
                    row = conn.execute(
                        "SELECT status FROM pautas WHERE uid=? LIMIT 1",
                        (uid,)
                    ).fetchone()
                return row["status"] if row else "nova"
            finally:
                conn.close()

    def titulo_similar_ja_publicado(
        self,
        titulo: str,
        limiar: float = 0.70,
        janela_horas: int = 72,
    ) -> Optional[str]:
        """
        Verifica se um título similar ao informado já foi publicado nas
        últimas `janela_horas` horas.

        Retorna o título publicado similar, ou None se não encontrar.

        Uso: evita publicar duas matérias sobre o mesmo fato com títulos
        diferentes mas conteúdo idêntico.
        """
        from datetime import timedelta
        import re

        cutoff = (datetime.now(TZ_BR) - timedelta(hours=janela_horas)).strftime("%Y-%m-%d %H:%M:%S")

        def _normalizar(t: str) -> set:
            stopwords = {
                "de", "da", "do", "das", "dos", "em", "na", "no", "nas", "nos",
                "e", "ou", "a", "o", "as", "os", "um", "uma", "que", "se",
                "com", "por", "para", "ao", "é", "foi", "ser", "ter",
            }
            palavras = set(re.sub(r"[^\w\s]", "", t.lower()).split())
            return palavras - stopwords

        palavras_alvo = _normalizar(titulo)
        if not palavras_alvo:
            return None

        with _lock:
            conn = self._conectar()
            try:
                rows = conn.execute(
                    """SELECT titulo_origem FROM pautas
                       WHERE status='publicada' AND atualizada_em>=?
                       ORDER BY atualizada_em DESC LIMIT 200""",
                    (cutoff,)
                ).fetchall()
            finally:
                conn.close()

        for row in rows:
            palavras_pub = _normalizar(row["titulo_origem"] or "")
            if not palavras_pub:
                continue
            intersecao = palavras_alvo & palavras_pub
            uniao = palavras_alvo | palavras_pub
            if uniao and len(intersecao) / len(uniao) >= limiar:
                return row["titulo_origem"]

        return None

    def listar_publicadas_recentes(self, horas: int = 48) -> list[dict]:
        """Retorna pautas com status publicada das últimas N horas."""
        from datetime import timedelta
        corte = (datetime.now(TZ_BR) - timedelta(hours=horas)).strftime("%Y-%m-%d %H:%M:%S")
        try:
            with _lock:
                conn = self._conectar()
                try:
                    rows = conn.execute(
                        """SELECT titulo_origem, link_origem, canal, atualizada_em
                           FROM pautas
                           WHERE status = 'publicada'
                           AND atualizada_em >= ?
                           ORDER BY atualizada_em DESC""",
                        (corte,)
                    ).fetchall()
                finally:
                    conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            print(f"[DB] listar_publicadas_recentes: {e}")
            return []

    def bloquear_link(self, link: str, uid: str = "", titulo: str = "",
                      motivo: str = "descarte"):
        """
        Registra um link na lista de bloqueio permanente.

        Dupla persistência:
          1. Cache em memória → lookup O(1) sem SQL em toda coleta futura
          2. Tabela links_bloqueados → persiste entre reinicializações

        Chamado por marcar_descartada() e registrar_publicacao().
        """
        if not link or link.strip() == "":
            return
        link = link.strip()
        # Cache em memória imediato
        _cache_add(link)
        # Persistência no banco
        with _lock:
            conn = self._conectar()
            try:
                conn.execute("""
                INSERT OR IGNORE INTO links_bloqueados
                    (link, uid, titulo, motivo, bloqueado_em)
                VALUES (?,?,?,?,?)
                """, (link, uid, titulo[:300], motivo, self._agora()))
                conn.commit()
            finally:
                conn.close()

    def link_esta_bloqueado(self, link: str) -> bool:
        """
        Verifica se um link está bloqueado permanentemente.

        Primeiro consulta o cache em memória (O(1)), depois o banco se necessário.
        """
        if not link:
            return False
        # Cache em memória — resposta instantânea sem SQL
        if _cache_has(link):
            return True
        # Fallback: consulta o banco (para links adicionados por outras instâncias)
        with _lock:
            conn = self._conectar()
            try:
                r = conn.execute(
                    "SELECT 1 FROM links_bloqueados WHERE link=? LIMIT 1",
                    (link.strip(),)
                ).fetchone()
                if r:
                    _cache_add(link)  # adiciona ao cache para próximas consultas
                return r is not None
            except Exception:
                return False
            finally:
                conn.close()

    def marcar_descartada(self, uid: str, motivo: str = "", pauta: dict = None):
        """
        Marca uma pauta como rejeitada de forma PERMANENTE.

        Dupla garantia:
          1. Atualiza status='rejeitada' na tabela pautas (se existir)
          2. Garante upsert na tabela pautas (INSERT OR REPLACE) se pauta dict fornecido
          3. Insere link na tabela links_bloqueados (barreira definitiva)
        """
        # 1. Tenta atualizar status na tabela pautas (pode não existir ainda)
        self.atualizar_status_pauta(uid, "rejeitada")

        # 2. Se temos o dict completo, garante persistência mesmo que nunca foi salvo
        if pauta:
            pauta_copia = dict(pauta)
            pauta_copia["status"] = "rejeitada"
            pauta_copia["_uid"]   = uid
            try:
                self.salvar_pauta(pauta_copia)
            except Exception:
                pass

        # 3. Registra link no bloqueio permanente
        link   = (pauta or {}).get("link_origem", "") if pauta else ""
        titulo = (pauta or {}).get("titulo_origem", "") if pauta else ""
        if link:
            self.bloquear_link(link, uid, titulo, motivo=motivo or "descarte")

        if motivo:
            self.log_auditoria(uid, "descarte", motivo, sucesso=False)

    # ── Matérias ──────────────────────────────────────────────────────────────

    def salvar_materia(self, pauta_uid: str, materia: dict) -> int:
        versao = self._proxima_versao_materia(pauta_uid)
        with _lock:
            conn = self._conectar()
            try:
                c = conn.execute("""
                INSERT INTO materias
                    (pauta_uid, versao, titulo, titulo_capa, slug, meta_description,
                     subtitulo, legenda, retranca, tags, conteudo, resumo_curto,
                     chamada_social, score_risco, termos_ia, status, gerada_em, dados_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    pauta_uid, versao,
                    materia.get("titulo", ""),
                    materia.get("titulo_capa", ""),
                    materia.get("slug", ""),
                    materia.get("meta_description", ""),
                    materia.get("subtitulo", ""),
                    materia.get("legenda", ""),
                    materia.get("retranca", ""),
                    materia.get("tags", ""),
                    materia.get("conteudo", ""),
                    materia.get("resumo_curto", ""),
                    materia.get("chamada_social", ""),
                    materia.get("score_risco", 0),
                    json.dumps(materia.get("termos_ia_detectados", []), ensure_ascii=False),
                    materia.get("status", "rascunho"),
                    self._agora(),
                    json.dumps(materia, ensure_ascii=False, default=str),
                ))
                conn.commit()
                return c.lastrowid
            finally:
                conn.close()

    def _proxima_versao_materia(self, pauta_uid: str) -> int:
        with _lock:
            conn = self._conectar()
            try:
                r = conn.execute(
                    "SELECT MAX(versao) FROM materias WHERE pauta_uid=?", (pauta_uid,)
                ).fetchone()
                return (r[0] or 0) + 1
            finally:
                conn.close()

    # ── Imagens ───────────────────────────────────────────────────────────────

    def salvar_imagem(self, pauta_uid: str, img: dict):
        with _lock:
            conn = self._conectar()
            try:
                conn.execute("""
                INSERT OR REPLACE INTO imagens
                    (pauta_uid, caminho_final, caminho_original, url_origem,
                     dimensoes_origem, estrategia, credito, score_imagem, aprovada, registrada_em, dados_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    pauta_uid,
                    img.get("caminho_imagem", ""),
                    img.get("caminho_original", ""),
                    img.get("url_imagem", ""),
                    img.get("dimensoes_origem", ""),
                    img.get("estrategia_imagem", ""),
                    img.get("credito_foto", "Reprodução"),
                    img.get("score_imagem", 0),
                    1,
                    self._agora(),
                    json.dumps(img, ensure_ascii=False, default=str),
                ))
                conn.commit()
            finally:
                conn.close()

    # ── Publicações ───────────────────────────────────────────────────────────

    def registrar_publicacao(self, pauta_uid: str, canal: str,
                              titulo: str, sucesso: bool, erro: str = "",
                              link_origem: str = ""):
        """
        Registra uma publicação e, se bem-sucedida, bloqueia o link permanentemente
        para que não seja recoletado.
        """
        with _lock:
            conn = self._conectar()
            try:
                conn.execute("""
                INSERT INTO publicacoes
                    (pauta_uid, canal, titulo_publicado, status, publicada_em, erro, dados_json)
                VALUES (?,?,?,?,?,?,?)
                """, (
                    pauta_uid, canal, titulo,
                    "publicada" if sucesso else "erro",
                    self._agora(), erro, "",
                ))
                conn.commit()
            finally:
                conn.close()

        # Bloqueia link permanentemente se publicação foi bem-sucedida
        if sucesso and link_origem:
            self.bloquear_link(link_origem, pauta_uid, titulo, motivo="publicada")

    # ── Auditoria ─────────────────────────────────────────────────────────────

    def log_auditoria(self, pauta_uid: str, acao: str,
                       detalhe: str = "", sucesso: bool = True, usuario: str = "sistema"):
        with _lock:
            conn = self._conectar()
            try:
                conn.execute("""
                INSERT INTO auditoria (pauta_uid, acao, detalhe, usuario, timestamp, sucesso)
                VALUES (?,?,?,?,?,?)
                """, (pauta_uid, acao, detalhe[:500], usuario, self._agora(), 1 if sucesso else 0))
                conn.commit()
            finally:
                conn.close()

    # ── Histórico (compatibilidade JSON ↔ SQLite) ─────────────────────────────

    def carregar_historico(self) -> list[dict]:
        """Carrega histórico do SQLite + JSON legado, unificados."""
        historico = []
        # SQLite (nova persistência)
        with _lock:
            conn = self._conectar()
            try:
                rows = conn.execute(
                    "SELECT dados_json FROM publicacoes ORDER BY publicada_em DESC LIMIT 200"
                ).fetchall()
                for row in rows:
                    try:
                        historico.append(json.loads(row[0] or "{}"))
                    except Exception:
                        pass
            finally:
                conn.close()
        return historico

    def salvar_historico_legado(self, item: dict):
        """Salva item no histórico legado (compatibilidade com JSON antigo)."""
        with _lock:
            conn = self._conectar()
            try:
                conn.execute("""
                INSERT INTO historico_legado
                    (titulo_origem, titulo_publicado, canal, status, publicado_em, dados_json)
                VALUES (?,?,?,?,?,?)
                """, (
                    item.get("titulo_origem", ""),
                    item.get("titulo_publicado", ""),
                    item.get("canal", ""),
                    item.get("status", "rascunho"),
                    item.get("publicado_em", self._agora()),
                    json.dumps(item, ensure_ascii=False, default=str),
                ))
                conn.commit()
            finally:
                conn.close()

    def contagem_publicacoes_canal_hoje(self, canal: str) -> int:
        hoje = datetime.now(TZ_BR).strftime("%Y-%m-%d")
        with _lock:
            conn = self._conectar()
            try:
                r = conn.execute(
                    "SELECT COUNT(*) FROM publicacoes WHERE canal=? AND publicada_em LIKE ? AND status='publicada'",
                    (canal, f"{hoje}%")
                ).fetchone()
                return r[0] if r else 0
            finally:
                conn.close()

    def estatisticas(self) -> dict:
        with _lock:
            conn = self._conectar()
            try:
                total_pautas     = conn.execute("SELECT COUNT(*) FROM pautas").fetchone()[0]
                total_publicadas = conn.execute("SELECT COUNT(*) FROM publicacoes WHERE status='publicada'").fetchone()[0]
                total_materias   = conn.execute("SELECT COUNT(*) FROM materias").fetchone()[0]
                return {
                    "total_pautas": total_pautas,
                    "total_publicadas": total_publicadas,
                    "total_materias": total_materias,
                }
            finally:
                conn.close()


# ── Singleton global ──────────────────────────────────────────────────────────
_db_instance: Optional[Database] = None

def get_db(caminho: str = "ururau.db") -> Database:
    global _db_instance
    if _db_instance is None:
        _db_instance = Database(caminho)
    return _db_instance


# ── Compatibilidade JSON legado ────────────────────────────────────────────────
def carregar_historico_json(arquivo: str = "historico_unico.json") -> list[dict]:
    try:
        p = Path(arquivo)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []

def salvar_historico_json(lista: list[dict], arquivo: str = "historico_unico.json"):
    try:
        Path(arquivo).write_text(
            json.dumps(lista, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        print(f"[DB] Erro ao salvar histórico JSON: {e}")
