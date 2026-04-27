"""
coleta/ururau_check.py — Verifica títulos publicados no site do Ururau.

Faz scraping da página "Últimas Notícias" do Portal Ururau para obter os
títulos das matérias publicadas nas últimas 48 horas e compara com novas
candidatas, evitando duplicatas de assunto.

URL base: https://www.ururau.com.br/ultimas-noticias
"""
from __future__ import annotations

import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

from ururau.config.settings import HEADERS, TIMEOUT_PADRAO

# ── Configurações ─────────────────────────────────────────────────────────────
URURAU_ULTIMAS_URL  = "https://www.ururau.com.br/ultimas-noticias"
URURAU_BASE_URL     = "https://www.ururau.com.br"
SIMILARIDADE_MIN    = 0.55   # threshold para considerar mesmo assunto
MAX_PAGINAS_SCRAPE  = 3      # máximo de páginas de "últimas notícias" a varrer
_TIMEOUT            = 15
_CACHE_TTL_SEG      = 1800   # 30 minutos — reusa resultado se recente

# Cache em memória: (timestamp, list[str])
_cache_titulos: tuple[float, list[str]] = (0.0, [])


def _normalizar(titulo: str) -> set:
    """Transforma título em bag-of-words sem stopwords."""
    stopwords = {
        "de", "da", "do", "das", "dos", "em", "na", "no", "nas", "nos",
        "e", "ou", "a", "o", "as", "os", "um", "uma", "uns", "umas",
        "que", "se", "com", "por", "para", "ao", "à", "é", "foi",
        "ser", "ter", "está", "são", "foi", "pelo", "pela", "pelos", "pelas",
    }
    palavras = set(re.sub(r"[^\w\s]", "", titulo.lower()).split())
    return palavras - stopwords


def _jaccard(a: str, b: str) -> float:
    pa = _normalizar(a)
    pb = _normalizar(b)
    if not pa or not pb:
        return 0.0
    return len(pa & pb) / len(pa | pb)


def _extrair_titulos_pagina(html: str) -> list[str]:
    """
    Extrai títulos de matérias de uma página do Ururau.
    Tenta múltiplos seletores para ser resiliente a mudanças de layout.
    """
    soup = BeautifulSoup(html, "html.parser")
    titulos: list[str] = []

    # Seletores em ordem de especificidade
    seletores = [
        "h2.titulo-noticia", "h2.entry-title", "h2.post-title",
        "h3.titulo-noticia", "h3.entry-title", "h3.post-title",
        ".ultimas-noticias h2", ".ultimas-noticias h3",
        ".lista-noticias h2", ".lista-noticias h3",
        "article h2", "article h3",
        ".news-title", ".article-title", ".materia-titulo",
        "h2", "h3",  # fallback genérico
    ]

    vistos: set[str] = set()
    for sel in seletores:
        elementos = soup.select(sel)
        for el in elementos:
            texto = el.get_text(separator=" ", strip=True)
            if not texto or len(texto) < 10:
                continue
            # Normaliza espaços
            texto = re.sub(r"\s+", " ", texto).strip()
            if texto not in vistos:
                vistos.add(texto)
                titulos.append(texto)
        if len(titulos) >= 20:
            break  # suficiente

    return titulos


def buscar_titulos_publicados_ururau(
    max_paginas: int = MAX_PAGINAS_SCRAPE,
    forcar_refresh: bool = False,
) -> list[str]:
    """
    Busca títulos publicados nas últimas horas no Portal Ururau.

    Usa cache de 30 minutos para não sobrecarregar o site.
    Retorna lista de strings com os títulos encontrados.
    """
    global _cache_titulos

    agora = time.time()
    ts, titulos_cache = _cache_titulos

    if not forcar_refresh and (agora - ts) < _CACHE_TTL_SEG and titulos_cache:
        print(f"[URURAU_CHECK] Usando cache ({len(titulos_cache)} títulos, "
              f"{int((agora - ts) / 60)}min atrás)")
        return titulos_cache

    print("[URURAU_CHECK] Buscando títulos publicados no Portal Ururau...")
    titulos: list[str] = []
    session = requests.Session()
    session.headers.update(HEADERS)

    urls_para_varrer = [URURAU_ULTIMAS_URL]
    # Adiciona páginas 2 e 3 se solicitado
    for p in range(2, max_paginas + 1):
        urls_para_varrer.append(f"{URURAU_ULTIMAS_URL}?pagina={p}")
        urls_para_varrer.append(f"{URURAU_ULTIMAS_URL}/page/{p}/")

    for url in urls_para_varrer[:max_paginas * 2]:
        try:
            resp = session.get(url, timeout=_TIMEOUT, allow_redirects=True)
            if resp.status_code != 200:
                continue
            novos = _extrair_titulos_pagina(resp.text)
            if not novos:
                continue
            for t in novos:
                if t not in titulos:
                    titulos.append(t)
            print(f"[URURAU_CHECK] {url}: {len(novos)} títulos encontrados")
            time.sleep(0.5)
        except Exception as e:
            print(f"[URURAU_CHECK] Falha ao acessar {url}: {e}")

        if len(titulos) >= 60:
            break

    # Também tenta a página inicial do Ururau para pegar destaques recentes
    if len(titulos) < 10:
        try:
            resp = session.get(URURAU_BASE_URL, timeout=_TIMEOUT)
            if resp.status_code == 200:
                extras = _extrair_titulos_pagina(resp.text)
                for t in extras:
                    if t not in titulos:
                        titulos.append(t)
                print(f"[URURAU_CHECK] Homepage: {len(extras)} títulos extras")
        except Exception as e:
            print(f"[URURAU_CHECK] Falha ao acessar homepage: {e}")

    print(f"[URURAU_CHECK] Total: {len(titulos)} títulos coletados do site")
    _cache_titulos = (agora, titulos)
    return titulos


def titulo_ja_publicado_no_site(
    titulo_candidato: str,
    titulos_site: Optional[list[str]] = None,
    limiar: float = SIMILARIDADE_MIN,
) -> Optional[str]:
    """
    Verifica se um título candidato já foi publicado no site do Ururau.

    Parâmetros:
      - titulo_candidato: título da nova pauta a verificar
      - titulos_site: lista de títulos (se None, busca automaticamente)
      - limiar: threshold de similaridade (padrão 0.55)

    Retorna o título similar encontrado no site, ou None se novo.
    """
    if titulos_site is None:
        titulos_site = buscar_titulos_publicados_ururau()

    for t_site in titulos_site:
        sim = _jaccard(titulo_candidato, t_site)
        if sim >= limiar:
            return t_site

    return None


def filtrar_contra_site_ururau(
    pautas: list[dict],
    limiar: float = SIMILARIDADE_MIN,
    db=None,
) -> tuple[list[dict], int]:
    """
    Remove pautas cujo assunto já foi publicado no Portal Ururau.

    Parâmetros:
      - pautas: lista de dicts com campo 'titulo_origem'
      - limiar: threshold de similaridade Jaccard
      - db: instância de Database (opcional) — se fornecido, bloqueia o link
            permanentemente no banco para que não volte em coletas futuras

    Retorna (pautas_filtradas, quantidade_removida).
    """
    titulos_site = buscar_titulos_publicados_ururau()

    if not titulos_site:
        print("[URURAU_CHECK] Nenhum título coletado do site — pulando filtro")
        return pautas, 0

    novas: list[dict] = []
    removidas = 0

    for pauta in pautas:
        titulo = pauta.get("titulo_origem", "")
        link   = pauta.get("link_origem", "")
        uid    = pauta.get("_uid", "") or pauta.get("uid", "")
        similar = titulo_ja_publicado_no_site(titulo, titulos_site, limiar)
        if similar:
            removidas += 1
            print(f"[URURAU_CHECK] JÁ NO SITE → '{titulo[:55]}' "
                  f"~ '{similar[:55]}'")
            # Bloqueia o link no banco para não reaparecer em coletas futuras
            if db and link:
                try:
                    db.bloquear_link(link, uid, titulo, motivo="ja_no_site")
                except Exception:
                    pass
        else:
            novas.append(pauta)

    if removidas:
        print(f"[URURAU_CHECK] {removidas} pautas removidas (já no ar no Portal Ururau)")
    else:
        print(f"[URURAU_CHECK] Nenhuma duplicata encontrada no site ({len(pautas)} pautas novas)")

    return novas, removidas
