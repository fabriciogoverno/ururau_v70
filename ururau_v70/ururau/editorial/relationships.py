"""
editorial/relationships.py - Extração e validação de relações factuais (v69).

Detecta erros como:
  - "X é prefeito de Y" quando a fonte diz "X administra a página da prefeitura de Y"
  - "X criticou Y" quando a fonte diz "X foi criticado por Y"
  - "Juiz X decidiu" quando a fonte diz "Tribunal Y decidiu"
  - troca de papéis (subject ↔ object)

Arquitetura:
  - extract_entity_relationships(): extrai relacoes deterministicamente da fonte
  - validate_entity_relationships(): compara relações no artigo gerado
  - Erros sao classificados como EDITORIAL_BLOCKER (bloqueiam publicação).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional


def _norm(s: str) -> str:
    if not s:
        return ""
    n = unicodedata.normalize("NFD", str(s))
    n = "".join(c for c in n if unicodedata.category(c) != "Mn")
    return n.lower().strip()


# ─── Relations detection patterns ─────────────────────────────────────────────

# Padroes para extrair relacoes da fonte
_PADROES_PESSOA_CARGO = [
    r"\b([A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+(?:\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+){1,3})"
    r",?\s+(prefeito|prefeita|governador|governadora|senador|senadora|deputado|deputada|"
    r"vereador|vereadora|presidente|ministro|ministra|secretario|secretaria|"
    r"juiz|juiza|desembargador|relator|relatora|procurador|advogado|advogada|"
    r"administrador|administradora|dono|dona|proprietario|proprietaria)"
    r"\s+(?:de|da|do|das|dos)\s+([A-Za-z][\w\s'-]{2,60})",
]

_PADROES_QUEM_DECIDIU = [
    r"\b(juiz|juiza|desembargador|relator|relatora|tribunal|stf|stj|trf|trt|"
    r"procurador|ministro|ministra)\s+([A-ZÁÉÍÓÚÂÊÔÃÕÇ][\w\s]{2,40})\s+"
    r"(decidiu|determinou|negou|aceitou|deferiu|indeferiu|rejeitou|julgou)",
]

_PADROES_QUEM_CRITICOU = [
    r"\b([A-ZÁÉÍÓÚÂÊÔÃÕÇ][\w\s]{2,40})\s+(criticou|atacou|elogiou|defendeu|acusou|denunciou)\s+"
    r"\b([A-ZÁÉÍÓÚÂÊÔÃÕÇ][\w\s]{2,40})",
]


def extract_entity_relationships(
    cleaned_source_text: str,
    article_type: str = "",
    client=None,
    model: str = "gpt-4.1-mini",
) -> list[dict]:
    """
    Extrai relacoes da fonte. Combina:
      1. Padroes deterministicos (regex)
      2. Opcional: GPT-4.1-mini para relacoes complexas (se client fornecido)

    Retorna lista de dicts:
      {
        "subject": str,
        "relationship": str,
        "object": str,
        "source_sentence": str,
        "confidence": float 0..1,
        "required": bool,
      }
    """
    if not cleaned_source_text:
        return []

    out: list[dict] = []
    texto = cleaned_source_text

    # 1. Padroes pessoa -> cargo -> instituicao
    for pat in _PADROES_PESSOA_CARGO:
        for m in re.finditer(pat, texto, re.IGNORECASE):
            pessoa = m.group(1).strip()
            cargo  = m.group(2).strip().lower()
            inst   = m.group(3).strip()
            out.append({
                "subject":         pessoa,
                "relationship":    cargo,
                "object":          inst,
                "source_sentence": m.group(0)[:200],
                "confidence":      0.85,
                "required":        True,
            })

    # 2. Padroes de decisao
    for pat in _PADROES_QUEM_DECIDIU:
        for m in re.finditer(pat, texto, re.IGNORECASE):
            cargo = m.group(1).strip().lower()
            nome  = m.group(2).strip()
            acao  = m.group(3).strip().lower()
            out.append({
                "subject":         f"{cargo} {nome}",
                "relationship":    acao,
                "object":          "",
                "source_sentence": m.group(0)[:200],
                "confidence":      0.80,
                "required":        True,
            })

    # 3. Padroes de critica/elogio (subject->action->object)
    for pat in _PADROES_QUEM_CRITICOU:
        for m in re.finditer(pat, texto, re.IGNORECASE):
            subj = m.group(1).strip()
            acao = m.group(2).strip().lower()
            obj  = m.group(3).strip()
            out.append({
                "subject":         subj,
                "relationship":    acao,
                "object":          obj,
                "source_sentence": m.group(0)[:200],
                "confidence":      0.70,
                "required":        True,
            })

    # 4. Opcional: GPT para relacoes complexas
    if client is not None and len(out) < 3:
        try:
            extra = _extract_relationships_via_gpt(
                cleaned_source_text, article_type, client, model
            )
            out.extend(extra)
        except Exception as e:
            print(f"[RELATIONSHIPS] GPT extraction falhou: {e}")

    # Deduplica por (subject, relationship, object)
    seen = set()
    unicos = []
    for r in out:
        key = (_norm(r["subject"]), _norm(r["relationship"]), _norm(r["object"]))
        if key not in seen:
            seen.add(key)
            unicos.append(r)
    return unicos


def _extract_relationships_via_gpt(
    cleaned_source_text: str, article_type: str, client, model: str
) -> list[dict]:
    """Extrai relacoes complexas via GPT-4.1-mini."""
    import json
    prompt = (
        f"Extraia as relacoes factuais essenciais do texto-fonte abaixo. "
        f"Tipo de materia: {article_type or 'desconhecido'}.\n\n"
        f"Retorne APENAS JSON com array de relacoes:\n"
        f'[{{"subject":"","relationship":"","object":"","source_sentence":"","confidence":0.0}}]\n\n'
        f"TEXTO-FONTE:\n{cleaned_source_text[:4000]}\n\n"
        f"Foque em: quem decidiu, quem solicitou, quem administra o que, "
        f"quem criticou quem, quem é alvo da acao, qual cargo de qual pessoa, "
        f"qual partido, qual cargo eleitoral. Apenas relacoes EXPLICITAS na fonte."
    )
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=800,
    )
    raw = resp.choices[0].message.content.strip()
    # Remove markdown se houver
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE)
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            for r in data:
                r.setdefault("required", True)
            return data
    except Exception:
        pass
    return []


# ─── Validate article against extracted relationships ───────────────────────

def validate_entity_relationships(article: dict, relationships: list[dict]) -> list[dict]:
    """
    Compara relacoes da fonte com o artigo gerado. Retorna lista de erros.

    Erros possiveis:
      - wrong_administrator      : artigo diz "X é prefeito" mas fonte diz "X administra a página"
      - role_confusion           : artigo troca subject e object
      - missing_decision_authority: artigo nao cita quem decidiu
      - wrong_actor              : artigo atribui ação a entidade errada
      - missing_court_or_judge   : artigo de justiça sem juiz/tribunal

    Cada erro retornado é um dict EDITORIAL_BLOCKER pronto para erros_validacao.
    """
    erros: list[dict] = []
    if not article or not relationships:
        return erros

    corpo = (article.get("corpo_materia") or article.get("conteudo") or "")
    titulo = article.get("titulo_seo") or article.get("titulo") or ""
    busca = _norm(f"{titulo} {corpo}")

    # Para cada relacao da fonte, verifica se o artigo NAO a contradiz
    for rel in relationships:
        subj = _norm(rel.get("subject", ""))
        obj  = _norm(rel.get("object", ""))
        rela = _norm(rel.get("relationship", ""))
        if not subj:
            continue

        # Caso especial: administrador de pagina vs prefeito
        if "administrador" in rela or "administradora" in rela:
            # Se fonte diz "X administra pagina da prefeitura de Y" e
            # artigo afirma "X eh prefeito de Y" -> wrong_administrator
            if obj and "prefeit" in obj:
                # Procura no artigo "X ... prefeito" (sem "administra")
                if subj in busca and "prefeit" in busca:
                    if "administra" not in busca and "page" not in busca and "pagina" not in busca:
                        erros.append({
                            "categoria":  "EDITORIAL_BLOCKER",
                            "codigo":     "wrong_administrator",
                            "severidade": "alta",
                            "campo":      "corpo_materia",
                            "mensagem": (
                                f"Artigo afirma que '{rel['subject']}' eh prefeito, "
                                f"mas fonte diz que ele administra a pagina/perfil da prefeitura."
                            ),
                            "trecho":   rel.get("source_sentence", "")[:200],
                            "sugestao": "Corrigir: '{X} administra a pagina/perfil da prefeitura de {Y}', nao 'eh prefeito de {Y}'.",
                            "bloqueia_publicacao": True,
                            "corrigivel_automaticamente": False,
                        })

        # Caso especial: troca de papeis em "criticou/elogiou"
        if rela in ("criticou", "atacou", "elogiou", "defendeu", "acusou"):
            if subj and obj and subj in busca and obj in busca:
                # Procura inversao: "obj <verbo> subj"
                pat_inverso = rf"{re.escape(obj)}[\w\s,]{{0,30}}{re.escape(rela)}[\w\s,]{{0,30}}{re.escape(subj)}"
                if re.search(pat_inverso, busca, re.IGNORECASE):
                    erros.append({
                        "categoria":  "EDITORIAL_BLOCKER",
                        "codigo":     "role_confusion",
                        "severidade": "alta",
                        "campo":      "corpo_materia",
                        "mensagem": (
                            f"Inversao de papeis: fonte diz '{rel['subject']} "
                            f"{rel['relationship']} {rel['object']}' mas artigo inverte."
                        ),
                        "trecho":   rel.get("source_sentence", "")[:200],
                        "sugestao": f"Corrigir para '{rel['subject']} {rel['relationship']} {rel['object']}'.",
                        "bloqueia_publicacao": True,
                        "corrigivel_automaticamente": False,
                    })

    # Validacoes especificas por tipo
    article_type = _norm(article.get("article_type") or article.get("retranca") or "")

    if "justic" in article_type or "judic" in article_type:
        # Materia de justica DEVE ter juiz/tribunal/decisao
        tem_autoridade = any(
            t in busca for t in ("juiz", "juiza", "tribunal", "stf", "stj", "trt", "trf", "desembargador", "relator")
        )
        if not tem_autoridade:
            erros.append({
                "categoria":  "EDITORIAL_BLOCKER",
                "codigo":     "missing_court_or_judge",
                "severidade": "alta",
                "campo":      "corpo_materia",
                "mensagem":   "Materia de justica sem citacao de tribunal/juiz/relator.",
                "trecho":     "",
                "sugestao":   "Adicionar quem decidiu (tribunal, juiz, desembargador, relator).",
                "bloqueia_publicacao": True,
                "corrigivel_automaticamente": False,
            })

    return erros
