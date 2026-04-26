"""
editorial/copydesk.py — Copydesk automático profissional.
Revisão pós-geração de texto: fluidez, consistência, termos de IA,
tom, atribuição, incoerências, adjetivos, ritmo jornalístico.
"""
from __future__ import annotations
import re
import json
from typing import TYPE_CHECKING

from ururau.config.house_style import detectar_termos_ia, BRIEFING_EDITORIAL

if TYPE_CHECKING:
    from openai import OpenAI


# ── Limpeza local (sem IA) ─────────────────────────────────────────────────────

_FECHOS_ARTIFICIAIS = [
    r"[Aa]compan[nh]e (?:o|a|as|os|mais) (?:notícia|cobertura|informaç)",
    r"[Ss]iga (?:o|a|as|os) (?:Ururau|portal|site)",
    r"[Ff]ique (?:por dentro|ligado|atento)",
    r"[Cc]ontinue (?:acompanhando|seguindo)",
    r"[Nn]ão (?:perca|deixe de)",
    r"[Ee]m breve[,\s]+(?:mais|novas) informaç",
    r"(?:Mais|Novas) informações em breve\.",
    r"[Aa] (?:redação|reportagem) (?:segue|continua|acompanha)",
    r"[Ee]sta (?:reportagem|matéria|redação) (?:será|foi) (?:atualizada|complementada)",
    r"[Dd]etalhes (?:a seguir|em breve|nas próximas horas)",
    r"(?:Em conclusão|Por fim|Portanto)[,\.\s]",
    r"[Ee]m suma[,\s]",
    r"[Pp]or tudo isso[,\s]",
    r"[Dd]iante do exposto[,\s]",
    r"[Ff]ica evidente que",
    r"[Rr]esta claro que",
    r"[Aa] lição que fica",
    r"[Oo] recado está dado",
]

_VICIOS_LEXICO = {
    " — ":        " - ",   # travessão → hífen (política da casa)
    " – ":        " - ",
    "Expresso Rio": "",
    "Ururau":     "",
}


def limpar_local(texto: str) -> str:
    """Limpeza determinística sem IA: fechos, vícios, normalização."""
    for padrao in _FECHOS_ARTIFICIAIS:
        # Remove a frase inteira até o fim do parágrafo
        texto = re.sub(padrao + r"[^\n]*", "", texto)

    for antigo, novo in _VICIOS_LEXICO.items():
        texto = texto.replace(antigo, novo)

    texto = re.sub(r"\n{3,}", "\n\n", texto)
    texto = re.sub(r" {2,}", " ", texto)
    return texto.strip()


def detectar_problemas(dados: dict) -> list[str]:
    """
    Detecta problemas sem chamar IA.
    Retorna lista de avisos para exibição no checklist da GUI.
    """
    problemas = []
    # Aceita tanto os nomes v45 quanto os aliases legados
    conteudo  = dados.get("conteudo") or dados.get("corpo_materia") or dados.get("texto_final") or ""
    titulo    = dados.get("titulo") or dados.get("titulo_seo") or ""
    capa      = dados.get("titulo_capa", "")
    meta      = dados.get("meta_description", "")
    tags      = dados.get("tags", "")
    subtitulo = dados.get("subtitulo_curto") or dados.get("subtitulo") or ""
    slug      = dados.get("slug", "")

    # Travessão
    if "—" in conteudo or "–" in conteudo:
        problemas.append("Travessão encontrado no corpo")

    # Ururau no corpo
    if "ururau" in conteudo.lower():
        problemas.append("'Ururau' mencionado no corpo")

    # Termos de IA
    termos = detectar_termos_ia(conteudo)
    if termos:
        problemas.append(f"Termos de IA detectados: {', '.join(termos[:4])}")

    # Tamanho título SEO
    if not (40 <= len(titulo) <= 89):
        problemas.append(f"Título SEO fora do intervalo 40-89 chars ({len(titulo)} chars)")

    # Tamanho título capa
    if capa and not (20 <= len(capa) <= 60):
        problemas.append(f"Título capa fora do intervalo 20-60 chars ({len(capa)} chars)")

    # Meta description
    if meta and not (120 <= len(meta) <= 160):
        problemas.append(f"Meta description fora do intervalo 120-160 chars ({len(meta)} chars)")

    # Slug
    if slug and " " in slug:
        problemas.append("Slug contém espaço")

    # Tags
    n_tags = len([t for t in tags.split(",") if t.strip()])
    if n_tags < 5:
        problemas.append(f"Poucas tags ({n_tags}, mínimo 5)")

    # Subtítulo
    if not subtitulo.strip():
        problemas.append("Subtítulo ausente")

    # Fecho artificial
    ultimos_300 = conteudo[-300:].lower()
    for padrao in _FECHOS_ARTIFICIAIS[:6]:
        if re.search(padrao, ultimos_300, re.IGNORECASE):
            problemas.append("Fecho artificial detectado no final do texto")
            break

    # Título repetido no lead
    primeiro_paragrafo = conteudo.split("\n\n")[0].lower() if conteudo else ""
    palavras_titulo = set(titulo.lower().split())
    palavras_lead   = set(primeiro_paragrafo.split())
    overlap = palavras_titulo & palavras_lead
    if len(overlap) > len(palavras_titulo) * 0.7 and len(palavras_titulo) > 4:
        problemas.append("Lead muito similar ao título SEO (redundância)")

    return problemas


def copydesk_ia(
    dados: dict,
    canal: str,
    mapa_evidencias: dict | None,
    client: "OpenAI",
    modelo: str,
) -> dict:
    """
    Copydesk profissional com IA.
    Revisão posterior à geração, focada em qualidade editorial real.
    """
    contexto_mapa = ""
    if mapa_evidencias:
        contexto_mapa = f"""
MAPA DE EVIDÊNCIAS (use para verificar consistência):
- Fato principal: {mapa_evidencias.get('fato_principal', '')}
- Quem: {', '.join(mapa_evidencias.get('quem', [])[:4])}
- Onde: {mapa_evidencias.get('onde', '')}
- Quando: {mapa_evidencias.get('quando', '')}
- Fonte primária: {mapa_evidencias.get('fonte_primaria', '')}
- Status atual: {mapa_evidencias.get('status_atual', '')}
"""

    prompt = f"""
Você é o copydesk de um portal jornalístico profissional brasileiro.
Revise a matéria abaixo e devolva APENAS JSON com os campos corrigidos.

{BRIEFING_EDITORIAL}

{contexto_mapa}

CANAL: {canal}

CHECKLIST DE REVISÃO OBRIGATÓRIA:
1. Elimine todos os termos e expressões de IA listados no briefing.
2. Verifique se o lead responde: o quê, quem, onde, quando.
3. Corrija frases genéricas por informação concreta.
4. Elimine redundâncias entre título, subtítulo e lead.
5. Corrija problemas de cronologia.
6. Verifique se afirmações importantes têm atribuição.
7. Elimine adjetivos decorativos sem base factual.
8. Corrija o fecho se for vazio, ornamental ou institucional.
9. Melhore fluidez e ritmo sem inventar informação.
10. Verifique se títulos são dentro do limite de caracteres.
11. Verifique incoerência entre título e corpo.
12. Elimine excesso de contexto que não acrescenta.
13. Nunca invente fatos novos.

MATÉRIA PARA REVISÃO (JSON):
{json.dumps({
    "titulo_seo": dados.get("titulo_seo") or dados.get("titulo", ""),
    "titulo_capa": dados.get("titulo_capa", ""),
    "subtitulo_curto": dados.get("subtitulo_curto") or dados.get("subtitulo", ""),
    "legenda_curta": dados.get("legenda_curta") or dados.get("legenda", ""),
    "retranca": dados.get("retranca", ""),
    "corpo_materia": dados.get("corpo_materia") or dados.get("conteudo") or dados.get("texto_final", ""),
    "meta_description": dados.get("meta_description", ""),
    "tags": dados.get("tags", ""),
    "resumo_curto": dados.get("resumo_curto", ""),
    "chamada_social": dados.get("chamada_social", ""),
}, ensure_ascii=False)}

Devolva o JSON completo com os campos corrigidos. Não adicione campos novos.
Não explique as alterações. Apenas devolva o JSON revisado.
"""

    try:
        resposta = client.responses.create(model=modelo, input=prompt)
        bruto = resposta.output_text.strip()
        if "```" in bruto:
            bruto = re.sub(r"```(?:json)?", "", bruto).strip()
        revisado = json.loads(bruto)

        # Aplica campos corrigidos, mantendo aliases sincronizados
        _mapa_aliases = {
            "titulo_seo":      ["titulo"],
            "subtitulo_curto": ["subtitulo"],
            "legenda_curta":   ["legenda"],
            "corpo_materia":   ["conteudo", "texto_final"],
        }
        campos_revisaveis = [
            "titulo_seo", "titulo_capa", "subtitulo_curto", "legenda_curta",
            "retranca", "corpo_materia", "meta_description", "tags",
            "resumo_curto", "chamada_social",
        ]
        for campo in campos_revisaveis:
            if campo in revisado and str(revisado[campo]).strip():
                dados[campo] = revisado[campo]
                # Sincroniza aliases legados
                for alias in _mapa_aliases.get(campo, []):
                    dados[alias] = revisado[campo]

        return dados
    except Exception as e:
        print(f"[COPYDESK] Falha no copydesk IA: {e}")
        return dados


def pipeline_copydesk(
    dados: dict,
    canal: str,
    mapa_evidencias: dict | None,
    client: "OpenAI",
    modelo: str,
) -> tuple[dict, list[str]]:
    """
    Pipeline completo de copydesk:
    1. Limpeza local determinística
    2. Detecção de problemas
    3. Copydesk IA
    4. Segunda limpeza local
    5. Detecção final de problemas residuais

    Retorna (dados_revisados, lista_de_problemas_residuais).
    """
    # Etapa 1: limpeza local — normaliza todos os aliases do corpo
    _corpo = dados.get("corpo_materia") or dados.get("conteudo") or dados.get("texto_final", "")
    _corpo_limpo = limpar_local(_corpo)
    dados["corpo_materia"] = _corpo_limpo
    dados["conteudo"]      = _corpo_limpo
    dados["texto_final"]   = _corpo_limpo

    # Etapa 2: problemas antes da IA
    problemas_antes = detectar_problemas(dados)

    # Etapa 3: copydesk IA
    dados = copydesk_ia(dados, canal, mapa_evidencias, client, modelo)

    # Etapa 4: limpeza local novamente (após copydesk IA)
    _corpo2 = dados.get("corpo_materia") or dados.get("conteudo") or dados.get("texto_final", "")
    _corpo2_limpo = limpar_local(_corpo2)
    dados["corpo_materia"] = _corpo2_limpo
    dados["conteudo"]      = _corpo2_limpo
    dados["texto_final"]   = _corpo2_limpo

    # Etapa 5: problemas residuais
    problemas_finais = detectar_problemas(dados)

    # Registra termos detectados nos dados
    dados["termos_ia_detectados"] = detectar_termos_ia(dados.get("conteudo", ""))

    return dados, problemas_finais
