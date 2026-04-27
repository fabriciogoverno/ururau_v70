"""
coleta/leitura_fonte.py — Leitura e extração de texto da fonte original.

Bloco 21 — Funcionalidade "Leitura da Fonte":
  - Busca o texto completo do artigo original via URL
  - Sanitiza o HTML e extrai o conteúdo principal
  - Destaca termos das watchlists editoriais
  - Cache em memória para evitar re-fetch
  - Timeout configurável via TIMEOUT_LEITURA_FONTE
  - Fallback silencioso: se falhar, retorna resultado vazio

Uso:
    from ururau.coleta.leitura_fonte import ler_fonte_pauta
    resultado = ler_fonte_pauta(pauta)
    print(resultado.texto_limpo)
    print(resultado.termos_destacados)
"""
from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

import requests


# ── Configurações ─────────────────────────────────────────────────────────────
try:
    from ururau.config.settings import HEADERS, TIMEOUT_LEITURA_FONTE, CACHE_LEITURA_FONTE_MIN
except Exception:
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    TIMEOUT_LEITURA_FONTE   = 12
    CACHE_LEITURA_FONTE_MIN = 30

_CACHE_TTL_SEG = CACHE_LEITURA_FONTE_MIN * 60  # segundos

# Cache em memória: url → (timestamp, ResultadoLeitura)
_cache: dict[str, tuple[float, "ResultadoLeitura"]] = {}


# ── Resultado ─────────────────────────────────────────────────────────────────

@dataclass
class ResultadoLeitura:
    """Resultado da leitura e extração de texto de uma fonte."""
    url: str = ""
    texto_limpo: str = ""            # texto principal extraído
    titulo_extraido: str = ""        # título encontrado no HTML
    imagem_url: str = ""             # URL da imagem principal (og:image ou primeiro <img>)
    termos_destacados: list[str] = field(default_factory=list)  # termos das watchlists detectados
    score_intel_adicional: int = 0   # score extra detectado no texto completo
    intel_log: str = ""              # log da análise intel
    tamanho_chars: int = 0           # comprimento do texto extraído
    sucesso: bool = False
    erro: str = ""


# ── Seletores CSS para extração de conteúdo principal ─────────────────────────
_SELETORES_CONTEUDO = [
    "article",
    "[class*='article-body']",
    "[class*='post-content']",
    "[class*='entry-content']",
    "[class*='content-body']",
    "[class*='news-content']",
    "[class*='materia-body']",
    "[class*='noticia-body']",
    "[class*='texto-noticia']",
    "main",
    ".content",
    "#content",
]

_TAGS_REMOVER = {
    "script", "style", "nav", "header", "footer", "aside",
    "noscript", "iframe", "svg", "form", "button",
    "figure",  # mantém alt text da imagem mas remove markup
}

# ── Utilidades ────────────────────────────────────────────────────────────────

def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return texto.lower()


def _extrair_texto_html(html: str) -> tuple[str, str]:
    """
    Extrai título e texto limpo de um HTML.
    Usa BeautifulSoup se disponível, fallback para regex.
    Retorna (titulo, texto_limpo).
    """
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        # Título
        titulo = ""
        tag_titulo = soup.find("h1") or soup.find("title")
        if tag_titulo:
            titulo = tag_titulo.get_text(separator=" ", strip=True)

        # Remove tags indesejadas
        for tag in soup.find_all(_TAGS_REMOVER):
            tag.decompose()

        # Tenta seletores de conteúdo principal
        conteudo = None
        for sel in _SELETORES_CONTEUDO:
            elemento = soup.select_one(sel)
            if elemento:
                texto_candidato = elemento.get_text(separator="\n", strip=True)
                if len(texto_candidato) > 200:
                    conteudo = texto_candidato
                    break

        # Fallback: pega todo o body
        if not conteudo:
            body = soup.find("body")
            conteudo = body.get_text(separator="\n", strip=True) if body else ""

        # Limpa espaços excessivos
        linhas = [l.strip() for l in conteudo.split("\n") if l.strip() and len(l.strip()) > 20]
        texto_limpo = "\n".join(linhas[:80])  # limita a 80 parágrafos para não sobrecarregar

        return titulo.strip(), texto_limpo

    except ImportError:
        # Fallback: regex básico sem BeautifulSoup
        titulo = ""
        m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
        if m:
            titulo = re.sub(r"<[^>]+>", "", m.group(1)).strip()

        texto = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
        texto = re.sub(r"<style[^>]*>.*?</style>", " ", texto, flags=re.DOTALL | re.IGNORECASE)
        texto = re.sub(r"<[^>]+>", " ", texto)
        texto = re.sub(r"\s+", " ", texto).strip()
        return titulo, texto[:8000]


def _extrair_imagem_html(html: str, url_base: str = "") -> str:
    """
    Extrai a URL da imagem principal do artigo.
    Prioridade: og:image > twitter:image > primeiro <img> de conteúdo (>= 100px).
    Retorna string vazia se não encontrar.
    """
    try:
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin

        soup = BeautifulSoup(html, "html.parser")

        # 1. og:image
        og = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
        if og and og.get("content", "").strip():
            return og["content"].strip()

        # 2. twitter:image
        tw = soup.find("meta", attrs={"name": "twitter:image"})
        if tw and tw.get("content", "").strip():
            return tw["content"].strip()

        # 3. Primeiro <img> dentro de article/main com src razoável (não ícone)
        container = soup.find("article") or soup.find("main") or soup.find("body")
        if container:
            for img in container.find_all("img", src=True):
                src = img.get("src", "").strip()
                if not src or src.startswith("data:"):
                    continue
                # Filtra ícones pequenos por atributo width/height
                w = img.get("width", "")
                h = img.get("height", "")
                try:
                    if int(str(w).replace("px", "").strip() or "999") < 100:
                        continue
                    if int(str(h).replace("px", "").strip() or "999") < 80:
                        continue
                except (ValueError, TypeError):
                    pass
                # Ignora URLs de trackers e ícones por padrão
                if any(x in src for x in ("pixel", "tracker", "1x1", "spacer", "blank")):
                    continue
                return urljoin(url_base, src) if url_base else src
    except Exception:
        # Fallback com regex apenas para og:image
        m = re.search(r'og:image["\s]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        m = re.search(r'content=["\']([^"\']+)["\']["\s]+property=["\']og:image["\']', html, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


def _detectar_termos_watchlist(texto_norm: str) -> list[str]:
    """Detecta termos das watchlists editoriais no texto."""
    try:
        import json
        from pathlib import Path
        p = Path("watchlists_editoriais.json")
        if not p.exists():
            return []
        wl = json.loads(p.read_text(encoding="utf-8"))
        encontrados: list[str] = []
        vistos: set[str] = set()
        for grupo_key, grupo in wl.items():
            if grupo_key.startswith("_"):
                continue
            if isinstance(grupo, dict):
                for t in grupo.get("termos", []) + grupo.get("nomes", []):
                    t_norm = _normalizar(t)
                    if t_norm in texto_norm and t_norm not in vistos:
                        encontrados.append(t)
                        vistos.add(t_norm)
        return encontrados[:20]
    except Exception:
        return []


# ── Função principal ──────────────────────────────────────────────────────────

def ler_fonte_pauta(pauta: dict, forcar_refresh: bool = False) -> ResultadoLeitura:
    """
    Busca e extrai o texto completo da fonte original de uma pauta.

    Parâmetros:
      - pauta: dict com campo 'link_origem'
      - forcar_refresh: ignora cache e refaz o fetch

    Retorna ResultadoLeitura. Em caso de erro, retorna ResultadoLeitura com
    sucesso=False e erro descritivo (NUNCA levanta exceção).
    """
    try:
        return _ler_fonte_impl(pauta, forcar_refresh)
    except Exception as e:
        return ResultadoLeitura(
            url=pauta.get("link_origem", ""),
            sucesso=False,
            erro=f"Erro inesperado: {e}",
        )


def _ler_fonte_impl(pauta: dict, forcar_refresh: bool) -> ResultadoLeitura:
    url = (pauta.get("link_origem") or "").strip()
    if not url:
        return ResultadoLeitura(sucesso=False, erro="URL não informada")

    # Verifica cache
    agora = time.time()
    if not forcar_refresh and url in _cache:
        ts, resultado = _cache[url]
        if (agora - ts) < _CACHE_TTL_SEG:
            return resultado

    print(f"[LEITURA_FONTE] Buscando: {url[:80]}")

    # Fetch
    try:
        session = requests.Session()
        session.headers.update(HEADERS)
        resp = session.get(url, timeout=TIMEOUT_LEITURA_FONTE, allow_redirects=True)
        if resp.status_code != 200:
            resultado = ResultadoLeitura(
                url=url,
                sucesso=False,
                erro=f"HTTP {resp.status_code}",
            )
            _cache[url] = (agora, resultado)
            return resultado
        html = resp.text
    except Exception as e:
        resultado = ResultadoLeitura(url=url, sucesso=False, erro=str(e))
        _cache[url] = (agora, resultado)
        return resultado

    # Extração de texto e imagem
    titulo_ext, texto_limpo = _extrair_texto_html(html)
    imagem_url = _extrair_imagem_html(html, url_base=url)
    texto_norm = _normalizar(texto_limpo)

    # Detecção de termos das watchlists
    termos = _detectar_termos_watchlist(texto_norm)

    # Análise intel editorial no texto completo
    score_intel = 0
    intel_log = ""
    try:
        from ururau.coleta.intel_editorial import analisar_intel_editorial
        intel = analisar_intel_editorial(
            titulo=pauta.get("titulo_origem", ""),
            resumo=pauta.get("resumo_origem", ""),
            texto_fonte=texto_limpo[:3000],
            canal=pauta.get("canal_forcado", ""),
        )
        score_intel = intel.score_adicional_total
        intel_log = intel.resumo_log()
    except Exception:
        pass

    resultado = ResultadoLeitura(
        url=url,
        texto_limpo=texto_limpo[:8000],   # limita para exibição
        titulo_extraido=titulo_ext,
        imagem_url=imagem_url,
        termos_destacados=termos,
        score_intel_adicional=score_intel,
        intel_log=intel_log,
        tamanho_chars=len(texto_limpo),
        sucesso=True,
    )

    _cache[url] = (agora, resultado)
    print(f"[LEITURA_FONTE] OK — {len(texto_limpo)} chars, {len(termos)} termos detectados")
    return resultado


def limpar_cache_leitura():
    """Limpa todo o cache de leitura de fonte."""
    global _cache
    _cache = {}


def obter_texto_para_redacao(pauta: dict) -> str:
    """
    Convenience: retorna apenas o texto limpo da fonte para uso na redação.
    Retorna string vazia se a leitura falhar.
    """
    resultado = ler_fonte_pauta(pauta)
    return resultado.texto_limpo if resultado.sucesso else ""
