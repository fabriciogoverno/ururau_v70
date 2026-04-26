"""
ui/copydesk_painel.py - Painel Copydesk Item-por-Item (v66)

Este painel substitui o antigo JanelaCopydesk visual side-by-side.
Em vez de "aceitar tudo / manter tudo", o editor revisa CADA campo
do pacote editorial separadamente:

  - titulo_seo, titulo_capa, retranca, subtitulo_curto, legenda_curta,
    tags, meta_description, nome_da_fonte, link_da_fonte,
    creditos_da_foto, corpo_materia (paragrafo a paragrafo).

Para cada item o editor pode:
  - Aceitar a sugestao da IA
  - Rejeitar (mantem original)
  - Editar manualmente
  - Marcar como OK
  - Regenerar sugestao

Ao clicar "Salvar", apenas os itens aceitos/editados sao gravados.
Validacao e re-rodada e can_publish() decide se a materia pode ir para o CMS.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Callable, Optional

try:
    import tkinter as tk
    from tkinter import ttk, messagebox, scrolledtext
    _TK_DISPONIVEL = True
except ImportError:
    tk = None  # type: ignore
    _TK_DISPONIVEL = False

# Cores (consistentes com painel.py)
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

FONTE_TITULO  = ("Helvetica", 12, "bold")
FONTE_NORMAL  = ("Helvetica", 10)
FONTE_PEQUENA = ("Helvetica", 9)
FONTE_MONO    = ("Courier New", 9)


# ─── Engine de Sugestoes ────────────────────────────────────────────────────

# Limites obrigatorios Ururau
LIMITES = {
    "titulo_seo":       89,
    "titulo_capa":      60,
    "subtitulo_curto":  140,
    "legenda_curta":    140,
    "meta_description": 160,
    "retranca":         30,
}

CAMPOS_REVISAVEIS = [
    ("titulo_seo",      "Titulo SEO",       89),
    ("titulo_capa",     "Titulo Capa",      60),
    ("retranca",        "Retranca",         30),
    ("subtitulo_curto", "Subtitulo",        140),
    ("legenda_curta",   "Legenda Foto",     140),
    ("tags",            "Tags",             None),
    ("meta_description","Meta Description", 160),
    ("nome_da_fonte",   "Nome da Fonte",    80),
    ("link_da_fonte",   "Link da Fonte",    None),
    ("creditos_da_foto","Creditos da Foto", 60),
]
# v67: Mantem compatibilidade do indice antigo
CAMPOS_REVISAVEIS_LEGACY = [
    ("titulo_seo",      "Titulo SEO",       89),
    ("titulo_capa",     "Titulo Capa",      60),
    ("retranca",        "Retranca",         30),
    ("subtitulo_curto", "Subtitulo",        140),
    ("legenda_curta",   "Legenda Foto",     140),
    ("tags",            "Tags",             None),
    ("meta_description","Meta Description", 160),
    ("nome_da_fonte",   "Nome da Fonte",    80),
    ("link_da_fonte",   "Link da Fonte",    None),
    ("creditos_da_foto","Creditos da Foto", 60),
]


def gerar_sugestoes_item(md: dict, fonte_texto: str = "",
                          mapa: Optional[dict] = None,
                          client=None, modelo: str = "gpt-4.1-mini") -> dict:
    """
    Gera sugestoes item-por-item para cada campo do pacote editorial.

    Sem IA disponivel: usa heuristicas (safe_title, normalizacao).
    Com IA: complementa com sugestoes geradas pelo GPT.
    """
    try:
        from ururau.editorial.safe_title import safe_title, validar_limites_titulos
    except ImportError:
        safe_title = lambda t, l: (t or "")[:l]
        validar_limites_titulos = lambda d: []

    sugestoes: dict[str, dict] = {}

    # Helper de criacao
    def _add(campo: str, atual: str, sug: str, motivo: str,
              limite: Optional[int] = None, severidade: str = "media",
              auto: bool = True):
        sugestoes[campo] = {
            "campo":              campo,
            "valor_atual":        atual or "",
            "sugestao":           sug or "",
            "motivo":             motivo,
            "limite":             limite,
            "caracteres_atual":   len(atual or ""),
            "caracteres_sugestao":len(sug or ""),
            "severidade":         severidade,
            "aplicavel_automaticamente": auto,
            "fonte_suporte":      "",
            "status":             "pending",
        }

    # 1. titulo_seo
    titulo = str(md.get("titulo_seo") or md.get("titulo") or "")
    if not titulo:
        _add("titulo_seo", "", "", "Campo vazio - obrigatorio", 89, "alta", False)
    elif len(titulo) > 89:
        sug = safe_title(titulo, 89)
        _add("titulo_seo", titulo, sug,
             f"Excede limite de 89 chars (tem {len(titulo)}).", 89, "alta", True)
    elif len(titulo) < 40:
        _add("titulo_seo", titulo, titulo,
             f"Curto demais ({len(titulo)} chars). Recomendado 40-89.",
             89, "media", False)
    else:
        _add("titulo_seo", titulo, titulo, "OK", 89, "baixa", True)
        sugestoes["titulo_seo"]["status"] = "ok"

    # 2. titulo_capa
    capa = str(md.get("titulo_capa") or "")
    if not capa:
        # Sugere derivar de titulo_seo via safe_title
        sug = safe_title(titulo, 60) if titulo else ""
        _add("titulo_capa", "", sug,
             "Vazio - sugestao derivada do titulo SEO.", 60, "alta", True)
    elif len(capa) > 60:
        sug = safe_title(capa, 60)
        _add("titulo_capa", capa, sug,
             f"Excede 60 chars (tem {len(capa)}).", 60, "alta", True)
    else:
        _add("titulo_capa", capa, capa, "OK", 60, "baixa", True)
        sugestoes["titulo_capa"]["status"] = "ok"

    # 3. retranca
    retranca = str(md.get("retranca") or "")
    palavras = len(retranca.split()) if retranca else 0
    if not retranca:
        _add("retranca", "", md.get("canal", ""),
             "Vazio - sugere usar o canal.", None, "alta", True)
    elif palavras > 3:
        primeiros_3 = " ".join(retranca.split()[:3])
        _add("retranca", retranca, primeiros_3,
             f"{palavras} palavras (limite: 3).", None, "media", True)
    else:
        _add("retranca", retranca, retranca, "OK", None, "baixa", True)
        sugestoes["retranca"]["status"] = "ok"

    # 4. subtitulo_curto
    sub = str(md.get("subtitulo_curto") or md.get("subtitulo") or "")
    if not sub:
        _add("subtitulo_curto", "", "",
             "Vazio - obrigatorio.", 200, "alta", False)
    elif len(sub) > 200:
        sug = safe_title(sub, 200)
        _add("subtitulo_curto", sub, sug,
             f"Excede 200 chars (tem {len(sub)}).", 200, "media", True)
    else:
        _add("subtitulo_curto", sub, sub, "OK", 200, "baixa", True)
        sugestoes["subtitulo_curto"]["status"] = "ok"

    # 5. legenda_curta
    leg = str(md.get("legenda_curta") or md.get("legenda") or "")
    if not leg:
        _add("legenda_curta", "", "Reproducao",
             "Vazio - sugestao default 'Reproducao'.", 100, "media", True)
    elif len(leg) > 100:
        sug = safe_title(leg, 100)
        _add("legenda_curta", leg, sug,
             f"Excede 100 chars (tem {len(leg)}).", 100, "media", True)
    else:
        _add("legenda_curta", leg, leg, "OK", 100, "baixa", True)
        sugestoes["legenda_curta"]["status"] = "ok"

    # 6. tags
    tags_raw = md.get("tags", "")
    if isinstance(tags_raw, list):
        tags_lista = [str(t).strip() for t in tags_raw if str(t).strip()]
    else:
        tags_lista = [t.strip() for t in str(tags_raw).split(",") if t.strip()]
    n = len(tags_lista)
    if n == 0:
        _add("tags", "", "", "Sem tags - obrigatorio.", None, "alta", False)
    elif n > 8:
        # Recorta para 8 tags
        sug = ", ".join(tags_lista[:8])
        _add("tags", ", ".join(tags_lista), sug,
             f"{n} tags (recomendado: 6-8). Sugere recortar para 8.",
             None, "media", True)
    elif n < 5:
        _add("tags", ", ".join(tags_lista), ", ".join(tags_lista),
             f"Apenas {n} tags (recomendado: 6-8).", None, "media", False)
    else:
        s = ", ".join(tags_lista)
        _add("tags", s, s, "OK", None, "baixa", True)
        sugestoes["tags"]["status"] = "ok"

    # 7. meta_description
    meta = str(md.get("meta_description") or "")
    if not meta:
        # Sugere usar resumo curto ou subtitulo
        sug = (md.get("resumo_curto") or sub or "")[:160]
        _add("meta_description", "", sug,
             "Vazio - derivado do resumo/subtitulo.", 160, "media", True)
    elif len(meta) > 160:
        sug = safe_title(meta, 160)
        _add("meta_description", meta, sug,
             f"Excede 160 chars (tem {len(meta)}).", 160, "media", True)
    elif len(meta) < 80:
        _add("meta_description", meta, meta,
             f"Curto ({len(meta)} chars). Recomendado 120-160.",
             160, "baixa", False)
    else:
        _add("meta_description", meta, meta, "OK", 160, "baixa", True)
        sugestoes["meta_description"]["status"] = "ok"

    # 8. nome_da_fonte
    fonte_n = str(md.get("nome_da_fonte") or "")
    if not fonte_n:
        _add("nome_da_fonte", "", "Redacao",
             "Vazio - sugestao default 'Redacao'.", 80, "alta", True)
    elif len(fonte_n) > 80:
        _add("nome_da_fonte", fonte_n, fonte_n[:80].rsplit(" ",1)[0],
             f"Excede 80 chars.", 80, "media", True)
    else:
        _add("nome_da_fonte", fonte_n, fonte_n, "OK", 80, "baixa", True)
        sugestoes["nome_da_fonte"]["status"] = "ok"

    # 9. link_da_fonte
    link = str(md.get("link_da_fonte") or md.get("link_origem") or "")
    if not link:
        _add("link_da_fonte", "", "",
             "Vazio - obrigatorio para credito.", None, "alta", False)
    else:
        _add("link_da_fonte", link, link, "OK", None, "baixa", True)
        sugestoes["link_da_fonte"]["status"] = "ok"

    # 10. creditos_da_foto
    cred = str(md.get("creditos_da_foto") or "")
    if not cred:
        _add("creditos_da_foto", "", "Reproducao",
             "Vazio - sugestao default 'Reproducao'.", 60, "media", True)
    elif len(cred) > 60:
        _add("creditos_da_foto", cred, cred[:60].rsplit(" ",1)[0],
             f"Excede 60 chars.", 60, "media", True)
    else:
        _add("creditos_da_foto", cred, cred, "OK", 60, "baixa", True)
        sugestoes["creditos_da_foto"]["status"] = "ok"

    return sugestoes


def regenerar_sugestao_ia_full(campo: str, valor_atual: str, contexto_full: dict,
                                  client=None, modelo: str = "gpt-4.1-mini") -> Optional[str]:
    """
    v69: versao COM CONTEXTO COMPLETO.

    contexto_full: cleaned_source_text, article_type, editorial_angle,
    paragraph_plan, facts_required/used/missing, entity_relationships,
    relationship_errors, validation_errors, current article fields.

    Usa GPT-4.1-mini com prompt rico.
    """
    if client is None:
        return None
    try:
        try:
            from ururau.editorial.field_limits import (
                TITULO_SEO_MAX, TITULO_CAPA_MAX,
                SUBTITULO_CURTO_MAX, LEGENDA_CURTA_MAX,
                META_DESCRIPTION_MAX, RETRANCA_MAX_WORDS,
                TAGS_MIN, TAGS_MAX,
            )
        except ImportError:
            TITULO_SEO_MAX = 89; TITULO_CAPA_MAX = 60
            SUBTITULO_CURTO_MAX = 140; LEGENDA_CURTA_MAX = 140
            META_DESCRIPTION_MAX = 160; RETRANCA_MAX_WORDS = 3
            TAGS_MIN = 6; TAGS_MAX = 8

        instr = {
            "titulo_seo":       f"Reescreva o TITULO SEO em ate {TITULO_SEO_MAX} chars. Palavra-chave forte no inicio.",
            "titulo_capa":      f"Reescreva o TITULO CAPA em ate {TITULO_CAPA_MAX} chars.",
            "subtitulo_curto":  f"Subtitulo em ate {SUBTITULO_CURTO_MAX} chars complementando o titulo.",
            "meta_description": f"Meta description com {META_DESCRIPTION_MAX-40}-{META_DESCRIPTION_MAX} chars.",
            "tags":             f"{TAGS_MIN}-{TAGS_MAX} tags fortes separadas por virgula.",
            "legenda_curta":    f"Legenda factual em ate {LEGENDA_CURTA_MAX} chars.",
            "retranca":         f"Retranca de 1 a {RETRANCA_MAX_WORDS} palavras.",
        }.get(campo, f"Reescreva o campo {campo}.")

        facts_missing = contexto_full.get("facts_missing") or []
        bloco_fatos = ""
        if facts_missing:
            bloco_fatos = "\nFATOS AUSENTES (incorpore se relevante):\n" + \
                          "\n".join(f"  - {f.get('text', '')}" for f in facts_missing[:8])

        rel_errors = contexto_full.get("relationship_errors") or []
        bloco_rel = ""
        if rel_errors:
            bloco_rel = "\nERROS DE RELACAO (corrigir):\n" + \
                        "\n".join(f"  - {e.get('mensagem', '')}" for e in rel_errors[:5])

        prompt = (
            f"Voce eh copydesk profissional do Ururau.\n{instr}\n\n"
            f"TIPO: {contexto_full.get('article_type', 'desconhecido')}\n"
            f"ANGULO: {(contexto_full.get('editorial_angle','') or '')[:200]}\n"
            f"VALOR ATUAL: {valor_atual!r}\n\n"
            f"ARTIGO ATUAL:\n"
            f"  Titulo: {contexto_full.get('titulo_seo','')[:120]}\n"
            f"  Subtitulo: {contexto_full.get('subtitulo','')[:200]}\n"
            f"  Inicio corpo: {(contexto_full.get('corpo','') or '')[:400]}\n"
            f"{bloco_fatos}{bloco_rel}\n\n"
            f"FONTE LIMPA (use APENAS estes fatos):\n"
            f"{(contexto_full.get('cleaned_source_text','') or '')[:3000]}\n\n"
            f"Retorne APENAS o novo valor, sem aspas extras, sem markdown."
        )

        resp = client.chat.completions.create(
            model=modelo,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=300,
        )
        novo = resp.choices[0].message.content.strip()
        if novo.startswith('"') and novo.endswith('"'):
            novo = novo[1:-1]
        return novo
    except Exception as e:
        print(f"[COPYDESK_IA v69] full({campo}): {e}")
        return None


def regenerar_sugestao_ia(campo: str, valor_atual: str, contexto: dict,
                            client=None, modelo: str = "gpt-4.1-mini") -> Optional[str]:
    """
    Usa GPT-4.1-mini para gerar uma sugestao melhor para o campo escolhido.
    Retorna None se IA indisponivel ou erro.

    contexto deve conter:
      - titulo_seo, subtitulo, corpo (referencia)
      - canal
      - fonte_texto (opcional, para verificar suporte)
    """
    if client is None:
        return None
    try:
        # Constroi prompt direcionado por campo
        instrucoes = {
            "titulo_seo": (
                "Reescreva o TITULO SEO em ate 89 caracteres. "
                "Coloque palavra-chave forte no inicio. Sem clickbait. Sem cortar palavra."
            ),
            "titulo_capa": (
                "Reescreva o TITULO DE CAPA em ate 60 caracteres. "
                "Forte para home, factual, sem cortar palavra."
            ),
            "subtitulo_curto": (
                "Reescreva o SUBTITULO em ate 140 caracteres. "
                "Complementa o titulo sem repetir. Factual."
            ),
            "meta_description": (
                "Escreva uma META DESCRIPTION de 120 a 160 caracteres. "
                "Resume o fato principal com termo de busca forte."
            ),
            "tags": (
                "Liste de 6 a 8 TAGS fortes separadas por virgula. "
                "Inclua personagens, instituicoes, cidade, tema. Sem hashtags."
            ),
            "legenda_curta": (
                "Escreva uma LEGENDA factual de ate 140 caracteres "
                "para a foto, descrevendo pessoa/local/evento."
            ),
            "retranca": (
                "Escreva uma RETRANCA editorial de 1 a 3 palavras "
                "(ex.: Politica, Justica, Cidades, Esportes)."
            ),
        }
        instr = instrucoes.get(campo, f"Reescreva o campo {campo} de forma profissional.")

        prompt = (
            f"Voce eh um copydesk profissional do jornal Ururau.\n"
            f"{instr}\n\n"
            f"VALOR ATUAL: {valor_atual!r}\n\n"
            f"CONTEXTO DA MATERIA:\n"
            f"  Titulo: {contexto.get('titulo_seo','')[:120]}\n"
            f"  Subtitulo: {contexto.get('subtitulo','')[:200]}\n"
            f"  Canal: {contexto.get('canal','')}\n"
            f"  Inicio do corpo: {(contexto.get('corpo','') or '')[:300]}\n\n"
            f"Retorne APENAS o novo valor do campo, sem explicacao, sem aspas extras, sem markdown."
        )

        resp = client.chat.completions.create(
            model=modelo,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=200,
        )
        novo = resp.choices[0].message.content.strip()
        # Remove aspas se a IA tiver envolvido
        if novo.startswith('"') and novo.endswith('"'):
            novo = novo[1:-1]
        return novo
    except Exception as e:
        print(f"[COPYDESK_IA] Falha em regenerar_sugestao_ia({campo}): {e}")
        return None


def gerar_sugestoes_paragrafos(corpo: str) -> list[dict]:
    """
    Analisa o corpo paragrafo a paragrafo e retorna sugestoes.
    Cada paragrafo recebe um dict {indice, texto, status, motivo, sugestao}.
    """
    if not corpo:
        return []
    paragrafos = [p.strip() for p in corpo.split("\n\n") if p.strip()]
    out: list[dict] = []

    EXPRESSOES_GENERICAS = [
        "vale lembrar", "e importante destacar", "cabe ressaltar",
        "em meio a", "cenario complexo", "nesse contexto",
        "a populacao aguarda", "novas informacoes serao divulgadas",
        "as investigacoes seguem", "o caso deve ter novos desdobramentos",
    ]

    for i, par in enumerate(paragrafos):
        problemas = []
        # Travessao
        if "—" in par or "–" in par:
            problemas.append("contem travessao (substitua por virgula/dois pontos)")
        # Expressao generica
        par_low = par.lower()
        for expr in EXPRESSOES_GENERICAS:
            if expr in par_low:
                problemas.append(f"expressao generica: '{expr}'")
                break
        # Curto demais
        if len(par) < 60 and i < len(paragrafos) - 1:
            problemas.append(f"paragrafo curto demais ({len(par)} chars)")
        # Longo demais
        if len(par) > 600:
            problemas.append(f"paragrafo longo demais ({len(par)} chars)")

        status = "ok" if not problemas else "atencao"
        out.append({
            "indice":   i,
            "texto":    par,
            "status":   status,
            "motivo":   "; ".join(problemas) if problemas else "OK",
            "sugestao": par,  # default: manter como esta
        })
    return out


# ─── Painel Copydesk Item-por-Item ──────────────────────────────────────────

class JanelaCopydeskItem(tk.Toplevel if _TK_DISPONIVEL else object):
    """
    Janela Copydesk com revisao ITEM-POR-ITEM.

    Layout:
      - Topo: barra de status + acoes globais (Salvar / Revalidar / Fechar)
      - Esquerda: lista de campos com status (OK / atencao / vazio)
      - Direita: editor do campo selecionado com:
          * valor atual (read-only)
          * sugestao IA (read-only)
          * caixa de edicao manual
          * acoes: Aceitar | Rejeitar | Editar | OK | Regenerar
    """

    def __init__(self, parent, pauta: dict, md: dict, db,
                  client, modelo: str,
                  on_salvar: Optional[Callable] = None):
        if not _TK_DISPONIVEL:
            raise RuntimeError("Tkinter nao disponivel - Copydesk requer GUI.")
        super().__init__(parent)
        self._pauta   = pauta
        self._md_orig = dict(md)
        self._md_atual = dict(md)
        self._db      = db
        self._client  = client
        self._modelo  = modelo
        self._on_salvar = on_salvar

        self.title(f"Copydesk - {(pauta.get('titulo_origem') or '')[:60]}")
        self.geometry("1200x780")
        self.configure(bg=COR_FUNDO)
        try:
            self.grab_set()
        except Exception:
            pass

        # Gera sugestoes
        try:
            self._sugestoes = gerar_sugestoes_item(md, client=client, modelo=modelo)
        except Exception as e:
            print(f"[COPYDESK] Erro gerando sugestoes: {e}")
            self._sugestoes = {}
        try:
            self._paragrafos = gerar_sugestoes_paragrafos(
                md.get("corpo_materia") or md.get("conteudo") or ""
            )
        except Exception as e:
            print(f"[COPYDESK] Erro gerando sugestoes de paragrafos: {e}")
            self._paragrafos = []

        # Estado: campo selecionado
        self._campo_sel: Optional[str] = None
        self._historico: list[dict] = []  # para salvar audit trail

        self._build_ui()

    # UI -----------------------------------------------------------------------

    def _build_ui(self):
        # Toolbar topo
        top = tk.Frame(self, bg=COR_PAINEL, height=46)
        top.pack(fill="x")
        top.pack_propagate(False)
        tk.Label(top, text="COPYDESK ITEM-POR-ITEM",
                 bg=COR_PAINEL, fg=COR_ROXO,
                 font=FONTE_TITULO).pack(side="left", padx=12)
        tk.Label(top, text="(Aceite, rejeite ou edite cada campo separadamente)",
                 bg=COR_PAINEL, fg=COR_CINZA, font=FONTE_PEQUENA).pack(side="left", padx=4)

        for txt, cmd, cor in [
            ("[X] Fechar sem salvar",  self.destroy,           "#374151"),
            ("[REVAL] Revalidar",      self._revalidar,        COR_AZUL),
            ("[OK] Salvar mudancas",   self._salvar,           COR_VERDE),
        ]:
            tk.Button(top, text=txt, command=cmd, bg=cor, fg="white",
                      relief="flat", padx=10, pady=4, cursor="hand2",
                      font=("Helvetica", 9, "bold")).pack(side="right", padx=4, pady=8)

        # Conteudo
        main = tk.Frame(self, bg=COR_FUNDO)
        main.pack(fill="both", expand=True, padx=8, pady=6)

        # Esquerda - lista de campos
        lf = tk.Frame(main, bg=COR_PAINEL, width=320)
        lf.pack(side="left", fill="y", padx=(0, 6))
        lf.pack_propagate(False)
        tk.Label(lf, text="Campos do Pacote Editorial",
                 bg=COR_PAINEL, fg=COR_TEXTO, font=("Helvetica", 10, "bold")
                 ).pack(anchor="w", padx=8, pady=6)

        cont = tk.Frame(lf, bg=COR_PAINEL)
        cont.pack(fill="both", expand=True, padx=4)

        # Lista scrollavel
        self._lista_frame = tk.Frame(cont, bg=COR_PAINEL)
        self._lista_frame.pack(fill="both", expand=True)

        for chave, label, lim in CAMPOS_REVISAVEIS:
            self._criar_item_lista(self._lista_frame, chave, label, lim)

        # Item especial: corpo (paragrafo a paragrafo)
        if self._paragrafos:
            sep = tk.Frame(self._lista_frame, bg=COR_PAINEL, height=8)
            sep.pack(fill="x")
            tk.Label(self._lista_frame, text=f"Corpo ({len(self._paragrafos)} paragrafos)",
                     bg=COR_PAINEL, fg=COR_AMARELO,
                     font=("Helvetica", 9, "bold")).pack(anchor="w", padx=8, pady=(6, 2))
            for p in self._paragrafos:
                cor_p = COR_VERDE if p["status"] == "ok" else COR_AMARELO
                btn = tk.Button(
                    self._lista_frame,
                    text=f"  Par. {p['indice']+1}: {p['texto'][:40]}...",
                    bg=COR_PAINEL, fg=cor_p, relief="flat", anchor="w",
                    font=FONTE_PEQUENA, padx=8, cursor="hand2",
                    command=lambda idx=p["indice"]: self._selecionar_paragrafo(idx),
                )
                btn.pack(fill="x", pady=1)

        # Direita - detalhe do campo
        self._detalhe = tk.Frame(main, bg=COR_FUNDO)
        self._detalhe.pack(side="left", fill="both", expand=True)
        self._mostrar_intro()

        # Status bar
        self._status_bar = tk.Label(self, text="Selecione um campo a esquerda.",
                                     bg="#0d0d20", fg=COR_CINZA, anchor="w",
                                     font=FONTE_PEQUENA, padx=8, pady=4)
        self._status_bar.pack(fill="x", side="bottom")

    def _criar_item_lista(self, parent, chave: str, label: str, limite):
        """Cria um botao de item na lista lateral."""
        sug = self._sugestoes.get(chave, {})
        sev = sug.get("severidade", "baixa")
        status = sug.get("status", "pending")

        if status == "ok":
            icone, cor = "[OK]", COR_VERDE
        elif sev == "alta":
            icone, cor = "[!] ", COR_VERMELHO
        elif sev == "media":
            icone, cor = "[~] ", COR_AMARELO
        else:
            icone, cor = "[ ] ", COR_CINZA

        atual = sug.get("caracteres_atual", 0)
        chars_lbl = f"({atual}/{limite})" if limite else ""
        texto = f"{icone} {label} {chars_lbl}"

        btn = tk.Button(
            parent, text=texto, bg=COR_PAINEL, fg=cor,
            relief="flat", anchor="w", font=FONTE_PEQUENA,
            padx=8, pady=4, cursor="hand2",
            command=lambda k=chave: self._selecionar(k),
        )
        btn.pack(fill="x", pady=1)

    def _mostrar_intro(self):
        for w in self._detalhe.winfo_children():
            w.destroy()
        tk.Label(self._detalhe,
                 text="Selecione um campo a esquerda para revisar.",
                 bg=COR_FUNDO, fg=COR_TEXTO,
                 font=FONTE_NORMAL).pack(pady=40)

        # Resumo
        n_total = len(self._sugestoes) + len(self._paragrafos)
        n_ok = sum(1 for s in self._sugestoes.values() if s.get("status") == "ok")
        n_alta = sum(1 for s in self._sugestoes.values() if s.get("severidade") == "alta")
        resumo = (
            f"Total de itens: {n_total}\n"
            f"Itens OK: {n_ok}\n"
            f"Severidade alta: {n_alta}\n"
            f"Paragrafos do corpo: {len(self._paragrafos)}"
        )
        tk.Label(self._detalhe, text=resumo, bg=COR_FUNDO, fg=COR_CINZA,
                 font=FONTE_PEQUENA, justify="left").pack(pady=10)

    def _selecionar(self, chave: str):
        self._campo_sel = chave
        sug = self._sugestoes.get(chave, {})
        for w in self._detalhe.winfo_children():
            w.destroy()

        # Cabecalho do campo
        label_lbl = next((l for k, l, _ in CAMPOS_REVISAVEIS if k == chave), chave)
        tk.Label(self._detalhe, text=label_lbl,
                 bg=COR_FUNDO, fg=COR_AZUL,
                 font=FONTE_TITULO).pack(anchor="w", padx=10, pady=(8, 2))
        tk.Label(self._detalhe,
                 text=sug.get("motivo", ""),
                 bg=COR_FUNDO, fg=COR_AMARELO,
                 font=FONTE_PEQUENA, wraplength=720).pack(anchor="w", padx=10)

        # Valor atual
        tk.Label(self._detalhe, text="Valor atual:",
                 bg=COR_FUNDO, fg=COR_CINZA, font=FONTE_PEQUENA
                 ).pack(anchor="w", padx=10, pady=(8, 2))
        atual_box = scrolledtext.ScrolledText(self._detalhe, bg="#16213e",
                                                fg=COR_TEXTO, font=FONTE_MONO,
                                                height=4, wrap="word")
        atual_box.pack(fill="x", padx=10)
        atual_box.insert("1.0", sug.get("valor_atual", ""))
        atual_box.config(state="disabled")

        # Sugestao IA
        tk.Label(self._detalhe, text="Sugestao da IA:",
                 bg=COR_FUNDO, fg=COR_VERDE, font=FONTE_PEQUENA
                 ).pack(anchor="w", padx=10, pady=(8, 2))
        sug_box = scrolledtext.ScrolledText(self._detalhe, bg="#0d2818",
                                              fg=COR_TEXTO, font=FONTE_MONO,
                                              height=4, wrap="word")
        sug_box.pack(fill="x", padx=10)
        sug_box.insert("1.0", sug.get("sugestao", ""))
        sug_box.config(state="disabled")

        # Edicao manual
        tk.Label(self._detalhe, text="Edicao manual (opcional):",
                 bg=COR_FUNDO, fg=COR_CIANO, font=FONTE_PEQUENA
                 ).pack(anchor="w", padx=10, pady=(8, 2))
        edit_box = scrolledtext.ScrolledText(self._detalhe, bg="#1a1a2e",
                                              fg=COR_TEXTO, font=FONTE_MONO,
                                              height=5, wrap="word")
        edit_box.pack(fill="x", padx=10)
        # Pre-preenche com valor atual
        edit_box.insert("1.0", sug.get("valor_atual", ""))
        self._edit_box = edit_box

        # Acoes
        af = tk.Frame(self._detalhe, bg=COR_FUNDO)
        af.pack(fill="x", padx=10, pady=10)

        for txt, cmd, cor in [
            ("Aceitar sugestao",      lambda: self._aplicar(chave, "accepted"),  COR_VERDE),
            ("Rejeitar (manter)",     lambda: self._aplicar(chave, "rejected"),  COR_VERMELHO),
            ("Salvar edicao manual",  lambda: self._aplicar(chave, "edited"),    COR_CIANO),
            ("Marcar como OK",        lambda: self._aplicar(chave, "ok"),        COR_AZUL),
        ]:
            tk.Button(af, text=txt, command=cmd, bg=cor, fg="white",
                      relief="flat", padx=8, pady=4, cursor="hand2",
                      font=("Helvetica", 9, "bold")).pack(side="left", padx=4)

        # v67: Botao "Regenerar com IA" se cliente disponivel
        if self._client is not None:
            tk.Button(af, text="Regenerar com IA",
                      command=lambda c=chave, sb=sug_box: self._regenerar_ia(c, sb),
                      bg=COR_ROXO, fg="white", relief="flat", padx=8, pady=4,
                      cursor="hand2",
                      font=("Helvetica", 9, "bold")).pack(side="left", padx=4)
        else:
            tk.Label(af, text="(IA indisponivel - modo manual)",
                     bg=COR_FUNDO, fg=COR_CINZA,
                     font=FONTE_PEQUENA).pack(side="left", padx=8)

    def _regenerar_ia(self, chave: str, sug_box):
        """v69b: usa regenerar_sugestao_ia_full() com CONTEXTO COMPLETO."""
        sug = self._sugestoes.get(chave, {})
        valor_atual = sug.get("valor_atual", "")
        # v69b: contexto FULL com fonte limpa, fatos ausentes, relacoes, tipo, angulo
        md = self._md_atual or {}
        pauta = self._pauta or {}
        contexto_full = {
            "titulo_seo": md.get("titulo_seo") or md.get("titulo", ""),
            "subtitulo":  md.get("subtitulo_curto") or md.get("subtitulo", ""),
            "corpo":      md.get("corpo_materia") or md.get("conteudo", ""),
            "canal":      md.get("canal", "") or pauta.get("canal", ""),
            # v69b: contexto editorial completo
            "cleaned_source_text":  md.get("cleaned_source_text", "") or pauta.get("cleaned_source_text", ""),
            "article_type":         md.get("article_type", "") or md.get("canal", ""),
            "editorial_angle":      md.get("editorial_angle", ""),
            "paragraph_plan":       md.get("paragraph_plan", []),
            "facts_required":       md.get("facts_required", []),
            "facts_used":           md.get("facts_used", []),
            "facts_missing":        md.get("facts_missing", []),
            "entity_relationships": md.get("entity_relationships", []),
            "relationship_errors":  md.get("relationship_errors", []),
            "validation_errors":    md.get("erros_validacao", []),
        }
        self._status_bar.config(text=f"[IA v69b] Regenerando {chave} com contexto completo...")
        try:
            self.update_idletasks()
        except Exception:
            pass
        novo = regenerar_sugestao_ia_full(
            chave, valor_atual, contexto_full,
            client=self._client, modelo=self._modelo,
        )
        if novo:
            sug["sugestao"] = novo
            sug["caracteres_sugestao"] = len(novo)
            try:
                sug_box.config(state="normal")
                sug_box.delete("1.0", "end")
                sug_box.insert("1.0", novo)
                sug_box.config(state="disabled")
            except Exception:
                pass
            self._status_bar.config(text=f"[OK] Nova sugestao IA para {chave} ({len(novo)} chars)")
        else:
            self._status_bar.config(text=f"[X] IA nao retornou sugestao para {chave}")

    def _selecionar_paragrafo(self, idx: int):
        """Mostra editor de paragrafo individual."""
        if idx >= len(self._paragrafos):
            return
        par = self._paragrafos[idx]
        for w in self._detalhe.winfo_children():
            w.destroy()
        tk.Label(self._detalhe, text=f"Paragrafo {idx+1}",
                 bg=COR_FUNDO, fg=COR_AMARELO,
                 font=FONTE_TITULO).pack(anchor="w", padx=10, pady=(8, 2))
        tk.Label(self._detalhe, text=par.get("motivo", ""),
                 bg=COR_FUNDO, fg=COR_CINZA, font=FONTE_PEQUENA,
                 wraplength=720).pack(anchor="w", padx=10)

        tk.Label(self._detalhe, text="Texto atual:",
                 bg=COR_FUNDO, fg=COR_CINZA, font=FONTE_PEQUENA
                 ).pack(anchor="w", padx=10, pady=(8, 2))
        edit = scrolledtext.ScrolledText(self._detalhe, bg="#1a1a2e",
                                          fg=COR_TEXTO, font=FONTE_MONO,
                                          height=10, wrap="word")
        edit.pack(fill="both", expand=True, padx=10)
        edit.insert("1.0", par.get("texto", ""))

        af = tk.Frame(self._detalhe, bg=COR_FUNDO)
        af.pack(fill="x", padx=10, pady=10)

        def _salvar_par():
            novo = edit.get("1.0", "end").strip()
            self._paragrafos[idx]["texto"] = novo
            self._paragrafos[idx]["status"] = "edited"
            self._reconstruir_corpo()
            self._status_bar.config(text=f"Paragrafo {idx+1} atualizado.")
        def _remover_par():
            if not messagebox.askyesno("Remover paragrafo",
                                        f"Remover o paragrafo {idx+1}?",
                                        parent=self):
                return
            self._paragrafos[idx]["status"] = "removed"
            self._paragrafos[idx]["texto"]  = ""
            self._reconstruir_corpo()
            self._status_bar.config(text=f"Paragrafo {idx+1} removido.")

        tk.Button(af, text="Salvar paragrafo",
                  command=_salvar_par, bg=COR_VERDE, fg="white",
                  relief="flat", padx=8, pady=4, cursor="hand2",
                  font=("Helvetica", 9, "bold")).pack(side="left", padx=4)
        tk.