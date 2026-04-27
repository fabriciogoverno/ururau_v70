"""
coleta/scraping.py — Extração de conteúdo web para apuração.
Extrai texto principal, meta tags og: e monta dossiê da pauta.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from ururau.config.settings import HEADERS, TIMEOUT_PADRAO


# ── Seletores de container de artigo (CSS classes/IDs comuns) ─────────────────
_ARTICLE_SELETORES = [
    "article",
    '[class*="article"]',
    '[class*="content"]',
    '[class*="materia"]',
    '[class*="noticia"]',
    '[class*="post-body"]',
    '[class*="entry-content"]',
    '[class*="news-body"]',
    "main",
]

# Elementos a remover antes de extrair texto
_REMOVER_TAGS = [
    "script", "style", "nav", "header", "footer", "aside",
    "form", "noscript", "iframe", "button", "figure[class*='ad']",
]


def _criar_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _limpar_texto(texto: str) -> str:
    """Remove espaços múltiplos, linhas em branco excessivas."""
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    texto = re.sub(r" {2,}", " ", texto)
    return texto.strip()


def extrair_texto_pagina(url: str) -> str:
    """
    Extrai o texto principal do artigo de uma URL.
    Usa heurística de containers de conteúdo.
    Retorna string com o texto ou string vazia em caso de falha.
    """
    sess = _criar_session()
    try:
        resp = sess.get(url, timeout=TIMEOUT_PADRAO, allow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove elementos indesejados
        for tag in _REMOVER_TAGS:
            for el in soup.select(tag):
                el.decompose()

        # Tenta encontrar container de artigo
        container = None
        for seletor in _ARTICLE_SELETORES:
            container = soup.select_one(seletor)
            if container:
                break

        alvo = container if container else soup.body
        if not alvo:
            return ""

        # Extrai parágrafos
        paragrafos = []
        for p in alvo.find_all(["p", "h2", "h3", "blockquote"], limit=60):
            texto = p.get_text(separator=" ", strip=True)
            if len(texto) > 30:
                paragrafos.append(texto)

        return _limpar_texto("\n\n".join(paragrafos))

    except Exception as e:
        print(f"[SCRAPING] Falha ao extrair texto de {url}: {e}")
        return ""


def extrair_meta_og(url: str) -> dict:
    """
    Extrai meta tags og: e twitter: de uma URL.

    Retorna dict com:
      - titulo: str
      - descricao: str
      - imagem: str
      - tipo: str
      - site_name: str
      - url_canonical: str
    """
    sess = _criar_session()
    resultado = {
        "titulo": "",
        "descricao": "",
        "imagem": "",
        "tipo": "",
        "site_name": "",
        "url_canonical": url,
    }

    try:
        resp = sess.get(url, timeout=TIMEOUT_PADRAO, allow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        mapeamento = {
            "titulo":       [("og:title",), ("twitter:title",)],
            "descricao":    [("og:description",), ("twitter:description",), ("description",)],
            "imagem":       [("og:image",), ("og:image:url",), ("twitter:image",), ("twitter:image:src",)],
            "tipo":         [("og:type",)],
            "site_name":    [("og:site_name",)],
            "url_canonical":[("og:url",)],
        }

        for campo, opcoes in mapeamento.items():
            for (nome,) in opcoes:
                # Tenta property= (og:) e name= (twitter:/description)
                el = soup.find("meta", property=nome) or soup.find("meta", attrs={"name": nome})
                if el and el.get("content", "").strip():
                    resultado[campo] = el["content"].strip()
                    break

        # Fallback para <title>
        if not resultado["titulo"]:
            title_tag = soup.find("title")
            if title_tag:
                resultado["titulo"] = title_tag.get_text(strip=True)

    except Exception as e:
        print(f"[SCRAPING] Falha ao extrair og: de {url}: {e}")

    return resultado


def extrair_dossie(url: str, texto_existente: str = "") -> str:
    """
    v68: SEMPRE tenta abrir URL quando disponivel.
    RSS texto >=500 chars NAO eh aceito como fonte completa.
    """
    MAX_DOSSIE = 8000
    if not url:
        return (texto_existente or "")[:MAX_DOSSIE]
    texto_scraped = extrair_texto_pagina(url) or ""
    partes = []
    if texto_existente:
        partes.append(texto_existente)
    if texto_scraped:
        partes.append(texto_scraped)
    dossie = "\n\n".join(partes)
    if not dossie:
        dossie = texto_existente or ""
    return dossie[:MAX_DOSSIE]


def extrair_dossie_completo(url: str, texto_existente: str = "") -> dict:
    """
    v68: versao estruturada que retorna metadados de extracao.

    Retorna:
      {
        "dossie": str,
        "raw_source_text": str,
        "cleaned_source_text": str,
        "extraction_method": "url_scraping | rss_only | failed",
        "source_sufficiency_score": int 0..100,
        "extraction_status": "ok | short_usable | failed",
        "metadata": {url, rss_chars, scraped_chars, total_chars},
      }
    """
    MAX_DOSSIE = 8000
    rss_chars = len(texto_existente or "")
    out = {
        "dossie": "",
        "raw_source_text": "",
        "cleaned_source_text": "",
        "extraction_method": "failed",
        "source_sufficiency_score": 0,
        "extraction_status": "failed",
        "metadata": {
            "url": url or "",
            "rss_chars": rss_chars,
            "scraped_chars": 0,
            "total_chars": 0,
        },
    }

    if not url:
        d = (texto_existente or "")[:MAX_DOSSIE]
        out["dossie"] = d
        out["raw_source_text"] = d
        out["cleaned_source_text"] = d
        out["extraction_method"] = "rss_only" if d else "failed"
        out["metadata"]["total_chars"] = len(d)
        if len(d) >= 1500:
            out["extraction_status"] = "ok"
            out["source_sufficiency_score"] = 80
        elif len(d) >= 500:
            out["extraction_status"] = "short_usable"
            out["source_sufficiency_score"] = 50
        else:
            out["extraction_status"] = "failed"
            out["source_sufficiency_score"] = 10
        return out

    texto_scraped = extrair_texto_pagina(url) or ""
    scraped_chars = len(texto_scraped)
    out["metadata"]["scraped_chars"] = scraped_chars
    out["raw_source_text"] = texto_scraped

    partes = []
    if texto_existente:
        partes.append(texto_existente)
    if texto_scraped:
        partes.append(texto_scraped)
    dossie = "\n\n".join(partes)[:MAX_DOSSIE]

    out["dossie"] = dossie
    out["cleaned_source_text"] = dossie
    out["metadata"]["total_chars"] = len(dossie)

    if scraped_chars >= 1500:
        out["extraction_method"] = "url_scraping"
        out["extraction_status"] = "ok"
        out["source_sufficiency_score"] = 90
    elif scraped_chars >= 500:
        out["extraction_method"] = "url_scraping"
        out["extraction_status"] = "short_usable"
        out["source_sufficiency_score"] = 70
    elif rss_chars >= 1500:
        out["extraction_method"] = "rss_only"
        out["extraction_status"] = "short_usable"
        out["source_sufficiency_score"] = 50
    elif rss_chars >= 300:
        out["extraction_method"] = "rss_only"
        out["extraction_status"] = "short_usable"
        out["source_sufficiency_score"] = 30
    else:
        out["extraction_method"] = "failed"
        out["extraction_status"] = "failed"
        out["source_sufficiency_score"] = 10

    return out
