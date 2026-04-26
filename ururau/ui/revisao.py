"""
ui/revisao.py — Painel de Revisão Editorial do Ururau (v59)

Substitui o antigo botão "Manual" na toolbar pelo fluxo estruturado de revisão.

Funcionalidades:
  - Lista de matérias que precisam de atenção humana (rascunhos, bloqueadas, pendentes)
  - Filtros: Todos, Pendentes, Reprovados, Corrigíveis, Bloqueados
  - Visualização de erros agrupados por categoria (EDITORIAL_BLOCKER, FIXABLE_FIELD, WARNING)
  - Ações: Corrigir pendências, Editar, Publicar, Revisar com IA, Aprovar manualmente
  - Comparação com a fonte original
  - Publicar só habilitado quando can_publish() retorna True
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from typing import Optional, TYPE_CHECKING, Callable

# tkinter é opcional: funções auxiliares puras (usadas em testes) não precisam dele
try:
    import tkinter as tk
    from tkinter import ttk, messagebox, scrolledtext, simpledialog
    _TK_DISPONIVEL = True
except ImportError:
    tk = None  # type: ignore
    ttk = None  # type: ignore
    messagebox = None  # type: ignore
    scrolledtext = None  # type: ignore
    simpledialog = None  # type: ignore
    _TK_DISPONIVEL = False

from ururau.config.settings import (
    MODELO_OPENAI,
    StatusPauta,
    LIMIAR_RISCO_MAXIMO,
    CategoriaErro,
)

if TYPE_CHECKING:
    from openai import OpenAI
    from ururau.core.database import Database

# ── Paleta (herda do painel principal) ───────────────────────────────────────
COR_FUNDO    = "#0f0f1a"
COR_PAINEL   = "#1a1a2e"
COR_TEXTO    = "#e2e8f0"
COR_VERDE    = "#22c55e"
COR_AMARELO  = "#eab308"
COR_VERMELHO = "#ef4444"
COR_CINZA    = "#64748b"
COR_AZUL     = "#0ea5e9"
COR_ROXO     = "#8b5cf6"
COR_LARANJA  = "#f97316"
COR_CIANO    = "#06b6d4"
COR_DESTAQUE = "#7c3aed"

FONTE_MONO    = ("Courier New", 10)
FONTE_TITULO  = ("Helvetica", 13, "bold")
FONTE_NORMAL  = ("Helvetica", 11)
FONTE_PEQUENA = ("Helvetica", 9)
FONTE_ITEM_T  = ("Segoe UI", 10, "bold")
FONTE_META    = ("Segoe UI", 8)

# ── Cores de status validação ─────────────────────────────────────────────────
_COR_STATUS = {
    "aprovado":           COR_VERDE,
    "pendente":           COR_AMARELO,
    "reprovado":          COR_VERMELHO,
    "rascunho":           "#60a5fa",   # azul claro
    "bloqueado":          COR_VERMELHO,
    "pronta":             COR_VERDE,
    "publicada":          "#10b981",
    "erro_configuracao":  COR_LARANJA,  # CONFIG_ERROR — falha de API/config
    "erro_extracao":      COR_ROXO,     # EXTRACTION_ERROR — fonte inválida/vazia
}

# ── Critérios de "matéria em revisão" ────────────────────────────────────────
# Uma matéria entra na fila de revisão se satisfaz qualquer condição abaixo.
_STATUS_REVISAO = {StatusPauta.REVISADA, StatusPauta.BLOQUEADA, StatusPauta.EM_REDACAO}
_STATUS_PAUTA_REVISAO = {
    StatusPauta.REVISADA, StatusPauta.BLOQUEADA,
    StatusPauta.EM_REDACAO, StatusPauta.PRONTA,  # pronta mas reprovada
}


def _parse_materia(pauta: dict) -> Optional[dict]:
    m = pauta.get("materia")
    if isinstance(m, dict):
        return m
    if isinstance(m, str):
        try:
            return json.loads(m)
        except Exception:
            pass
    return None


def _status_validacao_da_materia(md: dict) -> str:
    """Extrai o status de validação padronizado de uma matéria."""
    sv = md.get("status_validacao")
    if isinstance(sv, dict):
        return "aprovado" if sv.get("aprovado") else "reprovado"
    if isinstance(sv, str) and sv:
        return sv
    # Fallback: inferir do status da auditoria
    if md.get("auditoria_aprovada") and not md.get("auditoria_bloqueada"):
        return "aprovado"
    if md.get("auditoria_bloqueada"):
        return "reprovado"
    return "pendente"


def _pub_sugerida(pauta: dict, md: Optional[dict]) -> str:
    """Extrai sugestão de publicação do artigo."""
    if md:
        ps = md.get("status_publicacao_sugerido") or md.get("status_pipeline") or ""
        if ps:
            return ps
    if pauta.get("auditoria_bloqueada"):
        return "bloquear"
    return "salvar_rascunho"


def _erros_validacao(md: Optional[dict]) -> list[dict]:
    """Extrai lista padronizada de erros de validação."""
    if not md:
        return []
    erros_brutos = md.get("erros_validacao") or []
    erros_out = []
    for e in erros_brutos:
        if isinstance(e, dict):
            erros_out.append(e)
        elif isinstance(e, str):
            # Converte string legada para dict padronizado
            erros_out.append({
                "codigo": "",
                "categoria": "EDITORIAL_BLOCKER",
                "severidade": "alta",
                "campo": "",
                "mensagem": e,
                "trecho": "",
                "sugestao": "",
                "bloqueia_publicacao": True,
                "corrigivel_automaticamente": False,
            })
    # Complementa com auditoria_erros se não houver erros estruturados
    if not erros_out:
        aud_erros = md.get("auditoria_erros") or []
        for e in aud_erros:
            erros_out.append({
                "codigo": "",
                "categoria": "EDITORIAL_BLOCKER",
                "severidade": "alta",
                "campo": "",
                "mensagem": str(e),
                "trecho": "",
                "sugestao": "",
                "bloqueia_publicacao": True,
                "corrigivel_automaticamente": False,
            })
    return erros_out


def _e_config_error(md: Optional[dict]) -> bool:
    """Retorna True se a matéria tem um erro de configuração (CONFIG_ERROR)."""
    if not md:
        return False
    if md.get("_is_config_error"):
        return True
    sv = md.get("status_validacao", "")
    if isinstance(sv, str) and sv == "erro_configuracao":
        return True
    erros = _erros_validacao(md)
    return any(e.get("categoria") == CategoriaErro.CONFIG_ERROR for e in erros)


def _e_extraction_error(md: Optional[dict]) -> bool:
    """Retorna True se a matéria tem um erro de extração (EXTRACTION_ERROR)."""
    if not md:
        return False
    sv = md.get("status_validacao", "")
    if isinstance(sv, str) and sv == "erro_extracao":
        return True
    erros = _erros_validacao(md)
    return any(e.get("categoria") == CategoriaErro.EXTRACTION_ERROR for e in erros)


def _e_para_revisao(pauta: dict) -> bool:
    """Retorna True se a pauta/matéria deve aparecer na fila de revisão."""
    status = pauta.get("status", "")
    md = _parse_materia(pauta)
    if not md:
        return False  # sem matéria gerada — não é candidato a revisão

    # CONFIG_ERROR e EXTRACTION_ERROR sempre entram na fila de revisão
    if _e_config_error(md) or _e_extraction_error(md):
        return True

    # Checagem dos critérios normais
    if status in (StatusPauta.BLOQUEADA, StatusPauta.REVISADA):
        return True
    if md.get("auditoria_bloqueada"):
        return True
    if md.get("revisao_humana_necessaria"):
        return True
    sv = _status_validacao_da_materia(md)
    if sv in ("pendente", "reprovado", "erro_configuracao", "erro_extracao"):
        return True
    pub = _pub_sugerida(pauta, md)
    if pub in ("salvar_rascunho", "bloquear"):
        return True
    # "pronta" mas com erros ainda presentes
    if status == StatusPauta.PRONTA and _erros_validacao(md):
        return True
    return False


def _e_corrigivel(md: Optional[dict]) -> bool:
    """Retorna True se há erros do tipo FIXABLE_FIELD (sem EDITORIAL_BLOCKER)."""
    erros = _erros_validacao(md)
    tem_fixable = any(e.get("categoria") == "FIXABLE_FIELD" for e in erros)
    tem_blocker = any(e.get("categoria") == "EDITORIAL_BLOCKER" for e in erros)
    return tem_fixable and not tem_blocker


def _safe_parent(widget) -> "tk.Widget | None":
    """
    v62: Retorna um parent válido para messagebox / Toplevel.

    Resolve AttributeError: 'PainelRevisao' object has no attribute 'tk'
    quando o widget passado não é um tk.Widget legítimo.

    Estratégia:
      1. Se widget tem `.tk` e `.winfo_exists()` retorna True → usa widget.
      2. Caso contrário, procura raiz Tk via _default_root.
      3. Se nada disponível → None (deixa tkinter usar default).
    """
    if not _TK_DISPONIVEL or widget is None:
        return None
    try:
        # tk.Widget tem .tk e winfo_exists
        if hasattr(widget, "tk") and hasattr(widget, "winfo_exists"):
            if widget.winfo_exists():
                return widget
    except Exception:
        pass
    # Tenta default root
    try:
        return tk._default_root  # type: ignore[attr-defined]
    except Exception:
        return None


# ── Painel de Revisão ─────────────────────────────────────────────────────────

# Base class depende da disponibilidade do tkinter
_FrameBase = tk.Frame if _TK_DISPONIVEL else object


class PainelRevisao(_FrameBase):  # type: ignore[misc]
    """
    Painel de revisão editorial.

    Usado como substituto da lista principal quando o usuário clica "Revisão".
    Pode ser embutido diretamente no frame esquerdo do PainelUrurau ou
    aberto como Toplevel.

    v63 fix: _get_parent() retorna parent VÁLIDO para messagebox/Toplevel,
    inclusive quando a instância foi criada via __new__ (sem __init__) —
    como faz painel.py para acesso headless aos métodos de revisão.
    """

    def _get_parent(self):
        """
        Retorna um widget Tk valido para usar como parent em
        messagebox/Toplevel. Funciona tanto quando self e um tk.Frame real
        (instancia normal) quanto quando self foi criado via __new__
        (instancia headless usada como container de metodos).
        """
        if not _TK_DISPONIVEL:
            return None
        # Caso 1: self é um Tk widget legítimo (tem .tk)
        try:
            if hasattr(self, "tk") and hasattr(self, "winfo_exists") and self.winfo_exists():
                return self
        except Exception:
            pass
        # Caso 2: self tem _parent armazenado pelo __init__
        try:
            p = getattr(self, "_parent", None)
            if p is not None and hasattr(p, "tk"):
                return p
        except Exception:
            pass
        # Caso 3: usa default root do Tk
        try:
            r = tk._default_root  # type: ignore[attr-defined]
            if r is not None:
                return r
        except Exception:
            pass
        return None

    def __init__(
        self,
        parent,
        db: "Database",
        client: "OpenAI",
        modelo: str = MODELO_OPENAI,
        on_select: Optional[Callable[[dict], None]] = None,
        on_fechar: Optional[Callable[[], None]] = None,
        **kwargs,
    ):
        # ── v62: Inicialização segura ────────────────────────────────────────
        # Se tk não está disponível, PainelRevisao herda de object — o
        # super().__init__(parent, ...) deve degradar para super().__init__()
        # para evitar AttributeError: 'PainelRevisao' object has no attribute 'tk'.
        if _TK_DISPONIVEL:
            super().__init__(parent, bg=COR_FUNDO, **kwargs)
        else:
            super().__init__()  # Modo headless / testes sem tkinter

        self.db = db
        self.client = client
        self.modelo = modelo
        self._on_select = on_select   # callback ao selecionar item (atualiza painel dir.)
        self._on_fechar = on_fechar   # callback ao fechar (volta para fila normal)
        self._parent = parent          # guardado para uso como parent de dialogs

        self._pautas: list[dict] = []
        self._filtradas: list[dict] = []
        self._sel: Optional[dict] = None

        # Apenas constrói UI e agenda carga se tk está disponível
        if _TK_DISPONIVEL:
            self._construir()
            self.after(100, self.carregar)

    # ── Construção da UI ──────────────────────────────────────────────────────

    def _construir(self):
        # Cabeçalho
        hdr = tk.Frame(self, bg="#0d0d20")
        hdr.pack(fill="x")
        tk.Label(hdr, text="📋 Revisão Editorial", bg="#0d0d20",
                 fg=COR_AMARELO, font=FONTE_TITULO).pack(side="left", padx=8, pady=6)

        # Botão fechar / voltar para fila normal
        if self._on_fechar:
            tk.Button(hdr, text="✕ Voltar à fila", command=self._on_fechar,
                      bg="#1e293b", fg=COR_CINZA, relief="flat",
                      font=FONTE_PEQUENA, padx=6, pady=2, cursor="hand2"
                      ).pack(side="right", padx=8)

        # Faixa de filtros
        ff = tk.Frame(self, bg=COR_PAINEL)
        ff.pack(fill="x", padx=6, pady=2)
        tk.Label(ff, text="Filtro:", bg=COR_PAINEL, fg=COR_CINZA,
                 font=FONTE_PEQUENA).pack(side="left", padx=4)
        self._filtro_var = tk.StringVar(value="Todos")
        _filtros = ("Todos", "Pendentes", "Reprovados", "Corrigíveis", "Bloqueados",
                    "Erro de Config", "Extração")
        _filtro_cores = {
            "Erro de Config": COR_LARANJA,
            "Extração":       COR_ROXO,
        }
        for label in _filtros:
            cor_fg = _filtro_cores.get(label, COR_TEXTO)
            tk.Radiobutton(
                ff, text=label, variable=self._filtro_var, value=label,
                command=self._aplicar_filtro,
                bg=COR_PAINEL, fg=cor_fg, selectcolor=COR_FUNDO,
                activebackground=COR_PAINEL, font=FONTE_PEQUENA,
            ).pack(side="left", padx=2)

        # Campo de busca
        tk.Label(ff, text="Busca:", bg=COR_PAINEL, fg=COR_CINZA,
                 font=FONTE_PEQUENA).pack(side="left", padx=(8, 2))
        self._busca_var = tk.StringVar()
        tk.Entry(ff, textvariable=self._busca_var, bg=COR_FUNDO, fg=COR_TEXTO,
                 insertbackground=COR_TEXTO, font=FONTE_PEQUENA,
                 width=18).pack(side="left")
        self._busca_var.trace_add("write", lambda *_: self._aplicar_filtro())

        self._lbl_contagem = tk.Label(ff, text="", bg=COR_PAINEL, fg=COR_CINZA,
                                      font=FONTE_PEQUENA)
        self._lbl_contagem.pack(side="right", padx=8)

        # Lista de itens (scrollable)
        cont = tk.Frame(self, bg=COR_FUNDO)
        cont.pack(fill="both", expand=True, padx=4, pady=4)
        sb = tk.Scrollbar(cont, orient="vertical")
        sb.pack(side="right", fill="y")
        self._canvas = tk.Canvas(cont, bg=COR_FUNDO, bd=0, highlightthickness=0,
                                  yscrollcommand=sb.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        sb.config(command=self._canvas.yview)
        self._lista_frame = tk.Frame(self._canvas, bg=COR_FUNDO)
        self._canvas_win = self._canvas.create_window(
            (0, 0), window=self._lista_frame, anchor="nw")
        self._lista_frame.bind(
            "<Configure>",
            lambda e: self._canvas.configure(
                scrollregion=self._canvas.bbox("all")))
        self._canvas.bind(
            "<Configure>",
            lambda e: self._canvas.itemconfig(self._canvas_win, width=e.width))

        # Status bar
        self._lbl_status = tk.Label(self, text="Carregando...", bg=COR_FUNDO,
                                     fg=COR_CINZA, font=FONTE_PEQUENA, anchor="w")
        self._lbl_status.pack(fill="x", padx=8, pady=2)

    # ── Carregamento de dados ─────────────────────────────────────────────────

    def carregar(self):
        """Carrega da DB as pautas que precisam de revisão."""
        self._lbl_status.config(text="Carregando matérias para revisão...")
        threading.Thread(target=self._carregar_thread, daemon=True).start()

    def _carregar_thread(self):
        try:
            conn = self.db._conectar()
            try:
                rows = conn.execute(
                    "SELECT uid, titulo_origem, status, urgente, "
                    "score_editorial, dados_json, fonte_nome, "
                    "captada_em, atualizada_em "
                    "FROM pautas "
                    "WHERE status NOT IN ('publicada', 'excluida', 'captada', 'triada') "
                    "ORDER BY atualizada_em DESC LIMIT 500"
                ).fetchall()
                pautas = []
                for row in rows:
                    d = dict(row)
                    try:
                        extra = json.loads(d.get("dados_json") or "{}")
                        d.update(extra)
                    except Exception:
                        pass
                    if _e_para_revisao(d):
                        pautas.append(d)
            finally:
                conn.close()
            self._pautas = pautas
            self.after(0, self._aplicar_filtro)
        except Exception as e:
            self.after(0, lambda: self._lbl_status.config(
                text=f"Erro ao carregar: {e}"))

    def _aplicar_filtro(self):
        filtro = self._filtro_var.get()
        busca = self._busca_var.get().lower().strip()

        def _match(p: dict) -> bool:
            md = _parse_materia(p)
            if busca:
                campos = [
                    p.get("titulo_origem", ""),
                    p.get("fonte_nome", ""),
                    (md or {}).get("titulo", ""),
                    (md or {}).get("retranca", ""),
                ]
                if not any(busca in (c or "").lower() for c in campos):
                    return False
            if filtro == "Todos":
                return True
            sv = _status_validacao_da_materia(md or {})
            pub = _pub_sugerida(p, md)
            if filtro == "Pendentes":
                return sv == "pendente"
            if filtro == "Reprovados":
                return sv == "reprovado"
            if filtro == "Corrigíveis":
                return _e_corrigivel(md)
            if filtro == "Bloqueados":
                return bool(p.get("auditoria_bloqueada") or
                            (md or {}).get("auditoria_bloqueada") or
                            pub == "bloquear")
            if filtro == "Erro de Config":
                return _e_config_error(md)
            if filtro == "Extração":
                return _e_extraction_error(md)
            return True

        self._filtradas = [p for p in self._pautas if _match(p)]
        self._renderizar_lista()
        n = len(self._filtradas)
        total = len(self._pautas)
        self._lbl_contagem.config(text=f"{n}/{total}")
        msg = f"{n} matéria(s) para revisão." if n else "Nenhuma matéria pendente de revisão."
        self._lbl_status.config(text=msg)

    def _renderizar_lista(self):
        for w in self._lista_frame.winfo_children():
            w.destroy()

        if not self._filtradas:
            tk.Label(self._lista_frame, text="✓ Nenhuma matéria pendente de revisão.",
                     bg=COR_FUNDO, fg=COR_VERDE, font=FONTE_NORMAL,
                     pady=40).pack()
            return

        for i, pauta in enumerate(self._filtradas):
            self._criar_item(i, pauta)

    def _criar_item(self, idx: int, pauta: dict):
        md = _parse_materia(pauta)
        sv = _status_validacao_da_materia(md or {})
        pub = _pub_sugerida(pauta, md)
        erros = _erros_validacao(md)
        n_err = len(erros)
        n_blocker = sum(1 for e in erros if e.get("categoria") == "EDITORIAL_BLOCKER")
        n_fixable = sum(1 for e in erros if e.get("categoria") == "FIXABLE_FIELD")
        n_config = sum(1 for e in erros if e.get("categoria") == CategoriaErro.CONFIG_ERROR)
        n_extr   = sum(1 for e in erros if e.get("categoria") == CategoriaErro.EXTRACTION_ERROR)
        is_cfg_err = _e_config_error(md)
        is_ext_err = _e_extraction_error(md)

        cor_bg = "#131325" if idx % 2 == 0 else "#1c1c35"
        # STATUS badge: usa cor específica para erros de sistema
        if is_cfg_err:
            cor_sv = COR_LARANJA
            sv_label = "ERRO CONFIG"
        elif is_ext_err:
            cor_sv = COR_ROXO
            sv_label = "ERRO EXTRAÇÃO"
        else:
            cor_sv = _COR_STATUS.get(sv, COR_CINZA)
            sv_label = sv.upper()

        frame = tk.Frame(self._lista_frame, bg=cor_bg, bd=0,
                         highlightthickness=1,
                         highlightbackground=COR_LARANJA if is_cfg_err else (
                             COR_ROXO if is_ext_err else "#2d2d4a"))
        frame.pack(fill="x", padx=2, pady=1)

        # Linha de título + status
        l1 = tk.Frame(frame, bg=cor_bg)
        l1.pack(fill="x", padx=8, pady=(6, 2))
        titulo_disp = (md or {}).get("titulo") or pauta.get("titulo_origem", "")
        tk.Label(l1, text=titulo_disp[:80], bg=cor_bg, fg=COR_TEXTO,
                 font=FONTE_ITEM_T, anchor="w").pack(side="left", fill="x", expand=True)
        tk.Label(l1, text=sv_label, bg=cor_sv, fg="white",
                 font=FONTE_META, padx=5, pady=1).pack(side="right")

        # Linha de metadados
        l2 = tk.Frame(frame, bg=cor_bg)
        l2.pack(fill="x", padx=8, pady=(0, 2))
        canal = pauta.get("canal_forcado") or pauta.get("canal") or (md or {}).get("canal", "")
        fonte = pauta.get("fonte_nome", "")
        data = pauta.get("atualizada_em", "")[:16]
        tk.Label(l2, text=f"{canal}  |  {fonte}  |  {data}",
                 bg=cor_bg, fg=COR_CINZA, font=FONTE_META, anchor="w").pack(side="left")

        # Linha de erros + status publicação + ações
        l3 = tk.Frame(frame, bg=cor_bg)
        l3.pack(fill="x", padx=8, pady=(0, 6))

        if is_cfg_err:
            tk.Label(l3, text="⚙ ERRO DE CONFIGURAÇÃO — verifique a API key",
                     bg=cor_bg, fg=COR_LARANJA, font=FONTE_META).pack(side="left")
        elif is_ext_err:
            tk.Label(l3, text="⚠ ERRO DE EXTRAÇÃO — fonte vazia ou inválida",
                     bg=cor_bg, fg=COR_ROXO, font=FONTE_META).pack(side="left")
        elif n_err:
            cor_err = COR_VERMELHO if n_blocker else COR_AMARELO
            err_txt = f"⚠ {n_err} erros"
            if n_blocker:
                err_txt += f" ({n_blocker} blocker)"
            if n_fixable:
                err_txt += f" / {n_fixable} corrigíveis"
            tk.Label(l3, text=err_txt, bg=cor_bg, fg=cor_err,
                     font=FONTE_META).pack(side="left")
        else:
            tk.Label(l3, text="Sem erros registrados", bg=cor_bg, fg=COR_CINZA,
                     font=FONTE_META).pack(side="left")

        # Sugestão de publicação
        pub_map = {
            "publicar": ("PUBLICAR", COR_VERDE),
            "publicar_direto": ("PUBLICAR", COR_VERDE),
            "salvar_rascunho": ("RASCUNHO", COR_AMARELO),
            "bloquear": ("BLOQUEADO", COR_VERMELHO),
        }
        p_txt, p_cor = pub_map.get(pub, ("?", COR_CINZA))
        tk.Label(l3, text=p_txt, bg=cor_bg, fg=p_cor,
                 font=FONTE_META).pack(side="left", padx=(12, 0))

        # Botão "Abrir revisão"
        _p = pauta  # capture

        def _abrir(p=_p):
            self._selecionar(p)

        tk.Button(l3, text="Abrir revisão →", command=_abrir,
                  bg=COR_DESTAQUE, fg="white", relief="flat",
                  font=FONTE_META, padx=8, pady=2, cursor="hand2"
                  ).pack(side="right")

        # Botões especiais para erros de sistema
        if is_cfg_err:
            def _abrir_config(p=pauta):
                self._acao_abrir_config(p)

            def _reprocessar(p=pauta):
                self._acao_reprocessar_geracao(p)

            tk.Button(l3, text="⚙ Abrir Config", command=_abrir_config,
                      bg=COR_LARANJA, fg="white", relief="flat",
                      font=FONTE_META, padx=6, pady=2, cursor="hand2"
                      ).pack(side="right", padx=(0, 4))
            tk.Button(l3, text="↻ Reprocessar", command=_reprocessar,
                      bg="#b45309", fg="white", relief="flat",
                      font=FONTE_META, padx=6, pady=2, cursor="hand2"
                      ).pack(side="right", padx=(0, 4))

        elif is_ext_err:
            def _reprocessar_ext(p=pauta):
                self._acao_reprocessar_geracao(p)

            tk.Button(l3, text="↻ Reprocessar", command=_reprocessar_ext,
                      bg=COR_ROXO, fg="white", relief="flat",
                      font=FONTE_META, padx=6, pady=2, cursor="hand2"
                      ).pack(side="right", padx=(0, 4))

    def _selecionar(self, pauta: dict):
        self._sel = pauta
        if self._on_select:
            self._on_select(pauta)

    def _acao_abrir_config(self, pauta: dict):
        """
        Abre janela informativa sobre como corrigir o erro de configuração.
        Orienta o usuário a verificar a chave de API nas configurações.
        """
        md = _parse_materia(pauta) or {}
        erros = _erros_validacao(md)
        cfg_erros = [e for e in erros if e.get("categoria") == CategoriaErro.CONFIG_ERROR]

        msg_erros = "\n".join(
            f"  • [{e.get('codigo','')}] {e.get('mensagem','')}"
            for e in cfg_erros
        ) or "  • Chave de API OpenAI ausente ou inválida."

        dlg = tk.Toplevel(self._get_parent())
        dlg.title("Erro de Configuração — API OpenAI")
        dlg.geometry("520x360")
        dlg.configure(bg=COR_FUNDO)
        dlg.grab_set()
        dlg.resizable(False, False)

        tk.Label(dlg, text="⚙ Erro de Configuração Detectado",
                 bg=COR_FUNDO, fg=COR_LARANJA, font=FONTE_TITULO,
                 wraplength=480).pack(padx=16, pady=(14, 4))
        tk.Label(dlg, text="O pipeline abortou porque a chave de API OpenAI está ausente "
                 "ou inválida. O artigo NÃO foi gerado — nenhum conteúdo falso foi criado.",
                 bg=COR_FUNDO, fg=COR_TEXTO, font=FONTE_PEQUENA,
                 wraplength=480, justify="left").pack(padx=16, pady=(0, 8))

        tk.Label(dlg, text="Erros detectados:", bg=COR_FUNDO, fg=COR_CINZA,
                 font=FONTE_PEQUENA, anchor="w").pack(fill="x", padx=16, pady=(4, 0))
        t = scrolledtext.ScrolledText(dlg, bg="#1a1a2e", fg=COR_LARANJA,
                                      font=FONTE_MONO, height=5, wrap="word",
                                      state="normal")
        t.insert("1.0", msg_erros)
        t.config(state="disabled")
        t.pack(fill="x", padx=16, pady=(2, 8))

        tk.Label(dlg, text="Para corrigir:\n"
                 "1. Acesse Configurações → Produção → API Key OpenAI\n"
                 "2. Verifique a chave em platform.openai.com/account/api-keys\n"
                 "3. Salve e use 'Reprocessar' para regenerar o artigo.",
                 bg=COR_FUNDO, fg=COR_TEXTO, font=FONTE_PEQUENA,
                 wraplength=480, justify="left").pack(padx=16, pady=(0, 8))

        tk.Button(dlg, text="Fechar", command=dlg.destroy,
                  bg=COR_LARANJA, fg="white", relief="flat", font=FONTE_NORMAL,
                  padx=12, pady=6, cursor="hand2").pack(pady=8)

    def _acao_reprocessar_geracao(self, pauta: dict):
        """
        Marca o artigo para reprocessamento de geração.
        Remove flags de CONFIG_ERROR/EXTRACTION_ERROR e reseta o status
        para que o pipeline possa ser executado novamente.
        """
        md = _parse_materia(pauta) or {}
        uid = pauta.get("uid") or pauta.get("_uid", "")
        if not uid:
            messagebox.showerror("Erro", "UID não encontrado.", parent=self._get_parent())
            return

        is_cfg = _e_config_error(md)
        is_ext = _e_extraction_error(md)

        tipo_erro = "Erro de Configuração" if is_cfg else "Erro de Extração"
        if not messagebox.askyesno(
            "Reprocessar Geração",
            f"Reprocessar geração para:\n«{pauta.get('titulo_origem','')[:60]}»\n\n"
            f"Tipo de erro: {tipo_erro}\n\n"
            "O artigo será marcado como pendente de reprocessamento.\n"
            "Certifique-se de que a configuração foi corrigida antes de reprocessar.\n\n"
            "Continuar?",
            parent=self._get_parent(),
        ):
            return

        # Remove flags de erro e reseta status para reprocessamento
        md.pop("_is_config_error", None)
        erros_originais = _erros_validacao(md)
        # Preserva apenas erros que NÃO sejam CONFIG_ERROR nem EXTRACTION_ERROR
        md["erros_validacao"] = [
            e for e in erros_originais
            if e.get("categoria") not in (
                CategoriaErro.CONFIG_ERROR, CategoriaErro.EXTRACTION_ERROR
            )
        ]
        # Reseta status para indicar que precisa ser reprocessado
        md["status_validacao"] = "pendente"
        md["corpo_materia"] = ""  # Garante que não há conteúdo residual
        md["status_publicacao_sugerido"] = "salvar_rascunho"

        agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        hist = md.get("historico_correcoes") or []
        hist.append({
            "tipo": "reprocessamento_solicitado",
            "erro_original": tipo_erro,
            "timestamp": agora,
            "solicitado_por": "revisao_manual",
        })
        md["historico_correcoes"] = hist

        try:
            self.db.salvar_materia(uid, md)
            pauta["materia"] = md
            # Atualiza status da pauta para em_redacao para que o pipeline processe
            conn = self.db._conectar()
            try:
                conn.execute(
                    "UPDATE pautas SET status = 'em_redacao' WHERE uid = ?",
                    (uid,)
                )
                conn.commit()
            finally:
                conn.close()
            self.db.log_auditoria(uid, "reprocessamento_solicitado",
                                  f"Erro original: {tipo_erro}")
        except Exception as e:
            messagebox.showerror("Erro", f"Falha ao salvar: {e}", parent=self._get_parent())
            return

        messagebox.showinfo(
            "Reprocessar",
            f"Artigo marcado para reprocessamento.\n\n"
            f"Status resetado para 'em_redacao'.\n"
            f"Execute o pipeline novamente para regenerar o artigo.",
            parent=self._get_parent(),
        )
        self.carregar()

    # ── Ações de revisão ──────────────────────────────────────────────────────

    def corrigir_pendencias(self, pauta: dict, callback_ok: Optional[Callable] = None):
        """
        Corrige automaticamente apenas campos FIXABLE_FIELD.
        NÃO reescreve o corpo da matéria.
        """
        md = _parse_materia(pauta)
        if not md:
            messagebox.showwarning("Corrigir", "Matéria não encontrada.", parent=self._get_parent())
            return

        corrigidos = []
        agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # ── 1. Tags: máximo de 8, pelo menos 3 ───────────────────────────────
        tags = md.get("tags", "") or ""
        if isinstance(tags, list):
            lista_tags = tags
        else:
            lista_tags = [t.strip() for t in str(tags).split(",") if t.strip()]
        if len(lista_tags) > 8:
            md["tags"] = ", ".join(lista_tags[:8])
            corrigidos.append("tags reduzidas para 8")
        elif len(lista_tags) < 3 and md.get("retranca"):
            # Adiciona retranca como tag se faltar
            extra = md.get("retranca", "").strip()
            if extra and extra not in lista_tags:
                lista_tags.append(extra)
                md["tags"] = ", ".join(lista_tags)
                corrigidos.append("tag de retranca adicionada")

        # ── 2. meta_description: gera se ausente ou muito curta ──────────────
        meta = md.get("meta_description", "") or ""
        if len(meta.strip()) < 60:
            corpo = md.get("conteudo", "") or ""
            # Usa primeiros 160 chars do primeiro parágrafo como meta
            primeiro_par = (corpo.split("\n\n") or [""])[0].strip()
            if primeiro_par:
                novo_meta = primeiro_par[:160]
                md["meta_description"] = novo_meta
                corrigidos.append("meta_description gerada")

        # ── 3. legenda_curta: usa legenda se ausente ─────────────────────────
        if not (md.get("legenda_curta") or "").strip():
            leg = (md.get("legenda") or "").strip()
            if leg:
                md["legenda_curta"] = leg[:120]
                corrigidos.append("legenda_curta preenchida")

        # ── 4. legenda_instagram: gera se ausente ────────────────────────────
        if not (md.get("legenda_instagram") or "").strip():
            chamada = (md.get("chamada_social") or md.get("subtitulo") or "").strip()
            if chamada:
                md["legenda_instagram"] = chamada[:200]
                corrigidos.append("legenda_instagram preenchida")

        # ── 5. nome_da_fonte: usa fonte_nome da pauta ────────────────────────
        if not (md.get("nome_da_fonte") or "").strip():
            fn = pauta.get("fonte_nome", "Redação").strip() or "Redação"
            md["nome_da_fonte"] = fn
            corrigidos.append(f"nome_da_fonte preenchido: '{fn}'")

        # ── 6. creditos_da_foto: usa default se ausente ───────────────────────
        if not (md.get("creditos_da_foto") or "").strip():
            cred = pauta.get("imagem_credito", "") or "Reprodução"
            md["creditos_da_foto"] = cred
            corrigidos.append(f"creditos_da_foto preenchido: '{cred}'")

        # ── 7. titulo_capa: gera versão encurtada SEGURA se ausente/longo ────
        tc = (md.get("titulo_capa") or "").strip()
        if not tc or len(tc) > 60:
            titulo_seo = (md.get("titulo") or md.get("titulo_seo") or "").strip()
            if titulo_seo:
                # safe_title: corta no espaço, remove conector fraco final
                from ururau.editorial.safe_title import safe_title, LIMITE_TITULO_CAPA
                novo_tc = safe_title(titulo_seo, LIMITE_TITULO_CAPA)
                md["titulo_capa"] = novo_tc
                corrigidos.append("titulo_capa ajustado (safe_title)")

        # ── 8. fonte_nome: normaliza se muito longa ───────────────────────────
        fn = (md.get("nome_da_fonte") or "").strip()
        if len(fn) > 60:
            md["nome_da_fonte"] = fn[:60]
            corrigidos.append("nome_da_fonte encurtado")

        # ── 9. imagem_estrategia: valida ─────────────────────────────────────
        est = (md.get("imagem_estrategia") or pauta.get("imagem_estrategia") or "").strip()
        _validas = {"scraping", "bing", "arquivo", "placeholder", "manual"}
        if est and est not in _validas:
            md["imagem_estrategia"] = "manual"
            corrigidos.append("imagem_estrategia normalizada")

        if not corrigidos:
            messagebox.showinfo("Corrigir", "Nenhum campo FIXABLE_FIELD encontrado para corrigir.",
                                parent=self._get_parent())
            return

        # Registra no histórico de correções
        hist = md.get("historico_correcoes") or []
        hist.append({
            "tipo": "correcao_automatica",
            "campos": corrigidos,
            "timestamp": agora,
        })
        md["historico_correcoes"] = hist

        # Persiste no banco
        uid = pauta.get("uid") or pauta.get("_uid", "")
        if uid:
            try:
                self.db.salvar_materia(uid, md)
                pauta["materia"] = md
                self.db.log_auditoria(uid, "correcao_automatica",
                                      f"Campos: {', '.join(corrigidos)}")
            except Exception as e:
                messagebox.showerror("Erro", f"Falha ao salvar: {e}", parent=self._get_parent())
                return

        messagebox.showinfo("Corrigir", f"Corrigido:\n• " + "\n• ".join(corrigidos), parent=self._get_parent())
        if callback_ok:
            callback_ok()
        # Recarrega a lista
        self.carregar()

    def publicar_revisao(self, pauta: dict, on_publicar: Optional[Callable] = None):
        """
        Verifica can_publish() antes de delegar a publicação ao painel principal.
        Se bloqueado, exibe motivo claro.
        """
        md = _parse_materia(pauta) or {}
        ok, motivo = _can_publish_artigo(pauta, md)
        if not ok:
            messagebox.showwarning(
                "Publicação Bloqueada",
                f"Este artigo NÃO pode ser publicado.\n\n{motivo}",
                parent=self._get_parent(),
            )
            return
        if on_publicar:
            on_publicar(pauta)
        else:
            messagebox.showinfo("Publicar", "Delegue ao fluxo principal de publicação.", parent=self._get_parent())

    def aprovar_manualmente(self, pauta: dict, callback_ok: Optional[Callable] = None):
        """
        Abre diálogo de aprovação manual com nome e motivo.
        Salva: approved_by, approved_at, manual_approval_reason, histórico.
        NÃO apaga erros de validação — apenas permite publicação.
        """
        md = _parse_materia(pauta) or {}
        uid = pauta.get("uid") or pauta.get("_uid", "")
        if not uid:
            messagebox.showerror("Erro", "UID não encontrado.", parent=self._get_parent())
            return

        dlg = tk.Toplevel(self._get_parent())
        dlg.title("Aprovação Manual")
        dlg.geometry("500x340")
        dlg.configure(bg=COR_FUNDO)
        dlg.grab_set()
        dlg.resizable(False, False)

        tk.Label(dlg, text="Aprovação Manual — override da validação automática",
                 bg=COR_FUNDO, fg=COR_AMARELO, font=FONTE_NORMAL, wraplength=460
                 ).pack(padx=16, pady=(12, 4))
        tk.Label(dlg, text="⚠ O histórico de erros será preservado. Esta ação é auditada.",
                 bg=COR_FUNDO, fg=COR_LARANJA, font=FONTE_PEQUENA, wraplength=460
                 ).pack(padx=16, pady=(0, 8))

        campos = {}
        for lbl, key in [("Aprovado por (nome/cargo) *", "approved_by"),
                          ("Motivo da aprovação manual *", "reason")]:
            tk.Label(dlg, text=lbl, bg=COR_FUNDO, fg=COR_TEXTO,
                     font=FONTE_PEQUENA, anchor="w").pack(fill="x", padx=16, pady=(4, 0))
            w = tk.Entry(dlg, bg=COR_PAINEL, fg=COR_TEXTO, insertbackground=COR_TEXTO,
                         font=FONTE_NORMAL)
            w.pack(fill="x", padx=16, pady=(0, 4))
            campos[key] = w

        def confirmar():
            nome = campos["approved_by"].get().strip()
            motivo = campos["reason"].get().strip()
            if not nome or not motivo:
                messagebox.showerror("Campos obrigatórios",
                                     "Nome e motivo são obrigatórios.", parent=dlg)
                return
            agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            md["approved_by"] = nome
            md["approved_at"] = agora
            md["manual_approval_reason"] = motivo
            # Preserva histórico de erros — NÃO apaga auditoria_erros nem erros_validacao
            hist = md.get("historico_correcoes") or []
            hist.append({
                "tipo": "aprovacao_manual",
                "approved_by": nome,
                "motivo": motivo,
                "timestamp": agora,
                "erros_existentes": len(_erros_validacao(md)),
            })
            md["historico_correcoes"] = hist
            try:
                self.db.salvar_materia(uid, md)
                pauta["materia"] = md
                self.db.log_auditoria(uid, "aprovacao_manual",
                                      f"Por: {nome} | Motivo: {motivo[:60]}")
            except Exception as e:
                messagebox.showerror("Erro", f"Falha ao salvar: {e}", parent=dlg)
                return
            dlg.destroy()
            messagebox.showinfo("Aprovação", f"Aprovado manualmente por {nome}.\n"
                                f"O artigo pode ser publicado.", parent=self._get_parent())
            if callback_ok:
                callback_ok()
            self.carregar()

        tk.Button(dlg, text="✔ Confirmar aprovação", command=confirmar,
                  bg=COR_VERDE, fg="white", relief="flat", font=FONTE_NORMAL,
                  padx=12, pady=6, cursor="hand2").pack(pady=12)
        tk.Button(dlg, text="Cancelar", command=dlg.destroy,
                  bg="#1e293b", fg=COR_CINZA, relief="flat", font=FONTE_PEQUENA,
                  padx=8, cursor="hand2").pack()

    def abrir_edicao(self, pauta: dict, callback_salvo: Optional[Callable] = None):
        """
        Abre janela de edição dos campos editáveis da matéria.
        Após salvar, roda validação e atualiza status.
        """
        md = _parse_materia(pauta) or {}
        uid = pauta.get("uid") or pauta.get("_uid", "")
        if not uid:
            messagebox.showerror("Erro", "UID não encontrado.", parent=self._get_parent())
            return

        dlg = tk.Toplevel(self._get_parent())
        dlg.title("Editar Matéria")
        dlg.geometry("800x680")
        dlg.configure(bg=COR_FUNDO)
        dlg.grab_set()

        nb = ttk.Notebook(dlg)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        campos_widgets: dict[str, tk.Widget] = {}

        # ── Aba: Títulos e metadados ──────────────────────────────────────────
        f_meta = tk.Frame(nb, bg=COR_PAINEL)
        nb.add(f_meta, text="Títulos e Meta")

        _campos_meta = [
            ("titulo_seo (titulo)", "titulo"),
            ("subtitulo_curto (subtitulo)", "subtitulo"),
            ("retranca", "retranca"),
            ("titulo_capa", "titulo_capa"),
            ("slug", "slug"),
            ("meta_description", "meta_description"),
            ("nome_da_fonte", "nome_da_fonte"),
            ("creditos_da_foto", "creditos_da_foto"),
        ]
        for i, (lbl, key) in enumerate(_campos_meta):
            tk.Label(f_meta, text=lbl, bg=COR_PAINEL, fg=COR_CINZA,
                     font=FONTE_PEQUENA, anchor="w").grid(
                row=i*2, column=0, sticky="w", padx=10, pady=(6, 0))
            val = str(md.get(key, "") or "")
            e = tk.Entry(f_meta, bg=COR_FUNDO, fg=COR_TEXTO, insertbackground=COR_TEXTO,
                         font=FONTE_MONO, width=72)
            e.insert(0, val)
            e.grid(row=i*2+1, column=0, sticky="ew", padx=10, pady=(0, 2))
            campos_widgets[key] = e
        f_meta.columnconfigure(0, weight=1)

        # Tags
        i_tags = len(_campos_meta)
        tk.Label(f_meta, text="tags (separadas por vírgula)", bg=COR_PAINEL, fg=COR_CINZA,
                 font=FONTE_PEQUENA, anchor="w").grid(
            row=i_tags*2, column=0, sticky="w", padx=10, pady=(6, 0))
        tags_val = ", ".join(md.get("tags", []) or []) if isinstance(md.get("tags"), list) else str(md.get("tags", "") or "")
        e_tags = tk.Entry(f_meta, bg=COR_FUNDO, fg=COR_TEXTO, insertbackground=COR_TEXTO,
                          font=FONTE_MONO, width=72)
        e_tags.insert(0, tags_val)
        e_tags.grid(row=i_tags*2+1, column=0, sticky="ew", padx=10, pady=(0, 2))
        campos_widgets["tags"] = e_tags

        # ── Aba: Corpo ────────────────────────────────────────────────────────
        f_corpo = tk.Frame(nb, bg=COR_PAINEL)
        nb.add(f_corpo, text="Corpo da Matéria")
        tk.Label(f_corpo, text="corpo_materia (conteudo)", bg=COR_PAINEL, fg=COR_CINZA,
                 font=FONTE_PEQUENA, anchor="w").pack(fill="x", padx=8, pady=(6, 0))
        t_corpo = scrolledtext.ScrolledText(f_corpo, bg="#16213e", fg=COR_TEXTO,
                                            font=FONTE_MONO, height=20, wrap="word",
                                            insertbackground=COR_TEXTO)
        t_corpo.insert("1.0", md.get("conteudo", "") or "")
        t_corpo.pack(fill="both", expand=True, padx=8, pady=4)
        campos_widgets["conteudo"] = t_corpo

        # ── Aba: Legendas ─────────────────────────────────────────────────────
        f_leg = tk.Frame(nb, bg=COR_PAINEL)
        nb.add(f_leg, text="Legendas e Social")
        for lbl, key in [("legenda_curta", "legenda_curta"),
                          ("legenda_instagram", "legenda_instagram"),
                          ("chamada_social", "chamada_social"),
                          ("resumo_curto", "resumo_curto")]:
            tk.Label(f_leg, text=lbl, bg=COR_PAINEL, fg=COR_CINZA,
                     font=FONTE_PEQUENA, anchor="w").pack(fill="x", padx=8, pady=(6, 0))
            t = tk.Text(f_leg, bg=COR_FUNDO, fg=COR_TEXTO, font=FONTE_MONO,
                        height=3, insertbackground=COR_TEXTO, wrap="word")
            t.insert("1.0", md.get(key, "") or "")
            t.pack(fill="x", padx=8, pady=(0, 2))
            campos_widgets[key] = t

        # ── Botões ────────────────────────────────────────────────────────────
        bf = tk.Frame(dlg, bg=COR_FUNDO)
        bf.pack(fill="x", padx=8, pady=6)

        def salvar():
            # Lê todos os campos
            for key, w in campos_widgets.items():
                if isinstance(w, scrolledtext.ScrolledText) or isinstance(w, tk.Text):
                    val = w.get("1.0", "end").strip()
                else:
                    val = w.get().strip()
                md[key] = val
            # Mapeia titulo_seo → titulo para compatibilidade
            if "titulo" in md and not md.get("titulo_seo"):
                md["titulo_seo"] = md["titulo"]
            # Registra no histórico
            agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            hist = md.get("historico_correcoes") or []
            hist.append({
                "tipo": "edicao_manual",
                "campos": list(campos_widgets.keys()),
                "timestamp": agora,
            })
            md["historico_correcoes"] = hist
            # Persiste
            try:
                self.db.salvar_materia(uid, md)
                pauta["materia"] = md
                self.db.log_auditoria(uid, "edicao_manual",
                                      f"Campos editados: {len(campos_widgets)}")
            except Exception as e:
                messagebox.showerror("Erro", f"Falha ao salvar: {e}", parent=dlg)
                return
            dlg.destroy()
            messagebox.showinfo("Salvo", "Matéria atualizada com sucesso.\n"
                                "Rode nova validação para atualizar o status.", parent=self._get_parent())
            if callback_salvo:
                callback_salvo()
            self.carregar()

        tk.Button(bf, text="💾 Salvar edições", command=salvar,
                  bg=COR_VERDE, fg="white", relief="flat", font=FONTE_NORMAL,
                  padx=12, pady=6, cursor="hand2").pack(side="left", padx=4)
        tk.Button(bf, text="Cancelar", command=dlg.destroy,
                  bg="#1e293b", fg=COR_CINZA, relief="flat", font=FONTE_PEQUENA,
                  padx=8, cursor="hand2").pack(side="left")

    def revisar_com_ia(self, pauta: dict, callback_ok: Optional[Callable] = None):
        """
        Revisa com IA apenas os campos com EDITORIAL_BLOCKER.
        NÃO reescreve o corpo completo.
        Usa o modelo de IA configurado.
        """
        if not self.client:
            messagebox.showerror("IA indisponível",
                                 "Cliente OpenAI não configurado.", parent=self._get_parent())
            return
        md = _parse_materia(pauta) or {}
        erros = _erros_validacao(md)
        blockers = [e for e in erros if e.get("categoria") == "EDITORIAL_BLOCKER"]
        if not blockers:
            messagebox.showinfo("IA", "Não há EDITORIAL_BLOCKERs para revisar.",
                                parent=self._get_parent())
            return
        if not messagebox.askyesno("Revisar com IA",
            f"Revisar {len(blockers)} campo(s) bloqueado(s) com IA?\n"
            "O corpo da matéria NÃO será reescrito por completo.",
            parent=self._get_parent()):
            return

        def _thread():
            try:
                resumo_erros = "\n".join(
                    f"- [{e.get('campo','')}] {e.get('mensagem','')}"
                    for e in blockers[:5]
                )
                prompt = (
                    f"Você é um editor. A matéria abaixo tem os seguintes erros:\n"
                    f"{resumo_erros}\n\n"
                    f"Corrija APENAS os campos indicados acima. "
                    f"NÃO reescreva o corpo completo.\n"
                    f"Responda apenas com um JSON com os campos corrigidos.\n\n"
                    f"Matéria atual (JSON):\n"
                    f"{json.dumps({k: md.get(k,'') for k in ['titulo','titulo_capa','subtitulo','retranca','legenda','nome_da_fonte']}, ensure_ascii=False)}"
                )
                resp = self.client.chat.completions.create(
                    model=self.modelo,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    max_tokens=800,
                )
                texto = resp.choices[0].message.content or ""
                # Tenta extrair JSON
                m = re.search(r'\{[^{}]+\}', texto, re.DOTALL)
                if m:
                    correcoes = json.loads(m.group())
                    for k, v in correcoes.items():
                        if k in md:
                            md[k] = v
                    uid = pauta.get("uid") or pauta.get("_uid", "")
                    self.db.salvar_materia(uid, md)
                    pauta["materia"] = md
                    self.db.log_auditoria(uid, "revisao_ia",
                                          f"Campos: {list(correcoes.keys())}")
                    self.after(0, lambda: messagebox.showinfo(
                        "IA", f"Campos corrigidos: {list(correcoes.keys())}", parent=self._get_parent()))
                    self.after(0, self.carregar)
                    if callback_ok:
                        self.after(0, callback_ok)
                else:
                    self.after(0, lambda: messagebox.showwarning(
                        "IA", f"IA não retornou JSON válido:\n{texto[:200]}", parent=self._get_parent()))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror(
                    "IA", f"Erro: {e}", parent=self._get_parent()))

        threading.Thread(target=_thread, daemon=True).start()


# ── Helper compartilhado: can_publish para UI ────────────────────────────────

def _can_publish_artigo(pauta: dict, md: dict) -> tuple[bool, str]:
    """
    Wrapper de UI para can_publish().
    Aceita pauta e matéria separados.
    """
    from ururau.publisher.workflow import can_publish as _can
    # Mescla campos relevantes para o gate
    artigo = {**pauta, **md}
    return _can(artigo)


# ── Detalhe de revisão: aba de erros agrupados ───────────────────────────────

def montar_texto_erros(md: Optional[dict]) -> str:
    """
    Monta texto formatado de erros agrupados por categoria para exibição na aba Auditoria.
    """
    if not md:
        return "Matéria não disponível."

    erros = _erros_validacao(md)
    if not erros:
        # Sem erros estruturados — exibe dados da auditoria clássica
        aud_erros = md.get("auditoria_erros") or []
        if not aud_erros:
            return "✓ Nenhum erro de validação registrado."
        linhas = ["⚠ ERROS DA AUDITORIA (legado):", ""]
        for e in aud_erros:
            linhas.append(f"  • {e}")
        return "\n".join(linhas)

    grupos: dict[str, list] = {
        "CONFIG_ERROR":      [],
        "EXTRACTION_ERROR":  [],
        "EDITORIAL_BLOCKER": [],
        "FIXABLE_FIELD":     [],
        "WARNING":           [],
    }
    for e in erros:
        cat = e.get("categoria", "WARNING")
        grupos.setdefault(cat, []).append(e)

    linhas = []
    icones = {
        "CONFIG_ERROR":      "🔴 ERRO DE CONFIGURAÇÃO (API/Sistema)",
        "EXTRACTION_ERROR":  "🟠 ERRO DE EXTRAÇÃO (Fonte inválida)",
        "EDITORIAL_BLOCKER": "🔴 BLOQUEADOR EDITORIAL",
        "FIXABLE_FIELD":     "🟡 CAMPO CORRIGÍVEL",
        "WARNING":           "🔵 AVISO",
    }
    for cat in ("CONFIG_ERROR", "EXTRACTION_ERROR", "EDITORIAL_BLOCKER", "FIXABLE_FIELD", "WARNING"):
        itens = grupos.get(cat, [])
        if not itens:
            continue
        linhas += ["", f"{'-'*56}", icones[cat], f"{'-'*56}"]
        for e in itens:
            campo = e.get("campo", "")
            msg = e.get("mensagem", str(e))
            sug = e.get("sugestao", "")
            trecho = e.get("trecho", "")
            bloqueia = e.get("bloqueia_publicacao", False)
            linhas.append(f"\n  Campo    : {campo or '(geral)'}")
            linhas.append(f"  Mensagem : {msg}")
            if trecho:
                linhas.append(f"  Trecho   : <<{trecho[:80]}>>")
            if sug:
                linhas.append(f"  Sugestao : {sug}")
            linhas.append(f"  Bloqueia : {'SIM' if bloqueia else 'nao'}")

    sv = _status_validacao_da_materia(md)
    pub = (md.get("status_publicacao_sugerido") or md.get("status_pipeline") or "").upper()
    approved_by = md.get("approved_by", "") or ""
    approved_at = md.get("approved_at", "") or ""

    linhas += [
        "", "-" * 56,
        f"STATUS VALIDACAO    : {sv.upper()}",
        f"PUBLICACAO SUGERIDA : {pub or 'NAO DEFINIDA'}",
    ]
    if approved_by:
        linhas += [
            f"APROVACAO MANUAL    : {approved_by} ({approved_at})",
            f"MOTIVO              : {md.get('manual_approval_reason','')[:80]}",
        ]
    return "\n".join(linhas)
