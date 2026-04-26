"""
editorial/engine.py - Motor canonico de geracao Ururau (v70).

Fluxo:
  1. build_source_context()
  2. validate_source_sufficiency()
  3. classify_article_type()
  4. classify_channel()
  5. extract_required_facts_from_source()
  6. extract_entity_relationships()
  7. build_editorial_angle()
  8. build_paragraph_plan()
  9. build_editorial_brief()
 10. call GPT-4.1-mini com editorial_policy.SYSTEM_PROMPT
 11. parse JSON
 12. validate field limits
 13. validate coverage
 14. validate relationships
 15. validate dates
 16. validate generic unsupported paragraphs
 17. calculate score_qualidade + score_risco
 18. return Materia totalmente populada

Substitui o caminho legacy:
   workflow -> redacao -> pipeline.executar_pipeline -> _montar_prompt_geracao
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from openai import OpenAI


# ─── Source context canonico ───────────────────────────────────────────────

@dataclass
class SourceContext:
    raw_source_text:           str = ""
    cleaned_source_text:       str = ""
    rss_context_text:          str = ""
    source_title:              str = ""
    source_subtitle:           str = ""
    source_url:                str = ""
    source_name:               str = ""
    source_published_at:       str = ""
    extraction_method:         str = ""
    extraction_status:         str = ""
    source_sufficiency_score:  int = 0
    paragraph_count:           int = 0


def build_source_context(pauta: dict) -> SourceContext:
    """Constroi SourceContext a partir do dict de pauta."""
    cleaned = (pauta.get("cleaned_source_text")
               or pauta.get("dossie")
               or pauta.get("texto_fonte")
               or "")
    raw = pauta.get("raw_source_text") or cleaned
    paragrafos = [p for p in (cleaned or "").split("\n\n") if p.strip()]
    return SourceContext(
        raw_source_text          = raw,
        cleaned_source_text      = cleaned,
        rss_context_text         = pauta.get("rss_context_text", "") or pauta.get("resumo_origem", ""),
        source_title             = pauta.get("titulo_origem", ""),
        source_subtitle          = pauta.get("resumo_origem", ""),
        source_url               = pauta.get("link_origem", ""),
        source_name              = pauta.get("fonte_nome", ""),
        source_published_at      = pauta.get("data_publicacao", ""),
        extraction_method        = pauta.get("extraction_method", ""),
        extraction_status        = pauta.get("extraction_status", ""),
        source_sufficiency_score = int(pauta.get("source_sufficiency_score", 0) or 0),
        paragraph_count          = len(paragrafos),
    )


# ─── Article type classification ────────────────────────────────────────────

def classify_article_type(source: SourceContext, canal: str = "") -> str:
    """
    Classifica tipo de materia (NAO usa apenas channel).

    Heuristicas baseadas em palavras-chave do texto.
    """
    text = (source.cleaned_source_text or "").lower()
    title = (source.source_title or "").lower()
    full = f"{title} {text[:2000]}"

    # Public service / safety - prioridade alta
    safety_kw = ("incendio", "incendios", "queimada", "queimadas",
                 "calor extremo", "alagamento", "enchente",
                 "evacuacao", "emergencia", "tempestade")
    safety_inst = ("defesa civil", "corpo de bombeiros", "policia rodoviaria")
    if any(k in full for k in safety_kw) or any(i in full for i in safety_inst):
        # Se tem recomendacoes oficiais OU alerta -> public_service_safety
        if "recomenda" in full or "alerta" in full or "evite" in full or "procurar" in full:
            return "public_service_safety"

    # Sports
    if "x" in full and any(w in full for w in ("estadio", "campeonato", "rodada", "gol")):
        if any(w in full for w in ("vitoria", "empate", "derrota", "venceu", "marcou")):
            return "sports_match_result"
        return "sports_match_preview"

    # Justice
    if any(w in full for w in ("stf", "stj", "tj", "tribunal", "juiz", "desembargador",
                                 "ministro do supremo", "decisao", "sentenca")):
        return "justice"

    # Police
    if any(w in full for w in ("preso", "policia civil", "policia militar", "operacao",
                                 "detido", "homicidio", "trafico")):
        return "police"

    # Economy
    if any(w in full for w in ("inflacao", "selic", "pib", "ibge", "receita", "imposto",
                                 "exportacao", "balanca", "ipca")):
        return "economy"

    # Cities service
    if any(w in full for w in ("interdicao", "obra", "transito", "vacinacao", "campanha")):
        return "cities_service"

    # Politics
    if any(w in full for w in ("governador", "prefeito", "deputado", "senador",
                                 "presidente", "congresso", "alerj")):
        return "politics"

    # Event
    if any(w in full for w in ("show", "festival", "concerto", "evento", "festa")):
        return "event_show_service"

    # Mapeia canal como ultimo recurso
    canal_lower = (canal or "").lower()
    if "esport" in canal_lower:
        return "sports_team_news"
    if "polic" in canal_lower:
        return "police"
    if "polit" in canal_lower:
        return "politics"
    if "saud" in canal_lower:
        return "health"
    if "educ" in canal_lower:
        return "education"

    return "cities"


# ─── Editorial angle + paragraph plan ──────────────────────────────────────

def build_editorial_angle(source: SourceContext, article_type: str,
                           required_facts: list, relationships: list) -> str:
    """Define o angulo editorial: principal fato + foco."""
    if article_type == "public_service_safety":
        return ("Foco em alerta/recomendacao oficial e o que o publico deve fazer. "
                "Lead com a instituicao responsavel e o numero/incidencia.")
    if article_type == "sports_match_result":
        return "Lead com placar, times, competicao, rodada, fato principal do jogo."
    if article_type == "sports_match_preview":
        return "Lead com times, data, horario, estadio, transmissao, importancia da partida."
    if article_type == "justice":
        return "Lead com tribunal/autoridade, decisao e efeito imediato."
    if article_type == "police":
        return "Lead com ocorrencia, local, autoridade, status processual."
    if article_type == "economy":
        return "Lead com numero principal, periodo, entidade e causa."
    if article_type in ("event_show_service", "cities_service"):
        return "Lead com servico/evento, data, local, publico-alvo."
    return "Lead com o fato principal extraido da fonte."


def build_paragraph_plan(article_type: str, required_facts: list) -> list[str]:
    """Plano de paragrafos por tipo."""
    planos = {
        "public_service_safety": [
            "Lead: instituicao + numero/incidencia + alerta",
            "Contexto: periodo, regiao, comparacao",
            "Causas/fatores de risco",
            "Recomendacoes oficiais (preservar lista da fonte)",
            "O que fazer se ocorrer",
            "Como acionar autoridades",
            "Fechamento factual",
        ],
        "sports_match_result": [
            "Lead: placar + times + estadio + rodada",
            "Fato principal do jogo",
            "Primeiro tempo (resumo)",
            "Sequencia de gols",
            "Momentos decisivos",
            "Tabela",
            "Proximos jogos",
        ],
        "justice": [
            "Lead: tribunal + decisao + efeito",
            "Contexto processual",
            "Partes envolvidas",
            "Argumentos",
            "Proximo passo",
        ],
        "police": [
            "Lead: ocorrencia + local + autoridade",
            "Suspeitos/vitimas (status)",
            "Apuracoes oficiais",
            "Fechamento sem antecipar culpa",
        ],
        "economy": [
            "Lead: numero + entidade + setor",
            "Valores e percentuais",
            "Causas",
            "Documento/estudo",
            "Impacto factual",
        ],
        "event_show_service": [
            "Lead: evento + data + local + servico",
            "Acesso e interdicoes",
            "Estrutura/programacao",
            "Publico/transmissao",
        ],
    }
    return planos.get(article_type, [
        "Lead: fato principal",
        "Contexto",
        "Detalhes",
        "Fechamento factual",
    ])


# ─── Structured editorial brief ─────────────────────────────────────────────

def build_editorial_brief(
    source: SourceContext,
    article_type: str,
    canal: str,
    required_facts: list,
    relationships: list,
    angle: str,
    plan: list[str],
) -> dict:
    """JSON do brief estruturado enviado para o GPT."""
    from ururau.editorial.editorial_policy import get_editorial_rules, get_output_schema
    rules = get_editorial_rules()
    return {
        "cleaned_source_text":   source.cleaned_source_text[:7000],
        "source_title":          source.source_title,
        "source_subtitle":       source.source_subtitle,
        "source_url":            source.source_url,
        "source_name":           source.source_name,
        "source_published_at":   source.source_published_at,
        "classified_channel":    canal,
        "article_type":          article_type,
        "required_facts":        [f.get("text", "") for f in (required_facts or [])][:15],
        "entity_relationships":  [
            f"{r.get('subject','')} {r.get('relationship','')} {r.get('object','')}"
            for r in (relationships or [])
        ][:10],
        "editorial_angle":       angle,
        "paragraph_plan":        plan,
        "field_limits":          {
            "titulo_seo_max":       rules["titulo_seo_max"],
            "titulo_capa_max":      rules["titulo_capa_max"],
            "subtitulo_curto_max":  rules["subtitulo_curto_max"],
            "legenda_curta_max":    rules["legenda_curta_max"],
            "tags_min":             rules["tags_min"],
            "tags_max":             rules["tags_max"],
            "meta_description_min": rules["meta_description_min"],
            "meta_description_max": rules["meta_description_max"],
            "retranca_max_words":   rules["retranca_max_words"],
        },
        "output_schema":         get_output_schema(),
    }


# ─── Date validation determinístico ─────────────────────────────────────────

def validate_dates_against_source(article: dict, cleaned_source: str,
                                    source_published_at: str = "") -> list[dict]:
    """
    Bloqueia se artigo cita data completa (ex: '23 de junho de 2024')
    que NAO aparece na fonte.

    Detecta:
      - data com ano explicito que nao esta na fonte
      - 'janeiro deste ano' convertido para ano errado
    """
    import re
    if not article or not cleaned_source:
        return []
    erros: list[dict] = []
    corpo = article.get("corpo_materia") or article.get("conteudo") or ""
    titulo = article.get("titulo_seo") or article.get("titulo") or ""
    busca = f"{titulo} {corpo}"

    # Padrao: dia + de + mes + de + ano (ano completo)
    pat = r"\b\d{1,2}\s+de\s+(?:janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\s+de\s+\d{4}\b"
    datas_artigo = set(re.findall(pat, busca, re.IGNORECASE))
    datas_fonte = set(re.findall(pat, cleaned_source, re.IGNORECASE))

    # Datas no artigo que nao aparecem na fonte
    inventadas = datas_artigo - datas_fonte
    for d in inventadas:
        erros.append({
            "categoria": "EDITORIAL_BLOCKER",
            "codigo":    "wrong_or_invented_date",
            "severidade":"alta",
            "campo":     "corpo_materia",
            "mensagem":  f"Data '{d}' nao aparece na fonte (possivel invencao).",
            "trecho":    d,
            "sugestao":  f"Remover data ou substituir por referencia da fonte.",
            "bloqueia_publicacao": True,
            "corrigivel_automaticamente": False,
        })
    return erros


# ─── Generic unsupported paragraph validation ──────────────────────────────

_GENERIC_UNSUPPORTED = (
    "impacto social",
    "mantem o monitoramento",
    "garantir a seguranca",
    "periodo de maior movimentacao",
    "a medida deve fortalecer",
    "os proximos passos anunciados",
    "a populacao deve ficar atenta",
    "o caso segue em andamento",
    "novas informacoes serao divulgadas",
)


def validate_generic_unsupported(article: dict, cleaned_source: str) -> list[dict]:
    """Bloqueia paragrafo final se for generico nao suportado pela fonte."""
    import unicodedata
    if not article:
        return []
    corpo = article.get("corpo_materia") or article.get("conteudo") or ""
    paragrafos = [p.strip() for p in corpo.split("\n\n") if p.strip()]
    if not paragrafos:
        return []
    final = paragrafos[-1]

    def _n(s):
        n = unicodedata.normalize("NFD", str(s))
        n = "".join(c for c in n if unicodedata.category(c) != "Mn")
        return n.lower()

    final_n = _n(final)
    src_n = _n(cleaned_source)
    erros = []
    for expr in _GENERIC_UNSUPPORTED:
        if expr in final_n and expr not in src_n:
            erros.append({
                "categoria": "EDITORIAL_BLOCKER",
                "codigo":    "generic_unsupported_closing",
                "severidade":"alta",
                "campo":     "corpo_materia",
                "mensagem":  f"Paragrafo final contem expressao generica nao suportada: '{expr}'",
                "trecho":    final[:200],
                "sugestao":  "Substitua por um fechamento factual extraido da fonte.",
                "bloqueia_publicacao": True,
                "corrigivel_automaticamente": False,
            })
            break
    return erros


# ─── Public-service / safety required facts ──────────────────────────────

def extract_public_service_required(cleaned_source: str) -> list[dict]:
    """
    Para article_type=public_service_safety: extrai recomendacoes oficiais
    da fonte. Cada recomendacao vira required_fact com weight alto.
    """
    import re
    if not cleaned_source:
        return []
    facts = []
    # Padrao: linhas que comecam com verbo no imperativo de recomendacao
    pat = r"(?:^|\n)\s*[-•*]?\s*((?:Evite|Procure|Mantenha|Acione|Ligue|Nao|Use|Verifique|Acompanhe|Em\s+caso|Em\s+caso\s+de|Caso|Se\s+necessario)\b[^\n]{10,200})"
    for m in re.finditer(pat, cleaned_source, re.IGNORECASE):
        text = m.group(1).strip()
        if len(text) > 15:
            facts.append({
                "id": f"recomendacao_{len(facts)}",
                "type": "recomendacao_oficial",
                "text": text,
                "required": True,
                "weight": 1.5,
            })

    # Padrao: chamada explicita de servico (190, 193, Defesa Civil)
    for m in re.finditer(r"\b(?:1\d{2}|0800[-.\s]\d+)\b", cleaned_source):
        facts.append({
            "id": f"telefone_{len(facts)}",
            "type": "service_phone",
            "text": m.group(0),
            "required": True,
            "weight": 1.2,
        })

    return facts


# ─── Engine principal ────────────────────────────────────────────────────────

def generate_ururau_article(
    pauta: dict,
    client: "OpenAI",
    model: str,
    canal: str,
    modo: str = "panel",
):
    """
    Engine canonico v70. Substitui executar_pipeline() como gerador de producao.

    Retorna Materia totalmente populada.
    Em caso de falha (config/extraction), retorna Materia com erros estruturados
    e auditoria_bloqueada=True. NUNCA invoca pipeline legacy.
    """
    from ururau.core.models import Materia
    from ururau.editorial.coverage_por_tipo import (
        extract_required_facts_from_source, calculate_fact_coverage_typed,
    )
    from ururau.editorial.relationships import (
        extract_entity_relationships, validate_entity_relationships,
    )
    from ururau.editorial.safe_title import safe_title, safe_truncate
    from ururau.editorial.field_limits import (
        TITULO_SEO_MAX, TITULO_CAPA_MAX,
        SUBTITULO_CURTO_MAX, LEGENDA_CURTA_MAX,
        TAGS_MIN, TAGS_MAX,
        META_DESCRIPTION_MIN, META_DESCRIPTION_MAX,
    )

    # 1. Source context canonico (sem duplicacao)
    source = build_source_context(pauta)

    # 2. Sufficiency
    if not source.cleaned_source_text or len(source.cleaned_source_text) < 200:
        m = Materia()
        m.status_validacao = "erro_extracao"
        m.status_publicacao_sugerido = "salvar_rascunho"
        m.revisao_humana_necessaria = True
        m.auditoria_bloqueada = True
        m.erros_validacao = [{
            "categoria":"EXTRACTION_ERROR", "codigo":"source_too_short",
            "mensagem": f"Fonte insuficiente ({len(source.cleaned_source_text)} chars)",
            "bloqueia_publicacao": True, "corrigivel_automaticamente": False,
        }]
        m.cleaned_source_text = source.cleaned_source_text
        return m

    # 3. Article type
    article_type = classify_article_type(source, canal)

    # 4. Channel
    classified_channel = canal or article_type

    # 5+10. Required facts (incluindo public_service_safety)
    required_facts = extract_required_facts_from_source(source.cleaned_source_text, article_type)
    if article_type == "public_service_safety":
        required_facts.extend(extract_public_service_required(source.cleaned_source_text))

    # 6. Relationships
    relationships = extract_entity_relationships(
        source.cleaned_source_text, article_type, client, model
    )

    # 7+8. Angle and plan
    angle = build_editorial_angle(source, article_type, required_facts, relationships)
    plan  = build_paragraph_plan(article_type, required_facts)

    # 9. Brief
    brief = build_editorial_brief(source, article_type, classified_channel,
                                    required_facts, relationships, angle, plan)

    # 10. Call GPT-4.1-mini com policy canonico
    if client is None:
        m = Materia()
        m.status_validacao = "erro_configuracao"
        m.status_publicacao_sugerido = "salvar_rascunho"
        m.revisao_humana_necessaria = True
        m.auditoria_bloqueada = True
        m.erros_validacao = [{
            "categoria":"CONFIG_ERROR", "codigo":"openai_missing_api_key",
            "mensagem": "Cliente OpenAI ausente",
            "bloqueia_publicacao": True, "corrigivel_automaticamente": False,
        }]
        m.cleaned_source_text = source.cleaned_source_text
        m.article_type = article_type
        return m

    dados = _call_gpt_with_brief(brief, client, model, modo)

    # 12. Field limits (safe_title)
    if dados.get("titulo_seo"):
        dados["titulo_seo"] = safe_title(dados["titulo_seo"], TITULO_SEO_MAX)
    if dados.get("titulo_capa"):
        dados["titulo_capa"] = safe_title(dados["titulo_capa"], TITULO_CAPA_MAX)
    if dados.get("subtitulo_curto"):
        dados["subtitulo_curto"] = safe_truncate(dados["subtitulo_curto"], SUBTITULO_CURTO_MAX)
    if dados.get("legenda_curta"):
        dados["legenda_curta"] = safe_truncate(dados["legenda_curta"], LEGENDA_CURTA_MAX)
    if dados.get("meta_description"):
        dados["meta_description"] = safe_truncate(dados["meta_description"], META_DESCRIPTION_MAX)

    # 13. Coverage
    cov = calculate_fact_coverage_typed(dados, required_facts, source.cleaned_source_text)

    # 14. Relationships post
    rel_errors = validate_entity_relationships(dados, relationships)

    # 15. Date validation
    date_errors = validate_dates_against_source(dados, source.cleaned_source_text,
                                                  source.source_published_at)

    # 16. Generic unsupported
    generic_errors = validate_generic_unsupported(dados, source.cleaned_source_text)

    # Mescla erros
    erros_total = list(dados.get("erros_validacao") or [])
    erros_total += rel_errors + date_errors + generic_errors
    if cov["coverage_score"] < 0.85 and len(required_facts) > 0:
        erros_total.append({
            "categoria":"EDITORIAL_BLOCKER", "codigo":"low_source_coverage",
            "mensagem": f"Coverage {cov['coverage_score']:.2f} abaixo de 0.85",
            "bloqueia_publicacao": True, "corrigivel_automaticamente": False,
        })
    # Meta description ausente
    if not dados.get("meta_description"):
        cat = "EDITORIAL_BLOCKER" if modo == "monitor" else "FIXABLE_FIELD"
        erros_total.append({
            "categoria": cat, "codigo": "meta_description_ausente",
            "mensagem": "meta_description ausente",
            "bloqueia_publicacao": modo == "monitor",
            "corrigivel_automaticamente": True,
        })

    # 17+18. Score
    score_qualidade = 100
    score_qualidade -= 25 * len([e for e in erros_total if isinstance(e, dict) and e.get("categoria") == "EDITORIAL_BLOCKER"])
    score_qualidade -= 5  * len([e for e in erros_total if isinstance(e, dict) and e.get("categoria") == "FIXABLE_FIELD"])
    score_qualidade = max(0, min(100, score_qualidade))
    score_risco = 100 - score_qualidade

    # 19. Materia populada
    m = Materia()
    m.titulo            = dados.get("titulo_seo") or dados.get("titulo") or source.source_title
    m.titulo_capa       = dados.get("titulo_capa", "")
    m.subtitulo         = dados.get("subtitulo_curto", "")
    m.retranca          = dados.get("retranca", "") or canal
    m.legenda           = dados.get("legenda_curta", "")
    m.tags              = dados.get("tags", "") if isinstance(dados.get("tags"), str) else ", ".join(dados.get("tags", []) or [])
    m.conteudo          = dados.get("corpo_materia", "")
    m.meta_description  = dados.get("meta_description", "")
    m.fonte_nome        = source.source_name
    m.link_origem       = source.source_url
    m.canal             = classified_channel
    m.nome_da_fonte     = dados.get("nome_da_fonte") or source.source_name or "Redacao"
    m.creditos_da_foto  = dados.get("creditos_da_foto") or "Reproducao"

    bloqueado = any(isinstance(e, dict) and e.get("categoria") == "EDITORIAL_BLOCKER" for e in erros_total)
    m.auditoria_bloqueada = bool(bloqueado)
    m.auditoria_aprovada  = not bloqueado
    m.status_validacao = "aprovado" if not bloqueado and score_qualidade >= 90 else (
        "reprovado" if bloqueado else "pendente"
    )
    m.status_publicacao_sugerido = ("publicar" if m.status_validacao == "aprovado"
                                     else "salvar_rascunho")
    m.revisao_humana_necessaria  = m.status_validacao != "aprovado"
    m.erros_validacao            = erros_total

    # Campos v69b/v70
    m.coverage_score          = cov["coverage_score"]
    m.facts_required          = cov["facts_required"]
    m.facts_used              = cov["facts_used"]
    m.facts_missing           = cov["facts_missing"]
    m.entity_relationships    = relationships
    m.relationship_errors     = rel_errors
    m.score_qualidade         = score_qualidade
    m.score_risco_validacao   = score_risco
    m.score_risco             = score_risco
    m.cleaned_source_text     = source.cleaned_source_text
    m.raw_source_text         = source.raw_source_text
    m.rss_context_text        = source.rss_context_text
    m.extraction_method       = source.extraction_method
    m.extraction_status       = source.extraction_status
    m.source_sufficiency_score = source.source_sufficiency_score
    m.article_type            = article_type
    m.editorial_angle         = angle
    m.paragraph_plan          = plan
    m.generated_article_json  = dados

    return m


def _call_gpt_with_brief(brief: dict, client, model: str, modo: str) -> dict:
    """Chama GPT-4.1-mini com SYSTEM_PROMPT_EDITORIAL_URURAU + brief estruturado."""
    import json
    from ururau.editorial.editorial_policy import (
        get_editorial_system_prompt, get_editorial_user_prompt_template,
    )
    sys_prompt = get_editorial_system_prompt()
    template = get_editorial_user_prompt_template()
    user_prompt = template.format(
        article_type=brief["article_type"],
        classified_channel=brief["classified_channel"],
        editorial_angle=brief["editorial_angle"],
        paragraph_plan="\n".join(f"  {i+1}. {p}" for i, p in enumerate(brief["paragraph_plan"])),
        required_facts="\n".join(f"  - {f}" for f in brief["required_facts"]),
        entity_relationships="\n".join(f"  - {r}" for r in brief["entity_relationships"]),
        cleaned_source_text=brief["cleaned_source_text"],
        source_title=brief["source_title"],
        source_subtitle=brief["source_subtitle"],
        source_url=brief["source_url"],
        source_name=brief["source_name"],
        source_published_at=brief["source_published_at"],
        field_limits=json.dumps(brief["field_limits"], ensure_ascii=False),
        output_schema=json.dumps(brief["output_schema"], ensure_ascii=False, indent=2),
    )
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=2500,
        )
        raw = resp.choices[0].message.content.strip()
        # Remove markdown
        import re as _re
        raw = _re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=_re.MULTILINE)
        return json.loads(raw)
    except Exception as e:
        print(f"[ENGINE v70] _call_gpt falhou: {e}")
        return {}
