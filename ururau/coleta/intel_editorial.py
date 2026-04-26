"""
coleta/intel_editorial.py — Módulo de inteligência editorial expandida.

Implementa os novos sub-scores SEM substituir os existentes em scoring.py.
Todos os scores aqui são ADITIVOS — entram como camada extra após o score base.

Blocos implementados:
  3. Watchlists editoriais (nomes, termos, pesos configuráveis)
  4. Aliases e normalização (variantes, apelidos, grafias)
  5. Novos sub-scores (Porto do Açu, ALERJ, intenção de busca, etc.)
  7. Porto do Açu como entidade prioritária
  8. Triangulação estratégica regional
  9. Oportunidade editorial / vácuo de cobertura
  11. Score investigativo e transparência
  13. Fator SEO de intenção de busca
  14. Fator Google Discover e utilidade real
  16. Protocolo de verdade / verificador antialucinação
  17. Campos e Norte Fluminense com pesos separados
  19. Urgência / temas explosivos

FALLBACK: Se qualquer arquivo de configuração não existir, usa defaults internos.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ── Constantes de configuração via env (com defaults seguros) ────────────────
W_PORTO_DO_ACU              = int(os.getenv("W_PORTO_DO_ACU", "18"))
W_WATCHLIST_ALERJ           = int(os.getenv("W_WATCHLIST_ALERJ", "10"))
W_INTENCAO_BUSCA            = int(os.getenv("W_INTENCAO_BUSCA", "8"))
W_SURTO_COBERTURA           = int(os.getenv("W_SURTO_COBERTURA", "6"))
W_CONTINUIDADE_EDITORIAL    = int(os.getenv("W_CONTINUIDADE_EDITORIAL", "5"))
W_OPORTUNIDADE_EDITORIAL    = int(os.getenv("W_OPORTUNIDADE_EDITORIAL", "7"))
W_INVESTIGATIVO_TRANSPARENCIA = int(os.getenv("W_INVESTIGATIVO_TRANSPARENCIA", "12"))
W_DISCOVER_UTILIDADE        = int(os.getenv("W_DISCOVER_UTILIDADE", "6"))
W_TRIANGULACAO_REGIONAL     = int(os.getenv("W_TRIANGULACAO_REGIONAL", "15"))
W_TEMAS_EXPLOSIVOS          = int(os.getenv("W_TEMAS_EXPLOSIVOS", "20"))
W_REGIONAL_CAMPOS           = int(os.getenv("W_REGIONAL_CAMPOS", "20"))
W_REGIONAL_NORTE_FLUMINENSE = int(os.getenv("W_REGIONAL_NORTE_FLUMINENSE", "15"))
W_ENTIDADE_PORTO_DO_ACU     = int(os.getenv("W_ENTIDADE_PORTO_DO_ACU", "18"))

ENABLE_WATCHLISTS              = os.getenv("ENABLE_WATCHLISTS", "true").lower() != "false"
ENABLE_ALIASES                 = os.getenv("ENABLE_ALIASES", "true").lower() != "false"
ENABLE_TRIANGULACAO_REGIONAL   = os.getenv("ENABLE_TRIANGULACAO_REGIONAL", "true").lower() != "false"
ENABLE_OPORTUNIDADE_EDITORIAL  = os.getenv("ENABLE_OPORTUNIDADE_EDITORIAL", "true").lower() != "false"
ENABLE_PROTOCOLO_VERDADE       = os.getenv("ENABLE_PROTOCOLO_VERDADE", "true").lower() != "false"

# Caminho base para arquivos de configuração
_BASE = Path(__file__).parent.parent.parent


# ── Resultado da análise intel ────────────────────────────────────────────────
@dataclass
class IntelEditorial:
    """Resultado da análise de inteligência editorial expandida."""
    # Sub-scores novos (todos opcionais, adicionam ao score base)
    score_porto_do_acu: int = 0
    score_watchlist_alerj: int = 0
    score_intencao_busca: int = 0
    score_surto_cobertura: int = 0
    score_continuidade_editorial: int = 0
    score_oportunidade_editorial: int = 0
    score_investigativo_transparencia: int = 0
    score_discover_utilidade: int = 0
    score_triangulacao_regional: int = 0
    score_temas_explosivos: int = 0
    score_regional_campos: int = 0
    score_regional_norte_fluminense: int = 0
    score_watchlist_geral: int = 0

    # Metadados de decisão
    watchlists_acionadas: list[str] = field(default_factory=list)
    aliases_resolvidos: list[str] = field(default_factory=list)
    termos_detectados: list[str] = field(default_factory=list)
    triangulacao_ativa: bool = False
    triangulacao_detalhe: str = ""
    urgencia_detectada: bool = False
    urgencia_detalhe: str = ""
    protocolo_verdade_ok: bool = True
    protocolo_verdade_detalhe: str = ""
    recomendacao: str = ""  # "publicacao_direta", "painel_prioridade", "fila_normal", "revisao"

    # Score total adicional (soma das camadas extras, limitado a 40)
    @property
    def score_adicional_total(self) -> int:
        total = (
            self.score_porto_do_acu +
            self.score_watchlist_alerj +
            self.score_intencao_busca +
            self.score_surto_cobertura +
            self.score_continuidade_editorial +
            self.score_oportunidade_editorial +
            self.score_investigativo_transparencia +
            self.score_discover_utilidade +
            self.score_triangulacao_regional +
            self.score_temas_explosivos +
            self.score_regional_campos +
            self.score_regional_norte_fluminense +
            self.score_watchlist_geral
        )
        return min(total, 40)  # hard cap: máx 40 pontos adicionais

    def resumo_log(self) -> str:
        """Retorna string resumida para o log do monitor/painel."""
        partes = []
        if self.score_porto_do_acu > 0:
            partes.append(f"PortoAçu+{self.score_porto_do_acu}")
        if self.score_watchlist_alerj > 0:
            partes.append(f"ALERJ+{self.score_watchlist_alerj}")
        if self.score_intencao_busca > 0:
            partes.append(f"SEO+{self.score_intencao_busca}")
        if self.score_investigativo_transparencia > 0:
            partes.append(f"Invest+{self.score_investigativo_transparencia}")
        if self.score_triangulacao_regional > 0:
            partes.append(f"Triang+{self.score_triangulacao_regional}")
        if self.score_temas_explosivos > 0:
            partes.append(f"Urgente+{self.score_temas_explosivos}")
        if self.triangulacao_ativa:
            partes.append(f"[TRIANGULAÇÃO:{self.triangulacao_detalhe[:30]}]")
        if self.urgencia_detectada:
            partes.append(f"[URGÊNCIA:{self.urgencia_detalhe[:20]}]")
        if not self.protocolo_verdade_ok:
            partes.append(f"[VERDADE:REVISAR]")
        if self.watchlists_acionadas:
            partes.append(f"Watch:{','.join(self.watchlists_acionadas[:3])}")
        return " | ".join(partes) if partes else "sem sinais extras"


# ── Carregadores de configuração com fallback ─────────────────────────────────

def _carregar_json(nome_arquivo: str, fallback: dict) -> dict:
    """Carrega JSON do diretório raiz do projeto, com fallback seguro."""
    try:
        p = _BASE / nome_arquivo
        if p.exists():
            dados = json.loads(p.read_text(encoding="utf-8"))
            return dados
    except Exception as e:
        print(f"[INTEL] Aviso: não foi possível carregar {nome_arquivo}: {e}")
    return fallback


_watchlists_cache: Optional[dict] = None
_aliases_cache: Optional[dict] = None


def _watchlists() -> dict:
    global _watchlists_cache
    if _watchlists_cache is None:
        _watchlists_cache = _carregar_json("watchlists_editoriais.json", {})
    return _watchlists_cache


def _aliases() -> dict:
    global _aliases_cache
    if _aliases_cache is None:
        dados = _carregar_json("aliases_editoriais.json", {})
        _aliases_cache = dados.get("aliases", {})
    return _aliases_cache


# ── Normalização de texto ─────────────────────────────────────────────────────

def _normalizar(texto: str) -> str:
    """Remove acentos, normaliza espaços e converte para minúsculas."""
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower()
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def _resolver_aliases(texto_low: str) -> tuple[str, list[str]]:
    """
    Substitui aliases conhecidos no texto normalizado.
    Retorna (texto_expandido, lista_de_aliases_resolvidos).
    """
    if not ENABLE_ALIASES:
        return texto_low, []

    aliases = _aliases()
    resolvidos = []
    texto_exp = texto_low

    for termo_canonico, variantes in aliases.items():
        # Suporte ao formato com _contexto_obrigatorio
        if isinstance(variantes, dict):
            context_needed = variantes.get("_contexto_obrigatorio", [])
            variantes_lista = variantes.get("aliases", [])
            # Verifica se algum contexto necessário está presente
            tem_contexto = any(_normalizar(c) in texto_low for c in context_needed)
            if not tem_contexto:
                continue
            variantes = variantes_lista

        for var in variantes:
            var_norm = _normalizar(var)
            if var_norm in texto_exp:
                # Adiciona o termo canônico normalizado ao texto para facilitar busca
                canonico_norm = _normalizar(termo_canonico)
                if canonico_norm not in texto_exp:
                    texto_exp = texto_exp + " " + canonico_norm
                    resolvidos.append(f"{var} → {termo_canonico}")

    return texto_exp, resolvidos


# ── Defaults internos (usados quando watchlists não existe) ───────────────────

_PORTO_DO_ACU_TERMOS = {
    "porto do açu", "porto do acu", "porto açu", "prumo",
    "prumo logística", "terminal portuário", "são joão da barra terminal",
    "petróleo porto", "gás porto", "logística porto açu",
    "empregos porto açu", "expansão porto", "offshore norte fluminense"
}

_ALERJ_TERMOS = {
    "alerj", "assembleia legislativa do rio",
    "assembleia legislativa do estado do rio de janeiro",
    "deputado estadual rio", "sessão plenária alerj",
    "projeto lei estadual", "plenário alerj"
}

_CAMPOS_NF_TERMOS = {
    "campos dos goytacazes", "norte fluminense", "macaé",
    "são joão da barra", "são francisco de itabapoana",
    "quissamã", "rio das ostras", "uenf", "iff campos",
    "itaperuna", "bom jesus do itabapoana"
}

_INTENCAO_BUSCA_TERMOS = {
    "morte", "morto", "morreu", "mortes", "óbito",
    "preso", "presa", "detido", "detida", "operação policial",
    "terremoto", "tsunami", "apagão", "fora do ar",
    "concurso público", "vagas", "edital", "inscrições",
    "inss benefício", "receita federal", "imposto", "tarifa",
    "vacina", "surto", "epidemia", "emergência",
    "greve", "paralisação", "interdição", "bloqueio",
    "candidato", "candidatura", "eleição", "pesquisa eleitoral",
    "stf decisão", "tribunal", "prisão preventiva",
    "futebol gol", "placar", "campeão", "copa",
    "enchente", "deslizamento", "desabamento", "incêndio"
}

_DISCOVER_UTILIDADE_TERMOS = {
    "bolso", "preço", "custo", "valor", "quanto custa",
    "como fazer", "como pedir", "como solicitar", "onde fica",
    "emprego", "salário", "benefício", "direito", "prazo",
    "saúde", "hospital", "upa", "escola", "matrícula",
    "ônibus", "trem", "metrô", "transporte", "rota",
    "água", "luz", "energia", "conta", "tarifa",
    "prova", "gabarito", "resultado", "nota",
    "auxílio", "cadastro", "cras", "creas"
}

_INVESTIGATIVO_TERMOS = {
    "licitação", "contrato público", "convênio", "repasse",
    "emenda parlamentar", "obra pública", "diário oficial",
    "tce", "auditoria", "investigado", "indiciado",
    "desvio", "corrupção", "superfaturamento", "fraude",
    "nomeação", "exoneração", "cargo comissionado",
    "dispensa licitação", "pregão", "doerj"
}

_TEMAS_EXPLOSIVOS_TERMOS = {
    "terremoto", "tsunami", "apagão",
    "whatsapp fora do ar", "instagram fora do ar",
    "facebook fora do ar", "x fora do ar",
    "grande operação policial", "operação especial",
    "crise política", "desastre", "mortos", "vítimas fatais",
    "alerta vermelho", "estado de emergência",
    "ataque armado", "explosão", "desabamento",
    "greve geral", "greve transporte"
}

# Termos de triangulação regional
_TRIANG_DEPUTADOS = {
    "deputado estadual", "alerj", "assembleia legislativa",
    "bancada", "partido", "vereador", "senador", "governador"
}
_TRIANG_REGIONAL = {
    "campos dos goytacazes", "norte fluminense", "macaé",
    "são joão da barra", "são francisco de itabapoana",
    "quissamã", "rio das ostras", "campos rj"
}
_TRIANG_MATERIAL = {
    "verbas", "emenda", "orçamento", "recursos",
    "repasse", "convênio", "obra", "contrato",
    "saúde", "educação", "segurança", "infraestrutura",
    "saneamento", "pavimentação", "hospital", "escola"
}

# Termos de dúvida para protocolo de verdade
_TERMOS_DUVIDA = {
    "ex-governador", "ex-prefeito", "ex-deputado", "ex-secretário",
    "ex-presidente", "ex-ministro",
    "confirmado", "definitivo", "certamente", "sem dúvida",
    "acusado", "culpado", "condenado"
}


# ── Funções de score ──────────────────────────────────────────────────────────

def _score_porto_do_acu(texto_norm: str, wl: dict) -> tuple[int, list[str]]:
    """Score para Porto do Açu como entidade editorial prioritária."""
    if not ENABLE_WATCHLISTS:
        return 0, []

    termos_wl = set()
    if "porto_do_acu" in wl:
        termos_wl = {_normalizar(t) for t in wl["porto_do_acu"].get("termos", [])}
    termos = termos_wl or _PORTO_DO_ACU_TERMOS

    encontrados = [t for t in termos if t in texto_norm]
    if not encontrados:
        return 0, []

    score = min(W_ENTIDADE_PORTO_DO_ACU, len(encontrados) * 6)
    return score, encontrados


def _score_watchlist_alerj(texto_norm: str, wl: dict) -> tuple[int, list[str]]:
    """Score para ALERJ e deputados estaduais."""
    if not ENABLE_WATCHLISTS:
        return 0, []

    score = 0
    encontrados = []

    # Termos institucionais
    termos_inst = set()
    if "politica_rj_instituicoes" in wl:
        termos_inst = {_normalizar(t) for t in wl["politica_rj_instituicoes"].get("termos", [])}
    termos_inst = termos_inst or _ALERJ_TERMOS

    for t in termos_inst:
        if t in texto_norm:
            score += 3
            encontrados.append(t)

    # Deputados estaduais
    if "deputados_estaduais_alerj" in wl:
        peso_dep = wl["deputados_estaduais_alerj"].get("_peso", W_WATCHLIST_ALERJ)
        for nome in wl["deputados_estaduais_alerj"].get("nomes", []):
            nome_norm = _normalizar(nome)
            if nome_norm in texto_norm:
                score += 4
                encontrados.append(nome)
                break  # evita inflação por múltiplos nomes

    return min(score, W_WATCHLIST_ALERJ * 2), encontrados


def _score_intencao_busca(texto_norm: str, wl: dict) -> tuple[int, list[str]]:
    """Score SEO baseado em intenção de busca."""
    termos_wl = set()
    if "temas_explosivos" in wl:
        termos_wl = {_normalizar(t) for t in wl["temas_explosivos"].get("termos", [])}
    termos = (termos_wl | _INTENCAO_BUSCA_TERMOS) if termos_wl else _INTENCAO_BUSCA_TERMOS

    encontrados = [t for t in termos if t in texto_norm]
    if not encontrados:
        return 0, []

    score = min(W_INTENCAO_BUSCA, len(encontrados) * 3)
    return score, encontrados[:5]


def _score_investigativo(texto_norm: str, wl: dict) -> tuple[int, list[str]]:
    """Score investigativo e de transparência."""
    termos_wl = set()
    if "termos_investigativos" in wl:
        termos_wl = {_normalizar(t) for t in wl["termos_investigativos"].get("termos", [])}
    if "termos_transparencia" in wl:
        termos_wl |= {_normalizar(t) for t in wl["termos_transparencia"].get("termos", [])}
    termos = termos_wl or _INVESTIGATIVO_TERMOS

    encontrados = [t for t in termos if t in texto_norm]
    if not encontrados:
        return 0, []

    score = min(W_INVESTIGATIVO_TRANSPARENCIA, len(encontrados) * 4)
    return score, encontrados[:5]


def _score_discover_utilidade(texto_norm: str, wl: dict) -> tuple[int, list[str]]:
    """Score para Google Discover e utilidade pública."""
    termos_wl = set()
    if "termos_servico" in wl:
        termos_wl = {_normalizar(t) for t in wl["termos_servico"].get("termos", [])}
    termos = termos_wl or _DISCOVER_UTILIDADE_TERMOS

    encontrados = [t for t in termos if t in texto_norm]
    if not encontrados:
        return 0, []

    score = min(W_DISCOVER_UTILIDADE, len(encontrados) * 2)
    return score, encontrados[:5]


def _score_regional_campos_nf(texto_norm: str, wl: dict) -> tuple[int, int, list[str]]:
    """Score de regionalidade expandida (Campos + Norte Fluminense separados)."""
    termos_wl = set()
    if "campos_norte_fluminense" in wl:
        termos_wl = {_normalizar(t) for t in wl["campos_norte_fluminense"].get("termos", [])}
    termos = termos_wl or _CAMPOS_NF_TERMOS

    termos_campos_especificos = {
        "campos dos goytacazes", "campos rj", "uenf", "iff campos",
        "wra campos", "prefeitura de campos", "câmara campos"
    }

    score_campos = 0
    score_nf = 0
    encontrados = []

    for t in termos:
        if t in texto_norm:
            encontrados.append(t)
            if t in termos_campos_especificos:
                score_campos += W_REGIONAL_CAMPOS // 3
            else:
                score_nf += W_REGIONAL_NORTE_FLUMINENSE // 4

    return (
        min(score_campos, W_REGIONAL_CAMPOS),
        min(score_nf, W_REGIONAL_NORTE_FLUMINENSE),
        encontrados[:5]
    )


def _score_temas_explosivos(texto_norm: str, wl: dict) -> tuple[int, str]:
    """Score de urgência para temas explosivos."""
    termos_wl = set()
    if "temas_explosivos" in wl:
        termos_wl = {_normalizar(t) for t in wl["temas_explosivos"].get("termos", [])}
    termos = termos_wl or _TEMAS_EXPLOSIVOS_TERMOS

    for t in termos:
        if t in texto_norm:
            return W_TEMAS_EXPLOSIVOS, t
    return 0, ""


def _triangulacao_regional(texto_norm: str) -> tuple[int, bool, str]:
    """
    Triangulação estratégica: deputado + região + verba/serviço.
    Retorna (score, ativa, detalhe).
    """
    if not ENABLE_TRIANGULACAO_REGIONAL:
        return 0, False, ""

    tem_deputado = any(t in texto_norm for t in _TRIANG_DEPUTADOS)
    tem_regional = any(t in texto_norm for t in _TRIANG_REGIONAL)
    tem_material = any(t in texto_norm for t in _TRIANG_MATERIAL)

    if tem_deputado and tem_regional and tem_material:
        detalhe = f"dep={tem_deputado} + reg={tem_regional} + mat={tem_material}"
        return W_TRIANGULACAO_REGIONAL, True, detalhe

    if tem_deputado and tem_regional:
        return W_TRIANGULACAO_REGIONAL // 2, True, "dep+região (sem material)"

    return 0, False, ""


def _protocolo_verdade(texto_norm: str, titulo: str) -> tuple[bool, str]:
    """
    Verificador antialucinação básico.
    Detecta termos que indicam dúvida sobre cargo/fato atual.
    """
    if not ENABLE_PROTOCOLO_VERDADE:
        return True, ""

    titulo_norm = _normalizar(titulo)
    texto_completo = titulo_norm + " " + texto_norm

    problemas = []
    for termo in _TERMOS_DUVIDA:
        if termo in texto_completo:
            problemas.append(termo)

    # Heurística: se título usa cargo mas texto usa "ex-"
    if "governador" in titulo_norm and "ex-governador" in texto_norm:
        problemas.append("cargo 'governador' no título vs 'ex-governador' no texto")

    if problemas:
        return False, f"Termos que exigem revisão: {', '.join(problemas[:3])}"

    return True, ""


def _watchlist_geral(texto_norm: str, wl: dict) -> tuple[int, list[str]]:
    """Score geral de watchlist (protagonistas + investigados)."""
    if not ENABLE_WATCHLISTS:
        return 0, []

    score = 0
    acionadas = []

    for grupo_key in ["protagonistas_executivo_top_seo", "figuras_impacto_investigados"]:
        grupo = wl.get(grupo_key, {})
        peso = grupo.get("_peso", 6)
        for nome in grupo.get("nomes", []):
            nome_norm = _normalizar(nome)
            if nome_norm in texto_norm:
                score += peso // 2
                acionadas.append(nome)
                break  # um nome por grupo

    return min(score, 15), acionadas


# ── Função principal ──────────────────────────────────────────────────────────

def analisar_intel_editorial(
    titulo: str,
    resumo: str = "",
    texto_fonte: str = "",
    canal: str = "",
) -> IntelEditorial:
    """
    Função principal de análise de inteligência editorial.

    Recebe título, resumo e texto da pauta, retorna IntelEditorial com
    todos os sub-scores adicionais e metadados de decisão.

    FALLBACK TOTAL: Se qualquer erro ocorrer, retorna IntelEditorial() vazio (zeros).
    O score base de scoring.py não é afetado.
    """
    try:
        return _analisar_impl(titulo, resumo, texto_fonte, canal)
    except Exception as e:
        print(f"[INTEL] Erro na análise editorial (fallback seguro): {e}")
        return IntelEditorial()


def _analisar_impl(
    titulo: str,
    resumo: str,
    texto_fonte: str,
    canal: str,
) -> IntelEditorial:
    """Implementação interna da análise editorial."""
    intel = IntelEditorial()
    wl = _watchlists() if ENABLE_WATCHLISTS else {}

    # Normaliza texto completo para análise
    texto_completo = f"{titulo} {resumo} {texto_fonte[:2000]}"
    texto_norm, aliases_resolvidos = _resolver_aliases(_normalizar(texto_completo))

    intel.aliases_resolvidos = aliases_resolvidos

    # ── Porto do Açu ──────────────────────────────────────────────────────────
    sc_pa, termos_pa = _score_porto_do_acu(texto_norm, wl)
    intel.score_porto_do_acu = sc_pa
    if termos_pa:
        intel.termos_detectados.extend(termos_pa[:2])

    # ── ALERJ / Watchlist política ────────────────────────────────────────────
    sc_al, termos_al = _score_watchlist_alerj(texto_norm, wl)
    intel.score_watchlist_alerj = sc_al
    if termos_al:
        intel.watchlists_acionadas.append("ALERJ")

    # ── Regionalidade expandida (Campos + Norte Fluminense) ───────────────────
    sc_campos, sc_nf, termos_reg = _score_regional_campos_nf(texto_norm, wl)
    intel.score_regional_campos = sc_campos
    intel.score_regional_norte_fluminense = sc_nf
    if termos_reg:
        intel.termos_detectados.extend(termos_reg[:2])

    # ── Intenção de busca SEO ─────────────────────────────────────────────────
    sc_seo, termos_seo = _score_intencao_busca(texto_norm, wl)
    intel.score_intencao_busca = sc_seo

    # ── Investigativo e transparência ─────────────────────────────────────────
    sc_inv, termos_inv = _score_investigativo(texto_norm, wl)
    intel.score_investigativo_transparencia = sc_inv
    if termos_inv:
        intel.watchlists_acionadas.append("Investigativo")

    # ── Discover / Utilidade ──────────────────────────────────────────────────
    sc_disc, termos_disc = _score_discover_utilidade(texto_norm, wl)
    intel.score_discover_utilidade = sc_disc

    # ── Temas explosivos / Urgência ───────────────────────────────────────────
    sc_exp, termo_exp = _score_temas_explosivos(texto_norm, wl)
    intel.score_temas_explosivos = sc_exp
    if sc_exp > 0:
        intel.urgencia_detectada = True
        intel.urgencia_detalhe = termo_exp
        intel.watchlists_acionadas.append("Urgência")

    # ── Triangulação regional ─────────────────────────────────────────────────
    sc_tri, tri_ativa, tri_detalhe = _triangulacao_regional(texto_norm)
    intel.score_triangulacao_regional = sc_tri
    intel.triangulacao_ativa = tri_ativa
    intel.triangulacao_detalhe = tri_detalhe
    if tri_ativa:
        intel.watchlists_acionadas.append("Triangulação")

    # ── Watchlist geral ───────────────────────────────────────────────────────
    sc_wl, nomes_wl = _watchlist_geral(texto_norm, wl)
    intel.score_watchlist_geral = sc_wl
    if nomes_wl:
        intel.watchlists_acionadas.extend(nomes_wl[:2])

    # ── Protocolo de verdade ──────────────────────────────────────────────────
    pv_ok, pv_detalhe = _protocolo_verdade(texto_norm, titulo)
    intel.protocolo_verdade_ok = pv_ok
    intel.protocolo_verdade_detalhe = pv_detalhe

    # ── Recomendação consolidada ──────────────────────────────────────────────
    total = intel.score_adicional_total

    if not pv_ok:
        intel.recomendacao = "revisao"
    elif total >= 30 or intel.urgencia_detectada:
        intel.recomendacao = "painel_prioridade"
    elif total >= 15:
        intel.recomendacao = "painel_prioridade"
    else:
        intel.recomendacao = "fila_normal"

    return intel


# ── Integração com scoring.py (função de conveniência) ────────────────────────

def enriquecer_pauta_com_intel(pauta: dict) -> dict:
    """
    Adiciona análise intel_editorial ao dict de uma pauta.

    Não modifica campos existentes — apenas adiciona '_intel_editorial'.
    Fallback: se falhar, retorna pauta sem modificação.
    """
    try:
        intel = analisar_intel_editorial(
            titulo=pauta.get("titulo_origem", ""),
            resumo=pauta.get("resumo_origem", ""),
            texto_fonte=pauta.get("texto_fonte", ""),
            canal=pauta.get("canal_forcado", ""),
        )
        pauta["_intel_editorial"] = intel
        # Expõe score adicional para uso em scoring.py sem modificar sua estrutura
        pauta["_score_intel_adicional"] = intel.score_adicional_total
        pauta["_intel_urgencia"] = intel.urgencia_detectada
        pauta["_intel_triangulacao"] = intel.triangulacao_ativa
        pauta["_intel_protocolo_ok"] = intel.protocolo_verdade_ok
        pauta["_intel_watchlists"] = intel.watchlists_acionadas
        pauta["_intel_log"] = intel.resumo_log()
    except Exception as e:
        print(f"[INTEL] enriquecer_pauta_com_intel falhou (fallback): {e}")
    return pauta
