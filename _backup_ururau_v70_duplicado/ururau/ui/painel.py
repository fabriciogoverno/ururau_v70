"""
ui/painel.py — Interface gráfica principal do Ururau (tkinter).
v59 — Botão "Revisão" substitui "Manual" na toolbar.
      Fluxo estruturado de revisão editorial (rascunhos, bloqueados, pendentes).
      Função can_publish() obrigatória em todos os caminhos de publicação.

v23 — Monitor 24h integrado como aba interna do painel de detalhes.

NOVIDADES v23:
  1. Monitor 24h vira aba "Monitor" dentro do notebook de detalhes —
     não abre mais em janela Toplevel separada.
  2. Botão "Monitor OFF/ON" na toolbar seleciona a aba Monitor diretamente.
  3. AbaMonitor: classe que gerencia UI + robo + log ao vivo dentro do painel.

NOVIDADES v22 (mantidas):
  1. JanelaCopydesk: janela visual side-by-side com Original vs Proposto.
     Diff linha a linha com botões Aceitar/Rejeitar por alteração.
  2. _acao_copydesk() abre JanelaCopydesk ANTES de aplicar IA.

CORREÇÕES CRÍTICAS v21 (mantidas):
  1. FilaPautas virtualizada — só renderiza itens visíveis (máx ~40).
  2. popular() faz diff de UIDs — sem rebuild desnecessário.
  3. Auto-refresh REMOVIDO. F5 ou botão Atualizar.
  4. _set_status() sem update_idletasks().
  5. _publicar_thread chama etapa_publicacao() diretamente.
  6. Config: aba Producao integrada ao house_style.py.
"""
from __future__ import annotations

import json
import re
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox, scrolledtext, simpledialog, filedialog
from typing import Optional, TYPE_CHECKING

from ururau.config.settings import (
    LIMIAR_RISCO_MAXIMO,
    MODELO_OPENAI,
    StatusPauta,
    CANAIS_RODIZIO,
    CANAIS_CMS,
)

# Cor para pautas excluídas (tom apagado/cinza)
_COR_ITEM_EXCLUIDA = "#1a1a1a"
from ururau.core.database import get_db
from ururau.editorial.risco import analisar_risco, resumo_risco
from ururau.editorial.copydesk import detectar_problemas

if TYPE_CHECKING:
    from openai import OpenAI
    from ururau.core.database import Database


# ── Paleta visual ─────────────────────────────────────────────────────────────

COR_FUNDO    = "#0f0f1a"   # fundo principal — quase preto azulado
COR_PAINEL   = "#1a1a2e"   # painéis e barras
COR_DESTAQUE = "#7c3aed"   # roxo vibrante — ações principais
COR_TEXTO    = "#e2e8f0"   # texto principal
COR_VERDE    = "#22c55e"
COR_AMARELO  = "#eab308"
COR_VERMELHO = "#ef4444"
COR_CINZA    = "#64748b"
COR_AZUL     = "#0ea5e9"
COR_ROXO     = "#8b5cf6"
COR_LARANJA  = "#f97316"
COR_CIANO    = "#06b6d4"

# Cor do logo Ururau — vermelho vinho extraído do ícone oficial
COR_LOGO     = "#87322f"

# Cores alternadas para as linhas da fila
_COR_ITEM_PAR   = "#131325"   # linha par   — azul muito escuro
_COR_ITEM_IMPAR = "#1c1c35"   # linha ímpar — ligeiramente mais claro

FONTE_MONO    = ("Courier New", 10)
FONTE_TITULO  = ("Helvetica", 13, "bold")
FONTE_NORMAL  = ("Helvetica", 11)
FONTE_PEQUENA = ("Helvetica", 9)
FONTE_ITEM    = ("Segoe UI", 10)          # fonte principal dos itens da fila
FONTE_ITEM_T  = ("Segoe UI", 10, "bold")  # título do item
FONTE_META    = ("Segoe UI", 8)           # metadados (fonte, data)

_STATUS_COR = {
    StatusPauta.CAPTADA:    COR_CINZA,
    StatusPauta.TRIADA:     "#38bdf8",
    StatusPauta.APROVADA:   COR_VERDE,
    StatusPauta.EM_REDACAO: COR_AMARELO,
    StatusPauta.REVISADA:   "#a78bfa",
    StatusPauta.PRONTA:     COR_VERDE,
    StatusPauta.PUBLICADA:  "#10b981",
    StatusPauta.REJEITADA:  COR_VERMELHO,
    StatusPauta.BLOQUEADA:  COR_VERMELHO,
}

_BADGE_IMG = {
    "aprovada":   "IMG-OK",
    "sem_imagem": "SEM-IMG",
    "pendente":   "IMG-...",
    "erro":       "IMG-ERR",
}

_ITEM_H = 86  # altura em px por item na lista virtualizada


# ── Widget: fila virtualizada ─────────────────────────────────────────────────

class FilaPautas(tk.Frame):
    """
    Lista de pautas com virtualização de scroll.

    Só renderiza os itens dentro da janela visível + buffer de 8.
    popular() faz diff: se os UIDs não mudaram, não reconstrói nada.
    Resultado: zero freeze mesmo com 500+ pautas.
    """

    _BUFFER = 8

    def __init__(self, parent, on_select, **kwargs):
        super().__init__(parent, bg=_COR_ITEM_PAR, **kwargs)
        self._on_select = on_select
        self._on_select_callback = on_select   # usado pelo botão item
        self._on_gerar_callback  = lambda p: None
        self._itens: list[dict] = []
        self._sel_idx: Optional[int] = None
        self._frames: dict[int, tk.Frame] = {}  # idx -> frame renderizado
        self._uids_cache: list[str] = []
        self._render_start = -1
        self._render_end   = -1
        # ── Seleção múltipla (checkboxes) ────────────────────────────────────
        self._selecionados: set[str] = set()   # UIDs marcados com checkbox
        self._modo_selecao = False             # True quando pelo menos 1 checkbox marcado
        self._on_selecao_mudou: Optional[callable] = None  # avisa o painel
        self._on_reativar_callback: Optional[callable] = None  # reativa excluída

        self._canvas = tk.Canvas(self, bg=_COR_ITEM_PAR, highlightthickness=0)
        self._sb = tk.Scrollbar(self, orient="vertical", command=self._sb_cmd)
        self._canvas.configure(yscrollcommand=self._sb.set)
        self._sb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._inner = tk.Frame(self._canvas, bg=_COR_ITEM_PAR)
        self._win_id = self._canvas.create_window((0, 0), window=self._inner, anchor="nw")

        self._inner.bind("<Configure>", self._on_inner_cfg)
        self._canvas.bind("<Configure>", self._on_canvas_cfg)
        self._canvas.bind("<MouseWheel>", self._scroll)
        self._canvas.bind("<Button-4>",   self._scroll)
        self._canvas.bind("<Button-5>",   self._scroll)

        # Navegação por teclado — foca o canvas com clique ou Tab
        self._canvas.bind("<Button-1>", self._focar)
        self._canvas.bind("<Up>",       self._nav_cima)
        self._canvas.bind("<Down>",     self._nav_baixo)
        self._canvas.bind("<Return>",   self._nav_enter)
        self._canvas.bind("<space>",    self._nav_enter)
        self._canvas.bind("<Prior>",    self._nav_pgup)    # Page Up
        self._canvas.bind("<Next>",     self._nav_pgdn)    # Page Down
        self._canvas.bind("<Home>",     self._nav_home)
        self._canvas.bind("<End>",      self._nav_end)
        self._canvas.bind("<Delete>",   self._nav_delete)  # Del = descartar rápido
        self._canvas.configure(takefocus=True)

        # Callback externo para descarte (definido pelo PainelUrurau)
        self._on_descartar_callback: Optional[callable] = None

    def _sb_cmd(self, *args):
        self._canvas.yview(*args)
        self.after_idle(self._virtualizar)

    def _on_inner_cfg(self, _=None):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_cfg(self, _=None):
        self._canvas.itemconfig(self._win_id, width=self._canvas.winfo_width())
        self.after_idle(self._virtualizar)

    def _scroll(self, e):
        if e.num == 4:
            self._canvas.yview_scroll(-3, "units")
        elif e.num == 5:
            self._canvas.yview_scroll(3, "units")
        else:
            self._canvas.yview_scroll(int(-1*(e.delta/120)), "units")
        self.after_idle(self._virtualizar)

    # ── API pública ───────────────────────────────────────────────────────────

    def popular(self, itens: list[dict]):
        novos_uids = [p.get("uid") or p.get("_uid", str(i))
                      for i, p in enumerate(itens)]
        if novos_uids == self._uids_cache:
            return  # nada mudou — não reconstrói nada

        self._uids_cache = novos_uids
        self._itens = itens
        self._sel_idx = None

        for f in self._frames.values():
            f.destroy()
        self._frames.clear()
        self._render_start = -1
        self._render_end   = -1

        total_h = max(len(itens) * _ITEM_H, 1)
        self._inner.configure(height=total_h)
        self._canvas.configure(scrollregion=(
            0, 0, self._canvas.winfo_width(), total_h))
        self._canvas.yview_moveto(0)
        self.after_idle(self._virtualizar)

    def _virtualizar(self):
        if not self._itens:
            return
        total_h = len(self._itens) * _ITEM_H
        yv = self._canvas.yview()
        top_px = int(yv[0] * total_h)
        bot_px = int(yv[1] * total_h)

        ini = max(0, top_px // _ITEM_H - self._BUFFER)
        fim = min(len(self._itens) - 1, bot_px // _ITEM_H + self._BUFFER)

        if ini == self._render_start and fim == self._render_end:
            return

        for idx in [k for k in self._frames if k < ini or k > fim]:
            self._frames.pop(idx).destroy()

        for idx in range(ini, fim + 1):
            if idx not in self._frames:
                self._criar_item(idx)

        self._render_start = ini
        self._render_end   = fim

    def _criar_item(self, idx: int):
        p           = self._itens[idx]
        status      = p.get("status", "")
        sc_risco    = p.get("score_risco", 0) or 0
        img_st      = p.get("imagem_status", "pendente")
        titulo      = p.get("titulo_origem") or "(sem titulo)"
        cor_status  = _STATUS_COR.get(status, COR_CINZA)
        data_pub    = p.get("data_pub_fonte", "") or ""
        fonte       = p.get("fonte_nome", "") or ""
        canal       = p.get("canal_forcado") or p.get("canal", "") or ""
        selecionado = (idx == self._sel_idx)
        tem_materia = bool(p.get("materia"))
        uid         = p.get("uid") or p.get("_uid", "")
        excluida    = (status == StatusPauta.EXCLUIDA)
        checkbox_on = uid in self._selecionados

        # Fundo alternado — selecionado usa cor roxa, excluída usa cinza escuro
        if excluida:
            bg = _COR_ITEM_EXCLUIDA
            fg = "#555555"
        elif checkbox_on:
            bg = "#1e3a5f"   # azul seleção múltipla
            fg = "#7dd3fc"
        elif selecionado:
            bg = "#3b1f6e"   # roxo escuro selecionado
            fg = "#ffffff"
        else:
            bg = _COR_ITEM_PAR if idx % 2 == 0 else _COR_ITEM_IMPAR
            fg = COR_TEXTO

        # Borda esquerda colorida por status
        borda_cor = cor_status

        item = tk.Frame(self._inner, bg=bg, height=_ITEM_H, cursor="hand2")
        item.place(x=0, y=idx * _ITEM_H, relwidth=1.0)
        item.pack_propagate(False)
        self._frames[idx] = item

        # Borda colorida à esquerda (indicador de status)
        borda = tk.Frame(item, bg=borda_cor, width=4)
        borda.pack(side="left", fill="y")

        # ── Checkbox de seleção múltipla ────────────────────────────────────
        cb_var = tk.BooleanVar(value=checkbox_on)
        cb = tk.Checkbutton(item, variable=cb_var,
                            bg=bg, activebackground=bg,
                            selectcolor="#1e3a5f" if checkbox_on else COR_FUNDO,
                            bd=0, highlightthickness=0, cursor="hand2")
        cb.pack(side="left", padx=(2, 0))

        def _toggle_cb(uid_=uid, var_=cb_var, i=idx):
            if var_.get():
                self._selecionados.add(uid_)
            else:
                self._selecionados.discard(uid_)
            self._modo_selecao = bool(self._selecionados)
            if self._on_selecao_mudou:
                self._on_selecao_mudou(len(self._selecionados))
            # Redesenha item para atualizar cor
            if i in self._frames:
                self._frames.pop(i).destroy()
                self._criar_item(i)

        cb.config(command=_toggle_cb)

        # Conteúdo principal
        corpo = tk.Frame(item, bg=bg)
        corpo.pack(side="left", fill="both", expand=True, padx=(4, 2))

        # Thumbnail de imagem (lado direito do item)
        thumb_frame = tk.Frame(item, bg=bg, width=80)
        thumb_frame.pack(side="right", fill="y", padx=(0, 4))
        thumb_frame.pack_propagate(False)
        thumb_lbl = tk.Label(thumb_frame, bg=bg, fg=COR_CINZA,
                             text="", font=("Segoe UI", 7))
        thumb_lbl.pack(expand=True, fill="both")
        # Carrega thumbnail em background se houver imagem
        img_path = p.get("imagem_caminho", "")
        if img_path:
            self.after(0, lambda lbl=thumb_lbl, ip=img_path, b=bg:
                       self._carregar_thumb(lbl, ip, b))
        else:
            thumb_lbl.config(text="📷\n—")

        # ── Linha 1: status pill + canal + badges + botão ──────────────────
        r1 = tk.Frame(corpo, bg=bg)
        r1.pack(fill="x", pady=(4, 0))

        # Pill de status
        tk.Label(r1, text=f" {status.upper()[:10]} ", bg=cor_status, fg="#000000",
                 font=("Segoe UI", 7, "bold"), padx=2).pack(side="left", padx=(0, 4))

        # Canal
        if canal:
            tk.Label(r1, text=canal[:18], bg=bg, fg=COR_CIANO,
                     font=("Segoe UI", 8, "bold")).pack(side="left", padx=(0, 6))

        # Badge imagem
        img_cor  = COR_VERDE if img_st == "aprovada" else (COR_CINZA if img_st == "pendente" else COR_AMARELO)
        img_icon = "📷" if img_st == "aprovada" else ("⋯" if img_st == "pendente" else "✗")
        tk.Label(r1, text=img_icon, bg=bg, fg=img_cor,
                 font=("Segoe UI", 9)).pack(side="left", padx=(0, 4))

        # Badge risco
        if sc_risco >= LIMIAR_RISCO_MAXIMO:
            tk.Label(r1, text="⚠ RISCO", bg=COR_VERMELHO, fg="white",
                     font=("Segoe UI", 7, "bold"), padx=2).pack(side="left", padx=2)
        elif sc_risco >= 30:
            tk.Label(r1, text="△ REVISAR", bg="#92400e", fg="#fde68a",
                     font=("Segoe UI", 7, "bold"), padx=2).pack(side="left", padx=2)

        # Urgente
        if p.get("urgente"):
            tk.Label(r1, text="🔥 URGENTE", bg="#7c2d12", fg="#fed7aa",
                     font=("Segoe UI", 7, "bold"), padx=2).pack(side="left", padx=2)

        # ── Intel badges (v43) ───────────────────────────────────────────────
        # Triangulação estratégica regional
        if p.get("_intel_triangulacao"):
            tk.Label(r1, text="★ TRIANG", bg="#1e3a5f", fg="#7dd3fc",
                     font=("Segoe UI", 7, "bold"), padx=2).pack(side="left", padx=2)
        # Urgência detectada por intel (além do campo urgente)
        if p.get("_intel_urgencia") and not p.get("urgente"):
            tk.Label(r1, text="⚡ ALERTA", bg="#451a03", fg="#fdba74",
                     font=("Segoe UI", 7, "bold"), padx=2).pack(side="left", padx=2)
        # Protocolo de verdade falhou — revisão obrigatória
        if not p.get("_intel_protocolo_ok", True):
            tk.Label(r1, text="⚠ REVISAR", bg="#44403c", fg="#fbbf24",
                     font=("Segoe UI", 7, "bold"), padx=2).pack(side="left", padx=2)
        # Score intel adicional
        score_intel = p.get("_score_intel_adicional", 0) or 0
        if score_intel >= 10:
            tk.Label(r1, text=f"+{score_intel}SEO", bg="#1a2e1a", fg="#86efac",
                     font=("Segoe UI", 7, "bold"), padx=2).pack(side="left", padx=2)

        # Botão de ação à direita
        if excluida:
            btn_txt, btn_bg, btn_fg = "↩ Reativar", "#374151", "#9ca3af"
        elif tem_materia:
            btn_txt, btn_bg, btn_fg = "✓ Ver Matéria", "#14532d", "#86efac"
        else:
            btn_txt, btn_bg, btn_fg = "▶ Gerar", "#1e3a5f", "#7dd3fc"

        btn_acao = tk.Label(r1, text=btn_txt, bg=btn_bg, fg=btn_fg,
                            font=("Segoe UI", 8, "bold"), padx=6, pady=1,
                            cursor="hand2", relief="flat")
        btn_acao.pack(side="right", padx=4)
        btn_acao.bind("<Button-1>", lambda e, i=idx: self._on_btn_acao(i))

        # ── Linha 2: título ────────────────────────────────────────────────
        lbl = tk.Label(corpo, text=titulo, bg=bg, fg=fg,
                       font=FONTE_ITEM_T if selecionado else FONTE_ITEM,
                       anchor="w", justify="left", wraplength=380, padx=0, pady=1)
        lbl.pack(fill="x")

        # ── Linha 3: metadados ─────────────────────────────────────────────
        r3 = tk.Frame(corpo, bg=bg)
        r3.pack(fill="x", pady=(0, 2))
        meta_partes = []
        if fonte:
            meta_partes.append(fonte[:24])
        if data_pub:
            meta_partes.append(data_pub[:16])
        if meta_partes:
            tk.Label(r3, text="  ·  ".join(meta_partes), bg=bg, fg=COR_CINZA,
                     font=FONTE_META, anchor="w").pack(side="left")

        # Divisor inferior
        tk.Frame(item, bg="#2a2a4a", height=1).pack(fill="x", side="bottom")

        # Bind de clique e scroll em todos os widgets do item
        clickaveis = [item, borda, corpo, r1, lbl, r3]
        for w in clickaveis:
            w.bind("<Button-1>", lambda e, i=idx: self._selecionar(i))
            w.bind("<MouseWheel>", self._scroll)
            w.bind("<Button-4>",   self._scroll)
            w.bind("<Button-5>",   self._scroll)

    def _on_btn_acao(self, idx: int):
        """Botão 'Gerar' / 'Ver Matéria' / '↩ Reativar' por item da fila."""
        self._selecionar(idx)
        p           = self._itens[idx]
        status      = p.get("status", "")
        tem_materia = bool(p.get("materia"))
        if status == StatusPauta.EXCLUIDA:
            if self._on_reativar_callback:
                self.after(50, lambda: self._on_reativar_callback(p))
        elif tem_materia:
            self.after(50, lambda: self._on_select_callback(p))
        else:
            self.after(50, lambda: self._on_gerar_callback(p))

    # ── Navegação por teclado ─────────────────────────────────────────────────

    def _focar(self, _=None):
        """Garante foco no canvas ao clicar."""
        self._canvas.focus_set()

    def _nav_cima(self, _=None):
        if not self._itens:
            return "break"
        atual = self._sel_idx
        novo  = (len(self._itens) - 1) if atual is None else max(0, atual - 1)
        self._selecionar(novo)
        self._scroll_para_visivel(novo)
        return "break"

    def _nav_baixo(self, _=None):
        if not self._itens:
            return "break"
        atual = self._sel_idx
        novo  = 0 if atual is None else min(len(self._itens) - 1, atual + 1)
        self._selecionar(novo)
        self._scroll_para_visivel(novo)
        return "break"

    def _nav_enter(self, _=None):
        """Enter/Espaço: abre preview se tem matéria, senão gera."""
        idx = self._sel_idx
        if idx is None or idx >= len(self._itens):
            return "break"
        p = self._itens[idx]
        if p.get("materia"):
            self.after(50, lambda: self._on_select_callback(p))
        else:
            self.after(50, lambda: self._on_gerar_callback(p))
        return "break"

    def _nav_pgup(self, _=None):
        """Page Up: avança 5 itens para cima."""
        if not self._itens:
            return "break"
        atual = self._sel_idx or 0
        novo  = max(0, atual - 5)
        self._selecionar(novo)
        self._scroll_para_visivel(novo)
        return "break"

    def _nav_pgdn(self, _=None):
        """Page Down: avança 5 itens para baixo."""
        if not self._itens:
            return "break"
        atual = self._sel_idx if self._sel_idx is not None else -1
        novo  = min(len(self._itens) - 1, atual + 5)
        self._selecionar(novo)
        self._scroll_para_visivel(novo)
        return "break"

    def _nav_home(self, _=None):
        if not self._itens:
            return "break"
        self._selecionar(0)
        self._scroll_para_visivel(0)
        return "break"

    def _nav_end(self, _=None):
        if not self._itens:
            return "break"
        ultimo = len(self._itens) - 1
        self._selecionar(ultimo)
        self._scroll_para_visivel(ultimo)
        return "break"

    def _nav_delete(self, _=None):
        """Delete: descarta a pauta selecionada sem diálogo de motivo."""
        if self._sel_idx is None or not self._itens:
            return "break"
        idx = self._sel_idx
        if idx >= len(self._itens):
            return "break"
        if self._on_descartar_callback:
            self._on_descartar_callback(self._itens[idx], idx)
        return "break"

    def _scroll_para_visivel(self, idx: int):
        """Garante que o item selecionado esteja visível, rolando se necessário."""
        if not self._itens:
            return
        total_h = len(self._itens) * _ITEM_H
        yv      = self._canvas.yview()
        canvas_h = self._canvas.winfo_height()

        item_top = idx * _ITEM_H
        item_bot = item_top + _ITEM_H
        vis_top  = int(yv[0] * total_h)
        vis_bot  = vis_top + canvas_h

        if item_top < vis_top:
            # Sobe: coloca o item no topo com pequena margem
            frac = max(0.0, (item_top - 4) / total_h)
            self._canvas.yview_moveto(frac)
        elif item_bot > vis_bot:
            # Desce: garante que o item apareça na parte de baixo
            frac = max(0.0, (item_bot - canvas_h + 4) / total_h)
            self._canvas.yview_moveto(frac)

        self.after_idle(self._virtualizar)

    def focar(self):
        """Coloca foco no canvas da fila (chamado pelo painel)."""
        self._canvas.focus_set()

    def _carregar_thumb(self, lbl: tk.Label, caminho: str, bg: str):
        """Carrega thumbnail em background e exibe no label."""
        try:
            from PIL import Image, ImageTk
            from pathlib import Path
            p = Path(caminho)
            if not p.exists():
                p = Path("imagens") / p.name
            if not p.exists():
                return
            img = Image.open(p)
            img.thumbnail((76, 54), Image.LANCZOS)
            ftk = ImageTk.PhotoImage(img)
            # Guarda referência para evitar GC
            if not hasattr(self, "_thumbs"):
                self._thumbs = []
            self._thumbs.append(ftk)
            # Limita cache para não vazar memória
            if len(self._thumbs) > 120:
                self._thumbs = self._thumbs[-80:]
            self.after(0, lambda: lbl.config(image=ftk, text=""))
        except ImportError:
            self.after(0, lambda: lbl.config(text="📷"))
        except Exception:
            pass

    def set_callbacks(self, on_select, on_gerar, on_descartar=None,
                      on_selecao_mudou=None, on_reativar=None):
        """Define callbacks externos para ações dos botões de item."""
        self._on_select_callback    = on_select
        self._on_gerar_callback     = on_gerar
        self._on_descartar_callback = on_descartar
        self._on_selecao_mudou      = on_selecao_mudou
        self._on_reativar_callback  = on_reativar

    def get_uids_selecionados(self) -> list[str]:
        """Retorna lista de UIDs marcados com checkbox."""
        return list(self._selecionados)

    def limpar_selecao(self):
        """Desmarca todos os checkboxes e redesenha itens afetados."""
        afetados = set(self._selecionados)
        self._selecionados.clear()
        self._modo_selecao = False
        for idx, p in enumerate(self._itens):
            uid = p.get("uid") or p.get("_uid", "")
            if uid in afetados and idx in self._frames:
                self._frames.pop(idx).destroy()
                self._criar_item(idx)
        if self._on_selecao_mudou:
            self._on_selecao_mudou(0)

    def selecionar_todos_visiveis(self):
        """Marca todos os itens atualmente na fila filtrada."""
        for p in self._itens:
            uid = p.get("uid") or p.get("_uid", "")
            if uid:
                self._selecionados.add(uid)
        self._modo_selecao = True
        # Redesenha tudo renderizado
        for idx in list(self._frames.keys()):
            self._frames.pop(idx).destroy()
        self._render_start = -1
        self._render_end   = -1
        self.after_idle(self._virtualizar)
        if self._on_selecao_mudou:
            self._on_selecao_mudou(len(self._selecionados))

    def _selecionar(self, idx: int):
        prev = self._sel_idx
        self._sel_idx = idx
        for i in [prev, idx]:
            if i is not None and i in self._frames:
                self._frames.pop(i).destroy()
                self._criar_item(i)
        if idx < len(self._itens):
            self._on_select(self._itens[idx])
        # Mantém foco no canvas para navegação contínua por teclado
        self._canvas.focus_set()

    def get_selecionado(self) -> Optional[dict]:
        if self._sel_idx is not None and self._sel_idx < len(self._itens):
            return self._itens[self._sel_idx]
        return None


# ── Painel principal ───────────────────────────────────────────────────────────

class PainelUrurau(tk.Tk):
    """Interface principal do sistema Ururau — v21."""

    def __init__(self, db: "Database" = None, client: "OpenAI" = None,
                 modelo: str = MODELO_OPENAI):
        super().__init__()
        self.db     = db or get_db()
        self.client = client
        self.modelo = modelo
        self._pautas_cache: list[dict] = []
        self._pauta_sel: Optional[dict] = None
        self._carregando_aba   = False
        self._carregando_lista = False

        self._configurar_janela()
        self._construir_interface()
        self._carregar_pautas()

    def _configurar_janela(self):
        self.title("Ururau — Robô Editorial v43")
        self.geometry("1440x900")
        self.minsize(1024, 700)
        self.configure(bg=COR_FUNDO)
        self.option_add("*Font", FONTE_NORMAL)

        # ── Ícone da janela (logo oficial Ururau) ─────────────────────────────
        try:
            from pathlib import Path
            _ico = Path(__file__).parent.parent.parent / "ururau_atalho_icon.ico"
            if _ico.exists():
                self.iconbitmap(str(_ico))
        except Exception:
            pass  # fallback silencioso se .ico não for suportado no SO

        # ── Teclas de atalho globais ──────────────────────────────────────────
        # F5 = Atualizar lista (com feedback visual no status)
        def _f5(_=None):
            self._set_status("Atualizando lista...")
            self.after(50, self._carregar_pautas)
        self.bind("<F5>", _f5)
        # Ctrl+W = Redigir matéria
        self.bind("<Control-w>", lambda _: self._acao_redigir())
        # v66: Ctrl+R agora abre o Copydesk (Revisao item-a-item),
        # ja que o painel de Revisao foi removido.
        self.bind("<Control-r>", lambda _: self._acao_copydesk())
        # Ctrl+P = Preview
        self.bind("<Control-p>", lambda _: self._acao_preview())
        # Ctrl+B = Buscar imagem
        self.bind("<Control-b>", lambda _: self._acao_buscar_imagem())
        # Ctrl+G = Coletar (Get) novas pautas
        self.bind("<Control-g>", lambda _: self._acao_coletar())
        # Ctrl+D = Descartar pauta (com diálogo de motivo)
        self.bind("<Control-d>", lambda _: self._acao_descartar())
        # Delete = Descarte rápido (confirmação simples, sem motivo)
        self.bind("<Delete>",    lambda _: self._descartar_via_tecla())
        # Ctrl+M = Manual (adicionar pauta — mantido no menu secundário)
        self.bind("<Control-m>", lambda _: self._acao_manual())
        # Ctrl+Shift+P = Publicar
        self.bind("<Control-P>", lambda _: self._acao_publicar())
        # Ctrl+K = Copydesk
        self.bind("<Control-k>", lambda _: self._acao_copydesk())
        # Ctrl+L = Console (Log)
        self.bind("<Control-l>", lambda _: self._toggle_console())
        # Escape = foca a fila de pautas (atalho rápido para voltar à lista)
        self.bind("<Escape>",    lambda _: self._focar_fila())

        # Monitor
        self._monitor_thread: Optional[threading.Thread] = None
        self._monitor_robo = None
        # Console log widget (será criado em _construir_console)
        self._console_txt = None
        self._console_visible = False

    # ── Interface ─────────────────────────────────────────────────────────────

    def _construir_interface(self):
        self._construir_toolbar()
        self._construir_corpo()
        self._construir_console()
        self._construir_statusbar()
        # Redireciona stdout para o widget de console
        self._redirecionar_stdout()
        # Abre console por padrão
        self.after(100, self._toggle_console)

    def _construir_toolbar(self):
        tb = tk.Frame(self, bg="#11112a", height=52)
        tb.pack(fill="x")
        tb.pack_propagate(False)

        # ── Logo: ícone + nome na cor oficial do logo ─────────────────────────
        logo_frame = tk.Frame(tb, bg="#11112a")
        logo_frame.pack(side="left", padx=(8, 4), pady=4)

        # Tenta carregar o ícone como imagem pequena (24×24) ao lado do nome
        try:
            from PIL import Image, ImageTk
            from pathlib import Path
            _ico_path = Path(__file__).parent.parent.parent / "ururau_atalho_icon.ico"
            if _ico_path.exists():
                _img = Image.open(str(_ico_path)).resize((28, 28), Image.LANCZOS)
                _photo = ImageTk.PhotoImage(_img)
                _ico_lbl = tk.Label(logo_frame, image=_photo, bg="#11112a")
                _ico_lbl.image = _photo   # mantém referência para evitar GC
                _ico_lbl.pack(side="left", padx=(0, 4))
        except Exception:
            pass  # sem Pillow ou ícone: apenas o texto

        tk.Label(logo_frame, text="URURAU", bg="#11112a", fg=COR_LOGO,
                 font=("Helvetica", 15, "bold")).pack(side="left")
        tk.Label(logo_frame, text="robô editorial", bg="#11112a",
                 fg="#5a2a28", font=("Helvetica", 8)).pack(
                     side="left", padx=(4, 0), pady=(6, 0))
        def _btn_atualizar():
            self._set_status("Atualizando lista...")
            self.after(50, self._carregar_pautas)
        for texto, cmd, cor in [
            ("Atualizar F5", _btn_atualizar,          COR_CINZA),
            ("Coletar",      self._acao_coletar,       COR_DESTAQUE),
            ("Redigir",      self._acao_redigir,       COR_AZUL),
            ("Copydesk",     self._acao_copydesk,      COR_ROXO),
            ("Preview",      self._acao_preview,       COR_LARANJA),
            ("Publicar",     self._acao_publicar,      COR_VERDE),
            ("Imagem",       self._acao_buscar_imagem, COR_CIANO),
            # v66: botao "Revisao" REMOVIDO. Revisao agora acontece no Preview;
            # use o botao Copydesk para revisao item-a-item com sugestoes de IA.
            ("Descartar",    self._acao_descartar,     COR_VERMELHO),
            ("Historico",    self._acao_historico,     "#475569"),
            ("Stats",        self._acao_estatisticas,  "#334155"),
            ("Exportar",     self._acao_exportar,      "#1e3a5f"),
            ("Config",       self._acao_configuracoes, "#1e293b"),
        ]:
            tk.Button(tb, text=texto, command=cmd, bg=cor, fg="white",
                      relief="flat", padx=7, pady=3, cursor="hand2",
                      font=("Helvetica", 9, "bold")).pack(side="left", padx=1, pady=8)
        # Botão Monitor (toggle)
        self._btn_monitor = tk.Button(tb, text="Monitor OFF",
                                       command=self._toggle_monitor,
                                       bg="#374151", fg="#9ca3af",
                                       relief="flat", padx=7, pady=3, cursor="hand2",
                                       font=("Helvetica", 9, "bold"))
        self._btn_monitor.pack(side="left", padx=1, pady=8)
        # Botão Console (toggle log interno)
        self._btn_console = tk.Button(tb, text="Console",
                                       command=self._toggle_console,
                                       bg="#1c1c35", fg="#64748b",
                                       relief="flat", padx=7, pady=3, cursor="hand2",
                                       font=("Helvetica", 9, "bold"))
        self._btn_console.pack(side="left", padx=1, pady=8)
        # Botão de atalhos de teclado
        tk.Button(tb, text="⌨ Atalhos", command=self._mostrar_atalhos,
                  bg="#1c1c35", fg="#64748b",
                  relief="flat", padx=7, pady=3, cursor="hand2",
                  font=("Helvetica", 9, "bold")).pack(side="left", padx=1, pady=8)
        self._lbl_stats = tk.Label(tb, text="", bg=COR_PAINEL,
                                   fg=COR_CINZA, font=FONTE_PEQUENA)
        self._lbl_stats.pack(side="right", padx=10)

    def _atualizar_stats_async(self):
        def _t():
            try:
                s = self.db.estatisticas()
                txt = (f"Pautas: {s['total_pautas']}  |  "
                       f"Publicadas: {s['total_publicadas']}  |  "
                       f"Materias: {s['total_materias']}")
                self.after(0, lambda: self._lbl_stats.config(text=txt))
            except Exception:
                pass
        threading.Thread(target=_t, daemon=True).start()

    def _construir_corpo(self):
        self._paned = ttk.PanedWindow(self, orient="horizontal")
        self._paned.pack(fill="both", expand=True, padx=6, pady=4)

        # fl é o contêiner pai do lado esquerdo — guarda referência para o PainelRevisao
        fl = tk.Frame(self._paned, bg=COR_PAINEL)
        self._frame_lista_pai = fl   # referência para PainelRevisao
        self._paned.add(fl, weight=1)

        # _frame_lista é o sub-frame que contém a fila de pautas
        # (será oculto quando o PainelRevisao estiver ativo)
        self._frame_lista = tk.Frame(fl, bg=COR_PAINEL)
        self._frame_lista.pack(fill="both", expand=True)
        self._construir_lista(self._frame_lista)

        # Painel de revisão (criado sob demanda)
        self._painel_revisao_widget = None
        self._faixa_revisao = None

        fd = tk.Frame(self._paned, bg=COR_PAINEL)
        self._frame_detalhe = fd   # referência para _mostrar_acoes_revisao
        self._paned.add(fd, weight=1)
        self._construir_detalhe(fd)
        self.after(150, self._ajustar_divisor)

    def _focar_fila(self):
        """Devolve o foco para a fila de pautas (tecla Esc)."""
        try:
            self._fila.focar()
        except Exception:
            pass

    def _mostrar_atalhos(self):
        """Exibe janela com todos os atalhos de teclado disponíveis."""
        win = tk.Toplevel(self)
        win.title("Atalhos de Teclado")
        win.geometry("420x480")
        win.configure(bg=COR_FUNDO)
        win.resizable(False, False)
        win.grab_set()

        tk.Label(win, text="⌨  Atalhos de Teclado", bg=COR_FUNDO,
                 fg=COR_DESTAQUE, font=("Helvetica", 13, "bold")).pack(pady=(16, 8))

        atalhos = [
            ("FILA DE PAUTAS", None),
            ("↑ / ↓",         "Navegar entre pautas"),
            ("Enter / Espaço", "Abrir preview (ou gerar matéria)"),
            ("Page Up",        "Avança 5 pautas acima"),
            ("Page Down",      "Avança 5 pautas abaixo"),
            ("Home",           "Primeira pauta da lista"),
            ("End",            "Última pauta da lista"),
            ("",               ""),
            ("AÇÕES GLOBAIS",  None),
            ("F5",             "Atualizar lista de pautas"),
            ("Ctrl + G",       "Coletar novas pautas (Get)"),
            ("Ctrl + R",       "Redigir matéria da pauta selecionada"),
            ("Ctrl + K",       "Copydesk (revisão com IA)"),
            ("Ctrl + P",       "Preview — editar e escolher imagem"),
            ("Ctrl + Shift+P", "Publicar no CMS"),
            ("Ctrl + B",       "Buscar imagem automática"),
            ("Ctrl + M",       "Adicionar pauta manualmente"),
            ("Delete",          "Descartar pauta (confirmação rápida, sem motivo)"),
            ("Ctrl + D",       "Descartar pauta (com campo de motivo)"),
            ("Ctrl + L",       "Mostrar/ocultar Console de log"),
            ("Esc",            "Devolver foco à fila de pautas"),
        ]

        frame = tk.Frame(win, bg=COR_PAINEL, padx=20, pady=12)
        frame.pack(fill="both", expand=True, padx=16, pady=4)

        for tecla, descricao in atalhos:
            if descricao is None:
                # Cabeçalho de seção
                tk.Label(frame, text=tecla, bg=COR_PAINEL, fg=COR_CIANO,
                         font=("Helvetica", 9, "bold")).pack(anchor="w", pady=(8, 2))
                tk.Frame(frame, bg="#3a3a5c", height=1).pack(fill="x", pady=2)
            elif tecla == "":
                tk.Label(frame, text="", bg=COR_PAINEL, height=1).pack()
            else:
                row = tk.Frame(frame, bg=COR_PAINEL)
                row.pack(fill="x", pady=1)
                tk.Label(row, text=tecla, bg="#16213e", fg=COR_AMARELO,
                         font=("Courier New", 9, "bold"),
                         width=18, anchor="w", padx=4).pack(side="left")
                tk.Label(row, text=descricao, bg=COR_PAINEL, fg=COR_TEXTO,
                         font=("Helvetica", 9), anchor="w").pack(side="left", padx=8)

        tk.Button(win, text="Fechar", command=win.destroy,
                  bg=COR_DESTAQUE, fg="white", relief="flat",
                  padx=16, pady=4, cursor="hand2",
                  font=("Helvetica", 10, "bold")).pack(pady=12)

    def _ajustar_divisor(self):
        try:
            w = self._paned.winfo_width()
            if w > 100:
                self._paned.sashpos(0, w // 2)
        except Exception:
            pass

    def _construir_lista(self, frame):
        # ── Título ────────────────────────────────────────────────────────────
        tk.Label(frame, text="Fila de Pautas", bg=COR_PAINEL,
                 fg=COR_TEXTO, font=FONTE_TITULO, anchor="w").pack(
                     fill="x", padx=8, pady=4)

        # ── Linha de filtros ──────────────────────────────────────────────────
        ff = tk.Frame(frame, bg=COR_PAINEL)
        ff.pack(fill="x", padx=8, pady=2)
        tk.Label(ff, text="Status:", bg=COR_PAINEL, fg=COR_CINZA,
                 font=FONTE_PEQUENA).pack(side="left")
        self._filtro_var = tk.StringVar(value="todos")
        # Valores: "todos", statuses normais, separador "——", "excluídas"
        _vals_filtro = ["todos"] + StatusPauta.TODOS + ["── excluídas ──"]
        cb = ttk.Combobox(ff, textvariable=self._filtro_var,
                          values=_vals_filtro,
                          state="readonly", width=14)
        cb.pack(side="left", padx=2)
        cb.bind("<<ComboboxSelected>>", lambda _: self._aplicar_filtro())
        tk.Label(ff, text="Busca:", bg=COR_PAINEL, fg=COR_CINZA,
                 font=FONTE_PEQUENA).pack(side="left", padx=(6, 2))
        self._busca_var = tk.StringVar()
        tk.Entry(ff, textvariable=self._busca_var, bg=COR_FUNDO, fg=COR_TEXTO,
                 insertbackground=COR_TEXTO, font=FONTE_PEQUENA,
                 width=14).pack(side="left")
        self._busca_var.trace_add("write", lambda *_: self._aplicar_filtro())
        self._lbl_contagem = tk.Label(ff, text="", bg=COR_PAINEL,
                                      fg=COR_CINZA, font=FONTE_PEQUENA)
        self._lbl_contagem.pack(side="right")

        # ── Barra de ações em lote ────────────────────────────────────────────
        fb = tk.Frame(frame, bg="#0d0d20")
        fb.pack(fill="x", padx=8, pady=(0, 2))

        tk.Button(fb, text="☑ Selec. Todos", command=self._selecionar_todos,
                  bg="#1e293b", fg="#94a3b8", relief="flat", padx=6, pady=2,
                  cursor="hand2", font=("Helvetica", 8)).pack(side="left", padx=1)
        tk.Button(fb, text="☐ Limpar", command=self._limpar_selecao,
                  bg="#1e293b", fg="#94a3b8", relief="flat", padx=6, pady=2,
                  cursor="hand2", font=("Helvetica", 8)).pack(side="left", padx=1)

        self._btn_excluir_sel = tk.Button(
            fb, text="🗑 Excluir Selecionadas (0)",
            command=self._acao_excluir_selecionadas,
            bg="#4b0505", fg="#fca5a5", relief="flat", padx=6, pady=2,
            cursor="hand2", font=("Helvetica", 8, "bold"), state="disabled")
        self._btn_excluir_sel.pack(side="left", padx=(8, 1))

        tk.Button(fb, text="🗑 Excluir TUDO visível",
                  command=self._acao_excluir_tudo,
                  bg="#3b0000", fg="#ef4444", relief="flat", padx=6, pady=2,
                  cursor="hand2", font=("Helvetica", 8)).pack(side="left", padx=1)

        tk.Button(fb, text="🧹 Limpar Lista",
                  command=self._acao_limpar_lista,
                  bg="#1a2a1a", fg="#86efac", relief="flat", padx=6, pady=2,
                  cursor="hand2", font=("Helvetica", 8)).pack(side="left", padx=(12, 1))

        tk.Label(frame,
                 text="📷=imagem ok  ⋯=pendente  ⚠=risco alto  🔥=urgente  "
                      "▶ Gerar=redigir matéria  ✓ Ver=abrir preview  ☑=selecionar p/ excluir",
                 bg=COR_PAINEL, fg=COR_CINZA,
                 font=("Helvetica", 7)).pack(anchor="w", padx=8)

        self._fila = FilaPautas(frame, on_select=self._ao_selecionar)
        self._fila.set_callbacks(
            on_select=self._acao_preview_direto,
            on_gerar=self._acao_gerar_item,
            on_descartar=self._descartar_rapido,
            on_selecao_mudou=self._ao_mudar_selecao,
            on_reativar=self._acao_reativar_pauta,
        )
        self._fila.pack(fill="both", expand=True, padx=4, pady=4)

    def _construir_detalhe(self, frame):
        tk.Label(frame, text="Detalhe da Pauta", bg=COR_PAINEL,
                 fg=COR_TEXTO, font=FONTE_TITULO, anchor="w").pack(
                     fill="x", padx=8, pady=4)
        nb = ttk.Notebook(frame)
        nb.pack(fill="both", expand=True, padx=8, pady=4)
        self._notebook = nb
        nb.bind("<<NotebookTabChanged>>", self._ao_trocar_aba)
        self._aba_info      = self._nova_aba(nb, "Info")
        self._aba_checagem  = self._nova_aba(nb, "Checagem")
        self._aba_risco     = self._nova_aba(nb, "Risco")
        self._aba_materia   = self._nova_aba(nb, "Materia")
        self._aba_auditoria = self._nova_aba(nb, "Auditoria")
        # ── Aba Leitura da Fonte (v43) ───────────────────────────────────────
        self._aba_leitura_frame = tk.Frame(nb, bg=COR_FUNDO)
        nb.add(self._aba_leitura_frame, text="📄 Fonte")
        self._idx_aba_leitura = nb.index("end") - 1
        self._construir_aba_leitura(self._aba_leitura_frame)
        # ── Aba Monitor integrada ────────────────────────────────────────────
        f_monitor = tk.Frame(nb, bg=COR_FUNDO)
        nb.add(f_monitor, text="🤖 Monitor")
        self._aba_monitor_widget = AbaMonitor(f_monitor, self.db, self.client,
                                              self.modelo,
                                              cb_robo_atualizado=self._cb_monitor_atualizado)
        self._aba_monitor_widget.pack(fill="both", expand=True)
        # ── Aba Preview inline ───────────────────────────────────────────────
        self._aba_preview_frame = tk.Frame(nb, bg=COR_FUNDO)
        nb.add(self._aba_preview_frame, text="✏ Preview")
        self._idx_aba_preview = nb.index("end") - 1
        # ── Aba Config inline ────────────────────────────────────────────────
        self._aba_config_frame = tk.Frame(nb, bg=COR_FUNDO)
        nb.add(self._aba_config_frame, text="⚙ Config")
        self._idx_aba_config = nb.index("end") - 1

    def _nova_aba(self, nb, titulo):
        f = tk.Frame(nb, bg=COR_PAINEL)
        nb.add(f, text=titulo)
        st = scrolledtext.ScrolledText(f, bg="#16213e", fg=COR_TEXTO,
                                        font=FONTE_MONO, borderwidth=0,
                                        state="disabled", wrap="word")
        st.pack(fill="both", expand=True)
        return st

    def _ao_trocar_aba(self, _=None):
        if not self._pauta_sel or self._carregando_aba:
            return
        idx   = self._notebook.index("current")
        pauta = self._pauta_sel
        # Aba Leitura da Fonte (idx=5): carrega conteúdo da fonte
        if idx == self._idx_aba_leitura:
            self._carregar_aba_leitura(pauta)
            return
        # Abas Monitor(6), Preview(7) e Config(8) não usam _escrever
        if idx > self._idx_aba_leitura:
            return
        self._carregando_aba = True

        def _t():
            try:
                fns = [self._calcular_info, self._calcular_checagem,
                       self._calcular_risco, self._calcular_materia,
                       self._calcular_auditoria]
                abas = [self._aba_info, self._aba_checagem,
                        self._aba_risco, self._aba_materia, self._aba_auditoria]
                if 0 <= idx < len(fns):
                    txt = fns[idx](pauta)
                    self.after(0, lambda: self._escrever(abas[idx], txt))
            finally:
                self.after(0, lambda: setattr(self, "_carregando_aba", False))
        threading.Thread(target=_t, daemon=True).start()

    def _construir_console(self):
        """Painel de console interno — exibe print() do sistema em tempo real."""
        self._console_frame = tk.Frame(self, bg="#050510", height=320)
        # Não empacota por padrão — toggle visibilidade
        hdr = tk.Frame(self._console_frame, bg="#0a0a1a", height=24)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="▶ Console interno", bg="#0a0a1a", fg="#64748b",
                 font=("Segoe UI", 8, "bold")).pack(side="left", padx=8)
        tk.Button(hdr, text="Limpar", command=self._limpar_console,
                  bg="#0a0a1a", fg="#475569", relief="flat",
                  font=("Segoe UI", 7), padx=4, pady=0,
                  cursor="hand2").pack(side="right", padx=4)
        self._console_txt = scrolledtext.ScrolledText(
            self._console_frame, bg="#050510", fg="#94a3b8",
            font=("Courier New", 8), state="disabled",
            wrap="word", height=14)
        self._console_txt.pack(fill="both", expand=True)
        self._console_txt.tag_configure("ok",   foreground="#86efac")
        self._console_txt.tag_configure("err",  foreground="#fca5a5")
        self._console_txt.tag_configure("warn", foreground="#fde68a")
        self._console_txt.tag_configure("info", foreground="#94a3b8")

    def _toggle_console(self):
        """Mostra/esconde o painel de console."""
        self._console_visible = not self._console_visible
        if self._console_visible:
            # Empacota antes da statusbar
            self._console_frame.pack(fill="x", side="bottom", before=self._statusbar_frame)
            self._btn_console.config(bg="#1c4532", fg="#86efac")
        else:
            self._console_frame.pack_forget()
            self._btn_console.config(bg="#1c1c35", fg="#64748b")

    def _limpar_console(self):
        if self._console_txt:
            self._console_txt.config(state="normal")
            self._console_txt.delete("1.0", "end")
            self._console_txt.config(state="disabled")

    def _append_console(self, texto: str):
        """Adiciona linha ao console interno com coloração automática."""
        if not self._console_txt:
            return
        try:
            tag = "info"
            tl = texto.lower()
            if "[ok]" in tl or "ok]" in tl or "sucesso" in tl or "✓" in tl:
                tag = "ok"
            elif "erro" in tl or "error" in tl or "[xx]" in tl or "falha" in tl or "✗" in tl:
                tag = "err"
            elif "aviso" in tl or "warn" in tl or "⚠" in tl or "bloq" in tl:
                tag = "warn"
            self._console_txt.config(state="normal")
            self._console_txt.insert("end", texto.rstrip() + "\n", tag)
            self._console_txt.see("end")
            self._console_txt.config(state="disabled")
        except Exception:
            pass

    def _redirecionar_stdout(self):
        """Redireciona sys.stdout para o widget de console + terminal original."""
        import sys
        painel = self
        orig_stdout = sys.stdout
        orig_stderr = sys.stderr

        class _Tee:
            def __init__(self, orig):
                self._orig = orig
            def write(self, msg):
                if msg and msg.strip():
                    try:
                        painel.after(0, lambda m=msg: painel._append_console(m))
                    except Exception:
                        pass
                try:
                    self._orig.write(msg)
                except Exception:
                    pass
            def flush(self):
                try:
                    self._orig.flush()
                except Exception:
                    pass

        sys.stdout = _Tee(orig_stdout)
        sys.stderr = _Tee(orig_stderr)

    def _construir_statusbar(self):
        sb = tk.Frame(self, bg="#0a0a1a", height=26)
        sb.pack(fill="x", side="bottom")
        sb.pack_propagate(False)
        self._statusbar_frame = sb
        # Barra de status com indicador colorido
        self._status_dot = tk.Label(sb, text="●", bg="#0a0a1a", fg=COR_VERDE,
                                    font=("Helvetica", 8))
        self._status_dot.pack(side="left", padx=(8, 2))
        self._status_lbl = tk.Label(sb, text="Pronto. (F5 para atualizar)",
                                    bg="#0a0a1a", fg="#94a3b8",
                                    font=("Segoe UI", 9), anchor="w")
        self._status_lbl.pack(side="left")

    def _set_status(self, msg: str):
        self.after(0, lambda: self._status_lbl.config(text=msg))

    # ── Carregamento ──────────────────────────────────────────────────────────

    def _carregar_pautas(self):
        if self._carregando_lista:
            return
        self._carregando_lista = True
        self._set_status("Carregando pautas...")
        threading.Thread(target=self._carregar_thread, daemon=True).start()

    def _carregar_thread(self):
        try:
            conn = self.db._conectar()
            try:
                rows = conn.execute(
                    "SELECT uid, titulo_origem, status, urgente, "
                    "score_editorial, dados_json, fonte_nome, "
                    "captada_em, atualizada_em "
                    "FROM pautas ORDER BY atualizada_em DESC LIMIT 1000"
                ).fetchall()
                cache = []
                for row in rows:
                    d = dict(row)
                    try:
                        extra = json.loads(d.get("dados_json") or "{}")
                        d.update(extra)
                    except Exception:
                        pass
                    cache.append(d)

                # Reordena por data de publicação na fonte (mais recente primeiro).
                # data_pub_fonte pode vir em dois formatos:
                #   - "DD/MM/YYYY HH:MM"  (formato brasileiro — gerado por _dt_para_str)
                #   - string RFC/ISO livre (fallback do feedparser)
                # captada_em vem em "YYYY-MM-DD HH:MM:SS" (sempre preenchida).
                import datetime as _dt_mod

                def _parse_data_pub(s: str) -> str:
                    """Normaliza qualquer formato de data para YYYY-MM-DD HH:MM para ordenação."""
                    s = (s or "").strip()
                    if not s:
                        return ""
                    # Formato brasileiro: DD/MM/YYYY HH:MM
                    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y"):
                        try:
                            return _dt_mod.datetime.strptime(s, fmt).strftime("%Y-%m-%d %H:%M")
                        except ValueError:
                            pass
                    # Já em formato ISO ou similar — retorna como está
                    return s[:16]

                def _chave_data(p: dict) -> str:
                    pub = _parse_data_pub(p.get("data_pub_fonte") or "")
                    return pub or (p.get("captada_em") or "")[:16]

                cache.sort(key=_chave_data, reverse=True)
            finally:
                conn.close()

            def _ok():
                self._pautas_cache    = cache
                self._carregando_lista = False
                self._aplicar_filtro()
                self._atualizar_stats_async()
                self._set_status(f"{len(cache)} pautas. (F5 para atualizar)")
            self.after(0, _ok)
        except Exception as e:
            self._carregando_lista = False
            self.after(0, lambda: self._set_status(f"Erro ao carregar: {e}"))

    def _aplicar_filtro(self):
        filtro = self._filtro_var.get()
        busca  = self._busca_var.get().lower().strip()

        # Modo "excluídas": mostra apenas status=excluida
        if filtro == "── excluídas ──":
            filtradas = [
                p for p in self._pautas_cache
                if p.get("status") == StatusPauta.EXCLUIDA
                and (not busca or busca in (p.get("titulo_origem") or "").lower())
            ]
        elif filtro == "todos":
            # "todos" exclui excluídas — ficam ocultas por padrão
            filtradas = [
                p for p in self._pautas_cache
                if p.get("status") != StatusPauta.EXCLUIDA
                and (not busca or busca in (p.get("titulo_origem") or "").lower())
            ]
        else:
            filtradas = [
                p for p in self._pautas_cache
                if p.get("status") == filtro
                and (not busca or busca in (p.get("titulo_origem") or "").lower())
            ]
        self._fila.popular(filtradas)
        self._lbl_contagem.config(text=f"{len(filtradas)}")

    def _ao_selecionar(self, pauta: dict):
        self._pauta_sel = pauta
        self._set_status(f"Selecionado: {(pauta.get('titulo_origem') or '')[:60]}")
        self._ao_trocar_aba()

    # ── Conteúdo das abas ─────────────────────────────────────────────────────

    def _escrever(self, txt, conteudo):
        txt.config(state="normal")
        txt.delete("1.0", "end")
        txt.insert("end", conteudo)
        txt.config(state="disabled")

    def _calcular_info(self, p: dict) -> str:
        sc = p.get("score_risco", 0) or 0
        alerta = (" [BLOQUEADO]" if sc >= LIMIAR_RISCO_MAXIMO
                  else (" [REVISAR]" if sc >= 30 else ""))
        return (
            f"TITULO          : {p.get('titulo_origem', '')}\n"
            f"STATUS          : {p.get('status', '')}\n"
            f"CANAL           : {p.get('canal_forcado') or p.get('canal', '')}\n"
            f"FONTE           : {p.get('fonte_nome', '')}\n"
            f"PUB. NA FONTE   : {p.get('data_pub_fonte') or '(nao disponivel)'}\n"
            f"LINK            : {p.get('link_origem', '')}\n"
            f"UID             : {p.get('uid') or p.get('_uid', '')}\n"
            f"\nSCORE EDITORIAL : {p.get('score_editorial', 0)}\n"
            f"SCORE RISCO     : {sc}/100{alerta}\n"
            f"URGENTE         : {'Sim' if p.get('urgente') else 'Nao'}\n"
            f"\nIMAGEM STATUS   : {p.get('imagem_status', 'pendente')}\n"
            f"IMAGEM ESTRAT.  : {p.get('imagem_estrategia', '')}\n"
            f"IMAGEM CAMINHO  : {p.get('imagem_caminho', '')}\n"
            f"\nCAPTADA EM      : {p.get('captada_em', '')}\n"
            f"ATUALIZADA EM   : {p.get('atualizada_em', '')}\n"
            f"\nRESUMO:\n{p.get('resumo_origem', '')}\n"
        )

    def _calcular_checagem(self, p: dict) -> str:
        link  = p.get("link_origem", "")
        uid   = p.get("uid") or p.get("_uid", "")
        titulo = p.get("titulo_origem", "")
        linhas = ["=" * 60, "  CHECAGEM ANTI-REPETICAO E INTEGRIDADE", "=" * 60, ""]
        try:
            status_banco = self.db.classificar_pauta(link, uid)
            linhas.append(f"Status no banco  : {status_banco}")
            ja_pub     = self.db.pauta_ja_publicada(link, uid)
            descartada = self.db.pauta_foi_descartada(link, uid)
            similar    = self.db.titulo_similar_ja_publicado(titulo) if titulo else None
            linhas.append(f"{'[OK]' if not ja_pub else '[XX]'} Ja publicada    : {'SIM' if ja_pub else 'Nao'}")
            linhas.append(f"{'[OK]' if not descartada else '[XX]'} Descartada      : {'SIM' if descartada else 'Nao'}")
            linhas.append(f"[XX] Titulo similar:\n   -> '{similar[:70]}'" if similar
                          else "[OK] Sem titulo similar recente")
            img_st = p.get("imagem_status", "pendente")
            linhas.append(f"\n{'[OK]' if img_st == 'aprovada' else '[..]'} Imagem : {img_st}")
            if p.get("imagem_caminho"):
                linhas.append(f"   Arquivo : {p.get('imagem_caminho')}")
            md = _parse_materia(p)
            tem = bool(md and md.get("conteudo"))
            linhas.append(f"\n{'[OK]' if tem else '[..]'} Materia gerada : {'Sim' if tem else 'Nao'}")
            if tem:
                probs = detectar_problemas(md)
                if probs:
                    linhas += [f"\n[AVIS] Checklist ({len(probs)} problemas):"] + [f"   - {x}" for x in probs]
                else:
                    linhas.append("[OK] Checklist: OK")
            linhas.append("\n" + "-" * 60)
            bloqs = []
            if ja_pub: bloqs.append("Ja publicada no CMS")
            if descartada: bloqs.append("Descartada anteriormente")
            if similar: bloqs.append("Titulo similar publicado (72h)")
            sc = p.get("score_risco", 0) or 0
            if sc >= LIMIAR_RISCO_MAXIMO:
                bloqs.append(f"Score risco {sc}/100 acima de {LIMIAR_RISCO_MAXIMO}")
            if not p.get("_intel_protocolo_ok", True):
                bloqs.append("Protocolo de verdade: revisar cargo/fato antes de publicar")
            if bloqs:
                linhas += ["[BLOQ] PUBLICACAO REQUER CONFIRMACAO:"] + [f"   * {b}" for b in bloqs]
            else:
                linhas.append("[OK] PAUTA APTA PARA PUBLICACAO")

            # ── Intel editorial (v43) ─────────────────────────────────────────
            intel_log = p.get("_intel_log", "")
            score_intel = p.get("_score_intel_adicional", 0) or 0
            watchlists = p.get("_intel_watchlists") or []
            if score_intel > 0 or intel_log:
                linhas.append("\n" + "─" * 60)
                linhas.append("  INTEL EDITORIAL (v43)")
                linhas.append("─" * 60)
                linhas.append(f"Score adicional  : +{score_intel}")
                if intel_log:
                    linhas.append(f"Sinais detectados: {intel_log}")
                if watchlists:
                    linhas.append(f"Watchlists       : {', '.join(watchlists[:6])}")
                if p.get("_intel_triangulacao"):
                    linhas.append("[★] TRIANGULACAO REGIONAL ATIVA")
                if p.get("_intel_urgencia"):
                    linhas.append("[⚡] URGENCIA DETECTADA")
                if not p.get("_intel_protocolo_ok", True):
                    linhas.append("[⚠] PROTOCOLO DE VERDADE: REVISAR ANTES DE PUBLICAR")

            # ── Auditoria IA v44 ──────────────────────────────────────────────
            md = _parse_materia(p)
            aud_aprovada  = (md or {}).get("auditoria_aprovada", None)
            aud_bloqueada = (md or {}).get("auditoria_bloqueada", None)
            aud_erros     = (md or {}).get("auditoria_erros", [])
            aud_status    = (md or {}).get("status_pipeline", "")
            viol_fat      = (md or {}).get("violacoes_factuais", [])
            nome_fonte    = (md or {}).get("nome_da_fonte", "")
            credito_foto  = (md or {}).get("creditos_da_foto", "")

            if aud_aprovada is not None:
                linhas.append("\n" + "─" * 60)
                linhas.append("  AUDITORIA IA v44")
                linhas.append("─" * 60)
                aud_icone = "[OK]" if aud_aprovada else "[XX]"
                linhas.append(f"{aud_icone} Aprovada       : {'SIM' if aud_aprovada else 'NAO'}")
                linhas.append(f"     Status      : {aud_status.upper() if aud_status else '-'}")
                if nome_fonte:
                    linhas.append(f"     Nome fonte  : {nome_fonte}")
                if credito_foto:
                    linhas.append(f"     Cred. foto  : {credito_foto}")
                if viol_fat:
                    linhas.append("[BLOQ] VIOLACOES FACTUAIS:")
                    for v in viol_fat[:4]:
                        linhas.append(f"   * {v}")
                if aud_erros:
                    linhas.append("[AVIS] Erros da auditoria:")
                    for e_txt in aud_erros[:4]:
                        linhas.append(f"   - {e_txt}")
                if aud_bloqueada:
                    linhas.append("[BLOQ] PUBLICACAO BLOQUEADA PELA AUDITORIA IA")
                else:
                    linhas.append("[OK] Auditoria liberou para o fluxo configurado")
        except Exception as e:
            linhas.append(f"Erro ao checar: {e}")
        return "\n".join(linhas)

    def _calcular_risco(self, p: dict) -> str:
        md = _parse_materia(p)
        if not md or not md.get("conteudo"):
            return "Materia ainda nao gerada."
        try:
            return resumo_risco(analisar_risco(
                md["conteudo"], canal=p.get("canal_forcado") or p.get("canal", "")))
        except Exception as e:
            return f"Erro ao analisar risco: {e}"

    def _calcular_materia(self, p: dict) -> str:
        md = _parse_materia(p)
        if not md:
            return "Materia nao gerada ainda."
        alt      = md.get("titulos_alternativos") or []
        alt_capa = md.get("titulos_capa_alternativos") or []
        linhas = [
            f"TITULO SEO    : {md.get('titulo', '')}",
            f"TITULO CAPA   : {md.get('titulo_capa', '')}",
            f"SUBTITULO     : {md.get('subtitulo', '')}",
            f"LEGENDA FOTO  : {md.get('legenda', '')}",
            f"RETRANCA      : {md.get('retranca', '')}",
            f"SLUG          : {md.get('slug', '')}",
            f"TAGS          : {md.get('tags', '')}",
            f"META DESC     : {md.get('meta_description', '')}",
            f"RESUMO CURTO  : {md.get('resumo_curto', '')}",
            f"CHAMADA SOCIAL: {md.get('chamada_social', '')}",
        ]
        if md.get("nome_da_fonte"):
            linhas += [f"NOME FONTE    : {md.get('nome_da_fonte', '')}"]
        if md.get("creditos_da_foto"):
            linhas += [f"CRED. FOTO    : {md.get('creditos_da_foto', '')}"]
        if md.get("estrutura_decisao"):
            linhas += [f"ESTRUTURA     : {md.get('estrutura_decisao', '')}"]
        # Auditoria v44
        aud_status = md.get("status_pipeline", "")
        aud_ok     = md.get("auditoria_aprovada", None)
        if aud_status:
            icone = "[OK]" if aud_ok else "[XX]"
            linhas += [f"AUDITORIA IA  : {icone} {aud_status.upper()}"]
            viol = md.get("violacoes_factuais", [])
            if viol:
                linhas += ["  Violações factuais:"] + [f"    * {v}" for v in viol[:3]]
        if alt:
            linhas += ["\nTITULOS ALTERNATIVOS:"] + [f"  {i}. {t}" for i, t in enumerate(alt[:3], 1)]
        if alt_capa:
            linhas += ["\nTITULOS CAPA ALTERNATIVOS:"] + [f"  {i}. {t}" for i, t in enumerate(alt_capa[:3], 1)]
        linhas += ["", "-" * 60, md.get("conteudo", "")]
        return "\n".join(linhas)

    def _calcular_auditoria(self, p: dict) -> str:
        uid = p.get("uid") or p.get("_uid", "")
        if not uid:
            return "UID nao disponivel."
        try:
            conn = self.db._conectar()
            try:
                rows = conn.execute(
                    "SELECT timestamp, acao, detalhe, sucesso "
                    "FROM auditoria WHERE pauta_uid=? ORDER BY id ASC",
                    (uid,)).fetchall()
            finally:
                conn.close()
            linhas = ["=" * 60, f"  AUDITORIA — {uid}", "=" * 60, ""]
            for r in rows:
                linhas.append(f"[{r['timestamp']}] {'[OK]' if r['sucesso'] else '[XX]'} "
                              f"{r['acao']:<26} {r['detalhe']}")
            if not rows:
                linhas.append("Nenhum registro de auditoria.")
            return "\n".join(linhas)
        except Exception as e:
            return f"Erro ao carregar auditoria: {e}"

    # ── Aba Leitura da Fonte (v43) ────────────────────────────────────────────

    def _construir_aba_leitura(self, frame: tk.Frame):
        """Monta a aba '📄 Fonte' com imagem + área de texto + botão de atualizar."""
        # Toolbar
        tb = tk.Frame(frame, bg=COR_PAINEL)
        tb.pack(fill="x", padx=6, pady=(4, 0))
        tk.Label(tb, text="📄 Leitura da Fonte Original",
                 bg=COR_PAINEL, fg=COR_TEXTO,
                 font=("Segoe UI", 10, "bold")).pack(side="left", padx=4)
        self._btn_leitura_refresh = tk.Button(
            tb, text="↺ Recarregar", bg="#1e3a5f", fg="#7dd3fc",
            font=("Segoe UI", 8), relief="flat", padx=8, cursor="hand2",
            command=self._leitura_refresh)
        self._btn_leitura_refresh.pack(side="right", padx=4)
        self._lbl_leitura_status = tk.Label(
            tb, text="", bg=COR_PAINEL, fg=COR_CINZA,
            font=("Segoe UI", 8))
        self._lbl_leitura_status.pack(side="right", padx=8)

        # Painel lateral: imagem + termos (ao lado esquerdo)
        painel_lateral = tk.Frame(frame, bg=COR_FUNDO, width=330)
        painel_lateral.pack(side="left", fill="y", padx=(6, 0), pady=4)
        painel_lateral.pack_propagate(False)

        # Imagem da fonte
        self._leitura_img_frame = tk.Frame(painel_lateral, bg="#0d0d14",
                                           relief="flat", bd=1, height=200)
        self._leitura_img_frame.pack(fill="x", padx=4, pady=(4, 2))
        self._leitura_img_frame.pack_propagate(False)
        self._lbl_leitura_imagem = tk.Label(
            self._leitura_img_frame, text="",
            bg="#0d0d14", fg=COR_CINZA, anchor="center")
        self._lbl_leitura_imagem.pack(expand=True, fill="both")
        self._leitura_photo_ref = None  # mantém referência para evitar GC

        # Termos detectados
        self._lbl_leitura_termos = tk.Label(
            painel_lateral, text="", bg=COR_FUNDO, fg=COR_VERDE,
            font=("Segoe UI", 8), anchor="nw", wraplength=310, justify="left")
        self._lbl_leitura_termos.pack(fill="x", padx=6, pady=(2, 0))

        # Área de texto principal (ocupa o resto)
        self._leitura_txt = scrolledtext.ScrolledText(
            frame, bg="#101018", fg=COR_TEXTO,
            font=FONTE_MONO, borderwidth=0,
            state="disabled", wrap="word")
        self._leitura_txt.pack(side="left", fill="both", expand=True, padx=6, pady=4)
        self._leitura_txt.tag_configure("destaque", foreground="#fde68a",
                                        background="#451a03")
        self._leitura_txt.tag_configure("intel", foreground="#86efac")

    def _leitura_refresh(self):
        """Recarrega texto da fonte da pauta selecionada (ignora cache)."""
        if self._pauta_sel:
            self._carregar_aba_leitura(self._pauta_sel, forcar=True)

    def _carregar_aba_leitura(self, pauta: dict, forcar: bool = False):
        """Busca texto + imagem da fonte em thread e preenche a aba."""
        self._lbl_leitura_status.config(text="Carregando...", fg=COR_AMARELO)
        self._escrever(self._leitura_txt, "Buscando texto da fonte original...")
        # Limpa imagem anterior
        self._lbl_leitura_imagem.config(image="", text="Carregando imagem...", fg=COR_CINZA)
        self._leitura_photo_ref = None

        def _t():
            try:
                from ururau.coleta.leitura_fonte import ler_fonte_pauta
                resultado = ler_fonte_pauta(pauta, forcar_refresh=forcar)

                # Tenta baixar imagem fora da thread de UI
                photo_img = None
                if resultado.sucesso and resultado.imagem_url:
                    try:
                        import requests as _req
                        import io
                        from PIL import Image, ImageTk
                        resp_img = _req.get(resultado.imagem_url, timeout=8,
                                            headers={"User-Agent": "Mozilla/5.0"})
                        if resp_img.status_code == 200:
                            img_data = Image.open(io.BytesIO(resp_img.content))
                            img_data = img_data.convert("RGB")
                            # Redimensiona mantendo proporção, max 320×190
                            img_data.thumbnail((320, 190), Image.LANCZOS)
                            photo_img = ImageTk.PhotoImage(img_data)
                    except Exception:
                        photo_img = None

                def _ui():
                    # Exibe imagem
                    if photo_img is not None:
                        self._leitura_photo_ref = photo_img
                        self._lbl_leitura_imagem.config(
                            image=photo_img, text="", compound="center")
                    elif resultado.sucesso and resultado.imagem_url:
                        self._lbl_leitura_imagem.config(
                            image="", text="[imagem indisponível]", fg=COR_CINZA)
                    else:
                        self._lbl_leitura_imagem.config(
                            image="", text="[sem imagem]", fg=COR_CINZA)

                    if resultado.sucesso:
                        status_txt = (f"{resultado.tamanho_chars} chars | "
                                      f"{len(resultado.termos_destacados)} termos")
                        if resultado.score_intel_adicional > 0:
                            status_txt += f" | Intel +{resultado.score_intel_adicional}"
                        self._lbl_leitura_status.config(
                            text=status_txt, fg=COR_VERDE)
                        # Termos detectados
                        if resultado.termos_destacados:
                            self._lbl_leitura_termos.config(
                                text="Termos: " + " · ".join(resultado.termos_destacados[:12]))
                        else:
                            self._lbl_leitura_termos.config(text="")
                        # Intel log
                        intel_header = ""
                        if resultado.intel_log and resultado.intel_log != "sem sinais extras":
                            intel_header = (f"\n{'─'*60}\n"
                                            f"INTEL EDITORIAL: {resultado.intel_log}\n"
                                            f"{'─'*60}\n\n")
                        conteudo = intel_header + resultado.texto_limpo
                        self._escrever(self._leitura_txt, conteudo)
                    else:
                        self._lbl_leitura_status.config(
                            text=f"Erro: {resultado.erro[:50]}", fg=COR_VERMELHO)
                        self._escrever(self._leitura_txt,
                                       f"Não foi possível carregar a fonte.\n\nErro: {resultado.erro}")
                self.after(0, _ui)
            except Exception as e:
                self.after(0, lambda: (
                    self._lbl_leitura_status.config(text=f"Erro: {e}", fg=COR_VERMELHO),
                    self._escrever(self._leitura_txt, f"Erro ao carregar fonte: {e}")
                ))
        threading.Thread(target=_t, daemon=True).start()

    # ── Thread helper ─────────────────────────────────────────────────────────

    def _em_thread(self, fn, *args):
        threading.Thread(target=fn, args=args, daemon=True).start()

    # ── Coletar ───────────────────────────────────────────────────────────────

    def _acao_coletar(self):
        if not messagebox.askyesno("Coletar Pautas",
            "Iniciar coleta RSS + Google News?\n\n"
            "Pautas ja publicadas, descartadas ou em fila serao ignoradas."):
            return
        self._set_status("Coletando pautas...")
        self._em_thread(self._coletar_thread)

    def _coletar_thread(self):
        try:
            from ururau.coleta.rss import (coletar_rss, coletar_google_news,
                                            deduplicar, filtrar_contra_banco,
                                            obter_termos_google_news)
            from ururau.coleta.scoring import calcular_score_editorial, classificar_canal
            from ururau.coleta.ururau_check import filtrar_contra_site_ururau
            from ururau.config.settings import LIMIAR_RELEVANCIA_PUBLICAR
            fontes = _carregar_fontes_rss()
            raw: list[dict] = []
            if fontes:
                raw += coletar_rss(fontes)
            _termos_fb = ["Rio de Janeiro", "RJ policia", "RJ politica",
                          "RJ economia", "governo RJ", "Campos dos Goytacazes",
                          "Norte Fluminense", "Porto do Açu", "ALERJ"]
            termos_gnews = obter_termos_google_news(_termos_fb)
            raw += coletar_google_news(termos_gnews, max_por_termo=8)
            dedup, resumo = filtrar_contra_banco(deduplicar(raw), self.db)
            # Filtro anti-duplicata: verifica o que já está no ar no Portal Ururau
            # Passa db= para que links encontrados no site sejam bloqueados permanentemente
            dedup, removidas_site = filtrar_contra_site_ururau(dedup, db=self.db)
            resumo["similares"] = resumo.get("similares", 0) + removidas_site
            # Limita 4 por fonte
            from collections import defaultdict
            contagem_fonte: dict[str, int] = defaultdict(int)
            MAX_POR_FONTE = 4
            dedup_limitado = []
            for p in dedup:
                nome_fonte = p.get("fonte_nome") or p.get("nome_fonte") or "desconhecida"
                if contagem_fonte[nome_fonte] < MAX_POR_FONTE:
                    dedup_limitado.append(p)
                    contagem_fonte[nome_fonte] += 1
            dedup = dedup_limitado
            inseridas = 0
            for pauta in dedup:
                try:
                    sc = calcular_score_editorial(pauta)
                    canal = pauta.get("canal_forcado") or classificar_canal(
                        pauta.get("titulo_origem", ""), pauta.get("resumo_origem", ""))
                    pauta["score_editorial"] = sc
                    pauta["canal_forcado"]   = canal
                    pauta["status"]          = StatusPauta.CAPTADA
                    if sc >= LIMIAR_RELEVANCIA_PUBLICAR:
                        self.db.salvar_pauta(pauta)
                        inseridas += 1
                except Exception as e:
                    print(f"[COLETAR] {e}")
            msg = (f"Coleta concluida.\nBrutas: {resumo['total']} | Novas: {inseridas}\n"
                   f"Ja publicadas: {resumo['publicadas']} | Descartadas: {resumo['descartadas']}\n"
                   f"Em fila: {resumo['em_fila']} | Similares/Site: {resumo['similares']}")
            self.after(0, lambda: messagebox.showinfo("Coleta", msg))
            self.after(0, self._carregar_pautas)
            self.after(0, lambda: self._set_status(f"Coleta OK — {inseridas} novas"))
        except Exception as e:
            self.after(0, lambda: self._set_status(f"Erro na coleta: {e}"))
            self.after(0, lambda: messagebox.showerror("Erro na coleta", str(e)))

    # ── Redigir ───────────────────────────────────────────────────────────────

    def _acao_redigir(self):
        if not self._pauta_sel:
            messagebox.showwarning("Redigir", "Selecione uma pauta primeiro."); return
        if not self.client:
            messagebox.showerror("Erro", "Cliente OpenAI nao configurado."); return
        pauta = self._pauta_sel
        link  = pauta.get("link_origem", "")
        uid   = pauta.get("uid") or pauta.get("_uid", "")
        if self.db.pauta_ja_publicada(link, uid):
            messagebox.showerror("Bloqueado", "Esta pauta ja foi publicada."); return
        if self.db.pauta_foi_descartada(link, uid):
            messagebox.showerror("Bloqueado", "Esta pauta foi descartada."); return
        similar = self.db.titulo_similar_ja_publicado(pauta.get("titulo_origem", ""))
        if similar:
            if not messagebox.askyesno("Titulo similar",
                f"Publicado recentemente:\n'{similar[:80]}'\nRedigir mesmo assim?"):
                return
        self._set_status(f"Redigindo: {(pauta.get('titulo_origem') or '')[:50]}...")
        self._em_thread(self._redigir_thread, pauta)

    def _redigir_thread(self, pauta: dict):
        try:
            from ururau.publisher.workflow import WorkflowPublicacao, _uid_para_pauta
            uid = (pauta.get("uid") or pauta.get("_uid") or
                   _uid_para_pauta(pauta.get("link_origem", ""), pauta.get("titulo_origem", "")))
            pauta["_uid"] = uid
            wf = WorkflowPublicacao(self.db, self.client, self.modelo)
            if not wf.etapa_gate_antiduplicacao(uid, pauta, modo="redigir"):
                self.after(0, lambda: self._set_status("Pauta bloqueada pelo gate."))
                self.after(0, self._carregar_pautas)
                return
            wf.etapa_coleta_texto(uid, pauta)
            wf.etapa_imagem(uid, pauta)
            materia = wf.etapa_redacao(uid, pauta)
            if materia:
                materia = wf.etapa_pacote_editorial(uid, materia)
                wf.etapa_verificacao_risco(uid, pauta, materia)
                wf.etapa_persistir_materia(uid, pauta, materia)
                self.after(0, lambda: self._set_status("Redacao concluida [OK]"))
                self.after(0, lambda: messagebox.showinfo(
                    "Redacao Concluida", "Materia gerada! Use Preview antes de publicar."))
            else:
                self.after(0, lambda: self._set_status("Falha na redacao [XX]"))
            self.after(0, self._carregar_pautas)
        except Exception as e:
            self.after(0, lambda: self._set_status(f"Erro na redacao: {e}"))
            self.after(0, lambda: messagebox.showerror("Erro na redacao", str(e)))

    # ── Copydesk ──────────────────────────────────────────────────────────────

    def _acao_copydesk(self):
        """
        v66: Copydesk agora abre JanelaCopydeskItem (revisao item-por-item).
        Substitui o antigo painel "Revisao" e a janela de diff side-by-side.
        Cada campo do pacote editorial e revisado separadamente:
        accept/reject/edit/ok por campo + paragrafo a paragrafo no corpo.
        """
        if not self._pauta_sel:
            messagebox.showwarning("Copydesk", "Selecione uma pauta primeiro.")
            return
        md = _parse_materia(self._pauta_sel)
        if not md or not (md.get("conteudo") or md.get("corpo_materia")):
            messagebox.showwarning(
                "Copydesk",
                "Esta pauta nao tem materia gerada. Use 'Redigir' antes do Copydesk."
            )
            return
        try:
            from ururau.ui.copydesk_painel import JanelaCopydeskItem
        except Exception as e:
            messagebox.showerror("Copydesk indisponivel", str(e))
            return
        try:
            JanelaCopydeskItem(
                self, self._pauta_sel, md,
                db=self.db, client=self.client, modelo=self.modelo,
                on_salvar=self._ao_salvar_copydesk_item,
            )
            self._set_status("Copydesk aberto - revise cada campo e clique 'Salvar mudancas'.")
        except Exception as e:
            messagebox.showerror("Erro ao abrir Copydesk", str(e))

    def _ao_salvar_copydesk_item(self, pauta: dict, md_novo: dict, historico: list):
        """Callback apos JanelaCopydeskItem salvar. Recarrega painel."""
        self._set_status(f"Copydesk salvo: {len(historico)} alteracao(oes).")
        self._carregar_pautas()

    # legacy - mantem caminho antigo (diff) acessivel via _acao_copydesk_legacy
    def _acao_copydesk_legacy(self):
        if not self._pauta_sel:
            messagebox.showwarning("Copydesk", "Selecione uma pauta primeiro.")
            return
        if not self.client:
            messagebox.showerror("Erro", "Cliente OpenAI nao configurado.")
            return
        md = _parse_materia(self._pauta_sel)
        if not md or not md.get("conteudo"):
            messagebox.showwarning("Copydesk", "Esta pauta nao tem materia gerada.")
            return
        self._set_status("Executando copydesk com IA (aguarde)...")
        self._em_thread(self._copydesk_thread, self._pauta_sel)

    def _copydesk_thread(self, pauta: dict):
        """Roda pipeline_copydesk em background, depois abre JanelaCopydesk no main thread."""
        try:
            from ururau.editorial.copydesk import pipeline_copydesk, detectar_problemas, limpar_local
            md_orig = dict(_parse_materia(pauta))
            canal   = pauta.get("canal_forcado") or pauta.get("canal", "Brasil e Mundo")
            mapa    = md_orig.get("mapa_evidencias")
            # Cria uma cópia para o pipeline não alterar o original
            md_copia = dict(md_orig)
            rev, probs = pipeline_copydesk(md_copia, canal, mapa, self.client, self.modelo)
            def _abrir():
                self._set_status("Copydesk pronto — revisando proposta...")
                JanelaCopydesk(self, pauta, md_orig, rev, probs, self.db,
                               self._ao_aceitar_copydesk)
            self.after(0, _abrir)
        except Exception as e:
            self.after(0, lambda: self._set_status(f"Erro no copydesk: {e}"))
            self.after(0, lambda: messagebox.showerror("Erro no Copydesk", str(e)))

    def _ao_aceitar_copydesk(self, pauta: dict, md_rev: dict, probs: list):
        """Callback chamado quando o editor aceita (total ou parcialmente) o copydesk."""
        uid = pauta.get("uid") or pauta.get("_uid", "")
        if uid:
            self.db.salvar_materia(uid, md_rev)
            self.db.log_auditoria(uid, "copydesk_visual", f"{len(probs)} prob(s) residuais")
        self._set_status(f"Copydesk aplicado [OK] — {len(probs)} problema(s) residual(is)")
        self._carregar_pautas()

    # ── Monitor 24h ───────────────────────────────────────────────────────────

    def _toggle_monitor(self):
        """Navega para a aba Monitor integrada ao painel."""
        # Encontra o índice da aba Monitor e seleciona
        nb = self._notebook
        for idx in range(nb.index("end")):
            if "Monitor" in nb.tab(idx, "text"):
                nb.select(idx)
                break

    def _cb_monitor_atualizado(self, robo, thread):
        """Chamado pela AbaMonitor quando o robô é iniciado ou parado."""
        self._monitor_robo   = robo
        self._monitor_thread = thread
        self._atualizar_btn_monitor()
        if robo and robo.ativo:
            self._monitor_status_tick()

    def _atualizar_btn_monitor(self):
        ativo = bool(self._monitor_robo and self._monitor_robo.ativo)
        if ativo:
            n = self._monitor_robo.publicacoes_na_hora
            self._btn_monitor.config(
                text=f"Monitor ON ({n}/h)",
                bg="#065f46", fg="#34d399")
        else:
            self._btn_monitor.config(
                text="Monitor OFF",
                bg="#374151", fg="#9ca3af")

    def _monitor_status_tick(self):
        """Atualiza botão a cada 60s enquanto monitor ativo."""
        if not (self._monitor_robo and self._monitor_robo.ativo):
            return
        self._atualizar_btn_monitor()
        self.after(60_000, self._monitor_status_tick)

    # ── Preview ───────────────────────────────────────────────────────────────

    def _acao_preview(self):
        if not self._pauta_sel:
            messagebox.showwarning("Preview", "Selecione uma pauta primeiro."); return
        md = _parse_materia(self._pauta_sel)
        if not md or not md.get("conteudo"):
            messagebox.showwarning("Preview", "Sem materia gerada. Use Redigir primeiro."); return
        self._abrir_preview_inline(self._pauta_sel, md)

    def _ao_salvar_preview(self, pauta: dict, md: dict):
        uid = pauta.get("uid") or pauta.get("_uid", "")
        if uid:
            self.db.salvar_materia(uid, md)
            self.db.log_auditoria(uid, "edicao_manual_preview", "Conteudo editado via preview")
            # Atualiza o dict da pauta em memória para que _publicar_thread use o md salvo
            pauta["materia"] = md
            # Atualiza também em _pautas_cache
            for p in self._pautas_cache:
                if (p.get("uid") or p.get("_uid")) == uid:
                    p["materia"] = md
                    break
            self._set_status("Materia atualizada via preview [OK]")
            self.after(0, self._carregar_pautas)

    def _acao_preview_direto(self, pauta: dict):
        """Abre preview diretamente de um item clicado na fila (botão ✓ Ver Matéria)."""
        md = _parse_materia(pauta)
        if not md or not md.get("conteudo"):
            messagebox.showwarning("Preview", "Sem matéria gerada. Use 'Gerar' primeiro.")
            return
        self._abrir_preview_inline(pauta, md)

    def _acao_gerar_item(self, pauta: dict):
        """Dispara redação de um item clicado na fila (botão ▶ Gerar)."""
        self._pauta_sel = pauta
        self._acao_redigir()

    # ── Imagem ────────────────────────────────────────────────────────────────

    def _acao_buscar_imagem(self):
        if not self._pauta_sel:
            messagebox.showwarning("Imagem", "Selecione uma pauta primeiro."); return
        pauta = self._pauta_sel
        if not messagebox.askyesno("Buscar Imagem",
            f"{(pauta.get('titulo_origem') or '')[:60]}\n\n"
            f"Imagem atual: {pauta.get('imagem_status', 'pendente')}\n"
            "Refazer busca de imagem?"):
            return
        self._set_status("Buscando imagem...")
        self._em_thread(self._buscar_imagem_thread, pauta)

    def _buscar_imagem_thread(self, pauta: dict):
        try:
            from ururau.publisher.workflow import WorkflowPublicacao, _uid_para_pauta
            uid = (pauta.get("uid") or pauta.get("_uid") or
                   _uid_para_pauta(pauta.get("link_origem", ""), pauta.get("titulo_origem", "")))
            pauta["_uid"] = uid
            wf  = WorkflowPublicacao(self.db, self.client, self.modelo)
            res = wf.etapa_imagem(uid, pauta)
            if res and res.caminho_imagem:
                msg = f"Imagem obtida!\nEstrategia: {res.estrategia_imagem}\nArquivo: {Path(res.caminho_imagem).name}"
                self.after(0, lambda: messagebox.showinfo("Imagem", msg))
                self.after(0, lambda: self._set_status("Imagem atualizada [OK]"))
            else:
                self.after(0, lambda: messagebox.showwarning("Imagem", "Nao foi possivel obter imagem."))
                self.after(0, lambda: self._set_status("Sem imagem"))
            self.after(0, self._carregar_pautas)
        except Exception as e:
            self.after(0, lambda: self._set_status(f"Erro na imagem: {e}"))
            self.after(0, lambda: messagebox.showerror("Erro na Imagem", str(e)))

    # ── Publicar ──────────────────────────────────────────────────────────────

    def _acao_publicar(self, rascunho: bool = True):
        if not self._pauta_sel:
            messagebox.showwarning("Publicar", "Selecione uma pauta primeiro."); return
        pauta = self._pauta_sel
        link  = pauta.get("link_origem", "")
        uid   = pauta.get("uid") or pauta.get("_uid", "")
        if self.db.pauta_ja_publicada(link, uid):
            messagebox.showerror("Bloqueado", "Esta pauta ja foi publicada no CMS."); return

        md = _parse_materia(pauta)
        if not md or not md.get("conteudo"):
            messagebox.showerror("Sem Materia", "Nao tem materia gerada. Use Redigir primeiro."); return

        # ── Gate can_publish(): verifica se o artigo pode ser publicado ───────
        # Esta verificação é obrigatória em TODOS os caminhos de publicação.
        # Sem ela, artigos reprovados pela auditoria editorial poderiam ser publicados.
        from ururau.publisher.workflow import can_publish as _gate
        artigo_gate = {**pauta, **md}
        ok_pub, motivo_pub = _gate(artigo_gate)
        if not ok_pub:
            # Artigo não aprovado — exibe motivo e bloqueia publicação
            if not messagebox.askyesno(
                "Publicação bloqueada — can_publish() = False",
                f"⚠ Este artigo NÃO passou no gate editorial:\n\n"
                f"{motivo_pub}\n\n"
                f"Deseja forçar o envio assim mesmo?\n"
                f"(Só faça isso se você aprovou manualmente.)"
            ):
                return
            # Registra que o editor forçou a publicação
            self.db.log_auditoria(uid, "publicacao_forcada",
                                  f"can_publish=False | {motivo_pub[:80]}")

        img_st = pauta.get("imagem_status", "pendente")
        if img_st != "aprovada":
            if not messagebox.askyesno("Imagem nao aprovada",
                f"Imagem com status '{img_st}'.\nEnviar mesmo assim?"):
                return
        sc = pauta.get("score_risco", 0) or 0
        if sc >= LIMIAR_RISCO_MAXIMO:
            if not messagebox.askyesno("Risco Alto",
                f"Score de risco {sc}/100 (limite {LIMIAR_RISCO_MAXIMO}).\nEnviar mesmo assim?"):
                return

        modo_txt = "como RASCUNHO (não publica ao vivo)" if rascunho else "DIRETAMENTE (publicara ao vivo!)"
        if not messagebox.askyesno("Confirmar",
            f"Enviar {modo_txt}:\n'{(pauta.get('titulo_origem') or '')[:70]}'\n"
            f"Canal: {pauta.get('canal_forcado') or pauta.get('canal', '')} | Risco: {sc}/100"):
            return
        self._set_status("Enviando para o CMS...")
        self._em_thread(self._publicar_thread, pauta, md, rascunho)

    def _publicar_thread(self, pauta: dict, md: dict, rascunho: bool = True):
        """Envia ao CMS — chama etapa_publicacao() com controle de rascunho."""
        try:
            from ururau.publisher.workflow import WorkflowPublicacao, _uid_para_pauta
            from ururau.core.models import Materia, ImagemDados
            uid = (pauta.get("uid") or pauta.get("_uid") or
                   _uid_para_pauta(pauta.get("link_origem", ""), pauta.get("titulo_origem", "")))
            pauta["_uid"] = uid
            wf = WorkflowPublicacao(self.db, self.client, self.modelo)
            if not wf.etapa_gate_antiduplicacao(uid, pauta, modo="publicar"):
                self.after(0, lambda: messagebox.showerror("Bloqueado", "Ja publicada no CMS."))
                return
            # Garante link_origem e fonte_nome no md antes de construir Materia
            if not md.get("link_origem"):
                md["link_origem"] = pauta.get("link_origem", "")
            if not md.get("fonte_nome"):
                md["fonte_nome"] = pauta.get("fonte_nome", "")
            canal_pauta = pauta.get("canal_forcado") or pauta.get("canal", "Brasil e Mundo")
            if not md.get("canal"):
                md["canal"] = canal_pauta
            # Reconstrói objeto Materia
            try:
                materia = Materia.from_dict(md)
                # Sobrescreve campos críticos com valores da pauta (fallback robusto)
                if not materia.link_origem:
                    materia.link_origem = pauta.get("link_origem", "")
                if not materia.fonte_nome:
                    materia.fonte_nome = pauta.get("fonte_nome", "")
                if not materia.canal:
                    materia.canal = canal_pauta
            except Exception:
                materia = Materia(
                    titulo=md.get("titulo", ""),
                    titulo_capa=md.get("titulo_capa", ""),
                    subtitulo=md.get("subtitulo", ""),
                    legenda=md.get("legenda", ""),
                    retranca=md.get("retranca", ""),
                    conteudo=md.get("conteudo", ""),
                    slug=md.get("slug", ""),
                    tags=md.get("tags", ""),
                    meta_description=md.get("meta_description", ""),
                    canal=canal_pauta,
                    score_risco=pauta.get("score_risco", 0) or 0,
                    resumo_curto=md.get("resumo_curto", ""),
                    chamada_social=md.get("chamada_social", ""),
                    link_origem=pauta.get("link_origem", ""),
                    fonte_nome=pauta.get("fonte_nome", ""),
                )
            # Reconstrói imagem
            imagem = None
            if pauta.get("imagem_caminho"):
                try:
                    imagem = ImagemDados(
                        caminho_imagem=pauta.get("imagem_caminho", ""),
                        url_imagem=pauta.get("imagem_url", ""),
                        credito_foto=pauta.get("imagem_credito", ""),
                        estrategia_imagem=pauta.get("imagem_estrategia", ""),
                    )
                except Exception:
                    pass
            sucesso = wf.etapa_publicacao(uid, pauta, materia, imagem, rascunho=rascunho)
            if sucesso:
                modo = "Rascunho salvo no CMS!" if rascunho else "Materia publicada ao vivo!"
                self.after(0, lambda: self._set_status(f"{'Rascunho salvo' if rascunho else 'Publicado'} [OK]"))
                self.after(0, lambda: messagebox.showinfo(
                    "Rascunho Salvo" if rascunho else "Publicado", modo))
            else:
                self.after(0, lambda: self._set_status("Falha no envio ao CMS"))
                self.after(0, lambda: messagebox.showerror("Falha",
                    "Nao foi possivel enviar ao CMS.\nVerifique credenciais e conexao."))
            self.after(0, self._carregar_pautas)
        except Exception as e:
            self.after(0, lambda: self._set_status(f"Erro no envio: {e}"))
            self.after(0, lambda: messagebox.showerror("Erro", str(e)))

    # ── Revisão editorial ─────────────────────────────────────────────────────
    # v66: O painel de Revisão (ui/revisao.py) foi REMOVIDO da toolbar.
    # A revisao agora acontece de duas formas:
    #   1. Preview (botao Preview na toolbar) - editor ve o resultado pronto
    #      e edita inline antes de "Enviar ao CMS" / "Publicar!".
    #   2. Copydesk (botao Copydesk na toolbar / Ctrl+K / Ctrl+R) - revisao
    #      item-a-item com sugestoes de IA, accept/reject/edit por campo e por
    #      paragrafo do corpo.
    # Este metodo continua existindo para nao quebrar codigo legado mas redireciona
    # ao Copydesk, que e a ferramenta correta de revisao item-por-item.

    def _acao_revisao(self):
        """v66: redireciona para Copydesk (revisao item-por-item com IA)."""
        try:
            self._set_status("Painel 'Revisao' foi substituido pelo Copydesk (v66).")
        except Exception:
            pass
        return self._acao_copydesk()

    def _ao_selecionar_revisao(self, pauta: dict):
        """
        Callback quando o usuário clica "Abrir revisão" em um item do PainelRevisao.
        Popula o painel de detalhes à direita e adiciona ações de revisão na aba Auditoria.
        """
        from ururau.ui.revisao import (
            _parse_materia as _rpm, montar_texto_erros,
            _can_publish_artigo, _status_validacao_da_materia,
        )
        self._pauta_sel = pauta
        self._set_status(f"Revisão: {(pauta.get('titulo_origem') or '')[:60]}")

        # Mostra detalhes normais nas abas existentes
        self._ao_trocar_aba()

        # Sobrescreve a aba Auditoria com visão de erros agrupados por categoria
        md = _rpm(pauta)
        txt_erros = montar_texto_erros(md)

        def _atualizar_aba_auditoria():
            # Adiciona header de revisão e erros agrupados
            uid = pauta.get("uid") or pauta.get("_uid", "")
            try:
                conn = self.db._conectar()
                try:
                    rows = conn.execute(
                        "SELECT timestamp, acao, detalhe, sucesso "
                        "FROM auditoria WHERE pauta_uid=? ORDER BY id ASC",
                        (uid,)).fetchall()
                finally:
                    conn.close()
                linhas_aud = [f"[{r['timestamp']}] {'[OK]' if r['sucesso'] else '[XX]'} "
                              f"{r['acao']:<26} {r['detalhe']}" for r in rows]
            except Exception:
                linhas_aud = []

            conteudo = (
                "╔══════════════════════════════════════════════════════╗\n"
                "║          REVISÃO EDITORIAL — ERROS AGRUPADOS         ║\n"
                "╚══════════════════════════════════════════════════════╝\n\n"
                + txt_erros
                + "\n\n" + "═" * 56 + "\n"
                + "HISTÓRICO DE AUDITORIA\n"
                + "═" * 56 + "\n"
                + ("\n".join(linhas_aud) if linhas_aud else "(sem registros)")
            )
            self._escrever(self._aba_auditoria, conteudo)

            # Adiciona botões de ação na aba Auditoria (ou statusbar)
            self._mostrar_acoes_revisao(pauta)

        self.after(0, _atualizar_aba_auditoria)

    def _mostrar_acoes_revisao(self, pauta: dict):
        """
        Exibe uma faixa de ações de revisão no painel de detalhes.
        Aparece abaixo do título da matéria, acima das abas.
        As ações são removidas quando o usuário volta para a fila normal.
        """
        from ururau.ui.revisao import (
            _parse_materia as _rpm, _can_publish_artigo,
            PainelRevisao as _PR,
        )

        # Remove faixa anterior se existir
        if hasattr(self, "_faixa_revisao") and self._faixa_revisao:
            try:
                self._faixa_revisao.destroy()
            except Exception:
                pass

        md = _rpm(pauta) or {}
        ok_pub, motivo_pub = _can_publish_artigo(pauta, md)

        # Cria um PainelRevisao headless para acesso às ações
        # v63 fix: armazena self (PainelUrurau, que é tk.Tk) como _parent
        # para que _get_parent() retorne um Tk widget válido em messagebox/Toplevel.
        _pr = _PR.__new__(_PR)
        _pr.db = self.db
        _pr.client = self.client
        _pr.modelo = self.modelo
        _pr._parent = self

        # Frame de ações (insere entre o título e o notebook)
        faixa = tk.Frame(self._frame_detalhe, bg="#0d0d20", pady=3)
        self._faixa_revisao = faixa

        # Insere a faixa ANTES do notebook (repack)
        faixa.pack(fill="x", before=self._notebook, padx=8)

        tk.Label(faixa, text="⚙ Ações de Revisão:", bg="#0d0d20",
                 fg=COR_AMARELO, font=FONTE_PEQUENA).pack(side="left", padx=6)

        def _corrigir():
            _pr.corrigir_pendencias(pauta, callback_ok=lambda: self._ao_selecionar_revisao(pauta))
        tk.Button(faixa, text="🔧 Corrigir pendências", command=_corrigir,
                  bg="#1e3a5f", fg=COR_CIANO, relief="flat",
                  font=FONTE_PEQUENA, padx=6, pady=2, cursor="hand2"
                  ).pack(side="left", padx=2)

        def _editar():
            _pr.abrir_edicao(pauta, callback_salvo=lambda: self._ao_selecionar_revisao(pauta))
        tk.Button(faixa, text="✏ Editar", command=_editar,
                  bg="#1e3a5f", fg=COR_AZUL, relief="flat",
                  font=FONTE_PEQUENA, padx=6, pady=2, cursor="hand2"
                  ).pack(side="left", padx=2)

        # Publicar — desabilitado se not can_publish
        pub_cor   = COR_VERDE if ok_pub else COR_CINZA
        pub_state = "normal" if ok_pub else "disabled"
        pub_tip   = "" if ok_pub else motivo_pub[:60]

        def _publicar():
            _pr.publicar_revisao(pauta, on_publicar=lambda p: self._acao_publicar())
        btn_pub = tk.Button(faixa, text="🚀 Publicar", command=_publicar,
                            bg="#0d2a1a" if ok_pub else "#1a1a2e",
                            fg=pub_cor, relief="flat",
                            font=FONTE_PEQUENA, padx=6, pady=2,
                            cursor="hand2" if ok_pub else "arrow",
                            state=pub_state)
        btn_pub.pack(side="left", padx=2)
        if not ok_pub and pub_tip:
            # Tooltip simples
            _tip = tk.Label(faixa, text=f"⚠ {pub_tip}", bg="#0d0d20",
                            fg=COR_VERMELHO, font=FONTE_PEQUENA, wraplength=280)
            _tip.pack(side="left", padx=4)

        # Menu "Mais" com ações secundárias
        def _mais():
            menu = tk.Menu(self, tearoff=0, bg=COR_PAINEL, fg=COR_TEXTO,
                           activebackground=COR_DESTAQUE, activeforeground="white")

            def _revisar_ia():
                _pr.revisar_com_ia(pauta, callback_ok=lambda: self._ao_selecionar_revisao(pauta))
            menu.add_command(label="🤖 Revisar com IA", command=_revisar_ia)

            def _aprovar_manual():
                _pr.aprovar_manualmente(pauta, callback_ok=lambda: self._ao_selecionar_revisao(pauta))
            menu.add_command(label="✔ Aprovar manualmente", command=_aprovar_manual)

            menu.add_separator()

            def _comparar_fonte():
                self._notebook.select(self._idx_aba_leitura)
            menu.add_command(label="📄 Comparar com fonte", command=_comparar_fonte)

            def _manter_rascunho():
                uid = pauta.get("uid") or pauta.get("_uid","")
                if uid:
                    self.db.log_auditoria(uid, "manter_rascunho", "Editor manteve como rascunho")
                messagebox.showinfo("Rascunho", "Matéria mantida como rascunho.", parent=self)
            menu.add_command(label="📌 Manter como rascunho", command=_manter_rascunho)

            def _adicionar_manual():
                self._acao_manual()
            menu.add_separator()
            menu.add_command(label="➕ Adicionar pauta manual", command=_adicionar_manual)

            menu.tk_popup(faixa.winfo_rootx(), faixa.winfo_rooty() + faixa.winfo_height())

        tk.Button(faixa, text="Mais ▾", command=_mais,
                  bg="#1e293b", fg=COR_CINZA, relief="flat",
                  font=FONTE_PEQUENA, padx=6, pady=2, cursor="hand2"
                  ).pack(side="right", padx=4)

    # ── Manual (preservado — acessível via Ctrl+M e menu Mais) ────────────────

    def _acao_manual(self):
        dlg = tk.Toplevel(self)
        dlg.title("Adicionar Pauta Manual")
        dlg.geometry("580x470")
        dlg.configure(bg=COR_FUNDO)
        dlg.grab_set()
        dlg.resizable(False, False)
        campos = {}
        for label, key, multi in [("Titulo *","titulo",False),("Link *","link",False),
                                   ("Fonte","fonte",False),("Resumo","resumo",True)]:
            tk.Label(dlg, text=label, bg=COR_FUNDO, fg=COR_TEXTO,
                     font=FONTE_NORMAL).pack(anchor="w", padx=16, pady=4)
            w = (tk.Text(dlg, height=4, bg=COR_PAINEL, fg=COR_TEXTO,
                         font=FONTE_MONO, insertbackground=COR_TEXTO) if multi
                 else tk.Entry(dlg, bg=COR_PAINEL, fg=COR_TEXTO,
                               font=FONTE_MONO, insertbackground=COR_TEXTO))
            w.pack(fill="x", padx=16)
            campos[key] = w
        tk.Label(dlg, text="Canal", bg=COR_FUNDO, fg=COR_TEXTO,
                 font=FONTE_NORMAL).pack(anchor="w", padx=16, pady=4)
        cb_c = ttk.Combobox(dlg, values=CANAIS_RODIZIO, font=FONTE_MONO,
                            state="normal", width=30)
        cb_c.pack(fill="x", padx=16)
        campos["canal"] = cb_c
        lbl_av = tk.Label(dlg, text="", bg=COR_FUNDO, fg=COR_AMARELO,
                          font=FONTE_PEQUENA, wraplength=520)
        lbl_av.pack(padx=16, pady=4)
        def check_link(_=None):
            lk = campos["link"].get().strip()
            if lk:
                s = self.db.classificar_pauta(lk)
                lbl_av.config(text=f"[AVIS] URL ja existe: {s}" if s != "nova" else "[OK] URL nova")
        campos["link"].bind("<FocusOut>", check_link)
        def salvar():
            from ururau.publisher.workflow import _uid_para_pauta
            titulo = campos["titulo"].get().strip()
            link   = campos["link"].get().strip()
            if not titulo or not link:
                messagebox.showerror("Erro", "Titulo e link sao obrigatorios.", parent=dlg); return
            if self.db.pauta_ja_publicada(link):
                messagebox.showerror("Ja publicada", "Link ja publicado.", parent=dlg); return
            uid = _uid_para_pauta(link, titulo)
            self.db.salvar_pauta({
                "_uid": uid, "titulo_origem": titulo, "link_origem": link,
                "fonte_nome": campos["fonte"].get().strip() or "Manual",
                "canal_forcado": cb_c.get().strip(),
                "resumo_origem": campos["resumo"].get("1.0","end").strip(),
                "status": StatusPauta.CAPTADA, "score_editorial": 50,
                "imagem_status": "pendente",
            })
            self.db.log_auditoria(uid, "pauta_manual", titulo[:80])
            dlg.destroy()
            self._carregar_pautas()
            self._set_status("Pauta manual adicionada [OK]")
        tk.Button(dlg, text="Salvar Pauta", command=salvar, bg=COR_VERDE,
                  fg="white", font=FONTE_TITULO, relief="flat",
                  padx=14, pady=6, cursor="hand2").pack(pady=12)

    # ── Descartar ─────────────────────────────────────────────────────────────

    def _acao_descartar(self):
        """Descarte com diálogo de motivo (botão Descartar na toolbar / Ctrl+D)."""
        if not self._pauta_sel:
            messagebox.showwarning("Descartar", "Selecione uma pauta primeiro."); return
        p   = self._pauta_sel
        uid = p.get("uid") or p.get("_uid", "")
        if not uid:
            messagebox.showerror("Erro", "UID nao encontrado."); return
        motivo = simpledialog.askstring("Descartar",
            f"Motivo (opcional):\n'{(p.get('titulo_origem') or '')[:70]}'", parent=self)
        if motivo is None:
            return
        self.db.marcar_descartada(uid, motivo or "Descarte manual", pauta=p)
        self._set_status(f"Descartada: {(p.get('titulo_origem') or '')[:40]}")
        self._carregar_pautas()

    def _descartar_rapido(self, pauta: dict, idx: int = -1):
        """
        Descarte rápido via tecla Delete na fila.

        Dupla garantia: além de atualizar status no banco, registra o link
        em 'links_bloqueados' para que NUNCA volte em coletas futuras,
        mesmo que a pauta não tivesse sido formalmente salva no banco antes.
        """
        uid   = pauta.get("uid") or pauta.get("_uid", "")
        titulo = (pauta.get("titulo_origem") or "")[:80]
        link   = pauta.get("link_origem", "")

        # Gera uid a partir do link se não existir (pauta recém-coletada sem salvar)
        if not uid and link:
            import hashlib
            uid = hashlib.md5(f"{link}{titulo}".encode()).hexdigest()[:16]
            pauta["_uid"] = uid

        ok = messagebox.askyesno(
            "Descartar pauta",
            f"Descartar esta pauta?\n\n«{titulo}»\n\n"
            "Ela não voltará a ser captada.",
            default="yes",
            parent=self,
        )
        if not ok:
            self._fila.focar()
            return

        # Persistência DUPLA: tabela pautas + links_bloqueados
        self.db.marcar_descartada(uid, "Descarte rápido (Del)", pauta=pauta)
        self._set_status(f"Descartada: {titulo[:50]}")

        # Remove da cache local para atualização imediata sem recarregar tudo
        self._pautas_cache = [p for p in self._pautas_cache
                              if (p.get("uid") or p.get("_uid")) != uid]
        self._aplicar_filtro()   # repopula a fila com o item removido

        # Seleciona o próximo item no mesmo índice (ou o anterior se era o último)
        itens_visiveis = self._fila._itens
        if itens_visiveis:
            novo_idx = min(idx, len(itens_visiveis) - 1)
            self._fila._selecionar(novo_idx)
            self._fila._scroll_para_visivel(novo_idx)
        self._fila.focar()

    def _descartar_via_tecla(self):
        """
        Delete global: só aciona o descarte rápido se o foco não estiver em
        um campo de texto (Entry, Text, ScrolledText, Combobox) para não
        interferir com edição normal.
        """
        widget_foco = self.focus_get()
        if widget_foco is None:
            return
        # Não aciona em campos de texto/edição
        ignorar = (tk.Entry, tk.Text, scrolledtext.ScrolledText, ttk.Combobox)
        if isinstance(widget_foco, ignorar):
            return
        # Delega ao descarte rápido se há pauta selecionada
        if self._pauta_sel:
            idx = self._fila._sel_idx or 0
            self._descartar_rapido(self._pauta_sel, idx)

    # ── Exclusão em lote ──────────────────────────────────────────────────────

    def _ao_mudar_selecao(self, qtd: int):
        """Callback da FilaPautas: atualiza botão de exclusão selecionadas."""
        if qtd > 0:
            self._btn_excluir_sel.config(
                text=f"🗑 Excluir Selecionadas ({qtd})",
                state="normal", bg="#7f0000", fg="#fca5a5"
            )
        else:
            self._btn_excluir_sel.config(
                text="🗑 Excluir Selecionadas (0)",
                state="disabled", bg="#4b0505", fg="#fca5a5"
            )

    def _selecionar_todos(self):
        """Marca todos os itens visíveis na fila com checkbox."""
        self._fila.selecionar_todos_visiveis()

    def _limpar_selecao(self):
        """Desmarca todos os checkboxes."""
        self._fila.limpar_selecao()

    def _acao_excluir_selecionadas(self):
        """Exclui todas as pautas marcadas com checkbox."""
        uids = self._fila.get_uids_selecionados()
        if not uids:
            return
        ok = messagebox.askyesno(
            "Excluir pautas selecionadas",
            f"Excluir {len(uids)} pauta(s) selecionada(s)?\n\n"
            "Elas ficarão ocultas na fila normal e não serão recaptadas.\n"
            "Você pode ver e recuperar excluídas pelo filtro '── excluídas ──' no Status.",
            parent=self,
        )
        if not ok:
            return
        # Monta lista (uid, link, titulo) a partir do cache
        uid_set = set(uids)
        uid_map = {p.get("uid") or p.get("_uid", ""): p for p in self._pautas_cache}
        lote = []
        for uid in uids:
            p = uid_map.get(uid, {})
            lote.append((uid, p.get("link_origem", ""), (p.get("titulo_origem") or "")[:200]))

        # Persiste no banco
        self.db.excluir_pautas_em_lote(lote)

        # Remove imediatamente do cache local — sem precisar de F5
        self._pautas_cache = [
            p for p in self._pautas_cache
            if (p.get("uid") or p.get("_uid", "")) not in uid_set
        ]
        self._fila.limpar_selecao()
        self._aplicar_filtro()
        n = len(uids)
        self._set_status(f"✓ {n} pauta(s) excluída(s). Use filtro '── excluídas ──' para recuperar.")

    def _acao_excluir_tudo(self):
        """Exclui todas as pautas atualmente visíveis na fila filtrada."""
        itens = list(self._fila._itens)   # cópia antes de limpar
        if not itens:
            messagebox.showinfo("Excluir tudo", "A fila está vazia.", parent=self)
            return
        filtro = self._filtro_var.get()
        ok = messagebox.askyesno(
            "Excluir TUDO visível",
            f"Excluir as {len(itens)} pauta(s) atualmente visíveis na fila?\n\n"
            f"Filtro atual: «{filtro}»\n"
            "Elas ficarão ocultas e não serão recaptadas.\n"
            "Você pode recuperá-las pelo filtro '── excluídas ──'.",
            parent=self,
        )
        if not ok:
            return
        lote = [
            (p.get("uid") or p.get("_uid", ""),
             p.get("link_origem", ""),
             (p.get("titulo_origem") or "")[:200])
            for p in itens
        ]
        uid_excluidos = {t[0] for t in lote}

        # Persiste no banco
        self.db.excluir_pautas_em_lote(lote)

        # Remove imediatamente do cache local
        self._pautas_cache = [
            p for p in self._pautas_cache
            if (p.get("uid") or p.get("_uid", "")) not in uid_excluidos
        ]
        self._aplicar_filtro()
        self._set_status(f"✓ {len(lote)} pauta(s) excluída(s). Use filtro '── excluídas ──' para recuperar.")

    def _acao_limpar_lista(self):
        """
        Limpa a lista imediatamente recarregando do banco.
        Garante que exclusões persistidas apareçam sem restart.
        """
        self._pautas_cache = []
        self._fila.popular([])
        self._set_status("Recarregando lista...")
        self._carregar_pautas()

    def _acao_reativar_pauta(self, pauta: dict):
        """Reativa uma pauta excluída: volta para 'captada'."""
        uid   = pauta.get("uid") or pauta.get("_uid", "")
        titulo = (pauta.get("titulo_origem") or "")[:60]
        link   = pauta.get("link_origem", "")
        ok = messagebox.askyesno(
            "Reativar pauta",
            f"Reativar esta pauta?\n\n«{titulo}»\n\n"
            "Ela voltará à fila normal com status 'captada'.",
            parent=self,
        )
        if not ok:
            return
        self.db.reativar_pauta(uid, link)
        # Atualiza no cache local imediatamente
        for p in self._pautas_cache:
            if (p.get("uid") or p.get("_uid", "")) == uid:
                p["status"] = "captada"
                break
        self._aplicar_filtro()
        self._set_status(f"✓ Reativada: {titulo}")

    # ── Histórico ─────────────────────────────────────────────────────────────

    def _acao_historico(self):
        dlg = tk.Toplevel(self)
        dlg.title("Historico")
        dlg.geometry("960x580")
        dlg.configure(bg=COR_FUNDO)
        tk.Label(dlg, text="Historico de Publicacoes", bg=COR_FUNDO,
                 fg=COR_TEXTO, font=FONTE_TITULO).pack(padx=12, pady=8, anchor="w")
        txt = scrolledtext.ScrolledText(dlg, bg="#16213e", fg=COR_TEXTO,
                                         font=FONTE_MONO, wrap="none")
        txt.pack(fill="both", expand=True, padx=8, pady=8)
        def _t():
            try:
                conn = self.db._conectar()
                try:
                    rows = conn.execute(
                        "SELECT titulo_origem, status, captada_em, atualizada_em, canal, fonte_nome "
                        "FROM pautas WHERE status IN ('publicada','pronta','revisada') "
                        "ORDER BY atualizada_em DESC LIMIT 200").fetchall()
                finally:
                    conn.close()
                linhas = [f"{'DATA':<20} {'STATUS':<12} {'CANAL':<16} {'FONTE':<18} TITULO",
                          "-" * 100]
                for r in rows:
                    data = (r["atualizada_em"] or r["captada_em"] or "")[:19]
                    linhas.append(f"{data:<20} {(r['status'] or ''):<12} "
                                  f"{(r['canal'] or ''):<16} {(r['fonte_nome'] or ''):<18} "
                                  f"{(r['titulo_origem'] or '')[:60]}")
                conteudo = "\n".join(linhas) if rows else "Nenhuma publicacao encontrada."
                self.after(0, lambda: (txt.insert("1.0", conteudo), txt.config(state="disabled")))
            except Exception as e:
                self.after(0, lambda: (txt.insert("1.0", f"Erro: {e}"), txt.config(state="disabled")))
        threading.Thread(target=_t, daemon=True).start()

    # ── Estatísticas ──────────────────────────────────────────────────────────

    def _acao_estatisticas(self):
        dlg = tk.Toplevel(self)
        dlg.title("Estatisticas")
        dlg.geometry("720x540")
        dlg.configure(bg=COR_FUNDO)
        tk.Label(dlg, text="Estatisticas", bg=COR_FUNDO,
                 fg=COR_TEXTO, font=FONTE_TITULO).pack(padx=12, pady=8, anchor="w")
        txt = scrolledtext.ScrolledText(dlg, bg="#16213e", fg=COR_TEXTO,
                                         font=FONTE_MONO, wrap="word")
        txt.pack(fill="both", expand=True, padx=8, pady=8)
        def _t():
            try:
                s = self.db.estatisticas()
                conn = self.db._conectar()
                try:
                    por_st = conn.execute("SELECT status, COUNT(*) n FROM pautas GROUP BY status ORDER BY n DESC").fetchall()
                    por_c  = conn.execute("SELECT canal, COUNT(*) n FROM pautas GROUP BY canal ORDER BY n DESC LIMIT 15").fetchall()
                    por_f  = conn.execute("SELECT fonte_nome, COUNT(*) n FROM pautas GROUP BY fonte_nome ORDER BY n DESC LIMIT 15").fetchall()
                    hoje   = conn.execute("SELECT COUNT(*) n FROM pautas WHERE date(captada_em)=date('now')").fetchone()["n"]
                    sem    = conn.execute("SELECT COUNT(*) n FROM pautas WHERE captada_em>=datetime('now','-7 days')").fetchone()["n"]
                finally:
                    conn.close()
                linhas = ["="*50,"  RESUMO GERAL","="*50,
                          f"Total pautas     : {s.get('total_pautas',0)}",
                          f"Total publicadas : {s.get('total_publicadas',0)}",
                          f"Total materias   : {s.get('total_materias',0)}",
                          f"Captadas hoje    : {hoje}",
                          f"Captadas (7d)    : {sem}",
                          "","="*50,"  POR STATUS","="*50]
                for r in por_st:
                    linhas.append(f"  {(r['status'] or 'N/A'):<22}: {r['n']}")
                linhas += ["","="*50,"  POR CANAL","="*50]
                for r in por_c:
                    linhas.append(f"  {(r['canal'] or 'N/A'):<24}: {r['n']}")
                linhas += ["","="*50,"  POR FONTE","="*50]
                for r in por_f:
                    linhas.append(f"  {(r['fonte_nome'] or 'N/A'):<24}: {r['n']}")
                c = "\n".join(linhas)
                self.after(0, lambda: (txt.insert("1.0", c), txt.config(state="disabled")))
            except Exception as e:
                self.after(0, lambda: (txt.insert("1.0", f"Erro: {e}"), txt.config(state="disabled")))
        threading.Thread(target=_t, daemon=True).start()

    # ── Exportar ──────────────────────────────────────────────────────────────

    def _acao_exportar(self):
        if not self._pauta_sel:
            messagebox.showwarning("Exportar", "Selecione uma pauta primeiro."); return
        md = _parse_materia(self._pauta_sel)
        if not md or not md.get("conteudo"):
            messagebox.showwarning("Exportar", "Sem materia gerada."); return
        p = self._pauta_sel
        default = f"materia_{(p.get('titulo_origem') or 'pauta')[:40]}.txt".replace("/","_").replace("\\","_")
        caminho = filedialog.asksaveasfilename(
            title="Salvar Materia", defaultextension=".txt", initialfile=default,
            filetypes=[("Texto","*.txt"),("Todos","*.*")])
        if not caminho:
            return
        try:
            linhas = [
                f"TITULO SEO    : {md.get('titulo','')}",
                f"TITULO CAPA   : {md.get('titulo_capa','')}",
                f"SUBTITULO     : {md.get('subtitulo','')}",
                f"LEGENDA FOTO  : {md.get('legenda','')}",
                f"RETRANCA      : {md.get('retranca','')}",
                f"SLUG          : {md.get('slug','')}",
                f"TAGS          : {md.get('tags','')}",
                f"META DESC     : {md.get('meta_description','')}",
                f"RESUMO CURTO  : {md.get('resumo_curto','')}",
                f"CHAMADA SOCIAL: {md.get('chamada_social','')}",
                f"CANAL         : {p.get('canal_forcado') or p.get('canal','')}",
                f"FONTE ORIGEM  : {p.get('fonte_nome','')}",
                f"PUB. NA FONTE : {p.get('data_pub_fonte','')}",
                f"LINK ORIGEM   : {p.get('link_origem','')}",
                "", "=" * 70, "", md.get("conteudo",""),
            ]
            Path(caminho).write_text("\n".join(linhas), encoding="utf-8")
            messagebox.showinfo("Exportado", f"Salvo em:\n{caminho}")
            self._set_status(f"Exportado: {Path(caminho).name}")
        except Exception as e:
            messagebox.showerror("Erro ao Exportar", str(e))

    # ── Configurações ─────────────────────────────────────────────────────────

    def _acao_configuracoes(self):
        self._abrir_config_inline()

    # ── Preview inline ────────────────────────────────────────────────────────

    def _abrir_preview_inline(self, pauta: dict, md: dict):
        """Monta o conteúdo de preview dentro da aba '✏ Preview' do notebook."""
        frame = self._aba_preview_frame
        # Destroi conteúdo anterior
        for w in frame.winfo_children():
            w.destroy()

        # Armazena referências para uso nos callbacks
        self._prev_pauta = pauta
        self._prev_md    = dict(md)

        rascunho_var = tk.BooleanVar(value=True)
        canal_inicial = (
            md.get("canal") or
            pauta.get("canal_forcado") or
            pauta.get("canal") or
            "Brasil e Mundo"
        )
        canal_var = tk.StringVar(value=canal_inicial)

        # ── Toolbar ──────────────────────────────────────────────────────────
        tb = tk.Frame(frame, bg=COR_PAINEL, height=50)
        tb.pack(fill="x")
        tb.pack_propagate(False)
        tk.Label(tb, text="✏ Preview e Edição",
                 bg=COR_PAINEL, fg=COR_TEXTO,
                 font=("Helvetica", 11, "bold")).pack(side="left", padx=10)

        def _salvar_inline():
            m = _coletar_prev()
            self._prev_md = m
            self._ao_salvar_preview(self._prev_pauta, m)
            messagebox.showinfo("Salvo", "Edições salvas!")

        def _salvar_e_pub_inline():
            m = _coletar_prev()
            self._ao_salvar_preview(self._prev_pauta, m)
            rascunho = rascunho_var.get()
            self._pauta_sel = self._prev_pauta
            self.after(100, lambda: self._acao_publicar(rascunho=rascunho))

        tk.Button(tb, text="Salvar Edições", command=_salvar_inline,
                  bg=COR_AZUL, fg="white", relief="flat", padx=8, pady=3,
                  cursor="hand2", font=("Helvetica", 9, "bold")).pack(side="right", padx=4, pady=8)
        tk.Button(tb, text="Enviar ao CMS", command=_salvar_e_pub_inline,
                  bg=COR_VERDE, fg="white", relief="flat", padx=8, pady=3,
                  cursor="hand2", font=("Helvetica", 9, "bold")).pack(side="right", padx=4, pady=8)

        # Toggle rascunho/publicar
        modo_frame = tk.Frame(tb, bg="#1e293b", padx=6, pady=3)
        modo_frame.pack(side="right", padx=6, pady=8)
        tk.Label(modo_frame, text="Modo:", bg="#1e293b", fg=COR_CINZA,
                 font=("Helvetica", 8)).pack(side="left")
        tk.Radiobutton(modo_frame, text="Rascunho", variable=rascunho_var, value=True,
                       bg="#1e293b", fg=COR_AMARELO, selectcolor="#374151",
                       activebackground="#1e293b", activeforeground=COR_AMARELO,
                       font=("Helvetica", 8, "bold")).pack(side="left", padx=3)
        tk.Radiobutton(modo_frame, text="Publicar!", variable=rascunho_var, value=False,
                       bg="#1e293b", fg=COR_VERMELHO, selectcolor="#374151",
                       activebackground="#1e293b", activeforeground=COR_VERMELHO,
                       font=("Helvetica", 8, "bold")).pack(side="left", padx=3)

        # ── Corpo: paned left/right ───────────────────────────────────────────
        paned = ttk.PanedWindow(frame, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=4, pady=2)

        left = tk.Frame(paned, bg=COR_PAINEL)
        paned.add(left, weight=1)

        # Imagem
        img_hdr = tk.Frame(left, bg=COR_PAINEL)
        img_hdr.pack(fill="x", padx=6, pady=(4, 2))
        tk.Label(img_hdr, text="Imagem", bg=COR_PAINEL, fg=COR_TEXTO,
                 font=FONTE_TITULO).pack(side="left")

        lbl_img = tk.Label(left, bg="#16213e", fg=COR_CINZA,
                           text="Carregando...", width=38, height=8,
                           font=FONTE_PEQUENA)
        lbl_img.pack(padx=6, pady=2, fill="x")

        img_st = pauta.get("imagem_status", "pendente")
        tk.Label(left, text=f"Status: {img_st}", bg=COR_PAINEL,
                 fg=(COR_VERDE if img_st == "aprovada" else COR_AMARELO),
                 font=("Helvetica", 8, "bold")).pack(padx=6, anchor="w")
        ic = pauta.get("imagem_caminho", "")
        tk.Label(left, text=Path(ic).name if ic else "(sem imagem)",
                 bg=COR_PAINEL, fg=COR_CINZA, font=FONTE_PEQUENA,
                 wraplength=280).pack(padx=6, anchor="w")

        tk.Frame(left, bg="#3a3a5c", height=1).pack(fill="x", padx=6, pady=3)

        # Metadados com scroll
        meta_canvas = tk.Canvas(left, bg=COR_PAINEL, highlightthickness=0)
        meta_sb = tk.Scrollbar(left, orient="vertical", command=meta_canvas.yview)
        meta_canvas.configure(yscrollcommand=meta_sb.set)
        meta_sb.pack(side="right", fill="y")
        meta_canvas.pack(side="left", fill="both", expand=True, padx=(6, 0))
        meta_inner = tk.Frame(meta_canvas, bg=COR_PAINEL)
        meta_canvas.create_window((0, 0), window=meta_inner, anchor="nw")
        meta_inner.bind("<Configure>",
                        lambda e: meta_canvas.configure(scrollregion=meta_canvas.bbox("all")))
        meta_canvas.bind("<MouseWheel>",
                         lambda e: meta_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        tk.Label(meta_inner, text="Metadados (editáveis):", bg=COR_PAINEL,
                 fg=COR_CINZA, font=FONTE_PEQUENA).pack(anchor="w", pady=2)
        self._prev_mvars: dict[str, tk.StringVar] = {}

        # Campos com limite de caracteres: (label, key, limite_max ou None)
        _campos_meta = [
            ("Titulo SEO",     "titulo",        90),
            ("Titulo Capa",    "titulo_capa",   60),
            ("Subtitulo",      "subtitulo",     200),
            ("Legenda Foto",   "legenda",       100),
            ("Retranca",       "retranca",      None),
            ("Slug",           "slug",          None),
            ("Tags",           "tags",          None),
            ("Chamada Social", "chamada_social", None),
        ]
        for lbl_t, key, limite in _campos_meta:
            hrow = tk.Frame(meta_inner, bg=COR_PAINEL)
            hrow.pack(fill="x", pady=(3, 0))
            tk.Label(hrow, text=lbl_t+":", bg=COR_PAINEL, fg=COR_CINZA,
                     font=("Helvetica", 8), anchor="w").pack(side="left")
            if limite:
                lbl_cnt = tk.Label(hrow, text=f"0/{limite}", bg=COR_PAINEL,
                                   fg=COR_CINZA, font=("Helvetica", 7))
                lbl_cnt.pack(side="right")
            v = tk.StringVar(value=self._prev_md.get(key, ""))
            e = tk.Entry(meta_inner, textvariable=v, bg="#16213e", fg=COR_TEXTO,
                         insertbackground=COR_TEXTO, font=("Courier New", 9),
                         relief="flat")
            e.pack(fill="x")
            self._prev_mvars[key] = v
            # Contador ao vivo com cor: verde=ok, amarelo=próximo, vermelho=excedido
            if limite:
                def _fazer_cb(var=v, lbl=lbl_cnt, lim=limite):
                    def _cb(*_):
                        n = len(var.get())
                        lbl.config(
                            text=f"{n}/{lim}",
                            fg=(COR_VERMELHO if n > lim
                                else COR_AMARELO if n > lim * 0.9
                                else COR_VERDE))
                    return _cb
                cb = _fazer_cb()
                v.trace_add("write", cb)
                cb()  # atualiza imediatamente com o valor atual

        sc = pauta.get("score_risco", 0) or 0
        tk.Label(meta_inner, text=f"Score Risco: {sc}/100", bg=COR_PAINEL,
                 fg=(COR_VERMELHO if sc >= LIMIAR_RISCO_MAXIMO
                     else COR_AMARELO if sc >= 30 else COR_VERDE),
                 font=("Helvetica", 8, "bold")).pack(pady=3, anchor="w")

        tk.Frame(meta_inner, bg="#3a3a5c", height=1).pack(fill="x", pady=3)
        tk.Label(meta_inner, text="Canal (editoria):", bg=COR_PAINEL, fg=COR_CINZA,
                 font=("Helvetica", 8), anchor="w").pack(fill="x", pady=(2, 0))
        canal_cb = ttk.Combobox(meta_inner, textvariable=canal_var,
                                values=CANAIS_CMS, state="normal",
                                font=("Courier New", 9))
        canal_cb.pack(fill="x")
        tk.Label(meta_inner, text="↑ Editoria que aparecerá no CMS",
                 bg=COR_PAINEL, fg=COR_CINZA,
                 font=("Helvetica", 7)).pack(anchor="w")

        # Painel direito: conteúdo
        right = tk.Frame(paned, bg=COR_PAINEL)
        paned.add(right, weight=2)
        tk.Label(right, text="Conteúdo (Ctrl+Z = desfazer)", bg=COR_PAINEL,
                 fg=COR_TEXTO, font=FONTE_TITULO).pack(padx=6, pady=3, anchor="w")
        self._prev_txt = tk.Text(right, bg="#16213e", fg=COR_TEXTO,
                                 insertbackground=COR_TEXTO,
                                 font=("Courier New", 10), wrap="word",
                                 relief="flat", padx=6, pady=6, undo=True)
        self._prev_txt.pack(fill="both", expand=True, padx=6, pady=3)
        bar = tk.Frame(right, bg=COR_PAINEL)
        bar.pack(fill="x", padx=6, pady=2)
        self._prev_lbl_chars = tk.Label(bar, text="", bg=COR_PAINEL,
                                        fg=COR_CINZA, font=FONTE_PEQUENA)
        self._prev_lbl_chars.pack(side="right")

        def _contar(_=None):
            n = len(self._prev_txt.get("1.0", "end-1c"))
            self._prev_lbl_chars.config(
                text=f"{n} caracteres",
                fg=COR_VERDE if 2000 <= n <= 6200 else COR_AMARELO)

        self._prev_txt.bind("<KeyRelease>", _contar)
        self._prev_txt.insert("1.0", self._prev_md.get("conteudo", ""))
        _contar()

        def _coletar_prev() -> dict:
            m = dict(self._prev_md)
            for k, v in self._prev_mvars.items():
                m[k] = v.get().strip()
            m["conteudo"] = self._prev_txt.get("1.0", "end-1c").strip()
            canal_escolhido = canal_var.get().strip()
            if canal_escolhido:
                m["canal"] = canal_escolhido
                self._prev_pauta["canal_forcado"] = canal_escolhido
            # Garante link_origem no md
            if not m.get("link_origem"):
                m["link_origem"] = self._prev_pauta.get("link_origem", "")
            return m

        # Carrega imagem em background
        def _load_img_inline():
            c = pauta.get("imagem_caminho", "")
            if not c:
                lbl_img.config(text="Nenhuma imagem associada."); return
            p2 = Path(c)
            if not p2.exists():
                p2 = Path("imagens") / p2.name
            if not p2.exists():
                lbl_img.config(text=f"Não encontrada:\n{c}"); return
            try:
                from PIL import Image, ImageTk
                img = Image.open(p2)
                img.thumbnail((320, 200), Image.LANCZOS)
                ftk = ImageTk.PhotoImage(img)
                self._prev_ftk = ftk
                lbl_img.config(image=ftk, text="", width=img.width, height=img.height)
            except ImportError:
                lbl_img.config(text=f"Pillow não instalado.\n{p2.name}")
            except Exception as ex:
                lbl_img.config(text=f"Erro:\n{ex}")

        frame.after(200, _load_img_inline)

        # Seleciona a aba Preview
        self._notebook.select(self._idx_aba_preview)

    # ── Config inline ─────────────────────────────────────────────────────────

    def _abrir_config_inline(self):
        """Monta o conteúdo de configurações dentro da aba '⚙ Config'."""
        frame = self._aba_config_frame
        for w in frame.winfo_children():
            w.destroy()

        # Reutiliza JanelaConfiguracoes mas incorporada num frame, não Toplevel
        cfg_widget = _ConfigWidget(frame, self.db)
        cfg_widget.pack(fill="both", expand=True)

        self._notebook.select(self._idx_aba_config)


# ── Janela Preview ────────────────────────────────────────────────────────────

class JanelaPreview(tk.Toplevel):

    def __init__(self, parent, pauta, md, db, cb_salvar, cb_publicar):
        super().__init__(parent)
        self._pauta    = pauta
        self._md       = dict(md)
        self._db       = db
        self._cb_s     = cb_salvar
        self._cb_p     = cb_publicar
        self._rascunho = tk.BooleanVar(value=True)  # padrão: salvar como rascunho
        # Canal: usa o canal já definido na matéria ou pauta, fallback "Brasil e Mundo"
        canal_inicial = (
            md.get("canal") or
            pauta.get("canal_forcado") or
            pauta.get("canal") or
            "Brasil e Mundo"
        )
        self._canal_var = tk.StringVar(value=canal_inicial)
        self.title(f"Preview — {(pauta.get('titulo_origem') or '')[:60]}")
        self.geometry("1160x820")
        self.configure(bg=COR_FUNDO)
        self.grab_set()
        self.resizable(True, True)
        self._build()

    def _build(self):
        # ── Toolbar ──────────────────────────────────────────────────────────
        tb = tk.Frame(self, bg=COR_PAINEL, height=56)
        tb.pack(fill="x")
        tb.pack_propagate(False)
        tk.Label(tb, text="Preview e Edicao", bg=COR_PAINEL, fg=COR_TEXTO,
                 font=("Helvetica", 12, "bold")).pack(side="left", padx=12)

        # Botões de ação
        tk.Button(tb, text="Fechar", command=self.destroy,
                  bg=COR_CINZA, fg="white", relief="flat", padx=10, pady=4,
                  cursor="hand2", font=("Helvetica", 10, "bold")).pack(side="right", padx=4, pady=8)
        tk.Button(tb, text="Salvar Edicoes", command=self._salvar,
                  bg=COR_AZUL, fg="white", relief="flat", padx=10, pady=4,
                  cursor="hand2", font=("Helvetica", 10, "bold")).pack(side="right", padx=4, pady=8)
        tk.Button(tb, text="Enviar ao CMS", command=self._salvar_e_pub,
                  bg=COR_VERDE, fg="white", relief="flat", padx=10, pady=4,
                  cursor="hand2", font=("Helvetica", 10, "bold")).pack(side="right", padx=4, pady=8)

        # Toggle rascunho/publicar
        modo_frame = tk.Frame(tb, bg="#1e293b", padx=6, pady=3)
        modo_frame.pack(side="right", padx=8, pady=8)
        tk.Label(modo_frame, text="Modo:", bg="#1e293b", fg=COR_CINZA,
                 font=("Helvetica", 8)).pack(side="left")
        tk.Radiobutton(modo_frame, text="Rascunho", variable=self._rascunho, value=True,
                       bg="#1e293b", fg=COR_AMARELO, selectcolor="#374151",
                       activebackground="#1e293b", activeforeground=COR_AMARELO,
                       font=("Helvetica", 9, "bold")).pack(side="left", padx=4)
        tk.Radiobutton(modo_frame, text="Publicar!", variable=self._rascunho, value=False,
                       bg="#1e293b", fg=COR_VERMELHO, selectcolor="#374151",
                       activebackground="#1e293b", activeforeground=COR_VERMELHO,
                       font=("Helvetica", 9, "bold")).pack(side="left", padx=4)

        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=8, pady=4)

        left = tk.Frame(paned, bg=COR_PAINEL)
        paned.add(left, weight=1)

        # ── Seção de imagem ───────────────────────────────────────────────────
        img_hdr = tk.Frame(left, bg=COR_PAINEL)
        img_hdr.pack(fill="x", padx=8, pady=(4, 2))
        tk.Label(img_hdr, text="Imagem", bg=COR_PAINEL, fg=COR_TEXTO,
                 font=FONTE_TITULO).pack(side="left")
        # Botões de imagem inline
        tk.Button(img_hdr, text="📁 Escolher arquivo",
                  command=self._escolher_imagem_arquivo,
                  bg="#1e3a5f", fg="#7dd3fc", relief="flat",
                  padx=5, pady=1, cursor="hand2",
                  font=("Segoe UI", 7, "bold")).pack(side="right", padx=2)
        tk.Button(img_hdr, text="🔍 Buscar por tema",
                  command=self._buscar_imagem_tema,
                  bg="#1e293b", fg=COR_CIANO, relief="flat",
                  padx=5, pady=1, cursor="hand2",
                  font=("Segoe UI", 7, "bold")).pack(side="right", padx=2)

        self._lbl_img = tk.Label(left, bg="#16213e", fg=COR_CINZA,
                                  text="Carregando...", width=40, height=10,
                                  font=FONTE_PEQUENA)
        self._lbl_img.pack(padx=8, pady=4, fill="x")
        img_st = self._pauta.get("imagem_status", "pendente")
        self._lbl_img_status = tk.Label(left, text=f"Status: {img_st}", bg=COR_PAINEL,
                 fg=(COR_VERDE if img_st == "aprovada" else COR_AMARELO),
                 font=("Helvetica", 9, "bold"))
        self._lbl_img_status.pack(padx=8, anchor="w")
        self._lbl_img_nome = tk.Label(left,
                     text=Path(self._pauta["imagem_caminho"]).name if self._pauta.get("imagem_caminho") else "(sem imagem)",
                     bg=COR_PAINEL, fg=COR_CINZA, font=FONTE_PEQUENA,
                     wraplength=320)
        self._lbl_img_nome.pack(padx=8, anchor="w")

        tk.Frame(left, bg="#3a3a5c", height=1).pack(fill="x", padx=8, pady=4)

        # ── Metadados editáveis (com scroll) ─────────────────────────────────
        meta_canvas = tk.Canvas(left, bg=COR_PAINEL, highlightthickness=0)
        meta_sb = tk.Scrollbar(left, orient="vertical", command=meta_canvas.yview)
        meta_canvas.configure(yscrollcommand=meta_sb.set)
        meta_sb.pack(side="right", fill="y")
        meta_canvas.pack(side="left", fill="both", expand=True, padx=(8, 0))
        meta_inner = tk.Frame(meta_canvas, bg=COR_PAINEL)
        meta_canvas.create_window((0, 0), window=meta_inner, anchor="nw")
        meta_inner.bind("<Configure>",
                        lambda e: meta_canvas.configure(scrollregion=meta_canvas.bbox("all")))
        meta_canvas.bind("<MouseWheel>",
                         lambda e: meta_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        tk.Label(meta_inner, text="Metadados (editaveis):", bg=COR_PAINEL,
                 fg=COR_CINZA, font=FONTE_PEQUENA).pack(anchor="w", pady=2)
        self._mvars: dict[str, tk.StringVar] = {}
        _campos_jpreview = [
            ("Titulo SEO",     "titulo",        90),
            ("Titulo Capa",    "titulo_capa",   60),
            ("Subtitulo",      "subtitulo",     200),
            ("Legenda Foto",   "legenda",       100),
            ("Retranca",       "retranca",      None),
            ("Slug",           "slug",          None),
            ("Tags",           "tags",          None),
            ("Chamada Social", "chamada_social", None),
        ]
        for lbl, key, limite in _campos_jpreview:
            hrow = tk.Frame(meta_inner, bg=COR_PAINEL)
            hrow.pack(fill="x", pady=(3, 0))
            tk.Label(hrow, text=lbl+":", bg=COR_PAINEL, fg=COR_CINZA,
                     font=("Helvetica", 8), anchor="w").pack(side="left")
            if limite:
                lbl_cnt = tk.Label(hrow, text=f"0/{limite}", bg=COR_PAINEL,
                                   fg=COR_CINZA, font=("Helvetica", 7))
                lbl_cnt.pack(side="right")
            v = tk.StringVar(value=self._md.get(key, ""))
            tk.Entry(meta_inner, textvariable=v, bg="#16213e", fg=COR_TEXTO,
                     insertbackground=COR_TEXTO, font=("Courier New", 9),
                     relief="flat").pack(fill="x")
            self._mvars[key] = v
            if limite:
                def _fazer_cb_jp(var=v, lbl=lbl_cnt, lim=limite):
                    def _cb(*_):
                        n = len(var.get())
                        lbl.config(
                            text=f"{n}/{lim}",
                            fg=(COR_VERMELHO if n > lim
                                else COR_AMARELO if n > lim * 0.9
                                else COR_VERDE))
                    return _cb
                cb = _fazer_cb_jp()
                v.trace_add("write", cb)
                cb()
        sc = self._pauta.get("score_risco", 0) or 0
        tk.Label(meta_inner, text=f"Score Risco: {sc}/100", bg=COR_PAINEL,
                 fg=(COR_VERMELHO if sc >= LIMIAR_RISCO_MAXIMO
                     else COR_AMARELO if sc >= 30 else COR_VERDE),
                 font=("Helvetica", 9, "bold")).pack(pady=4, anchor="w")

        # ── Canal editorial ───────────────────────────────────────────────────
        tk.Frame(meta_inner, bg="#3a3a5c", height=1).pack(fill="x", pady=4)
        tk.Label(meta_inner, text="Canal (editoria):", bg=COR_PAINEL, fg=COR_CINZA,
                 font=("Helvetica", 8), anchor="w").pack(fill="x", pady=(2, 0))
        canal_cb = ttk.Combobox(meta_inner, textvariable=self._canal_var,
                                values=CANAIS_CMS, state="normal",
                                font=("Courier New", 9))
        canal_cb.pack(fill="x")
        tk.Label(meta_inner, text="↑ Editoria que aparecerá no CMS",
                 bg=COR_PAINEL, fg=COR_CINZA,
                 font=("Helvetica", 7)).pack(anchor="w")

        right = tk.Frame(paned, bg=COR_PAINEL)
        paned.add(right, weight=2)
        tk.Label(right, text="Conteudo (Ctrl+Z = desfazer)", bg=COR_PAINEL,
                 fg=COR_TEXTO, font=FONTE_TITULO).pack(padx=8, pady=4, anchor="w")
        self._txt = tk.Text(right, bg="#16213e", fg=COR_TEXTO,
                            insertbackground=COR_TEXTO,
                            font=("Courier New", 10), wrap="word",
                            relief="flat", padx=8, pady=8, undo=True)
        self._txt.pack(fill="both", expand=True, padx=8, pady=4)
        bar = tk.Frame(right, bg=COR_PAINEL)
        bar.pack(fill="x", padx=8, pady=2)
        self._lbl_chars = tk.Label(bar, text="", bg=COR_PAINEL,
                                   fg=COR_CINZA, font=FONTE_PEQUENA)
        self._lbl_chars.pack(side="right")
        self._txt.bind("<KeyRelease>", self._contar)
        self._txt.insert("1.0", self._md.get("conteudo", ""))
        self._contar()
        self.after(300, self._load_img)

    def _contar(self, _=None):
        n = len(self._txt.get("1.0", "end-1c"))
        self._lbl_chars.config(
            text=f"{n} caracteres",
            fg=COR_VERDE if 2000 <= n <= 6200 else COR_AMARELO)

    def _load_img(self):
        c = self._pauta.get("imagem_caminho", "")
        if not c:
            self._lbl_img.config(text="Nenhuma imagem associada.\nUse os botões acima para adicionar."); return
        p = Path(c)
        if not p.exists():
            p = Path("imagens") / p.name
        if not p.exists():
            self._lbl_img.config(text=f"Imagem nao encontrada:\n{c}"); return
        try:
            from PIL import Image, ImageTk
            img = Image.open(p)
            img.thumbnail((360, 240), Image.LANCZOS)
            self._ftk = ImageTk.PhotoImage(img)
            self._lbl_img.config(image=self._ftk, text="",
                                  width=img.width, height=img.height)
        except ImportError:
            self._lbl_img.config(text=f"Pillow nao instalado.\n{p.name}")
        except Exception as e:
            self._lbl_img.config(text=f"Erro ao exibir:\n{e}")

    def _escolher_imagem_arquivo(self):
        """Permite ao usuário escolher uma imagem do computador."""
        from tkinter import filedialog
        caminho = filedialog.askopenfilename(
            title="Escolher imagem",
            filetypes=[("Imagens", "*.jpg *.jpeg *.png *.webp *.gif *.bmp"),
                       ("Todos", "*.*")],
            parent=self)
        if not caminho:
            return
        p = Path(caminho)
        # Copia para a pasta de imagens do sistema
        import shutil
        pasta_img = Path("imagens")
        pasta_img.mkdir(exist_ok=True)
        destino = pasta_img / p.name
        try:
            shutil.copy2(caminho, destino)
        except Exception:
            destino = p  # usa o caminho original se não conseguir copiar
        self._pauta["imagem_caminho"] = str(destino)
        self._pauta["imagem_status"]  = "aprovada"
        self._pauta["imagem_credito"] = "Arquivo local"
        # Atualiza UI
        self._lbl_img_status.config(text="Status: aprovada", fg=COR_VERDE)
        self._lbl_img_nome.config(text=p.name)
        self._load_img()
        # Salva no banco
        uid = self._pauta.get("uid") or self._pauta.get("_uid", "")
        if uid:
            self._db.salvar_pauta({**self._pauta, "_uid": uid})
        messagebox.showinfo("Imagem carregada", f"Imagem '{p.name}' selecionada!", parent=self)

    def _buscar_imagem_tema(self):
        """Abre janela para buscar imagem por tema/palavra-chave."""
        # Sugere o título da matéria como tema inicial
        titulo = self._md.get("titulo", "") or self._pauta.get("titulo_origem", "")
        # Pega as primeiras palavras relevantes como sugestão
        import re
        palavras = re.findall(r'\b[A-Z][a-z]+\b|\b[a-z]{4,}\b', titulo)
        sugestao = " ".join(palavras[:4]) if palavras else titulo[:40]

        tema = simpledialog.askstring(
            "Buscar Imagem por Tema",
            f"Digite o tema para buscar imagens:\n\n"
            f"Exemplo: 'Polícia Rio de Janeiro operação'\n\n"
            f"Sugestão baseada na matéria:",
            initialvalue=sugestao,
            parent=self)
        if not tema:
            return

        self._lbl_img.config(text=f"🔍 Buscando: '{tema}'...")
        self.update()
        threading.Thread(target=self._buscar_imagem_tema_thread,
                         args=(tema,), daemon=True).start()

    def _buscar_imagem_tema_thread(self, tema: str):
        """Executa a busca de imagem em background."""
        try:
            from ururau.imaging.busca import buscar_imagem_bing, buscar_imagem_wikimedia
            from ururau.imaging.processamento import processar_imagem
            uid = self._pauta.get("uid") or self._pauta.get("_uid", "busca_manual")

            imagem = None
            # Tenta Bing primeiro
            try:
                imagem = buscar_imagem_bing(tema, uid)
            except Exception:
                pass
            # Fallback: Wikimedia
            if not imagem:
                try:
                    imagem = buscar_imagem_wikimedia(tema, uid)
                except Exception:
                    pass

            if imagem and imagem.caminho_imagem:
                self._pauta["imagem_caminho"]    = imagem.caminho_imagem
                self._pauta["imagem_status"]     = "aprovada"
                self._pauta["imagem_url"]        = imagem.url_imagem
                self._pauta["imagem_credito"]    = imagem.credito_foto
                self._pauta["imagem_estrategia"] = imagem.estrategia_imagem
                self.after(0, self._load_img)
                self.after(0, lambda: self._lbl_img_status.config(text="Status: aprovada", fg=COR_VERDE))
                self.after(0, lambda: self._lbl_img_nome.config(
                    text=Path(imagem.caminho_imagem).name))
                # Salva no banco
                if uid and uid != "busca_manual":
                    self._db.salvar_imagem(uid, imagem.to_dict())
                    self._db.salvar_pauta({**self._pauta, "_uid": uid})
                self.after(0, lambda: messagebox.showinfo(
                    "Imagem encontrada",
                    f"Imagem encontrada para '{tema}'!\n"
                    f"Estratégia: {imagem.estrategia_imagem}", parent=self))
            else:
                self.after(0, lambda: self._lbl_img.config(
                    text=f"Nenhuma imagem encontrada para:\n'{tema}'\n\nTente outro tema."))
                self.after(0, lambda: messagebox.showwarning(
                    "Sem imagem",
                    f"Não foi possível encontrar imagem para '{tema}'.\n"
                    f"Tente um tema diferente ou use 'Escolher arquivo'.",
                    parent=self))
        except Exception as e:
            self.after(0, lambda: self._lbl_img.config(text=f"Erro na busca:\n{e}"))
            self.after(0, lambda: messagebox.showerror("Erro", str(e), parent=self))

    def _coletar(self):
        m = dict(self._md)
        for k, v in self._mvars.items():
            m[k] = v.get().strip()
        m["conteudo"] = self._txt.get("1.0", "end-1c").strip()
        # Canal selecionado manualmente pelo editor
        canal_escolhido = self._canal_var.get().strip()
        if canal_escolhido:
            m["canal"] = canal_escolhido
            # Propaga para a pauta também, para o workflow usar corretamente
            self._pauta["canal_forcado"] = canal_escolhido
        return m

    def _salvar(self):
        m = self._coletar()
        self._md = m
        self._cb_s(self._pauta, m)
        messagebox.showinfo("Salvo", "Edicoes salvas!", parent=self)

    def _salvar_e_pub(self):
        m = self._coletar()
        self._cb_s(self._pauta, m)
        rascunho = self._rascunho.get()
        self.destroy()
        self.master.after(300, lambda: self._cb_p(rascunho=rascunho))


# ── Aba Monitor (integrada ao painel principal) ───────────────────────────────

class AbaMonitor(tk.Frame):
    """
    Painel de controle do Robô de Monitoramento 24h integrado como aba.

    Substitui JanelaMonitor (Toplevel) — tudo dentro do notebook de detalhes.
    Permite configurar e iniciar/parar o robô sem sair do painel.
    Exibe log ao vivo das atividades do robô.
    """

    def __init__(self, parent, db, client, modelo,
                 robo_existente=None, cb_robo_atualizado=None):
        super().__init__(parent, bg=COR_FUNDO)
        self._db             = db
        self._client         = client
        self._modelo         = modelo
        self._robo           = robo_existente
        self._thread         = None
        self._cb_atualizado  = cb_robo_atualizado or (lambda r, t: None)
        self._log_ultimas    = 0   # contador para leitura incremental do log
        self._build()
        self.after(500, self._tick)

    def _build(self):
        # ── Toolbar ──────────────────────────────────────────────────────────
        tb = tk.Frame(self, bg="#11112a", height=46)
        tb.pack(fill="x")
        tb.pack_propagate(False)
        tk.Label(tb, text="🤖 Robô de Monitoramento 24h",
                 bg="#11112a", fg=COR_DESTAQUE,
                 font=("Helvetica", 11, "bold")).pack(side="left", padx=10)

        self._btn_stop = tk.Button(tb, text="■  PARAR",
                                   command=self._parar,
                                   bg="#7f1d1d", fg="#fca5a5",
                                   relief="flat", padx=10, pady=3,
                                   cursor="hand2",
                                   font=("Helvetica", 9, "bold"),
                                   state="disabled")
        self._btn_stop.pack(side="right", padx=4, pady=6)

        self._btn_start = tk.Button(tb, text="▶  INICIAR MONITOR",
                                    command=self._iniciar,
                                    bg="#14532d", fg="#86efac",
                                    relief="flat", padx=10, pady=3,
                                    cursor="hand2",
                                    font=("Helvetica", 9, "bold"))
        self._btn_start.pack(side="right", padx=4, pady=6)

        # ── Status banner ─────────────────────────────────────────────────────
        self._banner = tk.Frame(self, bg="#1c1c35", height=32)
        self._banner.pack(fill="x")
        self._banner.pack_propagate(False)
        self._lbl_status = tk.Label(self._banner, text="● INATIVO",
                                    bg="#1c1c35", fg=COR_CINZA,
                                    font=("Segoe UI", 10, "bold"))
        self._lbl_status.pack(side="left", padx=10)
        self._lbl_contagem = tk.Label(self._banner, text="",
                                      bg="#1c1c35", fg=COR_CINZA,
                                      font=("Segoe UI", 8))
        self._lbl_contagem.pack(side="left", padx=8)

        # ── Configurações ─────────────────────────────────────────────────────
        cfg = tk.LabelFrame(self, text="Configurações", bg=COR_FUNDO, fg=COR_TEXTO,
                            font=("Segoe UI", 8, "bold"), padx=8, pady=4)
        cfg.pack(fill="x", padx=8, pady=4)

        from ururau.config.settings import (
            INTERVALO_ENTRE_CICLOS_SEGUNDOS,
            MAX_PUBLICACOES_MONITORAMENTO_POR_HORA,
        )

        row1 = tk.Frame(cfg, bg=COR_FUNDO)
        row1.pack(fill="x")
        tk.Label(row1, text="Intervalo entre ciclos (seg):",
                 bg=COR_FUNDO, fg=COR_TEXTO,
                 font=("Segoe UI", 8), width=28, anchor="w").pack(side="left")
        self._var_intervalo = tk.StringVar(value=str(INTERVALO_ENTRE_CICLOS_SEGUNDOS))
        tk.Entry(row1, textvariable=self._var_intervalo,
                 bg="#16213e", fg=COR_VERDE, insertbackground=COR_TEXTO,
                 font=("Courier New", 9), width=7, relief="flat").pack(side="left", padx=6)
        tk.Label(row1, text=f"(≈{INTERVALO_ENTRE_CICLOS_SEGUNDOS//60}min)",
                 bg=COR_FUNDO, fg=COR_CINZA, font=("Segoe UI", 7)).pack(side="left")

        row2 = tk.Frame(cfg, bg=COR_FUNDO)
        row2.pack(fill="x", pady=2)
        tk.Label(row2, text="Máx. matérias por hora:",
                 bg=COR_FUNDO, fg=COR_TEXTO,
                 font=("Segoe UI", 8), width=28, anchor="w").pack(side="left")
        self._var_max_hora = tk.StringVar(value=str(MAX_PUBLICACOES_MONITORAMENTO_POR_HORA))
        tk.Entry(row2, textvariable=self._var_max_hora,
                 bg="#16213e", fg=COR_VERDE, insertbackground=COR_TEXTO,
                 font=("Courier New", 9), width=7, relief="flat").pack(side="left", padx=6)

        row3 = tk.Frame(cfg, bg=COR_FUNDO)
        row3.pack(fill="x")
        self._var_publicar = tk.BooleanVar(value=False)
        tk.Checkbutton(row3, text="Publicar diretamente no CMS",
                       variable=self._var_publicar,
                       bg=COR_FUNDO, fg=COR_TEXTO, selectcolor="#1e3a5f",
                       activebackground=COR_FUNDO, activeforeground=COR_TEXTO,
                       font=("Segoe UI", 8)).pack(side="left")

        # ── Log ao vivo ───────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=COR_FUNDO)
        hdr.pack(fill="x", padx=8, pady=(4, 0))
        tk.Label(hdr, text="Log ao vivo:", bg=COR_FUNDO, fg=COR_CINZA,
                 font=("Segoe UI", 8)).pack(side="left")
        tk.Button(hdr, text="Limpar", command=self._limpar_log,
                  bg="#1e293b", fg=COR_CINZA, relief="flat",
                  font=("Segoe UI", 7), padx=6, pady=1,
                  cursor="hand2").pack(side="right")

        self._log_txt = scrolledtext.ScrolledText(self, bg="#080818", fg="#94a3b8",
                                                   font=("Courier New", 8),
                                                   state="disabled", wrap="word")
        self._log_txt.pack(fill="both", expand=True, padx=8, pady=(0, 6))
        self._log_txt.tag_configure("ok",   foreground="#86efac")
        self._log_txt.tag_configure("err",  foreground="#fca5a5")
        self._log_txt.tag_configure("info", foreground="#94a3b8")
        self._log_txt.tag_configure("warn", foreground="#fde68a")

        # Lê log existente
        self.after(300, self._ler_log_arquivo)

    # ── Log ───────────────────────────────────────────────────────────────────

    def _ler_log_arquivo(self):
        """Carrega as últimas 80 linhas do monitor.log."""
        log_path = Path("logs") / "monitor.log"
        if not log_path.exists():
            self._append_log("(nenhum log anterior encontrado)", "info")
            return
        try:
            linhas = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
            ultimas = linhas[-80:]
            self._log_ultimas = len(linhas)
            for ln in ultimas:
                self._append_log(ln, self._tag_linha(ln))
        except Exception as e:
            self._append_log(f"Erro ao ler log: {e}", "err")

    def _tag_linha(self, ln: str) -> str:
        if "[OK]" in ln or "OK" in ln:
            return "ok"
        if "ERROR" in ln or "ERRO" in ln or "[XX]" in ln:
            return "err"
        if "WARNING" in ln or "AVISO" in ln or "WARN" in ln:
            return "warn"
        return "info"

    def _append_log(self, texto: str, tag: str = "info"):
        self._log_txt.config(state="normal")
        self._log_txt.insert("end", texto + "\n", tag)
        self._log_txt.see("end")
        self._log_txt.config(state="disabled")

    def _limpar_log(self):
        self._log_txt.config(state="normal")
        self._log_txt.delete("1.0", "end")
        self._log_txt.config(state="disabled")

    # ── Controles ─────────────────────────────────────────────────────────────

    def _iniciar(self):
        if not self._client:
            messagebox.showerror("Monitor",
                "Configure OPENAI_API_KEY antes de iniciar.")
            return
        if self._robo and self._robo.ativo:
            messagebox.showinfo("Monitor", "O monitor já está ativo.")
            return
        try:
            intervalo = int(self._var_intervalo.get())
            max_hora  = int(self._var_max_hora.get())
        except ValueError:
            messagebox.showerror("Erro", "Valores inválidos nos campos.")
            return
        publicar = self._var_publicar.get()

        from ururau.publisher.monitor import MonitorRobo
        self._robo = MonitorRobo(
            db=self._db,
            client=self._client,
            modelo=self._modelo,
            intervalo_segundos=intervalo,
            max_por_hora=max_hora,
            publicar_no_cms=publicar,
        )
        def _run():
            try:
                self._robo.iniciar()
            except Exception as e:
                self.after(0, lambda: self._append_log(f"[ERRO] {e}", "err"))
            finally:
                self.after(0, self._atualizar_ui)
        self._thread = threading.Thread(target=_run, daemon=True, name="MonitorRobo")
        self._thread.start()
        self._atualizar_ui()
        self._cb_atualizado(self._robo, self._thread)
        self._append_log(
            f"[Monitor] Iniciado. Intervalo={intervalo}s Max/hora={max_hora} "
            f"CMS={'SIM' if publicar else 'NAO'}", "ok")

    def _parar(self):
        if self._robo:
            self._robo.parar()
        self._atualizar_ui()
        self._cb_atualizado(self._robo, self._thread)
        self._append_log("[Monitor] Parado pelo usuário.", "warn")

    def _atualizar_ui(self):
        ativo = bool(self._robo and self._robo.ativo)
        if ativo:
            n = self._robo.publicacoes_na_hora
            self._lbl_status.config(
                text=f"● ATIVO — {n} matéria(s) publicadas na última hora",
                fg=COR_VERDE)
            self._btn_start.config(state="disabled")
            self._btn_stop.config(state="normal")
        else:
            self._lbl_status.config(text="● INATIVO", fg=COR_CINZA)
            self._btn_start.config(state="normal")
            self._btn_stop.config(state="disabled")

    def _tick(self):
        """Atualiza UI e log incrementalmente a cada 20s."""
        try:
            self._atualizar_ui()
            # Lê novas linhas do log desde a última leitura
            log_path = Path("logs") / "monitor.log"
            if log_path.exists():
                try:
                    linhas = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
                    if len(linhas) > self._log_ultimas:
                        novas = linhas[self._log_ultimas:]
                        self._log_ultimas = len(linhas)
                        for ln in novas:
                            self._append_log(ln, self._tag_linha(ln))
                except Exception:
                    pass
        except Exception:
            pass
        # Agenda próximo tick apenas se o widget ainda existe
        try:
            self.after(20_000, self._tick)
        except Exception:
            pass


# ── Janela Monitor 24h (mantida para compatibilidade) ─────────────────────────

class JanelaMonitor(tk.Toplevel):
    """
    Painel de controle do Robô de Monitoramento 24h.

    Permite configurar e iniciar/parar o robô sem sair do painel principal.
    Exibe log ao vivo das atividades do robô.
    """

    def __init__(self, parent, db, client, modelo,
                 robo_existente=None, cb_robo_atualizado=None):
        super().__init__(parent)
        self._db             = db
        self._client         = client
        self._modelo         = modelo
        self._robo           = robo_existente
        self._thread         = None
        self._cb_atualizado  = cb_robo_atualizado or (lambda r, t: None)
        self.title("Robô de Monitoramento 24h")
        self.geometry("780x600")
        self.configure(bg=COR_FUNDO)
        self.resizable(True, True)
        self._build()
        self._tick()

    def _build(self):
        # ── Toolbar ──────────────────────────────────────────────────────────
        tb = tk.Frame(self, bg="#11112a", height=50)
        tb.pack(fill="x")
        tb.pack_propagate(False)
        tk.Label(tb, text="🤖 Robô de Monitoramento 24h",
                 bg="#11112a", fg=COR_DESTAQUE,
                 font=("Helvetica", 12, "bold")).pack(side="left", padx=12)

        self._btn_start = tk.Button(tb, text="▶  INICIAR MONITOR",
                                    command=self._iniciar,
                                    bg="#14532d", fg="#86efac",
                                    relief="flat", padx=12, pady=4,
                                    cursor="hand2",
                                    font=("Helvetica", 10, "bold"))
        self._btn_start.pack(side="right", padx=4, pady=8)

        self._btn_stop = tk.Button(tb, text="■  PARAR",
                                   command=self._parar,
                                   bg="#7f1d1d", fg="#fca5a5",
                                   relief="flat", padx=12, pady=4,
                                   cursor="hand2",
                                   font=("Helvetica", 10, "bold"),
                                   state="disabled")
        self._btn_stop.pack(side="right", padx=4, pady=8)

        # ── Status banner ─────────────────────────────────────────────────────
        self._banner = tk.Frame(self, bg="#1c1c35", height=38)
        self._banner.pack(fill="x")
        self._banner.pack_propagate(False)
        self._lbl_status = tk.Label(self._banner, text="● INATIVO",
                                    bg="#1c1c35", fg=COR_CINZA,
                                    font=("Segoe UI", 11, "bold"))
        self._lbl_status.pack(side="left", padx=12)
        self._lbl_contagem = tk.Label(self._banner, text="",
                                      bg="#1c1c35", fg=COR_CINZA,
                                      font=("Segoe UI", 9))
        self._lbl_contagem.pack(side="left", padx=12)

        # ── Configurações ─────────────────────────────────────────────────────
        cfg = tk.LabelFrame(self, text="Configurações", bg=COR_FUNDO, fg=COR_TEXTO,
                            font=("Segoe UI", 9, "bold"), padx=10, pady=6)
        cfg.pack(fill="x", padx=10, pady=6)

        from ururau.config.settings import (
            INTERVALO_ENTRE_CICLOS_SEGUNDOS,
            MAX_PUBLICACOES_MONITORAMENTO_POR_HORA,
        )

        row1 = tk.Frame(cfg, bg=COR_FUNDO)
        row1.pack(fill="x")
        tk.Label(row1, text="Intervalo entre ciclos (segundos):",
                 bg=COR_FUNDO, fg=COR_TEXTO,
                 font=("Segoe UI", 9), width=36, anchor="w").pack(side="left")
        self._var_intervalo = tk.StringVar(value=str(INTERVALO_ENTRE_CICLOS_SEGUNDOS))
        tk.Entry(row1, textvariable=self._var_intervalo,
                 bg="#16213e", fg=COR_VERDE, insertbackground=COR_TEXTO,
                 font=("Courier New", 10), width=8, relief="flat").pack(side="left", padx=8)
        tk.Label(row1, text=f"(atual: {INTERVALO_ENTRE_CICLOS_SEGUNDOS//60}min)",
                 bg=COR_FUNDO, fg=COR_CINZA, font=("Segoe UI", 8)).pack(side="left")

        row2 = tk.Frame(cfg, bg=COR_FUNDO)
        row2.pack(fill="x", pady=4)
        tk.Label(row2, text="Máximo de matérias por hora:",
                 bg=COR_FUNDO, fg=COR_TEXTO,
                 font=("Segoe UI", 9), width=36, anchor="w").pack(side="left")
        self._var_max_hora = tk.StringVar(value=str(MAX_PUBLICACOES_MONITORAMENTO_POR_HORA))
        tk.Entry(row2, textvariable=self._var_max_hora,
                 bg="#16213e", fg=COR_VERDE, insertbackground=COR_TEXTO,
                 font=("Courier New", 10), width=8, relief="flat").pack(side="left", padx=8)

        row3 = tk.Frame(cfg, bg=COR_FUNDO)
        row3.pack(fill="x")
        self._var_publicar = tk.BooleanVar(value=False)
        tk.Checkbutton(row3, text="Publicar diretamente no CMS (além de salvar rascunho local)",
                       variable=self._var_publicar,
                       bg=COR_FUNDO, fg=COR_TEXTO, selectcolor="#1e3a5f",
                       activebackground=COR_FUNDO, activeforeground=COR_TEXTO,
                       font=("Segoe UI", 9)).pack(side="left")

        # ── Log ao vivo ───────────────────────────────────────────────────────
        tk.Label(self, text="Log ao vivo:", bg=COR_FUNDO, fg=COR_CINZA,
                 font=("Segoe UI", 9), anchor="w").pack(fill="x", padx=10)
        self._log_txt = scrolledtext.ScrolledText(self, bg="#080818", fg="#94a3b8",
                                                   font=("Courier New", 8),
                                                   state="disabled", wrap="word",
                                                   height=14)
        self._log_txt.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self._log_txt.tag_configure("ok",   foreground="#86efac")
        self._log_txt.tag_configure("err",  foreground="#fca5a5")
        self._log_txt.tag_configure("info", foreground="#94a3b8")
        self._log_txt.tag_configure("warn", foreground="#fde68a")

        # Lê log existente
        self.after(200, self._ler_log_arquivo)

    # ── Log ───────────────────────────────────────────────────────────────────

    def _ler_log_arquivo(self):
        """Carrega as últimas linhas do monitor.log."""
        log_path = Path("logs") / "monitor.log"
        if not log_path.exists():
            self._append_log("(nenhum log anterior encontrado)", "info")
            return
        try:
            linhas = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
            ultimas = linhas[-60:]  # últimas 60 linhas
            for ln in ultimas:
                tag = "ok" if "[OK]" in ln else ("err" if "ERROR" in ln or "ERRO" in ln
                      else ("warn" if "WARNING" in ln or "AVISO" in ln else "info"))
                self._append_log(ln, tag)
        except Exception as e:
            self._append_log(f"Erro ao ler log: {e}", "err")

    def _append_log(self, texto: str, tag: str = "info"):
        self._log_txt.config(state="normal")
        self._log_txt.insert("end", texto + "\n", tag)
        self._log_txt.see("end")
        self._log_txt.config(state="disabled")

    # ── Controles ─────────────────────────────────────────────────────────────

    def _iniciar(self):
        if not self._client:
            messagebox.showerror("Monitor", "Configure OPENAI_API_KEY antes de iniciar.",
                                 parent=self)
            return
        if self._robo and self._robo.ativo:
            messagebox.showinfo("Monitor", "O monitor já está ativo.", parent=self)
            return
        try:
            intervalo = int(self._var_intervalo.get())
            max_hora  = int(self._var_max_hora.get())
        except ValueError:
            messagebox.showerror("Erro", "Valores inválidos nos campos.", parent=self)
            return
        publicar = self._var_publicar.get()

        from ururau.publisher.monitor import MonitorRobo
        self._robo = MonitorRobo(
            db=self._db,
            client=self._client,
            modelo=self._modelo,
            intervalo_segundos=intervalo,
            max_por_hora=max_hora,
            publicar_no_cms=publicar,
        )
        def _run():
            try:
                self._robo.iniciar()
            except Exception as e:
                self.after(0, lambda: self._append_log(f"[ERRO] {e}", "err"))
            finally:
                self.after(0, self._atualizar_ui)
        self._thread = threading.Thread(target=_run, daemon=True, name="MonitorRobo")
        self._thread.start()
        self._atualizar_ui()
        self._cb_atualizado(self._robo, self._thread)
        self._append_log(
            f"Monitor iniciado. Intervalo={intervalo}s Max/hora={max_hora} "
            f"CMS={'SIM' if publicar else 'NAO'}", "ok")

    def _parar(self):
        if self._robo:
            self._robo.parar()
        self._atualizar_ui()
        self._cb_atualizado(self._robo, self._thread)
        self._append_log("Monitor parado pelo usuário.", "warn")

    def _atualizar_ui(self):
        ativo = bool(self._robo and self._robo.ativo)
        if ativo:
            n = self._robo.publicacoes_na_hora
            self._lbl_status.config(
                text=f"● ATIVO — {n} matéria(s) na última hora",
                fg=COR_VERDE)
            self._btn_start.config(state="disabled")
            self._btn_stop.config(state="normal")
        else:
            self._lbl_status.config(text="● INATIVO", fg=COR_CINZA)
            self._btn_start.config(state="normal")
            self._btn_stop.config(state="disabled")

    def _tick(self):
        """Atualiza UI e log a cada 30s enquanto janela está aberta."""
        try:
            self._atualizar_ui()
            # Appenda novas linhas do log se houver
            log_path = Path("logs") / "monitor.log"
            if log_path.exists():
                try:
                    linhas = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
                    if linhas:
                        self._append_log(linhas[-1], "info")
                except Exception:
                    pass
        except Exception:
            pass
        self.after(30_000, self._tick)


# ── Janela Copydesk Visual ────────────────────────────────────────────────────

class JanelaCopydesk(tk.Toplevel):
    """
    Copydesk visual interativo.

    Mostra lado a lado:
      - Esquerda: texto ORIGINAL (não editável)
      - Direita:  texto PROPOSTO pela IA (editável)

    Lista de problemas detectados no topo.
    Botões: Aceitar Tudo | Aceitar Proposto | Rejeitar | Fechar.

    Diff linha a linha colorido para facilitar revisão.
    """

    # Cores do diff
    _COR_ADD    = "#14532d"   # fundo linha nova (verde escuro)
    _COR_DEL    = "#450a0a"   # fundo linha removida (vermelho escuro)
    _COR_ADD_FG = "#86efac"
    _COR_DEL_FG = "#fca5a5"
    _COR_EQ_FG  = COR_CINZA

    def __init__(self, parent, pauta, md_original, md_proposto, problemas, db, cb_aceitar):
        super().__init__(parent)
        self._pauta      = pauta
        self._md_orig    = dict(md_original)
        self._md_prop    = dict(md_proposto)
        self._probs      = list(problemas)
        self._db         = db
        self._cb_aceitar = cb_aceitar
        titulo_pauta     = (pauta.get("titulo_origem") or "")[:60]
        self.title(f"Copydesk Visual — {titulo_pauta}")
        self.geometry("1300x820")
        self.configure(bg=COR_FUNDO)
        self.grab_set()
        self.resizable(True, True)
        self._build()
        self.after(100, self._preencher_diff)

    def _build(self):
        # ── Toolbar ──────────────────────────────────────────────────────────
        tb = tk.Frame(self, bg=COR_PAINEL, height=50)
        tb.pack(fill="x")
        tb.pack_propagate(False)
        tk.Label(tb, text="COPYDESK VISUAL", bg=COR_PAINEL, fg=COR_DESTAQUE,
                 font=("Helvetica", 12, "bold")).pack(side="left", padx=12)
        for txt, cmd, cor in [
            ("Aceitar Proposto e Salvar", self._aceitar_proposto, COR_VERDE),
            ("Manter Original",           self._manter_original,  COR_CINZA),
            ("Fechar sem salvar",          self.destroy,            "#374151"),
        ]:
            tk.Button(tb, text=txt, command=cmd, bg=cor, fg="white",
                      relief="flat", padx=10, pady=4, cursor="hand2",
                      font=("Helvetica", 9, "bold")).pack(side="right", padx=4, pady=8)

        # ── Problemas detectados ──────────────────────────────────────────────
        pf = tk.Frame(self, bg="#1c1c2e")
        pf.pack(fill="x", padx=8, pady=4)
        lbl_t = ("Sem problemas residuais detectados." if not self._probs
                 else f"{len(self._probs)} problema(s) detectado(s) — revise antes de aceitar:")
        cor_t  = COR_VERDE if not self._probs else COR_AMARELO
        tk.Label(pf, text=lbl_t, bg="#1c1c2e", fg=cor_t,
                 font=("Helvetica", 9, "bold")).pack(anchor="w", padx=8, pady=2)
        for prob in self._probs[:8]:
            tk.Label(pf, text=f"  ▸ {prob}", bg="#1c1c2e", fg=COR_AMARELO,
                     font=("Helvetica", 8), anchor="w").pack(fill="x", padx=12)
        if len(self._probs) > 8:
            tk.Label(pf, text=f"  ... e mais {len(self._probs)-8} problema(s).",
                     bg="#1c1c2e", fg=COR_CINZA, font=("Helvetica", 8)).pack(anchor="w", padx=12)

        # ── Área principal ────────────────────────────────────────────────────
        main = tk.Frame(self, bg=COR_FUNDO)
        main.pack(fill="both", expand=True, padx=8, pady=4)

        # Metadados — comparação
        meta_frame = tk.Frame(main, bg=COR_PAINEL)
        meta_frame.pack(fill="x", pady=(0, 4))
        tk.Label(meta_frame, text="METADADOS (Original → Proposto)",
                 bg=COR_PAINEL, fg=COR_TEXTO, font=("Helvetica", 9, "bold")).pack(
                     anchor="w", padx=8, pady=4)
        self._meta_txt = scrolledtext.ScrolledText(meta_frame, bg="#16213e", fg=COR_TEXTO,
                                                    font=("Courier New", 8), height=7,
                                                    state="disabled", wrap="word")
        self._meta_txt.pack(fill="x", padx=8, pady=2)
        self._meta_txt.tag_configure("add", foreground=self._COR_ADD_FG, background=self._COR_ADD)
        self._meta_txt.tag_configure("del", foreground=self._COR_DEL_FG, background=self._COR_DEL)
        self._meta_txt.tag_configure("eq",  foreground=self._COR_EQ_FG)
        self._meta_txt.tag_configure("lbl", foreground=COR_ROXO, font=("Courier New", 8, "bold"))

        # Conteúdo — diff side-by-side
        paned = ttk.PanedWindow(main, orient="horizontal")
        paned.pack(fill="both", expand=True, pady=4)

        lf = tk.Frame(paned, bg=COR_PAINEL)
        paned.add(lf, weight=1)
        tk.Label(lf, text="ORIGINAL", bg=COR_PAINEL, fg=COR_VERMELHO,
                 font=("Helvetica", 10, "bold")).pack(anchor="w", padx=8, pady=4)
        self._txt_orig = scrolledtext.ScrolledText(lf, bg="#16213e", fg=COR_TEXTO,
                                                    font=("Courier New", 9), wrap="word",
                                                    state="disabled", relief="flat", padx=6, pady=6)
        self._txt_orig.pack(fill="both", expand=True, padx=4, pady=2)
        self._txt_orig.tag_configure("del", foreground=self._COR_DEL_FG, background=self._COR_DEL)
        self._txt_orig.tag_configure("eq",  foreground="#94a3b8")

        rf = tk.Frame(paned, bg=COR_PAINEL)
        paned.add(rf, weight=1)
        tk.Label(rf, text="PROPOSTO (editável)", bg=COR_PAINEL, fg=COR_VERDE,
                 font=("Helvetica", 10, "bold")).pack(anchor="w", padx=8, pady=4)
        self._txt_prop = tk.Text(rf, bg="#16213e", fg=COR_TEXTO,
                                  insertbackground=COR_TEXTO,
                                  font=("Courier New", 9), wrap="word",
                                  relief="flat", padx=6, pady=6, undo=True)
        self._txt_prop.pack(fill="both", expand=True, padx=4, pady=2)
        self._txt_prop.tag_configure("add", foreground=self._COR_ADD_FG, background=self._COR_ADD)
        self._txt_prop.tag_configure("eq",  foreground="#94a3b8")

        # Scrollbar sincronizada (best-effort)
        self._txt_orig.bind("<MouseWheel>", self._sync_scroll_orig)
        self._txt_prop.bind("<MouseWheel>", self._sync_scroll_prop)

        # Contador de chars
        bar = tk.Frame(rf, bg=COR_PAINEL)
        bar.pack(fill="x", padx=4)
        self._lbl_chars = tk.Label(bar, text="", bg=COR_PAINEL,
                                   fg=COR_CINZA, font=FONTE_PEQUENA)
        self._lbl_chars.pack(side="right")
        self._txt_prop.bind("<KeyRelease>", self._contar)

    # ── Preenchimento ─────────────────────────────────────────────────────────

    def _preencher_diff(self):
        """Preenche ambos os painéis com diff colorido."""
        import difflib
        orig_body = self._md_orig.get("conteudo", "")
        prop_body = self._md_prop.get("conteudo", "")

        orig_linhas = orig_body.splitlines()
        prop_linhas = prop_body.splitlines()

        matcher = difflib.SequenceMatcher(None, orig_linhas, prop_linhas, autojunk=False)

        # Painel original
        self._txt_orig.config(state="normal")
        self._txt_orig.delete("1.0", "end")
        # Painel proposto
        self._txt_prop.config(state="normal")
        self._txt_prop.delete("1.0", "end")

        for opcode, i1, i2, j1, j2 in matcher.get_opcodes():
            if opcode == "equal":
                for ln in orig_linhas[i1:i2]:
                    self._txt_orig.insert("end", ln + "\n", "eq")
                for ln in prop_linhas[j1:j2]:
                    self._txt_prop.insert("end", ln + "\n", "eq")
            elif opcode == "replace":
                for ln in orig_linhas[i1:i2]:
                    self._txt_orig.insert("end", ln + "\n", "del")
                for ln in prop_linhas[j1:j2]:
                    self._txt_prop.insert("end", ln + "\n", "add")
            elif opcode == "delete":
                for ln in orig_linhas[i1:i2]:
                    self._txt_orig.insert("end", ln + "\n", "del")
            elif opcode == "insert":
                for ln in prop_linhas[j1:j2]:
                    self._txt_prop.insert("end", ln + "\n", "add")

        self._txt_orig.config(state="disabled")
        self._contar()

        # Metadados
        self._meta_txt.config(state="normal")
        self._meta_txt.delete("1.0", "end")
        campos_meta = ["titulo", "titulo_capa", "subtitulo", "legenda",
                       "retranca", "slug", "tags", "meta_description",
                       "resumo_curto", "chamada_social"]
        for campo in campos_meta:
            v_orig = str(self._md_orig.get(campo, "") or "").strip()
            v_prop = str(self._md_prop.get(campo, "") or "").strip()
            self._meta_txt.insert("end", f"{campo:<22}: ", "lbl")
            if v_orig == v_prop:
                self._meta_txt.insert("end", v_orig[:120] + "\n", "eq")
            else:
                self._meta_txt.insert("end", f"[-] {v_orig[:80]}\n", "del")
                self._meta_txt.insert("end", " " * 24 + f"[+] {v_prop[:80]}\n", "add")
        self._meta_txt.config(state="disabled")

    def _contar(self, _=None):
        n = len(self._txt_prop.get("1.0", "end-1c"))
        from ururau.config.settings import MIN_CARACTERES_MATERIA, MAX_CARACTERES_MATERIA
        cor = (COR_VERDE if MIN_CARACTERES_MATERIA <= n <= MAX_CARACTERES_MATERIA
               else COR_AMARELO)
        self._lbl_chars.config(text=f"{n} chars", fg=cor)

    # ── Sync scroll ───────────────────────────────────────────────────────────

    def _sync_scroll_orig(self, e):
        delta = int(-1 * (e.delta / 120))
        self._txt_prop.yview_scroll(delta, "units")

    def _sync_scroll_prop(self, e):
        delta = int(-1 * (e.delta / 120))
        self._txt_orig.yview_scroll(delta, "units")

    # ── Ações ─────────────────────────────────────────────────────────────────

    def _aceitar_proposto(self):
        """Aceita o texto proposto (com as edições manuais feitas pelo usuário)."""
        md_final = dict(self._md_prop)
        # Usa o conteúdo do painel editável (pode ter ajustes manuais)
        md_final["conteudo"] = self._txt_prop.get("1.0", "end-1c").strip()
        self._cb_aceitar(self._pauta, md_final, self._probs)
        messagebox.showinfo("Copydesk Aceito",
            f"Revisão salva!\n{len(self._probs)} problema(s) residual(is).",
            parent=self)
        self.destroy()

    def _manter_original(self):
        """Fecha sem salvar nada — mantém o original."""
        if messagebox.askyesno("Manter Original",
                "Fechar sem aplicar o copydesk?\nO texto original será mantido.",
                parent=self):
            self.destroy()


# ── Widget de Configurações (Frame — usado inline no notebook) ────────────────

class _ConfigWidget(tk.Frame):
    """
    Versão Frame (não Toplevel) do painel de configurações.
    Pode ser incorporado diretamente numa aba do notebook.
    """

    def __init__(self, parent, db=None):
        super().__init__(parent, bg=COR_FUNDO)
        self._db = db
        self._build()
        self._carregar_valores()

    def _build(self):
        tb = tk.Frame(self, bg=COR_PAINEL, height=44)
        tb.pack(fill="x")
        tb.pack_propagate(False)
        tk.Label(tb, text="⚙ Configurações", bg=COR_PAINEL, fg=COR_DESTAQUE,
                 font=("Helvetica", 12, "bold")).pack(side="left", padx=10)
        tk.Button(tb, text="Salvar e Aplicar", command=self._salvar,
                  bg=COR_VERDE, fg="white", relief="flat",
                  padx=10, pady=3, cursor="hand2",
                  font=("Helvetica", 9, "bold")).pack(side="right", padx=6, pady=6)
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=6, pady=4)
        self._nb = nb
        self._criar_aba_rss(nb)
        self._criar_aba_params(nb)
        self._criar_aba_creds(nb)

    def _criar_aba_rss(self, nb):
        f = tk.Frame(nb, bg=COR_PAINEL)
        nb.add(f, text="Fontes RSS")
        tk.Label(f, text="Formato: URL|Nome|Canal  (uma por linha)",
                 bg=COR_PAINEL, fg=COR_TEXTO, font=FONTE_NORMAL).pack(padx=8, pady=4, anchor="w")
        self._txt_rss = tk.Text(f, bg="#16213e", fg=COR_TEXTO,
                                insertbackground=COR_TEXTO,
                                font=("Courier New", 9), wrap="none",
                                relief="flat", padx=6, pady=6)
        self._txt_rss.pack(fill="both", expand=True, padx=8, pady=8)
        tk.Button(f, text="+ Adicionar linha",
                  command=lambda: self._txt_rss.insert("end", "\nhttps://|Nome|Canal"),
                  bg=COR_AZUL, fg="white", relief="flat",
                  padx=8, pady=2, cursor="hand2", font=FONTE_PEQUENA).pack(side="left", padx=8)

    def _criar_aba_params(self, nb):
        outer = tk.Frame(nb, bg=COR_PAINEL)
        nb.add(outer, text="Parâmetros")
        canvas = tk.Canvas(outer, bg=COR_PAINEL, highlightthickness=0)
        sb = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        frame = tk.Frame(canvas, bg=COR_PAINEL)
        canvas.create_window((0, 0), window=frame, anchor="nw")
        frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
        self._param_vars: dict[str, tk.StringVar] = {}
        for key, desc, padrao in [
            ("LIMIAR_RELEVANCIA_PUBLICAR","Relevância mínima (0-100)","28"),
            ("LIMIAR_RISCO_MAXIMO","Risco máximo","70"),
            ("MIN_CARACTERES_MATERIA","Min. caracteres","2000"),
            ("MAX_CARACTERES_MATERIA","Max. caracteres","6200"),
            ("MAX_PUBLICACOES_POR_CICLO","Max. publicações por ciclo","3"),
            ("INTERVALO_ENTRE_CICLOS_SEGUNDOS","Intervalo ciclos (seg)","1800"),
            ("HEADLESS","Headless (true/false)","false"),
        ]:
            row = tk.Frame(frame, bg=COR_PAINEL)
            row.pack(fill="x", padx=10, pady=2)
            tk.Label(row, text=desc+":", bg=COR_PAINEL, fg=COR_TEXTO,
                     font=FONTE_PEQUENA, width=42, anchor="w").pack(side="left")
            v = tk.StringVar(value=padrao)
            tk.Entry(row, textvariable=v, bg="#16213e", fg=COR_VERDE,
                     insertbackground=COR_TEXTO, font=("Courier New", 9),
                     width=20, relief="flat").pack(side="left", padx=6)
            self._param_vars[key] = v

    def _criar_aba_creds(self, nb):
        f = tk.Frame(nb, bg=COR_PAINEL)
        nb.add(f, text="Credenciais")
        tk.Label(f, text="Não compartilhe o .env. Dados ficam apenas localmente.",
                 bg=COR_PAINEL, fg=COR_AMARELO, font=FONTE_PEQUENA).pack(padx=10, pady=6, anchor="w")
        self._cred_vars: dict[str, tk.StringVar] = {}
        for key, label, senha in [
            ("OPENAI_API_KEY","Chave OpenAI (sk-...)",False),
            ("URURAU_LOGIN","Login do CMS",False),
            ("URURAU_SENHA","Senha do CMS",True),
            ("URURAU_ASSINATURA","Assinatura das matérias",False),
            ("SITE_LOGIN_URL","URL de login do CMS",False),
            ("SITE_NOVA_URL","URL de nova notícia",False),
        ]:
            tk.Label(f, text=label+":", bg=COR_PAINEL, fg=COR_TEXTO,
                     font=FONTE_NORMAL, anchor="w").pack(padx=10, pady=3, anchor="w")
            v = tk.StringVar()
            tk.Entry(f, textvariable=v, bg="#16213e", fg=COR_VERDE,
                     insertbackground=COR_TEXTO, font=("Courier New", 9),
                     relief="flat", show="*" if senha else "").pack(fill="x", padx=10)
            self._cred_vars[key] = v

    def _carregar_valores(self):
        env = _ler_env_atual()
        for key, v in {**self._param_vars, **self._cred_vars}.items():
            if key in env:
                v.set(env[key])
        fontes = _carregar_fontes_rss()
        self._txt_rss.insert("1.0", "\n".join(
            f"{f.get('url','')}|{f.get('nome','')}|{f.get('canal_forcado','')}"
            for f in fontes))

    def _salvar(self):
        try:
            novos: dict[str, str] = {}
            for k, v in {**self._param_vars, **self._cred_vars}.items():
                val = v.get().strip()
                if val:
                    novos[k] = val
            _atualizar_env(novos)
            fontes = []
            for linha in self._txt_rss.get("1.0", "end").strip().splitlines():
                linha = linha.strip()
                if not linha or linha.startswith("#"):
                    continue
                ps = [p.strip() for p in linha.split("|")]
                if ps and ps[0].startswith("http"):
                    fontes.append({"url": ps[0],
                                   "nome": ps[1] if len(ps) > 1 else "",
                                   "canal_forcado": ps[2] if len(ps) > 2 else ""})
            Path("fontes_rss.json").write_text(
                json.dumps(fontes, ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                from ururau.config import settings as _s
                _s.recarregar()
            except Exception:
                pass
            messagebox.showinfo("Salvo",
                f"{len(novos)} parâmetros no .env\n{len(fontes)} fontes RSS")
        except Exception as e:
            messagebox.showerror("Erro ao Salvar", str(e))


# ── Janela Configurações ──────────────────────────────────────────────────────

class JanelaConfiguracoes(tk.Toplevel):
    """
    4 abas: Fontes RSS | Parametros | Credenciais | Producao
    A aba Producao permite editar briefing editorial, instrucoes por canal,
    termos proibidos de IA e parametros de formato — tudo integrado ao
    house_style.py e aplicado imediatamente em memoria.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Configuracoes do Ururau")
        self.geometry("940x740")
        self.configure(bg=COR_FUNDO)
        self.grab_set()
        self.resizable(True, True)
        self._build()
        self._carregar_valores()

    def _build(self):
        tb = tk.Frame(self, bg=COR_PAINEL, height=48)
        tb.pack(fill="x")
        tb.pack_propagate(False)
        tk.Label(tb, text="Configuracoes", bg=COR_PAINEL, fg=COR_DESTAQUE,
                 font=("Helvetica", 13, "bold")).pack(side="left", padx=12)
        tk.Button(tb, text="Salvar e Aplicar", command=self._salvar,
                  bg=COR_VERDE, fg="white", relief="flat",
                  padx=12, pady=4, cursor="hand2",
                  font=("Helvetica", 10, "bold")).pack(side="right", padx=8, pady=8)
        tk.Button(tb, text="Fechar sem salvar", command=self.destroy,
                  bg=COR_CINZA, fg="white", relief="flat",
                  padx=10, pady=4, cursor="hand2",
                  font=("Helvetica", 10, "bold")).pack(side="right", padx=4, pady=8)
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        self._nb = nb
        self._criar_aba_rss(nb)
        self._criar_aba_params(nb)
        self._criar_aba_creds(nb)
        self._criar_aba_producao(nb)
        self._criar_aba_estilo(nb)
        tk.Label(self,
                 text="Parametros: aplicados imediatamente. "
                      "Credenciais: proximo reinicio. "
                      "Producao: salva em house_style.py e aplica imediatamente.",
                 bg=COR_FUNDO, fg=COR_AMARELO, font=FONTE_PEQUENA,
                 wraplength=900).pack(pady=4, padx=8)

    # ── RSS ───────────────────────────────────────────────────────────────────

    def _criar_aba_rss(self, nb):
        f = tk.Frame(nb, bg=COR_PAINEL)
        nb.add(f, text="Fontes RSS")
        tk.Label(f, text="Formato: URL|Nome|Canal  (uma por linha)",
                 bg=COR_PAINEL, fg=COR_TEXTO, font=FONTE_NORMAL).pack(padx=8, pady=4, anchor="w")
        tk.Label(f, text="Ex: https://g1.globo.com/rss/g1/rj/ | G1 RJ | Estado RJ",
                 bg=COR_PAINEL, fg=COR_CINZA, font=FONTE_PEQUENA).pack(padx=8, anchor="w")
        self._txt_rss = tk.Text(f, bg="#16213e", fg=COR_TEXTO,
                                insertbackground=COR_TEXTO,
                                font=("Courier New", 9), wrap="none",
                                relief="flat", padx=6, pady=6)
        self._txt_rss.pack(fill="both", expand=True, padx=8, pady=8)
        bf = tk.Frame(f, bg=COR_PAINEL)
        bf.pack(fill="x", padx=8, pady=4)
        tk.Button(bf, text="+ Adicionar linha",
                  command=lambda: self._txt_rss.insert("end", "\nhttps://|Nome|Canal"),
                  bg=COR_AZUL, fg="white", relief="flat",
                  padx=8, pady=2, cursor="hand2", font=FONTE_PEQUENA).pack(side="left")
        tk.Label(bf,
                 text=f"Canais: {', '.join(CANAIS_RODIZIO)}",
                 bg=COR_PAINEL, fg=COR_CINZA,
                 font=FONTE_PEQUENA, wraplength=720).pack(side="left", padx=8)

    # ── Parâmetros ────────────────────────────────────────────────────────────

    def _criar_aba_params(self, nb):
        outer = tk.Frame(nb, bg=COR_PAINEL)
        nb.add(outer, text="Parametros")
        canvas = tk.Canvas(outer, bg=COR_PAINEL, highlightthickness=0)
        sb = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        frame = tk.Frame(canvas, bg=COR_PAINEL)
        canvas.create_window((0, 0), window=frame, anchor="nw")
        frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
        self._param_vars: dict[str, tk.StringVar] = {}
        grupos = [
            ("Limiares Editoriais", [
                ("LIMIAR_RELEVANCIA_PUBLICAR","Relevancia minima para publicar (0-100)","28"),
                ("LIMIAR_RELEVANCIA_URGENTE", "Limiar para pauta urgente (0-100)","52"),
                ("LIMIAR_RISCO_MAXIMO",       "Risco maximo (bloqueia acima)","70"),
            ]),
            ("Texto e Conteudo", [
                ("OPENAI_MODEL",            "Modelo de IA","gpt-4.1-mini"),
                ("MIN_CARACTERES_MATERIA",  "Min. caracteres","2000"),
                ("ALVO_CARACTERES_MATERIA", "Alvo de caracteres","3400"),
                ("MAX_CARACTERES_MATERIA",  "Max. caracteres","6200"),
                ("MAX_FONTES_APURACAO",     "Max. fontes por apuracao","4"),
            ]),
            ("Imagem", [
                ("QUALIDADE_JPEG_FINAL",          "Qualidade JPEG (1-95)","95"),
                ("MIN_LARGURA_IMAGEM_PUBLICAVEL", "Largura minima (px)","500"),
                ("MIN_ALTURA_IMAGEM_PUBLICAVEL",  "Altura minima (px)","350"),
                ("USAR_PLAYWRIGHT_IMAGEM",        "Usar Playwright (true/false)","true"),
                ("USAR_BING_IMAGEM",              "Usar Bing fallback (true/false)","true"),
                ("MAX_CANDIDATAS_IMAGEM",         "Max. candidatas de imagem","25"),
            ]),
            ("Publicacao e Ciclos", [
                ("MAX_PUBLICACOES_POR_CICLO",       "Max. publicacoes por ciclo","3"),
                ("MAX_PUBLICACOES_POR_CANAL",       "Max. por canal por ciclo","1"),
                ("INTERVALO_ENTRE_CICLOS_SEGUNDOS", "Intervalo ciclos (seg)","1800"),
                ("JANELA_ANTIDUPLICACAO_HORAS",     "Janela anti-duplicacao (h)","48"),
                ("MAX_CANDIDATAS_AVALIADAS",        "Max. candidatas avaliadas por ciclo","24"),
            ]),
            ("Playwright", [
                ("HEADLESS","Rodar sem janela visivel (true/false)","false"),
                ("SLOW_MO", "Delay entre acoes Playwright (ms)","150"),
            ]),
        ]
        for titulo_g, params in grupos:
            tk.Label(frame, text=titulo_g, bg=COR_PAINEL, fg=COR_ROXO,
                     font=("Helvetica", 11, "bold")).pack(anchor="w", padx=12, pady=8)
            for key, desc, padrao in params:
                row = tk.Frame(frame, bg=COR_PAINEL)
                row.pack(fill="x", padx=12, pady=2)
                tk.Label(row, text=desc, bg=COR_PAINEL, fg=COR_TEXTO,
                         font=FONTE_PEQUENA, width=48, anchor="w").pack(side="left")
                v = tk.StringVar(value=padrao)
                tk.Entry(row, textvariable=v, bg="#16213e", fg=COR_VERDE,
                         insertbackground=COR_TEXTO, font=("Courier New", 9),
                         width=22, relief="flat").pack(side="left", padx=8)
                self._param_vars[key] = v
            tk.Frame(frame, bg="#3a3a5c", height=1).pack(fill="x", padx=12, pady=4)

    # ── Credenciais ───────────────────────────────────────────────────────────

    def _criar_aba_creds(self, nb):
        f = tk.Frame(nb, bg=COR_PAINEL)
        nb.add(f, text="Credenciais")
        tk.Label(f, text="Nao compartilhe o .env. Dados ficam apenas localmente.",
                 bg=COR_PAINEL, fg=COR_AMARELO, font=FONTE_PEQUENA).pack(padx=12, pady=8, anchor="w")
        self._cred_vars: dict[str, tk.StringVar] = {}
        for key, label, senha in [
            ("OPENAI_API_KEY",   "Chave da OpenAI (sk-...)",   False),
            ("URURAU_LOGIN",     "Login do CMS Ururau",        False),
            ("URURAU_SENHA",     "Senha do CMS Ururau",        True),
            ("URURAU_ASSINATURA","Assinatura das materias",    False),
            ("SITE_LOGIN_URL",   "URL de login do CMS",        False),
            ("SITE_NOVA_URL",    "URL de nova noticia no CMS", False),
        ]:
            tk.Label(f, text=label+":", bg=COR_PAINEL, fg=COR_TEXTO,
                     font=FONTE_NORMAL, anchor="w").pack(padx=12, pady=4, anchor="w")
            v = tk.StringVar()
            tk.Entry(f, textvariable=v, bg="#16213e", fg=COR_VERDE,
                     insertbackground=COR_TEXTO, font=("Courier New", 10),
                     relief="flat", show="*" if senha else "").pack(fill="x", padx=12)
            self._cred_vars[key] = v

    # ── Produção ──────────────────────────────────────────────────────────────

    def _criar_aba_producao(self, nb):
        """
        Aba Producao: sub-abas para editar todos os parametros de producao
        de texto: Briefing Editorial, Instrucoes por Canal, Termos Proibidos,
        Formato e Estrutura. Tudo integrado ao house_style.py.
        """
        outer = tk.Frame(nb, bg=COR_PAINEL)
        nb.add(outer, text="Producao")
        sub = ttk.Notebook(outer)
        sub.pack(fill="both", expand=True, padx=4, pady=4)
        self._prod_txt: dict[str, tk.Text] = {}

        # Sub-aba: Briefing Editorial
        self._criar_sub_txt(sub, "Briefing Editorial", "briefing",
            "Briefing injetado em TODOS os prompts de geracao.\n"
            "Define tom, regras e proibicoes para toda a producao de texto.")

        # Sub-aba: Por Canal
        fc = tk.Frame(sub, bg=COR_PAINEL)
        sub.add(fc, text="Por Canal")
        tk.Label(fc, text="Instrucao editorial especifica para cada canal:",
                 bg=COR_PAINEL, fg=COR_TEXTO, font=FONTE_PEQUENA).pack(anchor="w", padx=8, pady=4)
        cr = tk.Frame(fc, bg=COR_PAINEL)
        cr.pack(fill="x", padx=8, pady=2)
        self._canal_var = tk.StringVar(value=CANAIS_RODIZIO[0])
        ttk.Combobox(cr, textvariable=self._canal_var,
                     values=CANAIS_RODIZIO, state="readonly",
                     width=24).pack(side="left")
        tk.Button(cr, text="Carregar", command=self._load_canal,
                  bg=COR_AZUL, fg="white", relief="flat",
                  padx=8, pady=2, cursor="hand2", font=FONTE_PEQUENA).pack(side="left", padx=6)
        tk.Button(cr, text="Salvar este canal", command=self._save_canal,
                  bg=COR_VERDE, fg="white", relief="flat",
                  padx=8, pady=2, cursor="hand2", font=FONTE_PEQUENA).pack(side="left", padx=2)
        tk.Button(cr, text="+ Novo canal", command=self._novo_canal,
                  bg=COR_ROXO, fg="white", relief="flat",
                  padx=8, pady=2, cursor="hand2", font=FONTE_PEQUENA).pack(side="left", padx=2)
        tk.Label(fc, text="Instrucao (injetada no prompt para este canal):",
                 bg=COR_PAINEL, fg=COR_CINZA, font=FONTE_PEQUENA).pack(anchor="w", padx=8, pady=2)
        self._txt_canal = tk.Text(fc, bg="#16213e", fg=COR_TEXTO,
                                  insertbackground=COR_TEXTO,
                                  font=("Courier New", 9), wrap="word",
                                  relief="flat", padx=6, pady=6, height=10)
        self._txt_canal.pack(fill="both", expand=True, padx=8, pady=4)
        self._load_canal()

        # Sub-aba: Termos Proibidos
        self._criar_sub_txt(sub, "Termos Proibidos", "termos_ia",
            "Um termo por linha (minusculas).\n"
            "Detectados automaticamente no texto gerado e sinalizados para revisao.")

        # Sub-aba: Formato e Estrutura
        ff = tk.Frame(sub, bg=COR_PAINEL)
        sub.add(ff, text="Formato e Estrutura")
        tk.Label(ff, text="Parametros de formato e estrutura do texto gerado:",
                 bg=COR_PAINEL, fg=COR_TEXTO, font=FONTE_NORMAL).pack(anchor="w", padx=12, pady=8)
        self._fmt_vars: dict[str, tk.StringVar] = {}
        for key, desc, pad in [
            ("URURAU_ASSINATURA",    "Assinatura padrao das materias",   "Fabricio Freitas"),
            ("MIN_CARACTERES_MATERIA","Minimo de caracteres por materia","2000"),
            ("ALVO_CARACTERES_MATERIA","Alvo de caracteres por materia", "3400"),
            ("MAX_CARACTERES_MATERIA", "Maximo de caracteres por materia","6200"),
            ("MAX_FONTES_APURACAO",    "Max. fontes citadas por apuracao","4"),
        ]:
            row = tk.Frame(ff, bg=COR_PAINEL)
            row.pack(fill="x", padx=12, pady=4)
            tk.Label(row, text=desc+":", bg=COR_PAINEL, fg=COR_TEXTO,
                     font=FONTE_PEQUENA, width=42, anchor="w").pack(side="left")
            v = tk.StringVar(value=pad)
            tk.Entry(row, textvariable=v, bg="#16213e", fg=COR_VERDE,
                     insertbackground=COR_TEXTO, font=("Courier New", 9),
                     width=26, relief="flat").pack(side="left", padx=8)
            self._fmt_vars[key] = v

        tk.Label(ff,
                 text="Instrucao adicional global (adicionada ao final de todo prompt de geracao):",
                 bg=COR_PAINEL, fg=COR_CINZA,
                 font=FONTE_PEQUENA).pack(anchor="w", padx=12, pady=(12, 2))
        self._txt_extra = tk.Text(ff, bg="#16213e", fg=COR_TEXTO,
                                  insertbackground=COR_TEXTO,
                                  font=("Courier New", 9), wrap="word",
                                  relief="flat", padx=6, pady=6, height=6)
        self._txt_extra.pack(fill="both", expand=True, padx=12, pady=4)

    def _criar_aba_estilo(self, nb):
        """
        Aba Estilo de Escrita: criterios editoriais personalizados.

        Permite ao editor:
        1. Escrever diretrizes positivas (como deve ser escrito)
        2. Escrever exclusões (formas que não deve usar)
        3. Exemplos de parágrafos de referência

        Tudo injetado no prompt de redação como instrução adicional.
        """
        outer = tk.Frame(nb, bg=COR_PAINEL)
        nb.add(outer, text="✍ Estilo de Escrita")

        # Cabeçalho explicativo
        tk.Label(outer,
                 text="Diretrizes personalizadas de estilo — injetadas em todo prompt de geração de matéria.\n"
                      "Escreva como se estivesse instruindo um repórter: o que fazer, o que evitar, exemplos.",
                 bg=COR_PAINEL, fg=COR_AMARELO, font=FONTE_PEQUENA,
                 wraplength=860, justify="left").pack(anchor="w", padx=12, pady=(8, 4))

        sub = ttk.Notebook(outer)
        sub.pack(fill="both", expand=True, padx=4, pady=4)

        # Sub-aba 1: Diretrizes positivas
        f1 = tk.Frame(sub, bg=COR_PAINEL)
        sub.add(f1, text="Diretrizes (o que fazer)")
        tk.Label(f1,
                 text="Descreva o estilo desejado. Ex: 'Use sempre o nome completo na primeira menção.'\n"
                      "'Priorize verbos no passado para fatos confirmados.' Uma instrução por linha.",
                 bg=COR_PAINEL, fg=COR_CINZA, font=FONTE_PEQUENA,
                 wraplength=840, justify="left").pack(anchor="w", padx=8, pady=4)
        self._txt_estilo_positivo = tk.Text(f1, bg="#16213e", fg="#86efac",
                                             insertbackground=COR_TEXTO,
                                             font=("Courier New", 9), wrap="word",
                                             relief="flat", padx=6, pady=6)
        self._txt_estilo_positivo.pack(fill="both", expand=True, padx=8, pady=4)

        # Sub-aba 2: Exclusões e proibições
        f2 = tk.Frame(sub, bg=COR_PAINEL)
        sub.add(f2, text="Exclusões (o que evitar)")
        tk.Label(f2,
                 text="Formas de escrita que você considera ruins ou inadequadas para o portal.\n"
                      "Ex: 'Não abra matéria com pergunta retórica.' 'Evite lide com mais de 3 linhas.'",
                 bg=COR_PAINEL, fg=COR_CINZA, font=FONTE_PEQUENA,
                 wraplength=840, justify="left").pack(anchor="w", padx=8, pady=4)
        self._txt_estilo_negativo = tk.Text(f2, bg="#16213e", fg="#fca5a5",
                                             insertbackground=COR_TEXTO,
                                             font=("Courier New", 9), wrap="word",
                                             relief="flat", padx=6, pady=6)
        self._txt_estilo_negativo.pack(fill="both", expand=True, padx=8, pady=4)

        # Sub-aba 3: Exemplos de referência
        f3 = tk.Frame(sub, bg=COR_PAINEL)
        sub.add(f3, text="Exemplos de Referência")
        tk.Label(f3,
                 text="Cole aqui parágrafos de matérias que considera bem escritas.\n"
                      "A IA usará como referência de tom e ritmo — não como conteúdo a copiar.",
                 bg=COR_PAINEL, fg=COR_CINZA, font=FONTE_PEQUENA,
                 wraplength=840, justify="left").pack(anchor="w", padx=8, pady=4)
        self._txt_estilo_exemplos = tk.Text(f3, bg="#16213e", fg="#93c5fd",
                                             insertbackground=COR_TEXTO,
                                             font=("Courier New", 9), wrap="word",
                                             relief="flat", padx=6, pady=6)
        self._txt_estilo_exemplos.pack(fill="both", expand=True, padx=8, pady=4)

        # Botão de ajuda
        tk.Label(outer,
                 text="💡 Dica: Quanto mais específicas e concretas as diretrizes, melhor o resultado. "
                      "Evite instruções vagas como 'escreva bem'. Prefira: 'Use vírgula antes de 'mas' quando a oração for longa.'",
                 bg=COR_PAINEL, fg=COR_CINZA,
                 font=("Helvetica", 7), wraplength=860, justify="left").pack(anchor="w", padx=12, pady=4)

    def _criar_sub_txt(self, nb, titulo, chave, desc):
        f = tk.Frame(nb, bg=COR_PAINEL)
        nb.add(f, text=titulo)
        tk.Label(f, text=desc, bg=COR_PAINEL, fg=COR_CINZA,
                 font=FONTE_PEQUENA, wraplength=860,
                 justify="left").pack(anchor="w", padx=8, pady=4)
        txt = tk.Text(f, bg="#16213e", fg=COR_TEXTO,
                      insertbackground=COR_TEXTO,
                      font=("Courier New", 9), wrap="word",
                      relief="flat", padx=6, pady=6)
        txt.pack(fill="both", expand=True, padx=8, pady=4)
        self._prod_txt[chave] = txt

    def _load_canal(self, _=None):
        canal = self._canal_var.get()
        try:
            from ururau.config.house_style import INSTRUCAO_POR_CANAL
            instrucao = INSTRUCAO_POR_CANAL.get(canal, "")
        except Exception:
            instrucao = ""
        self._txt_canal.delete("1.0", "end")
        self._txt_canal.insert("1.0", instrucao)

    def _save_canal(self):
        canal    = self._canal_var.get()
        instrucao = self._txt_canal.get("1.0", "end").strip()
        try:
            from ururau.config import house_style as hs
            hs.INSTRUCAO_POR_CANAL[canal] = instrucao
            messagebox.showinfo("Salvo",
                f"Canal '{canal}' atualizado em memoria.\n"
                "Clique 'Salvar e Aplicar' para persistir no arquivo.", parent=self)
        except Exception as e:
            messagebox.showerror("Erro", str(e), parent=self)

    def _novo_canal(self):
        nome = simpledialog.askstring("Novo Canal", "Nome do canal:", parent=self)
        if not nome:
            return
        nome = nome.strip()
        try:
            from ururau.config import house_style as hs
            if nome not in hs.INSTRUCAO_POR_CANAL:
                hs.INSTRUCAO_POR_CANAL[nome] = "Escreva em formato de noticia jornalistica objetiva."
            self._canal_var.set(nome)
            self._load_canal()
            messagebox.showinfo("Canal criado",
                f"Canal '{nome}' criado. Clique 'Salvar e Aplicar' para persistir.",
                parent=self)
        except Exception as e:
            messagebox.showerror("Erro", str(e), parent=self)

    # ── Carregar valores ──────────────────────────────────────────────────────

    def _carregar_valores(self):
        env = _ler_env_atual()
        for key, v in {**self._param_vars, **self._cred_vars, **self._fmt_vars}.items():
            if key in env:
                v.set(env[key])
        fontes = _carregar_fontes_rss()
        self._txt_rss.insert("1.0", "\n".join(
            f"{f.get('url','')}|{f.get('nome','')}|{f.get('canal_forcado','')}"
            for f in fontes))
        try:
            from ururau.config.house_style import BRIEFING_EDITORIAL, TERMOS_IA_PROIBIDOS
            self._prod_txt["briefing"].insert("1.0", BRIEFING_EDITORIAL.strip())
            self._prod_txt["termos_ia"].insert("1.0", "\n".join(TERMOS_IA_PROIBIDOS))
        except Exception:
            pass
        extra = env.get("URURAU_INSTRUCAO_EXTRA", "")
        if extra:
            self._txt_extra.insert("1.0", extra)
        # Carregar estilo de escrita
        try:
            env2 = _ler_env_atual()
            pos = env2.get("URURAU_ESTILO_POSITIVO", "")
            neg = env2.get("URURAU_ESTILO_NEGATIVO", "")
            ex  = env2.get("URURAU_ESTILO_EXEMPLOS", "")
            if pos:
                self._txt_estilo_positivo.insert("1.0", pos)
            if neg:
                self._txt_estilo_negativo.insert("1.0", neg)
            if ex:
                self._txt_estilo_exemplos.insert("1.0", ex)
        except Exception:
            pass

    # ── Salvar ────────────────────────────────────────────────────────────────

    def _salvar(self):
        try:
            novos: dict[str, str] = {}
            for k, v in {**self._param_vars, **self._cred_vars, **self._fmt_vars}.items():
                val = v.get().strip()
                if val:
                    novos[k] = val
            extra = self._txt_extra.get("1.0", "end").strip()
            if extra:
                novos["URURAU_INSTRUCAO_EXTRA"] = extra
            # Estilo de escrita
            estilo_pos = self._txt_estilo_positivo.get("1.0", "end").strip()
            estilo_neg = self._txt_estilo_negativo.get("1.0", "end").strip()
            estilo_ex  = self._txt_estilo_exemplos.get("1.0", "end").strip()
            if estilo_pos:
                novos["URURAU_ESTILO_POSITIVO"] = estilo_pos
            if estilo_neg:
                novos["URURAU_ESTILO_NEGATIVO"] = estilo_neg
            if estilo_ex:
                novos["URURAU_ESTILO_EXEMPLOS"] = estilo_ex
            _atualizar_env(novos)

            # Fontes RSS
            fontes = []
            for linha in self._txt_rss.get("1.0", "end").strip().splitlines():
                linha = linha.strip()
                if not linha or linha.startswith("#"):
                    continue
                ps = [p.strip() for p in linha.split("|")]
                if ps and ps[0].startswith("http"):
                    fontes.append({"url": ps[0],
                                   "nome": ps[1] if len(ps) > 1 else "",
                                   "canal_forcado": ps[2] if len(ps) > 2 else ""})
            Path("fontes_rss.json").write_text(
                json.dumps(fontes, ensure_ascii=False, indent=2), encoding="utf-8")

            # House style
            self._salvar_house_style()

            from ururau.config import settings as _s
            _s.recarregar()

            messagebox.showinfo("Salvo",
                f"{len(novos)} parametros no .env\n"
                f"{len(fontes)} fontes RSS\n"
                "Producao aplicada. Credenciais no proximo reinicio.", parent=self)
        except Exception as e:
            messagebox.showerror("Erro ao Salvar", str(e), parent=self)

    def _salvar_house_style(self):
        try:
            from ururau.config import house_style as hs
            novo_briefing = self._prod_txt["briefing"].get("1.0", "end").strip()
            hs.BRIEFING_EDITORIAL = "\n" + novo_briefing + "\n"
            termos_raw = self._prod_txt["termos_ia"].get("1.0", "end").strip()
            hs.TERMOS_IA_PROIBIDOS = [t.strip() for t in termos_raw.splitlines() if t.strip()]
            hs_path = Path(hs.__file__)
            if not hs_path.exists():
                return
            conteudo = hs_path.read_text(encoding="utf-8")
            # Patch BRIEFING_EDITORIAL
            conteudo = re.sub(
                r'BRIEFING_EDITORIAL\s*=\s*""".*?"""',
                f'BRIEFING_EDITORIAL = """\n{novo_briefing}\n"""',
                conteudo, flags=re.DOTALL)
            # Patch TERMOS_IA_PROIBIDOS
            termos_repr = "[\n" + "".join(f'    "{t}",\n' for t in hs.TERMOS_IA_PROIBIDOS) + "]"
            conteudo = re.sub(
                r'TERMOS_IA_PROIBIDOS\s*:\s*list\[str\]\s*=\s*\[.*?\]',
                f'TERMOS_IA_PROIBIDOS: list[str] = {termos_repr}',
                conteudo, flags=re.DOTALL)
            # Patch INSTRUCAO_POR_CANAL
            linhas_dict = ["INSTRUCAO_POR_CANAL: dict[str, str] = {\n"]
            for canal, instrucao in hs.INSTRUCAO_POR_CANAL.items():
                instr_esc = instrucao.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
                linhas_dict.append(f'    "{canal}": (\n        "{instr_esc}"\n    ),\n')
            linhas_dict.append("}\n")
            conteudo = re.sub(
                r'INSTRUCAO_POR_CANAL\s*:\s*dict\[str,\s*str\]\s*=\s*\{.*?\}',
                "".join(linhas_dict),
                conteudo, flags=re.DOTALL)
            hs_path.write_text(conteudo, encoding="utf-8")
        except Exception as e:
            print(f"[CONFIG] Aviso ao salvar house_style: {e}")


# ── Helpers ───────────────────────────────────────────────────────────────────

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


def _carregar_fontes_rss() -> list[dict]:
    p = Path("fontes_rss.json")
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[RSS] Erro: {e}")
    return [
        {"url": "https://g1.globo.com/rss/g1/rio-de-janeiro/",
         "nome": "G1 RJ", "canal_forcado": "Estado RJ"},
        {"url": "https://www.cnnbrasil.com.br/rss/",
         "nome": "CNN Brasil", "canal_forcado": ""},
        {"url": "https://feeds.folha.uol.com.br/poder/rss091.xml",
         "nome": "Folha Poder", "canal_forcado": "Politica"},
        {"url": "https://www.uol.com.br/esporte/rss.xml",
         "nome": "UOL Esportes", "canal_forcado": "Esportes"},
    ]


def _ler_env_atual() -> dict[str, str]:
    env_path = Path(".env")
    res: dict[str, str] = {}
    if not env_path.exists():
        return res
    for linha in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        if "=" in linha:
            chave, _, valor = linha.partition("=")
            res[chave.strip()] = valor.strip()
    return res


def _atualizar_env(novos: dict[str, str]):
    env_path    = Path(".env")
   