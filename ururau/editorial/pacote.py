"""
editorial/pacote.py — Pacote editorial completo.
Gera títulos alternativos, chamada social e resumo curto a partir de uma matéria.
"""
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from ururau.core.models import Materia
from ururau.editorial.redacao import _truncar_titulo_seguro

if TYPE_CHECKING:
    from openai import OpenAI


def _extrair_lista_json(texto: str, chave: str = "titulos") -> list[str]:
    """Extrai lista de strings de resposta JSON da IA."""
    bruto = texto.strip()
    if "```" in bruto:
        bruto = re.sub(r"```(?:json)?", "", bruto).strip()
    try:
        dados = json.loads(bruto)
        if isinstance(dados, list):
            return [str(x) for x in dados if x]
        if isinstance(dados, dict):
            for key in (chave, "lista", "alternativas", "titulos", "result", "results"):
                if key in dados and isinstance(dados[key], list):
                    return [str(x) for x in dados[key] if x]
    except Exception:
        # Extração por linha como fallback
        linhas = [
            l.strip().lstrip("0123456789.-) ").strip('"').strip()
            for l in bruto.splitlines()
            if l.strip() and not l.strip().startswith("{") and not l.strip().startswith("[")
        ]
        return [l for l in linhas if l][:3]
    return []


def gerar_titulos_alternativos(
    dados: "dict | Materia",
    client: "OpenAI",
    modelo: str,
) -> list[str]:
    """
    Gera 3 títulos SEO alternativos para a matéria.
    Retorna lista de strings. Cada título deve ter entre 50-80 caracteres.
    """
    titulo_atual = dados.get("titulo") if isinstance(dados, dict) else dados.titulo
    conteudo = dados.get("conteudo", "") if isinstance(dados, dict) else dados.conteudo
    canal = dados.get("canal", "") if isinstance(dados, dict) else dados.canal

    prompt = f"""
Você é um editor de portal jornalístico.
Gere 3 títulos SEO alternativos para a matéria abaixo.

Regras:
- Cada título deve ter entre 55 e 90 caracteres (MÁXIMO 90, incluindo espaços).
- Cada título deve ser factual, direto e jornalístico.
- Varie a construção (não repita a mesma estrutura).
- Não use termos de IA, floreios, adjetivos decorativos.
- Não invente fatos ausentes no texto.
- Canal: {canal}

TÍTULO ATUAL:
{titulo_atual}

RESUMO DO CONTEÚDO:
{conteudo[:800]}

Devolva apenas JSON:
{{"titulos": ["título 1", "título 2", "título 3"]}}
"""
    try:
        resposta = client.responses.create(model=modelo, input=prompt)
        titulos = _extrair_lista_json(resposta.output_text, "titulos")
        return [_truncar_titulo_seguro(t, 90) for t in titulos[:3]]
    except Exception as e:
        print(f"[PACOTE] Falha ao gerar títulos alternativos: {e}")
        return []


def gerar_titulos_capa_alternativos(
    dados: "dict | Materia",
    client: "OpenAI",
    modelo: str,
) -> list[str]:
    """
    Gera 3 títulos de capa/home alternativos (25-55 chars).
    """
    titulo_atual = dados.get("titulo_capa") if isinstance(dados, dict) else dados.titulo_capa
    titulo_seo   = dados.get("titulo") if isinstance(dados, dict) else dados.titulo
    canal = dados.get("canal", "") if isinstance(dados, dict) else dados.canal

    prompt = f"""
Você é editor de portal. Gere 3 títulos de capa/home alternativos.

Regras:
- Cada título deve ter entre 30 e 60 caracteres (MÁXIMO 60, incluindo espaços).
- Tom impactante, factual, sem clickbait.
- Não use termos de IA.
- Canal: {canal}

TÍTULO SEO: {titulo_seo}
TÍTULO CAPA ATUAL: {titulo_atual}

Devolva apenas JSON:
{{"titulos": ["título capa 1", "título capa 2", "título capa 3"]}}
"""
    try:
        resposta = client.responses.create(model=modelo, input=prompt)
        titulos = _extrair_lista_json(resposta.output_text, "titulos")
        return [_truncar_titulo_seguro(t, 60) for t in titulos[:3]]
    except Exception as e:
        print(f"[PACOTE] Falha ao gerar títulos de capa alternativos: {e}")
        return []


def gerar_chamada_social(
    dados: "dict | Materia",
    client: "OpenAI",
    modelo: str,
) -> str:
    """
    Gera chamada para redes sociais (Twitter/WhatsApp).
    Máximo 240 caracteres. Tom informativo, com gancho factual.
    """
    titulo = dados.get("titulo") if isinstance(dados, dict) else dados.titulo
    resumo = dados.get("resumo_curto", "") if isinstance(dados, dict) else dados.resumo_curto
    canal  = dados.get("canal", "") if isinstance(dados, dict) else dados.canal

    prompt = f"""
Escreva uma chamada para Twitter e WhatsApp sobre esta notícia.

Regras:
- Máximo 240 caracteres (obrigatório).
- Tom informativo, com gancho factual no início.
- Sem emojis excessivos (no máximo 1, opcional).
- Não use linguagem de marketing ou clickbait.
- Não invente informações.
- Canal: {canal}

TÍTULO: {titulo}
RESUMO: {resumo}

Devolva apenas o texto da chamada, sem aspas, sem explicações.
"""
    try:
        resposta = client.responses.create(model=modelo, input=prompt)
        chamada = resposta.output_text.strip().strip('"').strip("'")
        return chamada[:240]
    except Exception as e:
        print(f"[PACOTE] Falha ao gerar chamada social: {e}")
        chamada_atual = dados.get("chamada_social", "") if isinstance(dados, dict) else dados.chamada_social
        return chamada_atual[:240] if chamada_atual else titulo[:240]


def gerar_resumo_curto(
    dados: "dict | Materia",
    client: "OpenAI",
    modelo: str,
) -> str:
    """
    Gera resumo curto para cards e listagens.
    Máximo 280 caracteres. Factual, sem abertura genérica.
    """
    titulo   = dados.get("titulo") if isinstance(dados, dict) else dados.titulo
    conteudo = dados.get("conteudo", "") if isinstance(dados, dict) else dados.conteudo

    prompt = f"""
Escreva um resumo curto desta matéria para usar em cards e listagens de portal.

Regras:
- Máximo 280 caracteres (obrigatório).
- Sem abertura genérica ("A matéria trata de...", "Nesta notícia...").
- Comece direto pelo fato principal.
- Factual, sem adjetivos decorativos.
- Não invente informações ausentes.

TÍTULO: {titulo}
MATÉRIA (primeiros parágrafos):
{conteudo[:600]}

Devolva apenas o texto do resumo, sem aspas, sem explicações.
"""
    try:
        resposta = client.responses.create(model=modelo, input=prompt)
        resumo = resposta.output_text.strip().strip('"').strip("'")
        return resumo[:280]
    except Exception as e:
        print(f"[PACOTE] Falha ao gerar resumo curto: {e}")
        resumo_atual = dados.get("resumo_curto", "") if isinstance(dados, dict) else dados.resumo_curto
        return resumo_atual[:280] if resumo_atual else titulo[:280]


def completar_pacote_editorial(
    materia: Materia,
    client: "OpenAI",
    modelo: str,
) -> Materia:
    """
    Completa o pacote editorial da matéria:
    - Títulos alternativos (SEO e capa)
    - Chamada social
    - Resumo curto

    Modifica a matéria in-place e retorna ela mesma.
    """
    print("[PACOTE] Gerando títulos alternativos...")
    titulos_alt = gerar_titulos_alternativos(materia, client, modelo)
    if titulos_alt:
        materia.titulos_alternativos = titulos_alt

    print("[PACOTE] Gerando títulos de capa alternativos...")
    titulos_capa_alt = gerar_titulos_capa_alternativos(materia, client, modelo)
    if titulos_capa_alt:
        materia.titulos_capa_alternativos = titulos_capa_alt

    print("[PACOTE] Gerando chamada social...")
    chamada = gerar_chamada_social(materia, client, modelo)
    if chamada:
        materia.chamada_social = chamada

    print("[PACOTE] Gerando resumo curto...")
    resumo = gerar_resumo_curto(materia, client, modelo)
    if resumo:
        materia.resumo_curto = resumo

    print("[PACOTE] Pacote editorial completo.")
    return materia
