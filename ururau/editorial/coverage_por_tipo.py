"""
editorial/coverage_por_tipo.py - Coverage real por tipo de materia (v69).

Substitui o calculate_fact_coverage genérico do quality_gates por uma
versao que entende o que CADA tipo de materia DEVE conter.

Fluxo:
  1. extract_required_facts_from_source(cleaned_source, article_type)
     -> retorna lista de fatos OBRIGATÓRIOS por tipo
  2. calculate_fact_coverage_typed(article, required_facts)
     -> coverage_score baseado em fatos por tipo

Tipos suportados:
  - sports_match_result, sports_match_preview, sports_team_news
  - politics, justice, police, economy, labor, cities
  - event_show_service, public_policy_civil_society
  - institutional_note, official_statement
  - culture, health, education, technology
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional


def _norm(t: str) -> str:
    if not t:
        return ""
    s = unicodedata.normalize("NFD", str(t))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower().strip()


# ─── Padroes para extrair fatos por tipo ────────────────────────────────────

_PAT_NUMERO    = re.compile(r"\b(\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+)\b")
_PAT_PERCENT   = re.compile(r"\b(\d+(?:[,.]\d+)?)\s*%")
_PAT_VALOR_RS  = re.compile(r"R\$\s*\d[\d.,]*\s*(?:milhao|milhoes|bilhao|bilhoes|mil)?", re.IGNORECASE)
_PAT_PLACAR    = re.compile(r"\b\d+\s*[xX×]\s*\d+\b")
_PAT_DATA_REL  = re.compile(
    r"\b(?:nesta|nesse|na proxima|no proximo|no dia|domingo|"
    r"segunda|terca|quarta|quinta|sexta|sabado)[\w\s\(\)]*",
    re.IGNORECASE,
)
_PAT_DATA_ABS  = re.compile(r"\b\d{1,2}\s+de\s+(?:janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)(?:\s+de\s+\d{4})?", re.IGNORECASE)
_PAT_HORA      = re.compile(r"\b\d{1,2}h(?:\d{2})?\b")
_PAT_NOME_PROP = re.compile(r"\b[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+(?:\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+){1,3}\b")

_TIMES_FUTEBOL = {
    "flamengo", "fluminense", "vasco", "botafogo", "palmeiras", "corinthians", "santos",
    "sao paulo", "gremio", "internacional", "cruzeiro", "atletico mineiro", "atletico-mg",
    "athletico paranaense", "athletico-pr", "bahia", "vitoria", "ceara", "fortaleza",
    "bragantino", "red bull bragantino", "juventude", "criciuma", "cuiaba", "goias",
    "america-mg", "america mineiro", "guarani", "ponte preta", "chapecoense",
    "macae", "americano", "boavista", "portuguesa-rj",
}

_INSTITUICOES_JUSTICA = (
    "stf", "stj", "tj", "tjrj", "tjsp", "trf", "trt", "tre", "tse",
    "ministerio publico", "mpf", "mprj", "policia federal", "policia civil",
    "policia militar", "defensoria",
)

_CARGOS = (
    "prefeito", "prefeita", "governador", "governadora", "senador", "senadora",
    "deputado", "deputada", "vereador", "vereadora", "presidente",
    "ministro", "ministra", "secretario", "secretaria",
    "juiz", "juiza", "desembargador", "relator", "relatora",
    "promotor", "promotora", "procurador",
)


def _achar_times(texto: str) -> list[str]:
    n = _norm(texto)
    return [t for t in _TIMES_FUTEBOL if t in n]


def _achar_instituicoes(texto: str) -> list[str]:
    n = _norm(texto)
    return [i for i in _INSTITUICOES_JUSTICA if i in n]


def _achar_cargos_pessoas(texto: str) -> list[str]:
    """Encontra padroes 'Nome Sobrenome, cargo'."""
    out = []
    for m in re.finditer(
        r"([A-ZÁÉÍÓÚÂÊÔÃÕÇ][\w]+(?:\s[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\w]+){0,3})"
        r"\s*,?\s*(prefeit[oa]|governador[a]?|senador[a]?|deputad[oa]|vereador[a]?|"
        r"presidente|ministr[oa]|juiz[a]?|desembargador|relator[a]?|"
        r"procurador|advogad[oa]|empres[áa]rio|empres[áa]ria)",
        texto, re.IGNORECASE,
    ):
        out.append(f"{m.group(1)} ({m.group(2)})")
    return out


# ─── Extracao por tipo ──────────────────────────────────────────────────────

def extract_required_facts_from_source(
    cleaned_source_text: str,
    article_type: str = "",
) -> list[dict]:
    """
    Extrai fatos OBRIGATORIOS da fonte, por tipo de materia.

    Cada Fact tem:
      {
        "id":       str,           # identificador unico
        "type":     str,           # person|institution|date|number|score|...
        "text":     str,           # representação textual
        "required": bool,          # se eh obrigatório
        "weight":   float,         # peso na cobertura (0..1)
      }
    """
    if not cleaned_source_text:
        return []

    facts: list[dict] = []
    src = cleaned_source_text
    article_type = (article_type or "").lower()

    def _add(t, txt, req=True, w=1.0):
        facts.append({
            "id": f"{t}_{len(facts)}",
            "type": t, "text": str(txt).strip(),
            "required": req, "weight": w,
        })

    # Fatos universais (extraidos para todo tipo)
    for m in _PAT_VALOR_RS.findall(src):
        _add("number", m, req=True, w=1.0)
    for m in _PAT_PERCENT.findall(src):
        _add("number", f"{m}%", req=True, w=0.9)
    for m in _PAT_DATA_ABS.findall(src):
        _add("date", m, req=True, w=1.0)
    for m in _PAT_DATA_REL.findall(src):
        _add("date", m, req=True, w=0.7)
    for m in _PAT_HORA.findall(src):
        _add("time", m, req=False, w=0.5)

    # Cargos e pessoas
    for c in _achar_cargos_pessoas(src):
        _add("person", c, req=True, w=1.0)

    # Instituicoes
    for inst in set(_achar_instituicoes(src)):
        _add("institution", inst, req=True, w=1.0)

    # Por tipo
    if "sports_match_result" in article_type or "sports_result" in article_type:
        # Times
        times = list(set(_achar_times(src)))
        for t in times[:4]:
            _add("team", t, req=True, w=1.0)
        # Placar
        for p in _PAT_PLACAR.findall(src):
            _add("score", p, req=True, w=1.0)
        # Estadio (heuristica: palavra apos "no estadio")
        for m in re.finditer(r"no estadio\s+([A-Z][\w\s]{3,40})", src, re.IGNORECASE):
            _add("location", m.group(1).strip(), req=True, w=0.8)

    elif "sports_match_preview" in article_type:
        for t in list(set(_achar_times(src)))[:4]:
            _add("team", t, req=True, w=1.0)
        # Horario, transmissao
        for m in _PAT_HORA.findall(src):
            _add("time", m, req=True, w=0.9)

    elif "event" in article_type or "show" in article_type or "service" in article_type:
        # Local, data, horario, artista/evento
        for m in re.finditer(r"(?:no|na)\s+([A-Z][\w\s]{3,40})", src):
            _add("location", m.group(1).strip(), req=True, w=0.8)

    elif "justice" in article_type or "police" in article_type:
        # Tribunais, juiz, decisao
        for inst in _achar_instituicoes(src):
            _add("court", inst, req=True, w=1.0)

    elif "economy" in article_type or "labor" in article_type:
        # Numeros sao essenciais
        # Ja capturados acima
        pass

    # Deduplica por (type, _norm(text))
    seen = set()
    out = []
    for f in facts:
        k = (f["type"], _norm(f["text"]))
        if k in seen:
            continue
        seen.add(k)
        out.append(f)

    return out


# ─── Coverage tipado ────────────────────────────────────────────────────────

def calculate_fact_coverage_typed(
    article: dict,
    required_facts: list[dict],
    cleaned_source_text: str = "",
) -> dict:
    """
    Calcula coverage_score baseado em fatos OBRIGATÓRIOS por tipo.

    Diferenças vs calculate_fact_coverage genérico:
      - Considera weight
      - Considera type (numero/data exigem match exato; nome aceita match parcial)
      - Se source tem fatos mas required_facts esta vazio, NAO retorna 1.0
        (classifica como extraction/coverage failure)

    Retorna:
      {
        "coverage_score": float,
        "facts_required": list[dict],
        "facts_used":     list[dict],
        "facts_missing":  list[dict],
      }
    """
    if not article:
        return {"coverage_score": 0.0, "facts_required": [],
                "facts_used": [], "facts_missing": []}

    corpo  = article.get("corpo_materia") or article.get("conteudo") or ""
    titulo = article.get("titulo_seo") or article.get("titulo") or ""
    sub    = article.get("subtitulo_curto") or article.get("subtitulo") or ""
    busca  = _norm(f"{titulo} {sub} {corpo}")

    # Gate: source longa + required vazia = falha
    if not required_facts:
        if cleaned_source_text and len(cleaned_source_text) > 1000:
            return {
                "coverage_score": 0.0,
                "facts_required": [],
                "facts_used":     [],
                "facts_missing":  [{"id": "extraction_failed",
                                     "type": "meta", "text": "Source longa mas fatos requeridos vazios.",
                                     "required": True, "weight": 1.0}],
            }
        # Source curta sem fatos: 1.0
        return {"coverage_score": 1.0, "facts_required": [],
                "facts_used": [], "facts_missing": []}

    used: list[dict] = []
    missing: list[dict] = []
    total_weight = 0.0
    used_weight  = 0.0

    for f in required_facts:
        w = float(f.get("weight", 1.0))
        total_weight += w
        ftype = f.get("type", "")
        ftext = f.get("text", "")

        # Tipos que exigem match exato/quase-exato
        if ftype in ("number", "score", "percent"):
            if _norm(ftext) in busca:
                used.append(f); used_weight += w
            else:
                missing.append(f)
        elif ftype in ("date", "time"):
            if _norm(ftext) in busca:
                used.append(f); used_weight += w
            else:
                missing.append(f)
        else:
            # Match parcial: 60%+ das palavras "fortes"
            palavras = [w for w in _norm(ftext).split() if len(w) > 3]
            if not palavras:
                if _norm(ftext) in busca:
                    used.append(f); used_weight += w
                else:
                    missing.append(f)
            else:
                hits = sum(1 for w in palavras if w in busca)
                if hits / len(palavras) >= 0.6:
                    used.append(f); used_weight += w
                else:
                    missing.append(f)

    score = round(used_weight / total_weight, 4) if total_weight else 0.0

    return {
        "coverage_score": score,
        "facts_required": required_facts,
        "facts_used":     used,
        "facts_missing":  missing,
    }
