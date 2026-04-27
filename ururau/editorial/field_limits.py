"""
editorial/field_limits.py - Limites canônicos do Ururau (v69).

Source of truth para todos os limites de campos. Importar AQUI em
todos os módulos (safe_title, schemas, agente_editorial, redacao, copydesk,
form_filler, etc.). NUNCA harcoded em outros lugares.
"""
from __future__ import annotations

# Títulos
TITULO_SEO_MAX        = 89
TITULO_SEO_MIN        = 40
TITULO_CAPA_MAX       = 60
TITULO_CAPA_MIN       = 20

# Subtítulo / Legenda
SUBTITULO_CURTO_MAX   = 140
LEGENDA_CURTA_MAX     = 140

# Tags
TAGS_MIN              = 6
TAGS_MAX              = 8

# Meta description
META_DESCRIPTION_MIN  = 120
META_DESCRIPTION_MAX  = 160

# Retranca
RETRANCA_MAX_WORDS    = 3

# Corpo
CORPO_MIN_CHARS       = 500
CORPO_PARAGRAFOS_MIN  = 3

# Fonte
NOME_FONTE_MAX        = 80
CREDITOS_FOTO_MAX     = 60

# Validação
COVERAGE_PANEL_MIN    = 0.85
COVERAGE_MONITOR_MIN  = 0.90
SCORE_QUALIDADE_PANEL_MIN   = 90
SCORE_QUALIDADE_MONITOR_MIN = 92
SCORE_RISCO_MAX       = 10


# Objeto de conveniência para import único
class _Limites:
    """Container para acesso via field_limits.limites"""
    TITULO_SEO_MAX        = TITULO_SEO_MAX
    TITULO_SEO_MIN        = TITULO_SEO_MIN
    TITULO_CAPA_MAX       = TITULO_CAPA_MAX
    TITULO_CAPA_MIN       = TITULO_CAPA_MIN
    SUBTITULO_CURTO_MAX   = SUBTITULO_CURTO_MAX
    LEGENDA_CURTA_MAX     = LEGENDA_CURTA_MAX
    TAGS_MIN              = TAGS_MIN
    TAGS_MAX              = TAGS_MAX
    META_DESCRIPTION_MIN  = META_DESCRIPTION_MIN
    META_DESCRIPTION_MAX  = META_DESCRIPTION_MAX
    RETRANCA_MAX_PALAVRAS = RETRANCA_MAX_WORDS
    CORPO_MIN_CHARS       = CORPO_MIN_CHARS
    CORPO_PARAGRAFOS_MIN  = CORPO_PARAGRAFOS_MIN
    NOME_FONTE_MAX        = NOME_FONTE_MAX
    CREDITOS_FOTO_MAX     = CREDITOS_FOTO_MAX
    COVERAGE_PANEL_MIN    = COVERAGE_PANEL_MIN
    COVERAGE_MONITOR_MIN  = COVERAGE_MONITOR_MIN
    SCORE_QUALIDADE_PANEL_MIN   = SCORE_QUALIDADE_PANEL_MIN
    SCORE_QUALIDADE_MONITOR_MIN = SCORE_QUALIDADE_MONITOR_MIN
    SCORE_RISCO_MAX       = SCORE_RISCO_MAX


limites = _Limites()
