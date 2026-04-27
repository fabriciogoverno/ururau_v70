"""
editorial/editorial_policy.py - Source of truth UNICO da linha editorial Ururau (v70).

Re-exporta o SYSTEM_PROMPT_EDITORIAL_URURAU do agente canonico
e expoe funcoes de acesso a regras, schema e templates.

Toda chamada de IA em producao (geracao, copydesk, regenerate) deve
importar daqui:

    from ururau.editorial.editorial_policy import (
        get_editorial_system_prompt,
        get_editorial_user_prompt_template,
        get_editorial_rules,
        get_output_schema,
    )
"""
from __future__ import annotations

# Importa o prompt mestre do agente canonico (source of truth)
try:
    from ururau.agents.agente_editorial_ururau import SYSTEM_PROMPT_EDITORIAL_URURAU as _SYS
except Exception:
    _SYS = ""

# Limites canonicos
from ururau.editorial.field_limits import (
    TITULO_SEO_MAX, TITULO_CAPA_MAX,
    SUBTITULO_CURTO_MAX, LEGENDA_CURTA_MAX,
    TAGS_MIN, TAGS_MAX,
    META_DESCRIPTION_MIN, META_DESCRIPTION_MAX,
    RETRANCA_MAX_WORDS,
    COVERAGE_PANEL_MIN, COVERAGE_MONITOR_MIN,
    SCORE_QUALIDADE_PANEL_MIN, SCORE_QUALIDADE_MONITOR_MIN,
)


def get_editorial_system_prompt() -> str:
    """Retorna o system prompt mestre do Ururau."""
    return _SYS


def get_editorial_rules() -> dict:
    """Retorna o conjunto de regras editoriais (limites, palavras proibidas, etc.)."""
    return {
        "titulo_seo_max":        TITULO_SEO_MAX,
        "titulo_capa_max":       TITULO_CAPA_MAX,
        "subtitulo_curto_max":   SUBTITULO_CURTO_MAX,
        "legenda_curta_max":     LEGENDA_CURTA_MAX,
        "tags_min":              TAGS_MIN,
        "tags_max":              TAGS_MAX,
        "meta_description_min":  META_DESCRIPTION_MIN,
        "meta_description_max":  META_DESCRIPTION_MAX,
        "retranca_max_words":    RETRANCA_MAX_WORDS,
        "coverage_panel_min":    COVERAGE_PANEL_MIN,
        "coverage_monitor_min":  COVERAGE_MONITOR_MIN,
        "score_qualidade_panel_min":   SCORE_QUALIDADE_PANEL_MIN,
        "score_qualidade_monitor_min": SCORE_QUALIDADE_MONITOR_MIN,
        "expressoes_proibidas": [
            "vale lembrar", "e importante destacar", "cabe ressaltar",
            "em meio a", "cenario complexo", "nesse contexto",
            "novas informacoes serao divulgadas", "o caso segue em andamento",
            "a populacao deve ficar atenta", "mantem o monitoramento",
            "garantir a seguranca", "impacto social", "periodo de maior movimentacao",
            "a medida deve fortalecer", "os proximos passos anunciados",
        ],
    }


def get_output_schema() -> dict:
    """JSON schema completo do pacote editorial Ururau."""
    return {
        "titulo_seo":               "",
        "subtitulo_curto":          "",
        "retranca":                 "",
        "titulo_capa":              "",
        "tags":                     "",
        "legenda_curta":            "",
        "corpo_materia":            "",
        "legenda_instagram":        "",
        "meta_description":         "",
        "nome_da_fonte":            "",
        "link_da_fonte":            "",
        "creditos_da_foto":         "",
        "status_validacao":         "",
        "erros_validacao":          [],
        "observacoes_editoriais":   [],
    }


def get_editorial_user_prompt_template() -> str:
    """Template de user prompt usando structured editorial brief."""
    return (
        "TIPO DE MATERIA: {article_type}\n"
        "CANAL: {classified_channel}\n"
        "ANGULO EDITORIAL: {editorial_angle}\n"
        "PLANO DE PARAGRAFOS: {paragraph_plan}\n\n"
        "FATOS OBRIGATORIOS DA FONTE:\n{required_facts}\n\n"
        "RELACOES FACTUAIS (preservar subject->relationship->object):\n{entity_relationships}\n\n"
        "FONTE LIMPA (use APENAS estes fatos):\n{cleaned_source_text}\n\n"
        "TITULO ORIGINAL: {source_title}\n"
        "SUBTITULO ORIGINAL: {source_subtitle}\n"
        "URL: {source_url}\n"
        "FONTE: {source_name}\n"
        "PUBLICADA EM: {source_published_at}\n\n"
        "LIMITES OBRIGATORIOS: {field_limits}\n\n"
        "RETORNE JSON com este schema:\n{output_schema}\n"
    )
