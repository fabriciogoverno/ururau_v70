"""
editorial/quality_gates.py — Gates de qualidade integrados (v67).

Centraliza:
  - calculate_fact_coverage(): coverage_score 0..1
  - calculate_quality_score(): score_qualidade 0..100
  - run_autopub_copydesk(): copydesk automatico antes de publicacao direta
  - safe_can_publish(): wrapper de can_publish que FAIL-CLOSED em modo monitor

Esses gates sao chamados:
  - Pelo redacao.py apos a geracao
  - Pelo monitor.py antes de publicacao direta (rascunho=False)
  - Pelo workflow.py.etapa_publicacao
  - Pelo Copydesk UI ao revalidar
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional


# ─── Normalizacao de texto ──────────────────────────────────────────────────

def _norm(t: str) -> str:
    """Normaliza texto para comparacao: lower, sem acento, sem pontuacao extra."""
    if not t:
        return ""
    s = unicodedata.normalize("NFD", str(t))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower().strip()


# ─── Coverage Score ─────────────────────────────────────────────────────────

def _flatten_facts(essential_facts: dict) -> list[str]:
    """
    Achata o dict de essential_facts em lista de strings comparaveis.

    Cada chave do mapa de evidencias contribui:
      - main_fact, fato_principal      -> texto direto
      - quem (lista)                   -> cada nome
      - dados_numericos (lista)        -> cada valor
      - estudos_citados (lista)        -> cada estudo
      - artigos_lei_citados            -> cada artigo
      - argumentos_centrais            -> cada argumento
      - pedidos_ou_encaminhamentos     -> cada pedido
      - declaracoes_identificadas      -> cada declaracao
      - quando, onde, numero_principal, orgao_central -> texto direto
    """
    out: list[str] = []
    if not essential_facts:
        return out

    # Strings simples
    for key in (
        "fato_principal", "main_fact", "quando", "onde",
        "numero_principal", "orgao_central", "fonte_primaria",
        "por_que_importa", "consequencia", "status_atual",
        "proximos_passos", "base_juridica",
    ):
        v = essential_facts.get(key)
        if isinstance(v, str) and v.strip():
            out.append(v.strip())

    # Listas
    for key in (
        "quem", "dados_numericos", "estudos_citados",
        "artigos_lei_citados", "argumentos_centrais",
        "pedidos_ou_encaminhamentos", "declaracoes_identificadas",
        "fatos_secundarios", "impactos_citados",
    ):
        v = essential_facts.get(key)
        if isinstance(v, list):
            for item in v:
                if isinstance(item, str) and item.strip():
                    out.append(item.strip())

    return out


def calculate_fact_coverage(article: dict, essential_facts: dict) -> dict:
    """
    Calcula coverage_score = facts_used / facts_required.

    Compara essential_facts com corpo do artigo e tags.
    Retorna dict com coverage_score (0..1), facts_required, facts_used,
    facts_missing.
    """
    if not article or not essential_facts:
        return {
            "coverage_score": 0.0,
            "facts_required": [],
            "facts_used": [],
            "facts_missing": [],
        }

    corpo = (article.get("corpo_materia")
             or article.get("conteudo")
             or "")
    tags = article.get("tags") or ""
    titulo = article.get("titulo_seo") or article.get("titulo") or ""
    subtit = article.get("subtitulo_curto") or article.get("subtitulo") or ""

    busca = _norm(f"{titulo} {subtit} {corpo} {tags}")

    required = _flatten_facts(essential_facts)
    if not required:
        return {
            "coverage_score": 1.0,  # sem fatos exigidos = 100% cobertura
            "facts_required": [],
            "facts_used": [],
            "facts_missing": [],
        }

    used: list[str] = []
    missing: list[str] = []
    for fato in required:
        # Match parcial: divide o fato em palavras "fortes" (>3 chars) e
        # exige que pelo menos 60% delas apareçam no corpo.
        palavras = [w for w in _norm(fato).split() if len(w) > 3]
        if not palavras:
            # fato curto demais → exige match exato
            if _norm(fato) in busca:
                used.append(fato)
            else:
                missing.append(fato)
            continue
        encontradas = sum(1 for w in palavras if w in busca)
        if encontradas / len(palavras) >= 0.6:
            used.append(fato)
        else:
            missing.append(fato)

    score = len(used) / len(required) if required else 1.0
    return {
        "coverage_score": round(score, 4),
        "facts_required": required,
        "facts_used": used,
        "facts_missing": missing,
    }


# ─── Quality Score ──────────────────────────────────────────────────────────

# Penalidades em pontos
_PENALIDADES = {
    "titulo_excedeu_limite":      15,
    "titulo_capa_excedeu_limite": 12,
    "titulo_ausente":             40,
    "corpo_ausente":              80,
    "corpo_curto":                20,
    "tags_insuficientes":         8,
    "tags_excessivas":            5,
    "meta_ausente":               6,
    "subtitulo_ausente":          6,
    "legenda_ausente":            4,
    "creditos_ausentes":          3,
    "fonte_ausente":              5,
    "travessao":                  4,
    "expressao_proibida":         5,  # por ocorrencia
    "data_inventada":             20,
    "low_coverage":               25,
    "wrong_angle":                15,
    "unsupported_claim":          15,
    "repeated_paragraph":         8,
    "generic_paragraph":          5,
}


def calculate_quality_score(
    article: dict,
    essential_facts: Optional[dict] = None,
    erros_validacao: Optional[list[dict]] = None,
    coverage: Optional[dict] = None,
) -> dict:
    """
    Calcula score_qualidade (0..100) e score_risco (0..100).

    Score baixo = mais erros / problemas. Score alto = artigo limpo.
    """
    pontos = 100
    detalhes: list[str] = []

    titulo = article.get("titulo_seo") or article.get("titulo") or ""
    titulo_capa = article.get("titulo_capa") or ""
    corpo = article.get("corpo_materia") or article.get("conteudo") or ""
    tags = article.get("tags") or ""
    sub = article.get("subtitulo_curto") or article.get("subtitulo") or ""
    leg = article.get("legenda_curta") or article.get("legenda") or ""
    meta = article.get("meta_description") or ""
    cred = article.get("creditos_da_foto") or ""
    fonte_n = article.get("nome_da_fonte") or ""

    # 1. Titulos
    if not titulo:
        pontos -= _PENALIDADES["titulo_ausente"]
        detalhes.append("titulo_ausente (-40)")
    elif len(titulo) > 89:
        pontos -= _PENALIDADES["titulo_excedeu_limite"]
        detalhes.append(f"titulo_seo_excedeu_limite ({len(titulo)} chars) (-15)")

    if titulo_capa and len(titulo_capa) > 60:
        pontos -= _PENALIDADES["titulo_capa_excedeu_limite"]
        detalhes.append(f"titulo_capa_excedeu_limite ({len(titulo_capa)} chars) (-12)")

    # 2. Corpo
    if not corpo:
        pontos -= _PENALIDADES["corpo_ausente"]
        detalhes.append("corpo_ausente (-80)")
    elif len(corpo) < 500:
        pontos -= _PENALIDADES["corpo_curto"]
        detalhes.append(f"corpo_curto ({len(corpo)} chars) (-20)")

    # 3. Tags
    tags_lista = [t.strip() for t in str(tags).split(",") if t.strip()] \
                  if isinstance(tags, str) else list(tags or [])
    n_tags = len(tags_lista)
    if n_tags == 0:
        pontos -= _PENALIDADES["tags_insuficientes"]
        detalhes.append("tags_ausentes (-8)")
    elif n_tags < 5:
        pontos -= _PENALIDADES["tags_insuficientes"]
        detalhes.append(f"tags_insuficientes ({n_tags}) (-8)")
    elif n_tags > 12:
        pontos -= _PENALIDADES["tags_excessivas"]
        detalhes.append(f"tags_excessivas ({n_tags}) (-5)")

    # 4. Meta description
    if not meta:
        pontos -= _PENALIDADES["meta_ausente"]
        detalhes.append("meta_ausente (-6)")

    # 5. Subtitulo
    if not sub:
        pontos -= _PENALIDADES["subtitulo_ausente"]
        detalhes.append("subtitulo_ausente (-6)")

    # 6. Legenda
    if not leg:
        pontos -= _PENALIDADES["legenda_ausente"]
        detalhes.append("legenda_ausente (-4)")

    # 7. Creditos foto / fonte
    if not cred:
        pontos -= _PENALIDADES["creditos_ausentes"]
        detalhes.append("creditos_ausentes (-3)")
    if not fonte_n:
        pontos -= _PENALIDADES["fonte_ausente"]
        detalhes.append("fonte_ausente (-5)")

    # 8. Travessao no corpo
    if "—" in corpo or "–" in corpo:
        pontos -= _PENALIDADES["travessao"]
        detalhes.append("travessao_no_corpo (-4)")

    # 9. Expressoes proibidas (penalidade por ocorrencia, max 3)
    EXPR_PROIBIDAS = (
        "vale lembrar", "e importante destacar", "cabe ressaltar",
        "em meio a", "cenario complexo", "nesse contexto",
        "novas informacoes serao divulgadas",
    )
    n_expr = 0
    corpo_n = _norm(corpo)
    for expr in EXPR_PROIBIDAS:
        if expr in corpo_n:
            n_expr += 1
    if n_expr:
        p = min(n_expr, 3) * _PENALIDADES["expressao_proibida"]
        pontos -= p
        detalhes.append(f"expressao_proibida ({n_expr}x) (-{p})")

    # 10. Erros de validacao explicitos
    if erros_validacao:
        for e in erros_validacao:
            if not isinstance(e, dict):
                continue
            cat = e.get("categoria", "")
            cod = e.get("codigo", "")
            if cat == "EDITORIAL_BLOCKER":
                if cod == "low_source_coverage":
                    pontos -= _PENALIDADES["low_coverage"]
                    detalhes.append(f"low_coverage (-{_PENALIDADES['low_coverage']})")
                elif cod == "wrong_editorial_angle":
                    pontos -= _PENALIDADES["wrong_angle"]
                    detalhes.append(f"wrong_angle (-{_PENALIDADES['wrong_angle']})")
                elif cod == "data_inventada":
                    pontos -= _PENALIDADES["data_inventada"]
                    detalhes.append(f"data_inventada (-{_PENALIDADES['data_inventada']})")
                elif cod == "unsupported_claim":
                    pontos -= _PENALIDADES["unsupported_claim"]
                    detalhes.append(f"unsupported_claim (-{_PENALIDADES['unsupported_claim']})")

    # 11. Coverage como bonus/penalidade
    if coverage:
        cov_score = coverage.get("coverage_score", 1.0)
        if cov_score < 0.85:
            penalty = int((0.85 - cov_score) * 100)
            pontos -= penalty
            detalhes.append(f"coverage_baixa ({cov_score:.2f}) (-{penalty})")

    pontos = max(0, min(100, pontos))

    # Risco: simetricamente, soma das penalidades alta -> risco alto
    score_risco = 100 - pontos
    score_risco = max(0, min(100, score_risco // 2))

    return {
        "score_qualidade": pontos,
        "score_risco":     score_risco,
        "detalhes":        detalhes,
    }


# ─── Auto-Copydesk para monitor (publicacao direta) ─────────────────────────

def run_autopub_copydesk(
    article: dict,
    source: str = "",
    essential_facts: Optional[dict] = None,
    coverage: Optional[dict] = None,
) -> dict:
    """
    Copydesk automatico antes de publicacao direta (monitor 24h).

    Aplica correcoes seguras (campos ausentes preenchidos com defaults
    razoaveis) e detecta problemas residuais. NAO chama IA - precisa
    funcionar em modo standalone, sem latencia adicional.

    Retorna dict:
      {
        "passou": bool,
        "alteracoes": [list de mudancas],
        "problemas_residuais": [list de erros que nao podem ser auto-corrigidos],
        "article": <dict com correcoes aplicadas>,
      }
    """
    try:
        from ururau.editorial.safe_title import (
            safe_title, safe_truncate,
            LIMITE_TITULO_SEO, LIMITE_TITULO_CAPA,
        )
    except ImportError:
        safe_title = lambda t, l: (t or "")[:l]
        safe_truncate = lambda t, l: (t or "")[:l]
        LIMITE_TITULO_SEO = 89
        LIMITE_TITULO_CAPA = 60

    art = dict(article)
    alteracoes: list[str] = []
    residuais: list[dict] = []

    # 1. titulo_seo: aplica safe_title se exceder limite
    titulo = art.get("titulo_seo") or art.get("titulo") or ""
    if titulo and len(titulo) > LIMITE_TITULO_SEO:
        novo = safe_title(titulo, LIMITE_TITULO_SEO)
        art["titulo_seo"] = novo
        art["titulo"]     = novo
        alteracoes.append(f"titulo_seo cortado de {len(titulo)} para {len(novo)} chars")

    # 2. titulo_capa: idem
    capa = art.get("titulo_capa") or ""
    if not capa and titulo:
        capa = safe_title(titulo, LIMITE_TITULO_CAPA)
        art["titulo_capa"] = capa
        alteracoes.append("titulo_capa derivado do titulo_seo")
    elif capa and len(capa) > LIMITE_TITULO_CAPA:
        novo = safe_title(capa, LIMITE_TITULO_CAPA)
        art["titulo_capa"] = novo
        alteracoes.append(f"titulo_capa cortado de {len(capa)} para {len(novo)} chars")

    # 3. retranca: trim para 3 palavras
    ret = art.get("retranca") or ""
    palavras_ret = ret.split()
    if len(palavras_ret) > 3:
        art["retranca"] = " ".join(palavras_ret[:3])
        alteracoes.append("retranca cortada para 3 palavras")

    # 4. legenda_curta: default
    if not art.get("legenda_curta") and not art.get("legenda"):
        art["legenda_curta"] = "Reproducao"
        alteracoes.append("legenda_curta default 'Reproducao'")

    # 5. nome_da_fonte: default
    if not art.get("nome_da_fonte"):
        art["nome_da_fonte"] = "Redacao"
        alteracoes.append("nome_da_fonte default 'Redacao'")

    # 6. creditos_da_foto: default
    if not art.get("creditos_da_foto"):
        art["creditos_da_foto"] = "Reproducao"
        alteracoes.append("creditos_da_foto default 'Reproducao'")

    # 7. tags: trim para 8 se excessivo
    tags_raw = art.get("tags") or ""
    if isinstance(tags_raw, str):
        tags_lista = [t.strip() for t in tags_raw.split(",") if t.strip()]
    else:
        tags_lista = list(tags_raw or [])
    if len(tags_lista) > 12:
        art["tags"] = ", ".join(tags_lista[:8])
        alteracoes.append(f"tags reduzidas de {len(tags_lista)} para 8")

    # 8. meta_description: usa subtitulo se ausente
    if not art.get("meta_description"):
        sub = art.get("subtitulo_curto") or art.get("subtitulo") or ""
        if sub:
            art["meta_description"] = safe_truncate(sub, 160)
            alteracoes.append("meta_description derivada do subtitulo")

    # ── Detecta problemas residuais que NAO podem ser auto-corrigidos ────
    corpo = art.get("corpo_materia") or art.get("conteudo") or ""
    if not corpo:
        residuais.append({
            "categoria": "EDITORIAL_BLOCKER",
            "codigo": "corpo_ausente",
            "mensagem": "Corpo da materia ausente",
        })

    # Cobertura baixa
    if coverage and coverage.get("coverage_score", 1.0) < 0.90:
        residuais.append({
            "categoria": "EDITORIAL_BLOCKER",
            "codigo": "low_source_coverage_monitor",
            "mensagem": (f"Coverage baixa para publicacao direta: "
                          f"{coverage['coverage_score']:.2f} < 0.90"),
        })

    # Travessao no corpo
    if "—" in corpo or "–" in corpo:
        residuais.append({
            "categoria": "FIXABLE_FIELD",
            "codigo": "travessao_no_corpo",
            "mensagem": "Corpo contem travessao",
        })

    # Expressoes proibidas
    corpo_n = _norm(corpo)
    EXPR = ("vale lembrar", "e importante destacar", "cabe ressaltar")
    for expr in EXPR:
        if expr in corpo_n:
            residuais.append({
                "categoria": "FIXABLE_FIELD",
                "codigo": "expressao_proibida",
                "mensagem": f"Corpo contem expressao proibida: '{expr}'",
            })

    bloqueadores = [r for r in residuais if r.get("categoria") == "EDITORIAL_BLOCKER"]
    passou = len(bloqueadores) == 0

    return {
        "passou":              passou,
        "alteracoes":          alteracoes,
        "problemas_residuais": residuais,
        "bloqueadores":        bloqueadores,
        "article":             art,
    }


# ─── Safe can_publish (fail-closed para monitor) ────────────────────────────

def safe_can_publish(article: dict, modo: str = "panel") -> tuple[bool, str]:
    """
    Wrapper de can_publish() que FAIL-CLOSED quando exception ocorre.

    modo='panel'  : exception loga aviso mas NAO bloqueia (comportamento atual)
    modo='monitor': exception RETORNA False (bloqueia publicacao direta)
    modo='direct' : alias para 'monitor'
    """
    try:
        from ururau.publisher.workflow import can_publish
        return can_publish(article)
    except Exception as e:
        msg = f"Excecao em can_publish: {type(e).__name__}: {e}"
        if modo in ("monitor", "direct"):
            # FAIL-CLOSED: bloqueia publicacao direta se gate nao puder ser avaliado
            return False, msg + " (modo monitor: bloqueado por seguranca)"
        else:
            # FAIL-OPEN para painel: loga mas deixa editor decidir
            print(f"[QUALITY_GATES] {msg} (modo painel: prosseguindo)")
            return True, ""


def monitor_autopub_check(
    article: dict,
    essential_facts: Optional[dict] = None,
    score_qualidade_min: int = 92,
    coverage_min: float = 0.90,
    score_risco_max: int = 10,
) -> tuple[bool, list[str]]:
    """
    Gate completo para publicacao DIRETA do monitor 24h.

    Mais rigoroso que o gate do painel:
      - score_qualidade >= 92
      - coverage_score  >= 0.90
      - score_risco     <= 10
      - safe_can_publish OK (fail-closed)
      - sem CONFIG_ERROR / EXTRACTION_ERROR / EDITORIAL_BLOCKER
      - corpo presente
      - titulos validos
      - autopub copydesk passou

    Retorna (pode_publicar: bool, motivos_bloqueio: list[str]).
    """
    motivos: list[str] = []

    # 1. can_publish (fail-closed)
    pode, motivo = safe_can_publish(article, modo="monitor")
    if not pode:
        motivos.append(f"can_publish: {motivo}")
        return False, motivos

    # 2. Coverage
    coverage = calculate_fact_coverage(article, essential_facts or {})
    if coverage["coverage_score"] < coverage_min:
        motivos.append(
            f"coverage_score {coverage['coverage_score']:.2f} < {coverage_min}"
        )

    # 3. Quality score
    erros = article.get("erros_validacao") or []
    qual = calculate_quality_score(article, essential_facts, erros, coverage)
    if qual["score_qualidade"] < score_qualidade_min:
        motivos.append(
            f"score_qualidade {qual['score_qualidade']} < {score_qualidade_min}"
        )
    if qual["score_risco"] > score_risco_max:
        motivos.append(
            f"score_risco {qual['score_risco']} > {score_risco_max}"
        )

    # 4. Auto-copydesk
    autopub = run_autopub_copydesk(
        article, "", essential_facts, coverage
    )
    if not autopub["passou"]:
        for b in autopub["bloqueadores"]:
            motivos.append(f"autopub_copydesk: {b.get('mensagem','')}")

    return (len(motivos) == 0), motivos
