"""
coleta/rss.py — Coleta de pautas via RSS e Google News.
Inclui deduplicação por similaridade de título.

Filtro temporal:
  - Apenas pautas publicadas nas últimas MAX_HORAS_PAUTA horas (padrão 8h).
  - Pautas das últimas 4h recebem prioridade 2; demais recebem prioridade 1.
  - O campo `prioridade` é usado pelo scoring para dar preferência a notícias recentes.

v43: Lê consultas_google_news.json e fontes_oficiais_prioritarias.json (se existirem).
     Chama enriquecer_pauta_com_intel() em cada pauta coletada.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

import feedparser
import requests

from ururau.config.settings import HEADERS, TIMEOUT_PADRAO


# ── Carregadores de config externos ───────────────────────────────────────────

def _carregar_consultas_google_news() -> dict:
    """
    Carrega consultas_google_news.json do diretório raiz.
    Retorna dict de grupos de termos ou {} se não existir.
    """
    try:
        p = Path("consultas_google_news.json")
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[RSS] Aviso: não foi possível carregar consultas_google_news.json: {e}")
    return {}


def _carregar_fontes_oficiais() -> list[dict]:
    """
    Carrega fontes_oficiais_prioritarias.json e retorna lista de fontes RSS ativas.
    Retorna [] se não existir ou se todas estiverem inativas.
    """
    try:
        p = Path("fontes_oficiais_prioritarias.json")
        if p.exists():
            dados = json.loads(p.read_text(encoding="utf-8"))
            fontes = dados.get("fontes", []) if isinstance(dados, dict) else dados
            return [f for f in fontes if f.get("ativo", False) and f.get("url")]
    except Exception as e:
        print(f"[RSS] Aviso: não foi possível carregar fontes_oficiais_prioritarias.json: {e}")
    return []


def obter_termos_google_news(termos_fallback: list[str]) -> list[str]:
    """
    Retorna lista consolidada de termos para Google News.
    Lê de consultas_google_news.json se disponível; caso contrário usa fallback.
    Desduplicados e em ordem.
    """
    consultas = _carregar_consultas_google_news()
    if not consultas:
        return termos_fallback

    termos: list[str] = []
    vistos: set[str] = set()
    for grupo_key, grupo in consultas.items():
        if grupo_key.startswith("_"):
            continue
        if isinstance(grupo, dict):
            for t in grupo.get("termos", []):
                if t not in vistos:
                    termos.append(t)
                    vistos.add(t)
    # Se não extraiu nada do JSON, usa fallback
    return termos if termos else termos_fallback


def _enriquecer_pautas_com_intel(pautas: list[dict]) -> list[dict]:
    """
    Aplica enriquecer_pauta_com_intel() em cada pauta.
    Silencioso em caso de erro de importação (compatibilidade retroativa).
    """
    try:
        from ururau.coleta.intel_editorial import enriquecer_pauta_com_intel
        return [enriquecer_pauta_com_intel(p) for p in pautas]
    except Exception as e:
        print(f"[RSS] Intel editorial indisponível (fallback): {e}")
    return pautas

# ── Janela temporal ───────────────────────────────────────────────────────────
MAX_HORAS_PAUTA    = 8    # ignora pautas com mais de 8h
PRIO_ALTA_HORAS    = 4    # pautas dentro de 4h recebem prioridade alta


# ── Utilitários ───────────────────────────────────────────────────────────────

def _normalizar_titulo(titulo: str) -> str:
    """Normaliza título para comparação de duplicatas."""
    t = titulo.lower()
    t = re.sub(r"[^\w\s]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _similaridade(a: str, b: str) -> float:
    """
    Similaridade simples entre dois títulos baseada em palavras comuns.
    Retorna float entre 0 e 1.
    """
    palavras_a = set(_normalizar_titulo(a).split())
    palavras_b = set(_normalizar_titulo(b).split())

    # Remove stopwords comuns
    stopwords = {
        "de", "da", "do", "das", "dos", "em", "na", "no", "nas", "nos",
        "e", "ou", "a", "o", "as", "os", "um", "uma", "uns", "umas",
        "que", "se", "com", "por", "para", "ao", "à", "é", "foi",
    }
    palavras_a -= stopwords
    palavras_b -= stopwords

    if not palavras_a or not palavras_b:
        return 0.0

    intersecao = palavras_a & palavras_b
    uniao = palavras_a | palavras_b
    return len(intersecao) / len(uniao)


def _uid_pauta(link: str, titulo: str) -> str:
    return hashlib.md5(f"{link}{titulo}".encode()).hexdigest()[:16]


def _limpar_html(texto: str) -> str:
    """Remove tags HTML básicas de resumos RSS."""
    texto = re.sub(r"<[^>]+>", " ", texto or "")
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def _extrair_dt(entry: dict) -> Optional[datetime.datetime]:
    """
    Extrai datetime e normaliza para horário de Brasília (America/Sao_Paulo).

    Regra de interpretação do fuso:
    - feedparser.published_parsed é sempre naive (sem tzinfo), mas pode representar:
        a) UTC — quando o feed declara explicitamente o offset no campo `published`
           (ex: "Thu, 24 Apr 2026 19:27:00 +0000" ou "... GMT")
        b) Hora local do feed — quando não há offset (ex: "24 Apr 2026 16:27:00")
    - Detectamos o caso (a) lendo o campo published/updated como string e procurando
      indicadores de UTC (+0000, +00:00, GMT, Z, UTC).
    - Se UTC detectado: converte published_parsed UTC → BRT (subtrai 3h).
    - Se sem tzinfo ou offset local: trata como BRT direto (não converte).
    """
    from zoneinfo import ZoneInfo
    _UTC = ZoneInfo("UTC")
    _BR  = ZoneInfo("America/Sao_Paulo")

    tp = entry.get("published_parsed") or entry.get("updated_parsed")
    if not tp:
        return None

    # Tenta ler o campo de texto original para detectar se há offset UTC
    raw_dt_str = str(entry.get("published") or entry.get("updated") or "").upper()
    _UTC_INDICATORS = ("+0000", "+00:00", " GMT", " UTC", " Z", "T00:", "Z\"")
    e_utc = any(ind in raw_dt_str for ind in _UTC_INDICATORS)

    try:
        if e_utc:
            # Feed mandou em UTC — converte para BRT
            dt_utc = datetime.datetime(*tp[:6], tzinfo=_UTC)
            return dt_utc.astimezone(_BR).replace(tzinfo=None)
        else:
            # Feed não declarou offset — trata como BRT diretamente
            return datetime.datetime(*tp[:6])
    except Exception:
        pass
    return None


def _dt_para_str(dt: Optional[datetime.datetime]) -> str:
    """Formata datetime (já em horário de Brasília) para string de exibição."""
    if dt:
        try:
            return dt.strftime("%d/%m/%Y %H:%M")
        except Exception:
            pass
    return ""


def _calcular_prioridade(dt: Optional[datetime.datetime], agora: datetime.datetime) -> int:
    """
    Calcula prioridade temporal da pauta:
      2 = publicada nas últimas PRIO_ALTA_HORAS horas (alta prioridade)
      1 = publicada entre PRIO_ALTA_HORAS e MAX_HORAS_PAUTA horas atrás
      0 = muito antiga (deve ser filtrada)
    """
    if dt is None:
        # Sem data → aceita com prioridade baixa (não sabemos a idade)
        return 1
    diff_horas = (agora - dt).total_seconds() / 3600
    if diff_horas > MAX_HORAS_PAUTA:
        return 0
    if diff_horas <= PRIO_ALTA_HORAS:
        return 2
    return 1


# ── Coleta RSS ────────────────────────────────────────────────────────────────

def coletar_rss(fontes_config: list[dict]) -> list[dict]:
    """
    Coleta pautas de uma lista de feeds RSS configurados.

    Parâmetro fontes_config: lista de dicts com:
      - url: str — URL do feed RSS
      - nome: str — Nome da fonte para exibição
      - canal_forcado: str (opcional) — Canal editorial pré-definido

    Retorna lista de dicts com campos padronizados.
    """
    pautas: list[dict] = []

    from zoneinfo import ZoneInfo as _ZI
    agora    = datetime.datetime.now(_ZI("America/Sao_Paulo")).replace(tzinfo=None)
    filtradas = 0

    for fonte in fontes_config:
        url_feed   = fonte.get("url", "")
        nome_fonte = fonte.get("nome", urlparse_nome(url_feed))
        canal      = fonte.get("canal_forcado", "")

        if not url_feed:
            continue

        try:
            feed = feedparser.parse(url_feed)
            entradas = feed.get("entries", [])
            print(f"[RSS] {nome_fonte}: {len(entradas)} entradas")

            for entry in entradas[:30]:
                titulo = (entry.get("title") or "").strip()
                link   = (entry.get("link") or "").strip()
                if not titulo or not link:
                    continue

                resumo = _limpar_html(
                    entry.get("summary") or
                    entry.get("description") or
                    ""
                )

                # Data de publicação original na fonte
                dt       = _extrair_dt(entry)
                data_pub = (_dt_para_str(dt) or
                            str(entry.get("published") or entry.get("updated") or ""))

                # Filtro temporal — ignora pautas muito antigas
                prio = _calcular_prioridade(dt, agora)
                if prio == 0:
                    filtradas += 1
                    continue

                pautas.append({
                    "titulo_origem":   titulo,
                    "link_origem":     link,
                    "fonte_nome":      nome_fonte,
                    "resumo_origem":   resumo[:600],
                    "canal_forcado":   canal,
                    "data_pub_fonte":  data_pub,
                    "_uid":            _uid_pauta(link, titulo),
                    "prioridade":      prio,   # 2=últimas 4h, 1=4-8h
                })

        except Exception as e:
            print(f"[RSS] Falha ao processar feed {url_feed}: {e}")

        time.sleep(0.3)  # Pausa gentil entre feeds

    if filtradas:
        print(f"[RSS] {filtradas} entradas ignoradas (mais de {MAX_HORAS_PAUTA}h)")

    # ── Fontes oficiais prioritárias (adicional v43) ───────────────────────────
    fontes_oficiais = _carregar_fontes_oficiais()
    if fontes_oficiais:
        print(f"[RSS] Fontes oficiais: {len(fontes_oficiais)} ativa(s)")
        for fo in fontes_oficiais:
            fo_config = {
                "url":           fo.get("url", ""),
                "nome":          fo.get("nome", fo.get("id", "Fonte oficial")),
                "canal_forcado": fo.get("canal_sugerido", ""),
            }
            try:
                feed = feedparser.parse(fo_config["url"])
                entradas = feed.get("entries", [])
                print(f"[RSS-OFICIAL] {fo_config['nome']}: {len(entradas)} entradas")
                for entry in entradas[:20]:
                    titulo = (entry.get("title") or "").strip()
                    link   = (entry.get("link") or "").strip()
                    if not titulo or not link:
                        continue
                    resumo = _limpar_html(entry.get("summary") or entry.get("description") or "")
                    dt       = _extrair_dt(entry)
                    data_pub = (_dt_para_str(dt) or str(entry.get("published") or ""))
                    prio = _calcular_prioridade(dt, agora)
                    if prio == 0:
                        filtradas += 1
                        continue
                    pautas.append({
                        "titulo_origem":   titulo,
                        "link_origem":     link,
                        "fonte_nome":      fo_config["nome"],
                        "resumo_origem":   resumo[:600],
                        "canal_forcado":   fo_config["canal_forcado"],
                        "data_pub_fonte":  data_pub,
                        "_uid":            _uid_pauta(link, titulo),
                        "prioridade":      prio,
                        "sinal_fonte_oficial": True,  # flag para scoring
                    })
            except Exception as e_fo:
                print(f"[RSS-OFICIAL] Falha ao processar {fo_config['nome']}: {e_fo}")
            time.sleep(0.3)

    # ── Enriquece com intel editorial ─────────────────────────────────────────
    pautas = _enriquecer_pautas_com_intel(pautas)
    return pautas


def urlparse_nome(url: str) -> str:
    """Extrai nome legível da URL do feed."""
    try:
        from urllib.parse import urlparse as _urlparse
        hostname = _urlparse(url).hostname or url
        # Remove www. e extensões de domínio comuns
        return re.sub(r"^www\.", "", hostname).split(".")[0].capitalize()
    except Exception:
        return "Fonte desconhecida"


# ── Google News RSS ───────────────────────────────────────────────────────────

def coletar_google_news(
    termos: list[str],
    max_por_termo: int = 10,
) -> list[dict]:
    """
    Coleta pautas do Google News via RSS para cada termo de busca.

    Parâmetros:
      - termos: lista de strings de busca (ex: ["Rio de Janeiro", "Lula"])
      - max_por_termo: número máximo de resultados por termo

    Retorna lista de dicts com campos padronizados.
    """
    pautas: list[dict] = []
    BASE_URL  = "https://news.google.com/rss/search?q={query}&hl=pt-BR&gl=BR&ceid=BR:pt-419"
    from zoneinfo import ZoneInfo as _ZI
    agora     = datetime.datetime.now(_ZI("America/Sao_Paulo")).replace(tzinfo=None)
    filtradas = 0

    for termo in termos:
        query = quote_plus(termo)
        url_feed = BASE_URL.format(query=query)

        try:
            feed = feedparser.parse(url_feed)
            entradas = feed.get("entries", [])
            print(f"[GNEWS] Termo '{termo}': {len(entradas)} entradas")

            for entry in entradas[:max_por_termo]:
                titulo = (entry.get("title") or "").strip()
                link   = (entry.get("link") or "").strip()
                if not titulo or not link:
                    continue

                # Google News codifica a fonte no título: "Título - Fonte"
                fonte_nome = "Google News"
                if " - " in titulo:
                    partes = titulo.rsplit(" - ", 1)
                    titulo = partes[0].strip()
                    fonte_nome = partes[1].strip() if len(partes) > 1 else "Google News"

                resumo   = _limpar_html(entry.get("summary") or "")
                dt       = _extrair_dt(entry)
                data_pub = (_dt_para_str(dt) or
                            str(entry.get("published") or ""))

                # Filtro temporal
                prio = _calcular_prioridade(dt, agora)
                if prio == 0:
                    filtradas += 1
                    continue

                pautas.append({
                    "titulo_origem":  titulo,
                    "link_origem":    link,
                    "fonte_nome":     fonte_nome,
                    "resumo_origem":  resumo[:600],
                    "canal_forcado":  "",
                    "data_pub_fonte": data_pub,
                    "_uid":           _uid_pauta(link, titulo),
                    "prioridade":     prio,
                })

        except Exception as e:
            print(f"[GNEWS] Falha para termo '{termo}': {e}")

        time.sleep(0.5)

    if filtradas:
        print(f"[GNEWS] {filtradas} entradas ignoradas (mais de {MAX_HORAS_PAUTA}h)")

    # ── Enriquece com intel editorial ─────────────────────────────────────────
    pautas = _enriquecer_pautas_com_intel(pautas)
    return pautas


# ── Filtragem contra banco de dados ──────────────────────────────────────────

def filtrar_contra_banco(
    pautas: list[dict],
    db,
    janela_horas: int = 48,
) -> tuple[list[dict], dict]:
    """
    Filtra pautas já conhecidas no banco antes de entrar na fila.

    Checagens realizadas (em ordem):
      1. Pauta já publicada no Ururau (link exato ou uid)       → descarta
      2. Pauta descartada/rejeitada/bloqueada anteriormente     → descarta
      3. Pauta já captada e em processamento (em_redacao/pronta)→ descarta
      4. Título similar já publicado nas últimas 72h             → descarta
      5. Título similar a publicações das últimas janela_horas   → descarta

    Parâmetros:
      - pautas: lista de dicts vindos de coletar_rss / coletar_google_news
      - db: instância de Database (ururau.core.database.Database)
      - janela_horas: janela de horas para deduplicação temática (padrão 48h)

    Retorna:
      - (novas, resumo) onde 'novas' é a lista filtrada e 'resumo' é um dict
        com contagens de cada motivo de descarte.
    """
    novas: list[dict] = []
    resumo = {
        "total":       len(pautas),
        "publicadas":  0,
        "descartadas": 0,
        "em_fila":     0,
        "similares":   0,
        "aprovadas":   0,
    }

    # Busca títulos publicados nas últimas janela_horas para deduplicação temática
    try:
        publicadas_recentes = db.listar_publicadas_recentes(horas=janela_horas)
        titulos_recentes = [
            p.get("titulo_origem", "") or p.get("titulo", "")
            for p in publicadas_recentes if p
        ]
    except Exception:
        titulos_recentes = []

    for pauta in pautas:
        link  = pauta.get("link_origem", "")
        uid   = pauta.get("_uid", "")
        titulo = pauta.get("titulo_origem", "")

        # 0. Barreira definitiva: link bloqueado permanentemente
        #    Cobre tanto pautas descartadas quanto publicadas com um único índice
        try:
            if link and db.link_esta_bloqueado(link):
                resumo["descartadas"] += 1
                print(f"[FILTRO] Link bloqueado (desc/pub): {titulo[:60]}")
                continue
        except AttributeError:
            pass  # db mais antigo sem o método — segue com os checks normais

        # 1. Já publicada no Ururau?
        if db.pauta_ja_publicada(link, uid):
            resumo["publicadas"] += 1
            print(f"[FILTRO] Já publicada: {titulo[:60]}")
            continue

        # 2. Foi descartada/bloqueada antes?
        if db.pauta_foi_descartada(link, uid):
            resumo["descartadas"] += 1
            print(f"[FILTRO] Descartada anteriormente: {titulo[:60]}")
            continue

        # 3. Já está sendo processada (captada / em_redacao / pronta)?
        status_atual = db.classificar_pauta(link, uid)
        if status_atual in ("captada", "triada", "aprovada", "em_redacao", "revisada", "pronta"):
            resumo["em_fila"] += 1
            print(f"[FILTRO] Já na fila ({status_atual}): {titulo[:60]}")
            continue

        # 4. Título similar já publicado nas últimas 72h?
        titulo_similar = db.titulo_similar_ja_publicado(titulo)
        if titulo_similar:
            resumo["similares"] += 1
            print(f"[FILTRO] Título similar publicado: '{titulo_similar[:50]}' ← '{titulo[:50]}'")
            continue

        # 5. Verifica similaridade com publicações das últimas janela_horas
        if titulos_recentes:
            similar_recente = None
            for titulo_pub in titulos_recentes:
                if titulo_pub and _similaridade(titulo, titulo_pub) > 0.60:
                    similar_recente = titulo_pub
                    break
            if similar_recente:
                resumo["similares"] += 1
                print(f"[FILTRO] Similar a publicação recente ({janela_horas}h): "
                      f"'{similar_recente[:50]}' ← '{titulo[:50]}'")
                continue

        novas.append(pauta)
        resumo["aprovadas"] += 1

    print(
        f"[FILTRO] {resumo['total']} pautas → "
        f"{resumo['aprovadas']} novas | "
        f"{resumo['publicadas']} já publicadas | "
        f"{resumo['descartadas']} descartadas | "
        f"{resumo['em_fila']} em fila | "
        f"{resumo['similares']} similares"
    )
    return novas, resumo


# ── Deduplicação ──────────────────────────────────────────────────────────────

def deduplicar(
    pautas: list[dict],
    limiar_similaridade: float = 0.65,
) -> list[dict]:
    """
    Remove pautas duplicadas ou muito similares.
    Usa similaridade de Jaccard entre títulos normalizados.
    Mantém a primeira ocorrência de cada grupo de duplicatas.

    Parâmetro limiar_similaridade: float 0-1.
      Padrão 0.65 — títulos com 65%+ de palavras comuns são considerados duplicatas.

    Retorna lista deduplicada.
    """
    unicas: list[dict] = []
    titulos_aceitos: list[str] = []

    for pauta in pautas:
        titulo = pauta.get("titulo_origem", "")
        if not titulo:
            continue

        # Verifica link exato duplicado
        links_aceitos = {p["link_origem"] for p in unicas}
        if pauta.get("link_origem") in links_aceitos:
            continue

        # Verifica similaridade de título
        duplicata = False
        for titulo_aceito in titulos_aceitos:
            if _similaridade(titulo, titulo_aceito) >= limiar_similaridade:
                duplicata = True
                break

        if not duplicata:
            unicas.append(pauta)
            titulos_aceitos.append(titulo)

    print(f"[RSS] Deduplicação: {len(pautas)} → {len(unicas)} pautas")
    return unicas
