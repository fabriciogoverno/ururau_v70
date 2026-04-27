"""
editorial/safe_title.py — Módulo único de truncagem segura de títulos (v62).

Substitui qualquer slicing bruto do tipo `titulo_seo[:89]` ou `titulo_capa[:60]`.

Garante que:
  - Nenhum título termine em palavra cortada.
  - Nenhum título ultrapasse o limite oficial.
  - O texto resultante seja legível e não termine em hífen ou pontuação solta.
  - Use o máximo possível do limite quando o título original é muito grande.

Uso:
    from ururau.editorial.safe_title import safe_title, LIMITE_TITULO_SEO, LIMITE_TITULO_CAPA
    titulo_seo  = safe_title(texto_bruto, LIMITE_TITULO_SEO)
    titulo_capa = safe_title(texto_bruto, LIMITE_TITULO_CAPA)
"""
from __future__ import annotations

import re

LIMITE_TITULO_SEO   = 89   # caracteres com espaços (Ururau)
LIMITE_TITULO_CAPA  = 60   # caracteres com espaços (Ururau)
LIMITE_SUBTITULO    = 200
LIMITE_LEGENDA      = 100
LIMITE_META         = 160

# Caracteres que, se ficarem na ponta, indicam título mal cortado
_PONTUACAO_INDESEJADA_NO_FIM = (
    " ", ",", ";", ":", "-", "—", "–", "(", "[", "{", "/", "\\", "&", "+", "|"
)

# Palavras curtas finais que tornam o título incompleto se aparecerem isoladas
_PALAVRAS_FUNCIONAIS_FRACAS_NO_FIM = {
    "a", "o", "as", "os", "um", "uma", "uns", "umas",
    "e", "ou", "mas", "se", "que", "de", "da", "do", "das", "dos",
    "em", "na", "no", "nas", "nos", "por", "para", "com", "sem", "sob",
    "ao", "à", "aos", "às", "como", "quando", "onde", "porque", "porém",
    "também", "tambem",
}


def _strip_pontuacao_final(texto: str) -> str:
    """Remove pontuação solta no fim e espaços."""
    while texto and texto[-1] in _PONTUACAO_INDESEJADA_NO_FIM:
        texto = texto[:-1]
    return texto.rstrip()


def _termina_em_palavra_fraca(texto: str) -> bool:
    """Detecta se o título termina em conector / artigo / preposição."""
    palavras = texto.rsplit(" ", 1)
    if len(palavras) < 2:
        return False
    ultima = palavras[-1].lower().strip(".,;:!?")
    return ultima in _PALAVRAS_FUNCIONAIS_FRACAS_NO_FIM


def safe_title(texto: str, limite: int) -> str:
    """
    Trunca um título de forma SEGURA, sem cortar palavras no meio.

    Regras:
      1. Se o texto cabe no limite, retorna sem mudança.
      2. Encontra o último espaço antes do limite.
      3. Retira a última palavra incompleta.
      4. Remove pontuação solta no fim (vírgula, hífen, dois pontos).
      5. Remove conectores fracos finais (de, do, da, em, para, com, ao, à...).
      6. Garante que o resultado não fique vazio nem absurdamente curto.
      7. Nunca devolve string maior que o limite.

    Args:
        texto:   título bruto (pode ter qualquer tamanho).
        limite:  caracteres máximos permitidos (ex.: 89 para SEO, 60 para capa).

    Returns:
        Título com no máximo `limite` caracteres, sem palavra cortada.
    """
    if not texto:
        return ""
    texto = str(texto).strip()
    if len(texto) <= limite:
        return texto

    # Tentativa 1: cortar no último espaço antes do limite
    truncado = texto[:limite]
    ultimo_espaco = truncado.rfind(" ")
    if ultimo_espaco > 0:
        truncado = truncado[:ultimo_espaco]
    truncado = _strip_pontuacao_final(truncado)

    # Se acabou em conector fraco, remove ele também
    if _termina_em_palavra_fraca(truncado):
        # remove a última palavra fraca
        partes = truncado.rsplit(" ", 1)
        if len(partes) > 1:
            truncado = _strip_pontuacao_final(partes[0])

    # Resultado curto demais (< 10 chars): tenta uma versão um pouco mais
    # tolerante (corte simples + strip pontuação). Mantém a integridade da palavra.
    if len(truncado) < 10:
        truncado = texto[:limite]
        ultimo_espaco = truncado.rfind(" ")
        if ultimo_espaco > 0:
            truncado = truncado[:ultimo_espaco]
        truncado = _strip_pontuacao_final(truncado)

    # Garantia final: nunca exceder limite, mesmo após manipulações
    if len(truncado) > limite:
        truncado = truncado[:limite]
        truncado = _strip_pontuacao_final(truncado)

    return truncado


def safe_truncate(texto: str, limite: int) -> str:
    """
    Truncagem segura genérica para qualquer texto curto (subtítulo, legenda,
    meta-description). Igual a safe_title, mas sem checagem de palavra fraca
    no fim (para textos curtos com terminação natural).
    """
    if not texto:
        return ""
    texto = str(texto).strip()
    if len(texto) <= limite:
        return texto

    truncado = texto[:limite]
    ultimo_espaco = truncado.rfind(" ")
    if ultimo_espaco > 0:
        truncado = truncado[:ultimo_espaco]
    truncado = _strip_pontuacao_final(truncado)

    if len(truncado) < 10:
        truncado = _strip_pontuacao_final(texto[:limite])

    if len(truncado) > limite:
        truncado = _strip_pontuacao_final(truncado[:limite])

    return truncado


def validar_limites_titulos(dados: dict) -> list[dict]:
    """
    Valida que os títulos no dict respeitam os limites do Ururau.
    Retorna lista de erros (FIXABLE_FIELD) se houver violação.

    Útil para chamar após geração e antes de publicação.
    """
    erros: list[dict] = []
    titulo_seo  = str(dados.get("titulo_seo")  or dados.get("titulo")  or "")
    titulo_capa = str(dados.get("titulo_capa") or "")

    if titulo_seo and len(titulo_seo) > LIMITE_TITULO_SEO:
        erros.append({
            "codigo": "titulo_seo_excedeu_limite",
            "categoria": "FIXABLE_FIELD",
            "severidade": "alta",
            "campo": "titulo_seo",
            "mensagem": f"titulo_seo tem {len(titulo_seo)} chars (limite: {LIMITE_TITULO_SEO}).",
            "trecho": titulo_seo[:120],
            "sugestao": "Use safe_title(texto, 89) para reescrever sem cortar palavra.",
            "bloqueia_publicacao": True,
            "corrigivel_automaticamente": True,
        })
    if titulo_capa and len(titulo_capa) > LIMITE_TITULO_CAPA:
        erros.append({
            "codigo": "titulo_capa_excedeu_limite",
            "categoria": "FIXABLE_FIELD",
            "severidade": "alta",
            "campo": "titulo_capa",
            "mensagem": f"titulo_capa tem {len(titulo_capa)} chars (limite: {LIMITE_TITULO_CAPA}).",
            "trecho": titulo_capa[:120],
            "sugestao": "Use safe_title(texto, 60) para reescrever sem cortar palavra.",
            "bloqueia_publicacao": True,
            "corrigivel_automaticamente": True,
        })

    # Detecta título que termina em palavra cortada (sem espaço final, fim
    # bruto sem pontuação adequada, parece corte mecânico)
    for campo, lim in (("titulo_seo", LIMITE_TITULO_SEO),
                        ("titulo_capa", LIMITE_TITULO_CAPA)):
        val = str(dados.get(campo) or "")
        if not val:
            continue
        if _termina_em_palavra_fraca(val):
            erros.append({
                "codigo": f"{campo}_termina_em_palavra_fraca",
                "categoria": "FIXABLE_FIELD",
                "severidade": "media",
                "campo": campo,
                "mensagem": f"{campo} termina em conector fraco: '{val[-15:]}'",
                "trecho": val,
                "sugestao": f"Reescreva ou aplique safe_title(text, {lim}).",
                "bloqueia_publicacao": False,
                "corrigivel_automaticamente": True,
            })

    return erros
