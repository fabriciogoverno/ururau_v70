"""
imaging/busca.py — Busca e seleção de imagem para matérias.

Hierarquia de prioridade:
  PRIORIDADE 1 — og:image / twitter:image da página de origem
  PRIORIDADE 2 — melhor imagem encontrada no corpo da página
  PRIORIDADE 3 — Bing Image Search (último recurso)
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from ururau.config.settings import HEADERS, TIMEOUT_PADRAO, USAR_BING_IMAGEM


# ── Utilitários ───────────────────────────────────────────────────────────────

def _criar_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def _url_absoluta(url: str, base: str) -> str:
    if url.startswith("//"):
        scheme = urlparse(base).scheme or "https"
        return f"{scheme}:{url}"
    if url.startswith("http"):
        return url
    return urljoin(base, url)


def _score_imagem_url(url: str) -> int:
    """Pontuação heurística para priorizar URLs de imagem mais prováveis."""
    score = 0
    url_lower = url.lower()
    # Formato preferido
    for ext in (".jpg", ".jpeg"):
        if ext in url_lower:
            score += 10
    if ".webp" in url_lower:
        score += 8
    if ".png" in url_lower:
        score += 6
    # Indicadores de imagem editorial
    for kw in ("foto", "photo", "image", "imagem", "picture", "media", "uploads", "wp-content"):
        if kw in url_lower:
            score += 5
    # Penalizar ícones, logos, banners
    for kw in ("icon", "logo", "favicon", "banner", "ad", "pixel", "track", "gif"):
        if kw in url_lower:
            score -= 10
    return score


# ── PRIORIDADE 1: og:image / twitter:image ────────────────────────────────────

def buscar_imagem_og(
    url_pagina: str,
    session: Optional[requests.Session] = None,
) -> Optional[str]:
    """
    Extrai URL de imagem das meta tags og:image ou twitter:image.
    Retorna a URL ou None se não encontrar.
    """
    sess = session or _criar_session()
    try:
        resp = sess.get(url_pagina, timeout=TIMEOUT_PADRAO, allow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Ordem de preferência para meta tags
        seletores = [
            ("meta", {"property": "og:image"}),
            ("meta", {"property": "og:image:url"}),
            ("meta", {"name": "twitter:image"}),
            ("meta", {"name": "twitter:image:src"}),
        ]
        for tag, attrs in seletores:
            el = soup.find(tag, attrs=attrs)
            if el and el.get("content"):
                url = el["content"].strip()
                if url:
                    return _url_absoluta(url, url_pagina)
    except Exception as e:
        print(f"[BUSCA_IMG] og:image falhou ({url_pagina}): {e}")
    return None


# ── PRIORIDADE 2: melhor imagem no corpo da página ────────────────────────────

def buscar_imagem_corpo_pagina(
    soup: BeautifulSoup,
    url_pagina: str,
) -> Optional[str]:
    """
    Extrai a melhor imagem do corpo da página.
    Prefere imagens grandes em containers de conteúdo.
    Retorna URL ou None.
    """
    candidatas: list[tuple[int, str]] = []

    # Procura em containers de artigo primeiro
    article = (
        soup.find("article") or
        soup.find(class_=re.compile(r"(content|body|materia|post|entry|single)", re.I)) or
        soup.body
    )
    if not article:
        article = soup

    for img in article.find_all("img", limit=30):
        src = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
        if not src:
            continue
        src = src.strip()
        if not src or src.startswith("data:"):
            continue

        # Tenta pegar largura declarada
        try:
            largura = int(img.get("width", 0) or 0)
        except (ValueError, TypeError):
            largura = 0

        score = _score_imagem_url(src) + (largura // 100)

        url_abs = _url_absoluta(src, url_pagina)
        candidatas.append((score, url_abs))

    if candidatas:
        candidatas.sort(key=lambda x: x[0], reverse=True)
        melhor_score, melhor_url = candidatas[0]
        if melhor_score > 0:
            return melhor_url

    return None


# ── PRIORIDADE 3: Bing Image Search ───────────────────────────────────────────

def buscar_imagem_bing(
    titulo: str,
    session: Optional[requests.Session] = None,
) -> Optional[str]:
    """
    Busca imagem no Bing Images como último recurso.
    Utiliza scraping básico da SERP do Bing (sem API key).
    Retorna URL da primeira imagem relevante ou None.
    """
    if not USAR_BING_IMAGEM:
        return None

    sess = session or _criar_session()
    query = titulo[:120].replace(" ", "+")
    url_busca = f"https://www.bing.com/images/search?q={query}&first=1&count=5"

    try:
        resp = sess.get(url_busca, timeout=TIMEOUT_PADRAO)
        resp.raise_for_status()

        # Bing inclui URLs de imagem em atributo m= ou src
        # Tenta extrair do JSON embutido nas thumbnails
        padrao = re.compile(r'"murl":"(https?://[^"]+\.(?:jpg|jpeg|png|webp))"', re.I)
        resultados = padrao.findall(resp.text)

        # Filtra imagens muito pequenas ou de domínios de anúncios
        for url in resultados[:5]:
            if not any(bad in url.lower() for bad in ("tbn", "gstatic", "pixel", "track", "ad.")):
                return url

    except Exception as e:
        print(f"[BUSCA_IMG] Bing falhou para '{titulo[:40]}': {e}")

    return None


# ── Orquestrador principal ────────────────────────────────────────────────────

def selecionar_melhor_imagem(
    url_pagina: str,
    titulo: str,
    dossie_texto: str = "",
    session: Optional[requests.Session] = None,
) -> dict:
    """
    Orquestra busca de imagem em ordem de prioridade:
      1. og:image / twitter:image
      2. Melhor imagem do corpo da página
      3. Bing Image Search

    Retorna dict com:
      - url_imagem: str
      - estrategia_imagem: str
      - credito_foto: str
    """
    sess = session or _criar_session()
    soup_cache: Optional[BeautifulSoup] = None

    resultado = {
        "url_imagem": "",
        "estrategia_imagem": "",
        "credito_foto": "Reprodução",
    }

    # ── Prioridade 1: og:image ────────────────────────────────────────────────
    if url_pagina:
        try:
            resp = sess.get(url_pagina, timeout=TIMEOUT_PADRAO, allow_redirects=True)
            resp.raise_for_status()
            soup_cache = BeautifulSoup(resp.text, "html.parser")

            # og/twitter via soup já carregado
            for tag, attrs in [
                ("meta", {"property": "og:image"}),
                ("meta", {"property": "og:image:url"}),
                ("meta", {"name": "twitter:image"}),
                ("meta", {"name": "twitter:image:src"}),
            ]:
                el = soup_cache.find(tag, attrs=attrs)
                if el and el.get("content", "").strip():
                    url = _url_absoluta(el["content"].strip(), url_pagina)
                    if url:
                        resultado["url_imagem"] = url
                        resultado["estrategia_imagem"] = "og_image"
                        print(f"[BUSCA_IMG] og:image encontrado: {url[:80]}")
                        return resultado
        except Exception as e:
            print(f"[BUSCA_IMG] Falha ao carregar página ({url_pagina}): {e}")

    # ── Prioridade 2: corpo da página ─────────────────────────────────────────
    if soup_cache and url_pagina:
        url_corpo = buscar_imagem_corpo_pagina(soup_cache, url_pagina)
        if url_corpo:
            resultado["url_imagem"] = url_corpo
            resultado["estrategia_imagem"] = "corpo_pagina"
            print(f"[BUSCA_IMG] Imagem do corpo encontrada: {url_corpo[:80]}")
            return resultado

    # ── Prioridade 3: Bing ────────────────────────────────────────────────────
    url_bing = buscar_imagem_bing(titulo, session=sess)
    if url_bing:
        resultado["url_imagem"] = url_bing
        resultado["estrategia_imagem"] = "bing_search"
        resultado["credito_foto"] = "Reprodução/Internet"
        print(f"[BUSCA_IMG] Bing image encontrado: {url_bing[:80]}")
        return resultado

    print(f"[BUSCA_IMG] Nenhuma imagem encontrada para: {titulo[:60]}")
    return resultado
