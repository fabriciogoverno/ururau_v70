"""
ia/memoria.py — CAMADA 3: Memória editorial dinâmica persistente.

Armazena e recupera preferências, regras, correções, exemplos aprovados,
histórico de erros e pesos editoriais do Ururau.

Persistência: SQLite (banco principal ururau.db, tabelas dedicadas).
Fallback: JSON local (memoria_editorial.json) se o banco não estiver disponível.

A memória NÃO fica só armazenada — ela é INJETADA como contexto em cada
chamada editorial relevante da OpenAI.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

TZ_BR = ZoneInfo("America/Sao_Paulo")
_lock = threading.Lock()

# Caminho padrão do arquivo JSON de fallback
_MEMORIA_JSON = Path("memoria_editorial.json")


# ── Estruturas de dados ───────────────────────────────────────────────────────

@dataclass
class EntradaMemoria:
    """Uma entrada na memória editorial."""
    categoria: str          # regra, veto, exemplo, alerta, peso, preferencia, erro
    chave: str              # identificador único da entrada
    valor: str              # conteúdo
    contexto: str = ""      # contexto de origem (editoria, canal, tipo de pauta)
    recorrencia: int = 1    # quantas vezes foi reforçada
    gravidade: str = "media"  # baixa, media, alta, critica
    ativo: bool = True
    criado_em: str = ""
    atualizado_em: str = ""


@dataclass
class ErroCometido:
    """Registro de erro cometido pela IA e corrigido pelo editor."""
    categoria: str          # erro_factual, erro_data, extrapolacao, etc.
    campo: str              # campo onde ocorreu
    valor_errado: str       # o que a IA gerou
    valor_correto: str      # o que o editor corrigiu para
    contexto_pauta: str = ""
    recorrencia: int = 1
    gravidade: str = "media"
    ultima_ocorrencia: str = ""


@dataclass
class ExemploAprovado:
    """Exemplo de matéria ou campo aprovado pelo editor."""
    tipo: str               # titulo, subtitulo, legenda, retranca, abertura, fecho, materia_completa
    conteudo: str
    editoria: str = ""
    tema: str = ""
    score_qualidade: int = 5  # 1-10
    aprovado_em: str = ""


@dataclass
class PesoRegional:
    """Peso editorial de entidade/tema regional."""
    entidade: str           # nome da cidade, órgão, pessoa ou tema
    tipo: str               # cidade, orgao, pessoa, tema, combinacao
    peso: int = 5           # 1-10
    contexto: str = ""
    ativo: bool = True


# ── Gerenciador de memória ────────────────────────────────────────────────────

class MemoriaEditorial:
    """
    Gerenciador central de memória editorial dinâmica.

    Uso:
        mem = MemoriaEditorial()
        bloco = mem.montar_bloco_contexto(editoria="Política", limite=20)
        # injetar bloco no prompt da OpenAI
    """

    def __init__(self, caminho_db: str = "ururau.db"):
        self._db_path = Path(caminho_db)
        self._json_path = _MEMORIA_JSON
        self._inicializar_tabelas()
        self._seed_inicial()

    # ── Inicialização ─────────────────────────────────────────────────────────

    def _conectar(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _inicializar_tabelas(self):
        """Cria as tabelas de memória se não existirem."""
        try:
            with _lock:
                conn = self._conectar()
                conn.executescript("""
                CREATE TABLE IF NOT EXISTS mem_entradas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    categoria TEXT NOT NULL,
                    chave TEXT NOT NULL,
                    valor TEXT NOT NULL,
                    contexto TEXT DEFAULT '',
                    recorrencia INTEGER DEFAULT 1,
                    gravidade TEXT DEFAULT 'media',
                    ativo INTEGER DEFAULT 1,
                    criado_em TEXT,
                    atualizado_em TEXT,
                    UNIQUE(categoria, chave)
                );

                CREATE TABLE IF NOT EXISTS mem_erros (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    categoria TEXT NOT NULL,
                    campo TEXT NOT NULL,
                    valor_errado TEXT NOT NULL,
                    valor_correto TEXT NOT NULL,
                    contexto_pauta TEXT DEFAULT '',
                    recorrencia INTEGER DEFAULT 1,
                    gravidade TEXT DEFAULT 'media',
                    ultima_ocorrencia TEXT,
                    UNIQUE(categoria, campo, valor_errado)
                );

                CREATE TABLE IF NOT EXISTS mem_exemplos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tipo TEXT NOT NULL,
                    conteudo TEXT NOT NULL,
                    editoria TEXT DEFAULT '',
                    tema TEXT DEFAULT '',
                    score_qualidade INTEGER DEFAULT 5,
                    aprovado_em TEXT
                );

                CREATE TABLE IF NOT EXISTS mem_pesos_regionais (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entidade TEXT NOT NULL UNIQUE,
                    tipo TEXT NOT NULL,
                    peso INTEGER DEFAULT 5,
                    contexto TEXT DEFAULT '',
                    ativo INTEGER DEFAULT 1
                );

                CREATE INDEX IF NOT EXISTS idx_mem_entradas_cat ON mem_entradas(categoria);
                CREATE INDEX IF NOT EXISTS idx_mem_erros_cat ON mem_erros(categoria);
                CREATE INDEX IF NOT EXISTS idx_mem_exemplos_tipo ON mem_exemplos(tipo);
                """)
                conn.commit()
                conn.close()
        except Exception as e:
            print(f"[MEMORIA] Aviso: não foi possível inicializar tabelas SQLite: {e}")

    def _agora(self) -> str:
        return datetime.now(TZ_BR).isoformat(timespec="seconds")

    # ── Escrita ───────────────────────────────────────────────────────────────

    def registrar_entrada(self, e: EntradaMemoria):
        """Insere ou atualiza uma entrada na memória."""
        agora = self._agora()
        try:
            with _lock:
                conn = self._conectar()
                conn.execute("""
                    INSERT INTO mem_entradas
                        (categoria, chave, valor, contexto, recorrencia, gravidade, ativo, criado_em, atualizado_em)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(categoria, chave) DO UPDATE SET
                        valor        = excluded.valor,
                        contexto     = excluded.contexto,
                        recorrencia  = mem_entradas.recorrencia + 1,
                        gravidade    = excluded.gravidade,
                        ativo        = excluded.ativo,
                        atualizado_em = excluded.atualizado_em
                """, (e.categoria, e.chave, e.valor, e.contexto,
                      e.recorrencia, e.gravidade, int(e.ativo), agora, agora))
                conn.commit()
                conn.close()
        except Exception as ex:
            print(f"[MEMORIA] Erro ao registrar entrada: {ex}")

    def registrar_erro(self, err: ErroCometido):
        """Registra um erro cometido pela IA."""
        agora = self._agora()
        try:
            with _lock:
                conn = self._conectar()
                conn.execute("""
                    INSERT INTO mem_erros
                        (categoria, campo, valor_errado, valor_correto, contexto_pauta,
                         recorrencia, gravidade, ultima_ocorrencia)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(categoria, campo, valor_errado) DO UPDATE SET
                        recorrencia       = mem_erros.recorrencia + 1,
                        valor_correto     = excluded.valor_correto,
                        contexto_pauta    = excluded.contexto_pauta,
                        gravidade         = excluded.gravidade,
                        ultima_ocorrencia = excluded.ultima_ocorrencia
                """, (err.categoria, err.campo, err.valor_errado, err.valor_correto,
                      err.contexto_pauta, err.recorrencia, err.gravidade, agora))
                conn.commit()
                conn.close()
        except Exception as ex:
            print(f"[MEMORIA] Erro ao registrar erro: {ex}")

    def registrar_exemplo(self, ex: ExemploAprovado):
        """Registra um exemplo aprovado."""
        agora = self._agora()
        try:
            with _lock:
                conn = self._conectar()
                conn.execute("""
                    INSERT INTO mem_exemplos
                        (tipo, conteudo, editoria, tema, score_qualidade, aprovado_em)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (ex.tipo, ex.conteudo, ex.editoria, ex.tema,
                      ex.score_qualidade, agora))
                conn.commit()
                conn.close()
        except Exception as e:
            print(f"[MEMORIA] Erro ao registrar exemplo: {e}")

    def registrar_peso(self, p: PesoRegional):
        """Insere ou atualiza peso regional de entidade."""
        try:
            with _lock:
                conn = self._conectar()
                conn.execute("""
                    INSERT INTO mem_pesos_regionais (entidade, tipo, peso, contexto, ativo)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(entidade) DO UPDATE SET
                        peso    = excluded.peso,
                        tipo    = excluded.tipo,
                        contexto = excluded.contexto,
                        ativo   = excluded.ativo
                """, (p.entidade, p.tipo, p.peso, p.contexto, int(p.ativo)))
                conn.commit()
                conn.close()
        except Exception as e:
            print(f"[MEMORIA] Erro ao registrar peso: {e}")

    # ── Leitura ───────────────────────────────────────────────────────────────

    def listar_entradas(self, categoria: str | None = None,
                        ativo: bool = True, limite: int = 50) -> list[dict]:
        try:
            conn = self._conectar()
            q = "SELECT * FROM mem_entradas WHERE ativo=?"
            params: list = [int(ativo)]
            if categoria:
                q += " AND categoria=?"
                params.append(categoria)
            q += " ORDER BY recorrencia DESC, atualizado_em DESC LIMIT ?"
            params.append(limite)
            rows = conn.execute(q, params).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def listar_erros(self, limite: int = 30, categoria: str | None = None) -> list[dict]:
        try:
            conn = self._conectar()
            q = "SELECT * FROM mem_erros"
            params: list = []
            if categoria:
                q += " WHERE categoria=?"
                params.append(categoria)
            q += " ORDER BY recorrencia DESC, ultima_ocorrencia DESC LIMIT ?"
            params.append(limite)
            rows = conn.execute(q, params).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def listar_exemplos(self, tipo: str | None = None,
                        editoria: str | None = None, limite: int = 5) -> list[dict]:
        try:
            conn = self._conectar()
            q = "SELECT * FROM mem_exemplos WHERE 1=1"
            params: list = []
            if tipo:
                q += " AND tipo=?"
                params.append(tipo)
            if editoria:
                q += " AND (editoria=? OR editoria='')"
                params.append(editoria)
            q += " ORDER BY score_qualidade DESC, aprovado_em DESC LIMIT ?"
            params.append(limite)
            rows = conn.execute(q, params).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def listar_pesos(self, ativo: bool = True) -> list[dict]:
        try:
            conn = self._conectar()
            rows = conn.execute(
                "SELECT * FROM mem_pesos_regionais WHERE ativo=? ORDER BY peso DESC",
                (int(ativo),)
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception:
            return []

    # ── Montagem de contexto para injeção no prompt ───────────────────────────

    def montar_bloco_contexto(self,
                               editoria: str = "",
                               tema: str = "",
                               limite_erros: int = 10,
                               limite_exemplos: int = 3,
                               limite_regras: int = 15) -> str:
        """
        Monta bloco de texto com memória editorial relevante para injeção no prompt.
        Seletivo: carrega apenas o que é relevante para a ação atual.
        """
        partes: list[str] = []

        # 1. Regras e preferências ativas
        regras = self.listar_entradas(categoria="regra", limite=limite_regras)
        vetos  = self.listar_entradas(categoria="veto",  limite=10)
        alertas = self.listar_entradas(categoria="alerta", limite=8)

        if regras:
            partes.append("== REGRAS EDITORIAIS ATIVAS DO URURAU ==\n" +
                          "\n".join(f"- {r['valor']}" for r in regras))
        if vetos:
            partes.append("== VETOS EDITORIAIS (nunca fazer) ==\n" +
                          "\n".join(f"- {v['valor']}" for v in vetos))
        if alertas:
            partes.append("== ALERTAS EDITORIAIS ATIVOS ==\n" +
                          "\n".join(f"⚠ {a['valor']}" for a in alertas))

        # 2. Erros recentes e recorrentes — injeção crítica de feedback negativo
        erros = self.listar_erros(limite=limite_erros)
        if erros:
            linhas_erros = []
            for e in erros:
                recorr = f" [×{e['recorrencia']}]" if e['recorrencia'] > 1 else ""
                linhas_erros.append(
                    f"- [{e['categoria']}] campo '{e['campo']}': "
                    f"ERRADO='{e['valor_errado'][:80]}' → "
                    f"CORRETO='{e['valor_correto'][:80]}'{recorr}"
                )
            partes.append(
                "== ERROS RECENTES — NÃO REPITA ==\n"
                "Você cometeu os erros abaixo recentemente. Não os repita:\n" +
                "\n".join(linhas_erros)
            )

        # 3. Exemplos aprovados relevantes (few-shot)
        exemplos = self.listar_exemplos(editoria=editoria, limite=limite_exemplos)
        if exemplos:
            linhas_ex = []
            for ex in exemplos:
                linhas_ex.append(
                    f"[{ex['tipo']} / {ex['editoria'] or 'geral'}]: {ex['conteudo'][:200]}"
                )
            partes.append("== EXEMPLOS APROVADOS (referência de qualidade) ==\n" +
                          "\n".join(linhas_ex))

        # 4. Pesos regionais
        pesos = self.listar_pesos()
        if pesos:
            top = [f"{p['entidade']} (peso {p['peso']})" for p in pesos[:12]]
            partes.append("== PESOS REGIONAIS E EDITORIAIS ==\n" +
                          ", ".join(top))

        if not partes:
            return ""

        return (
            "\n\n" + "═" * 60 + "\n"
            "MEMÓRIA EDITORIAL DINÂMICA DO URURAU\n"
            "═" * 60 + "\n\n" +
            "\n\n".join(partes) +
            "\n\n" + "═" * 60
        )

    # ── Extração de aprendizado de auditoria ──────────────────────────────────

    def aprender_de_auditoria(self, json_auditoria: dict, contexto_pauta: str = ""):
        """
        Extrai aprendizado do JSON de auditoria e persiste na memória.
        Chamado automaticamente após cada auditoria com reprovação.
        """
        if not json_auditoria:
            return

        atualizar = json_auditoria.get("atualizar_memoria", {})
        if not atualizar:
            return

        ts = self._agora()

        # Novos erros
        for err_txt in atualizar.get("novos_erros", []):
            if err_txt:
                self.registrar_erro(ErroCometido(
                    categoria="erro_auditoria",
                    campo="geral",
                    valor_errado=str(err_txt)[:300],
                    valor_correto="ver correção manual",
                    contexto_pauta=contexto_pauta,
                    gravidade="alta",
                    ultima_ocorrencia=ts,
                ))

        # Novas regras
        for regra in atualizar.get("novas_regras", []):
            if regra:
                self.registrar_entrada(EntradaMemoria(
                    categoria="regra",
                    chave=f"auditoria_{ts}_{hash(regra) % 99999}",
                    valor=str(regra)[:500],
                    contexto=contexto_pauta,
                    gravidade="alta",
                ))

        # Novos alertas
        for alerta in atualizar.get("novos_alertas", []):
            if alerta:
                self.registrar_entrada(EntradaMemoria(
                    categoria="alerta",
                    chave=f"alerta_{ts}_{hash(alerta) % 99999}",
                    valor=str(alerta)[:500],
                    contexto=contexto_pauta,
                    gravidade="media",
                ))

    def aprender_de_correcao_manual(self,
                                    campo: str,
                                    valor_errado: str,
                                    valor_correto: str,
                                    categoria_erro: str = "correcao_manual",
                                    contexto: str = ""):
        """
        Registra correção manual do editor como memória operacional reutilizável.
        Transforma correção humana em regra/alerta para próximas execuções.
        """
        self.registrar_erro(ErroCometido(
            categoria=categoria_erro,
            campo=campo,
            valor_errado=valor_errado[:400],
            valor_correto=valor_correto[:400],
            contexto_pauta=contexto,
            gravidade="alta",
            ultima_ocorrencia=self._agora(),
        ))

        # Gera alerta automático para campo problemático recorrente
        erros_campo = [e for e in self.listar_erros(categoria=categoria_erro)
                       if e["campo"] == campo]
        if len(erros_campo) >= 2:
            self.registrar_entrada(EntradaMemoria(
                categoria="alerta",
                chave=f"campo_recorrente_{campo}",
                valor=f"Campo '{campo}' tem histórico de erro recorrente. Verifique com cuidado redobrado.",
                gravidade="alta",
            ))

    def aprender_de_aprovacao(self,
                               tipo: str,
                               conteudo: str,
                               editoria: str = "",
                               tema: str = "",
                               score: int = 7):
        """Registra conteúdo aprovado como exemplo para few-shot futuro."""
        self.registrar_exemplo(ExemploAprovado(
            tipo=tipo,
            conteudo=conteudo[:1000],
            editoria=editoria,
            tema=tema,
            score_qualidade=score,
        ))

    # ── Seed inicial de memória ───────────────────────────────────────────────

    def _seed_inicial(self):
        """
        Popula a memória com regras base do Ururau na primeira execução.
        Idempotente — não duplica se já existir.
        """
        regras_base = [
            ("regra", "titulo_max_chars",
             "Título SEO deve ter no máximo 89 caracteres. Contar antes de entregar.",
             "alta"),
            ("regra", "titulo_capa_max",
             "Título de capa deve ter no máximo 60 caracteres.",
             "alta"),
            ("regra", "sem_travessao",
             "Nunca usar travessão (— ou –) no corpo do texto. Substituir por vírgula, ponto ou reescrita.",
             "alta"),
            ("regra", "nome_fonte_multipla",
             "Se a notícia aparece em múltiplas fontes: Nome da fonte = 'Redação'.",
             "alta"),
            ("regra", "credito_foto_limite",
             "Crédito da foto: máximo 6 palavras. Nunca 'Internet'. Nunca inventar.",
             "alta"),
            ("regra", "imagem_dimensao",
             "Dimensão final da imagem: sempre 900x675 px. Usar crop_focal, crop_central ou contain_fundo_falso.",
             "alta"),
            ("regra", "status_fato",
             "Nunca inflar status: debate público ≠ tramitação; investigação ≠ condenação.",
             "critica"),
            ("regra", "sem_invencao",
             "NUNCA inventar fato, data, cargo, número, processo ou reação não presente na fonte.",
             "critica"),
            ("veto", "termos_ia_basicos",
             "Proibido: reforça, reacende, acende o alerta, vale destacar, cabe ressaltar, em meio ao cenário, diante desse cenário.",
             "alta"),
            ("veto", "sem_ururau_no_corpo",
             "Nunca mencionar 'Ururau' ou o próprio veículo dentro do corpo da matéria.",
             "alta"),
            ("veto", "retranca_generica",
             "Nunca usar retranca 'Notícias', 'Geral', 'Atualidade' ou 'Brasil' quando houver opção mais específica.",
             "media"),
            ("alerta", "porto_acu_entidade",
             "Porto do Açu é entidade editorial prioritária. Pautas sobre petróleo, logística, empregos, contratos e expansão têm peso máximo regional.",
             "media"),
            ("alerta", "triangulacao_alerj",
             "Triangulação ALERJ + região Norte Fluminense + verbas/emendas = oportunidade regional forte. Sinalizar.",
             "media"),
        ]

        for cat, chave, valor, gravidade in regras_base:
            try:
                conn = self._conectar()
                conn.execute("""
                    INSERT OR IGNORE INTO mem_entradas
                        (categoria, chave, valor, contexto, recorrencia, gravidade, ativo, criado_em, atualizado_em)
                    VALUES (?, ?, ?, '', 1, ?, 1, ?, ?)
                """, (cat, chave, valor, gravidade, self._agora(), self._agora()))
                conn.commit()
                conn.close()
            except Exception:
                pass

        # Pesos regionais base
        pesos_base = [
            ("Campos dos Goytacazes", "cidade", 10),
            ("Norte Fluminense",      "regiao",  10),
            ("Porto do Açu",          "entidade", 10),
            ("Macaé",                 "cidade",   9),
            ("São João da Barra",     "cidade",   8),
            ("ALERJ",                 "orgao",    9),
            ("Governo RJ",            "orgao",    8),
            ("TCE-RJ",                "orgao",    8),
            ("MPRJ",                  "orgao",    8),
            ("TRE-RJ",                "orgao",    7),
            ("Eleições RJ 2026",      "tema",     9),
            ("São Francisco de Itabapoana", "cidade", 7),
            ("Quissamã",              "cidade",   7),
            ("Rio das Ostras",        "cidade",   7),
        ]

        for entidade, tipo, peso in pesos_base:
            try:
                conn = self._conectar()
                conn.execute("""
                    INSERT OR IGNORE INTO mem_pesos_regionais
                        (entidade, tipo, peso, contexto, ativo)
                    VALUES (?, ?, ?, '', 1)
                """, (entidade, tipo, peso))
                conn.commit()
                conn.close()
            except Exception:
                pass


# ── Singleton global ──────────────────────────────────────────────────────────
_instancia: Optional[MemoriaEditorial] = None

def obter_memoria(caminho_db: str = "ururau.db") -> MemoriaEditorial:
    """Retorna instância singleton da MemoriaEditorial."""
    global _instancia
    if _instancia is None:
        _instancia = MemoriaEditorial(caminho_db)
    return _instancia
