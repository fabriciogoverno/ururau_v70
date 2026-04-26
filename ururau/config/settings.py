"""
config/settings.py — Camada central de configuração do Ururau.
Todas as variáveis de ambiente, constantes e parâmetros operacionais em um único lugar.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv(override=True)


def _int(key: str, default: int) -> int:
    return int(os.getenv(key, str(default)) or str(default))


def _bool(key: str, default: bool) -> bool:
    v = os.getenv(key, "true" if default else "false").strip().lower()
    return v in {"1", "true", "sim", "yes"}


def _str(key: str, default: str) -> str:
    return os.getenv(key, default).strip()


# ── Credenciais ───────────────────────────────────────────────────────────────
OPENAI_API_KEY  = _str("OPENAI_API_KEY", "")
LOGIN           = _str("URURAU_LOGIN", "")
SENHA           = _str("URURAU_SENHA", "")
ASSINATURA_FIXA = _str("URURAU_ASSINATURA", "Fabrício Freitas")

# ── Modelo de IA ──────────────────────────────────────────────────────────────
MODELO_OPENAI   = _str("OPENAI_MODEL", "gpt-4.1-mini")

# ── URLs do CMS ───────────────────────────────────────────────────────────────
SITE_LOGIN_URL  = _str("SITE_LOGIN_URL",  "https://www.ururau.com.br/acessocpainel/")
SITE_NOVA_URL   = _str("SITE_NOVA_URL",   "https://www.ururau.com.br/acessocpainel/noticias/nova/")

# ── Playwright ────────────────────────────────────────────────────────────────
HEADLESS        = _bool("HEADLESS", False)
SLOW_MO         = _int("SLOW_MO", 150)

# ── Ciclos e limites ──────────────────────────────────────────────────────────
INTERVALO_ENTRE_CICLOS_SEGUNDOS          = _int("INTERVALO_ENTRE_CICLOS_SEGUNDOS", 1800)
MAX_CANDIDATAS_AVALIADAS                 = _int("MAX_CANDIDATAS_AVALIADAS", 24)
MAX_PUBLICACOES_POR_CICLO                = _int("MAX_PUBLICACOES_POR_CICLO", 3)
MAX_PUBLICACOES_POR_CANAL                = _int("MAX_PUBLICACOES_POR_CANAL", 1)
MAX_PUBLICACOES_IMEDIATAS                = _int("MAX_PUBLICACOES_IMEDIATAS", 10)
MAX_PUBLICACOES_MONITORAMENTO_POR_HORA   = _int("MAX_PUBLICACOES_MONITORAMENTO_POR_HORA", 4)
MAX_EXTRA_URGENTE_POR_HORA               = _int("MAX_EXTRA_URGENTE_POR_HORA", 1)

# ── Limiares editoriais ───────────────────────────────────────────────────────
LIMIAR_RELEVANCIA_PUBLICAR  = _int("LIMIAR_RELEVANCIA_PUBLICAR", 28)
LIMIAR_RELEVANCIA_URGENTE   = _int("LIMIAR_RELEVANCIA_URGENTE", 52)
LIMIAR_RISCO_MAXIMO         = _int("LIMIAR_RISCO_MAXIMO", 70)   # bloqueia publicação automática

# ── Anti-duplicação ───────────────────────────────────────────────────────────
JANELA_ANTIDUPLICACAO_HORAS = _int("JANELA_ANTIDUPLICACAO_HORAS", 48)
MAX_ITENS_URURAU_RECENTES   = _int("MAX_ITENS_URURAU_RECENTES", 80)

# ── Texto ─────────────────────────────────────────────────────────────────────
MIN_CARACTERES_MATERIA  = _int("MIN_CARACTERES_MATERIA", 2000)
ALVO_CARACTERES_MATERIA = _int("ALVO_CARACTERES_MATERIA", 3400)
MAX_CARACTERES_MATERIA  = _int("MAX_CARACTERES_MATERIA", 6200)
MAX_FONTES_APURACAO     = _int("MAX_FONTES_APURACAO", 4)

# ── Imagem ────────────────────────────────────────────────────────────────────
QUALIDADE_JPEG_FINAL             = _int("QUALIDADE_JPEG_FINAL", 95)
MIN_LARGURA_IMAGEM_PUBLICAVEL    = _int("MIN_LARGURA_IMAGEM_PUBLICAVEL", 500)
MIN_ALTURA_IMAGEM_PUBLICAVEL     = _int("MIN_ALTURA_IMAGEM_PUBLICAVEL", 350)
USAR_PLAYWRIGHT_IMAGEM           = _bool("USAR_PLAYWRIGHT_IMAGEM", True)
USAR_BING_IMAGEM                 = _bool("USAR_BING_IMAGEM", True)
MAX_CANDIDATAS_IMAGEM            = _int("MAX_CANDIDATAS_IMAGEM", 25)

# ── Persistência ──────────────────────────────────────────────────────────────
ARQUIVO_HISTORICO  = _str("ARQUIVO_HISTORICO", "historico_unico.json")
ARQUIVO_DB         = _str("ARQUIVO_DB", "ururau.db")
PASTA_IMAGENS      = _str("PASTA_IMAGENS", "imagens")
PASTA_PRINTS       = _str("PASTA_PRINTS", "prints")
PASTA_LOGS         = _str("PASTA_LOGS", "logs")

# ── HTTP ──────────────────────────────────────────────────────────────────────
TIMEOUT_PADRAO = _int("TIMEOUT_PADRAO", 30)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ── Intel Editorial — pesos e feature flags ──────────────────────────────────
# Pesos dos sub-scores de inteligência editorial (camada aditiva sobre scoring.py)
W_PORTO_DO_ACU              = _int("W_PORTO_DO_ACU", 18)
W_WATCHLIST_ALERJ           = _int("W_WATCHLIST_ALERJ", 10)
W_INTENCAO_BUSCA            = _int("W_INTENCAO_BUSCA", 8)
W_SURTO_COBERTURA           = _int("W_SURTO_COBERTURA", 6)
W_CONTINUIDADE_EDITORIAL    = _int("W_CONTINUIDADE_EDITORIAL", 5)
W_OPORTUNIDADE_EDITORIAL    = _int("W_OPORTUNIDADE_EDITORIAL", 7)
W_INVESTIGATIVO_TRANSPARENCIA = _int("W_INVESTIGATIVO_TRANSPARENCIA", 12)
W_DISCOVER_UTILIDADE        = _int("W_DISCOVER_UTILIDADE", 6)
W_TRIANGULACAO_REGIONAL     = _int("W_TRIANGULACAO_REGIONAL", 15)
W_TEMAS_EXPLOSIVOS          = _int("W_TEMAS_EXPLOSIVOS", 20)
W_REGIONAL_CAMPOS           = _int("W_REGIONAL_CAMPOS", 20)
W_REGIONAL_NORTE_FLUMINENSE = _int("W_REGIONAL_NORTE_FLUMINENSE", 15)
W_ENTIDADE_PORTO_DO_ACU     = _int("W_ENTIDADE_PORTO_DO_ACU", 18)
W_WATCHLIST_GERAL           = _int("W_WATCHLIST_GERAL", 8)
W_PRE_CANDIDATOS            = _int("W_PRE_CANDIDATOS", 11)

# Feature flags de intel editorial
ENABLE_WATCHLISTS               = _bool("ENABLE_WATCHLISTS", True)
ENABLE_ALIASES                  = _bool("ENABLE_ALIASES", True)
ENABLE_LEITURA_FONTE            = _bool("ENABLE_LEITURA_FONTE", True)
ENABLE_TRIANGULACAO_REGIONAL    = _bool("ENABLE_TRIANGULACAO_REGIONAL", True)
ENABLE_OPORTUNIDADE_EDITORIAL   = _bool("ENABLE_OPORTUNIDADE_EDITORIAL", True)
ENABLE_PROTOCOLO_VERDADE        = _bool("ENABLE_PROTOCOLO_VERDADE", True)
ENABLE_FONTES_OFICIAIS_PRIORITARIAS = _bool("ENABLE_FONTES_OFICIAIS_PRIORITARIAS", True)

# Limiares de decisão do monitor (tiers expandidos)
SCORE_MONITOR_DIRETO_IMEDIATO   = _int("SCORE_MONITOR_DIRETO_IMEDIATO", 90)   # pub. direta imediata
SCORE_MONITOR_DIRETO_CONFIANCA  = _int("SCORE_MONITOR_DIRETO_CONFIANCA", 80)  # direta se alta confiança
SCORE_MONITOR_PAINEL_PRIORIDADE = _int("SCORE_MONITOR_PAINEL_PRIORIDADE", 65) # painel prioritário
# <65 → fila normal de painel

# Leitura da fonte
TIMEOUT_LEITURA_FONTE   = _int("TIMEOUT_LEITURA_FONTE", 12)   # segundos
CACHE_LEITURA_FONTE_MIN = _int("CACHE_LEITURA_FONTE_MIN", 30) # minutos

# ── Canais ────────────────────────────────────────────────────────────────────
CANAIS_RODIZIO = [
    "Política", "Estado RJ", "Cidades", "Polícia", "Economia",
    "Esportes", "Saúde", "Educação", "Tecnologia", "Rural",
    "Entretenimento", "Curiosidades", "Brasil e Mundo", "Opinião",
    "Bizarro", "Carnaval", "Podcast",
]

# Lista exata de canais disponíveis no CMS (para o select name="canais")
CANAIS_CMS = [
    "Bizarro", "Brasil e Mundo", "Carnaval", "Cidades", "Curiosidades",
    "Economia", "Educação", "Entretenimento", "Esportes", "Estado RJ",
    "Opinião", "Podcast", "Polícia", "Política", "Rural", "Saúde", "Tecnologia",
]
CANAIS_COM_FOCO_RJ = {"Política", "Estado RJ", "Cidades", "Polícia"}

# ── Categorias de erro editorial ─────────────────────────────────────────────
# Usadas em erros_validacao de toda matéria gerada.
class CategoriaErro:
    CONFIG_ERROR       = "CONFIG_ERROR"        # chave API inválida, modelo ausente
    EXTRACTION_ERROR   = "EXTRACTION_ERROR"    # fonte vazia, extração falhou
    EDITORIAL_BLOCKER  = "EDITORIAL_BLOCKER"   # fato inventado, data inválida, etc.
    FIXABLE_FIELD      = "FIXABLE_FIELD"       # campo ausente/curto, corrigível
    WARNING            = "WARNING"             # aviso editorial, não bloqueia

# Códigos específicos de CONFIG_ERROR
CODIGO_OPENAI_INVALID_API_KEY  = "openai_invalid_api_key"
CODIGO_OPENAI_MISSING_API_KEY  = "openai_missing_api_key"
CODIGO_OPENAI_QUOTA_ERROR      = "openai_quota_error"
CODIGO_OPENAI_TIMEOUT          = "openai_timeout"
CODIGO_OPENAI_MODEL_NOT_SET    = "model_not_configured"

# Códigos específicos de EXTRACTION_ERROR
CODIGO_SOURCE_TOO_SHORT        = "source_too_short"
CODIGO_SOURCE_EMPTY            = "source_empty"
CODIGO_RELATED_LINKS_IN_BODY   = "related_links_in_body"
CODIGO_EXTRACTION_FAILED       = "extraction_failed"
CODIGO_CLEANED_SOURCE_TOO_SMALL = "cleaned_source_too_small"

# Status de validação expandido
STATUS_VALIDACAO_APROVADO          = "aprovado"
STATUS_VALIDACAO_PENDENTE          = "pendente"
STATUS_VALIDACAO_REPROVADO         = "reprovado"
STATUS_VALIDACAO_ERRO_CONFIGURACAO = "erro_configuracao"
STATUS_VALIDACAO_ERRO_EXTRACAO     = "erro_extracao"


# ── Resultado de validação de config ─────────────────────────────────────────

@dataclass
class ConfigValidationResult:
    ok: bool = False
    reason: str = ""
    codigo: str = ""
    # Erro padronizado para inserir em erros_validacao
    erro_dict: dict = field(default_factory=dict)

    def __bool__(self):
        return self.ok


def _build_config_error(codigo: str, mensagem: str, sugestao: str) -> dict:
    """Monta dict de erro CONFIG_ERROR padronizado."""
    return {
        "codigo": codigo,
        "categoria": CategoriaErro.CONFIG_ERROR,
        "severidade": "alta",
        "campo": "OPENAI_API_KEY",
        "mensagem": mensagem,
        "trecho": "",
        "sugestao": sugestao,
        "bloqueia_publicacao": True,
        "corrigivel_automaticamente": False,
    }


# Placeholders que indicam chave não configurada
_PLACEHOLDERS_CHAVE = {
    "", "sua_chave_aqui", "sk-...", "sk-proj-...",
    "coloque_sua_chave", "insira_sua_chave",
    "your_api_key_here", "sk-XXXXXXXX",
}


def validate_openai_config(api_key: str = "", modelo: str = "") -> ConfigValidationResult:
    """
    Valida a configuração da OpenAI ANTES de qualquer chamada à API.

    Verifica:
    - OPENAI_API_KEY existe, não é vazia, não é placeholder
    - Modelo está configurado como gpt-4.1-mini (ou compatível)

    Retorna ConfigValidationResult com ok=True se tudo correto.
    Se inválida, retorna ok=False com erro_dict pronto para erros_validacao.

    Uso obrigatório:
        result = validate_openai_config()
        if not result:
            # não chamar geração — salvar como erro_configuracao
            return resultado_config_error(result)
    """
    # Recarrega do ambiente para pegar valor atual (após usuário editar .env)
    load_dotenv(override=True)
    chave = api_key or os.getenv("OPENAI_API_KEY", "").strip()
    mod   = modelo or os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip()

    # 1. Chave ausente
    if not chave:
        err = _build_config_error(
            CODIGO_OPENAI_MISSING_API_KEY,
            "OPENAI_API_KEY não configurada. Nenhuma matéria pode ser gerada.",
            "Abra o arquivo .env, adicione OPENAI_API_KEY=sk-... e clique em Reprocessar.",
        )
        print("[OPENAI_CONFIG] ok=false reason=missing_api_key")
        return ConfigValidationResult(ok=False, reason="missing_api_key",
                                      codigo=CODIGO_OPENAI_MISSING_API_KEY, erro_dict=err)

    # 2. Chave é placeholder
    if chave.lower() in _PLACEHOLDERS_CHAVE or chave.lower().startswith("sua_") or (
        chave.startswith("sk-") and len(chave) < 20
    ):
        err = _build_config_error(
            CODIGO_OPENAI_INVALID_API_KEY,
            f"OPENAI_API_KEY parece ser um placeholder ('{chave[:12]}...'). "
            "Configure uma chave real antes de gerar matérias.",
            "Atualize OPENAI_API_KEY no .env com sua chave sk-... real e clique em Reprocessar.",
        )
        print(f"[OPENAI_CONFIG] ok=false reason=placeholder_key key={chave[:12]}")
        return ConfigValidationResult(ok=False, reason="placeholder_key",
                                      codigo=CODIGO_OPENAI_INVALID_API_KEY, erro_dict=err)

    # 3. Modelo não configurado ou inválido
    if not mod:
        err = _build_config_error(
            CODIGO_OPENAI_MODEL_NOT_SET,
            "OPENAI_MODEL não configurado. Defina como 'gpt-4.1-mini'.",
            "Adicione OPENAI_MODEL=gpt-4.1-mini no .env.",
        )
        print("[OPENAI_CONFIG] ok=false reason=model_not_configured")
        return ConfigValidationResult(ok=False, reason="model_not_configured",
                                      codigo=CODIGO_OPENAI_MODEL_NOT_SET, erro_dict=err)

    print(f"[OPENAI_CONFIG] ok=true key={chave[:8]}... model={mod}")
    return ConfigValidationResult(ok=True, reason="", codigo="")


def classify_openai_exception(exc: Exception) -> ConfigValidationResult:
    """
    Classifica uma exceção da OpenAI API em CONFIG_ERROR padronizado.

    Usado para tratar erros HTTP 401, 429, timeout, etc.
    Retorna ConfigValidationResult com ok=False e erro_dict preenchido.
    """
    msg = str(exc).lower()

    # 401 — Invalid API key
    if "401" in msg or "incorrect api key" in msg or "invalid_api_key" in msg or "authentication" in msg:
        err = _build_config_error(
            CODIGO_OPENAI_INVALID_API_KEY,
            "Chave da OpenAI inválida ou sem permissão (erro 401). "
            "Nenhuma matéria pode ser gerada com esta chave.",
            "Atualize OPENAI_API_KEY no .env com uma chave válida e clique em Reprocessar.",
        )
        print(f"[OPENAI_CONFIG] ok=false reason=invalid_api_key exception={str(exc)[:80]}")
        return ConfigValidationResult(ok=False, reason="invalid_api_key",
                                      codigo=CODIGO_OPENAI_INVALID_API_KEY, erro_dict=err)

    # 429 — Quota / rate limit
    if "429" in msg or "quota" in msg or "rate_limit" in msg or "insufficient_quota" in msg:
        err = _build_config_error(
            CODIGO_OPENAI_QUOTA_ERROR,
            "Cota da OpenAI esgotada ou limite de taxa atingido (erro 429). "
            "Aguarde ou atualize seu plano.",
            "Verifique sua cota em platform.openai.com e tente novamente em alguns minutos.",
        )
        print(f"[OPENAI_CONFIG] ok=false reason=quota_error exception={str(exc)[:80]}")
        return ConfigValidationResult(ok=False, reason="quota_error",
                                      codigo=CODIGO_OPENAI_QUOTA_ERROR, erro_dict=err)

    # Timeout
    if "timeout" in msg or "timed out" in msg:
        err = _build_config_error(
            CODIGO_OPENAI_TIMEOUT,
            "Timeout na conexão com a OpenAI. A API não respondeu no prazo.",
            "Verifique sua conexão de internet e clique em Reprocessar.",
        )
        print(f"[OPENAI_CONFIG] ok=false reason=timeout exception={str(exc)[:80]}")
        return ConfigValidationResult(ok=False, reason="timeout",
                                      codigo=CODIGO_OPENAI_TIMEOUT, erro_dict=err)

    # Erro genérico — não é config error, propaga como exceção
    return ConfigValidationResult(ok=True, reason="non_config_error", codigo="")


# ── Workflow: estados formais de pauta ────────────────────────────────────────
class StatusPauta:
    CAPTADA      = "captada"
    TRIADA       = "triada"
    APROVADA     = "aprovada"
    EM_REDACAO   = "em_redacao"
    REVISADA     = "revisada"
    PRONTA       = "pronta"
    PUBLICADA    = "publicada"
    REJEITADA    = "rejeitada"
    BLOQUEADA    = "bloqueada"
    EXCLUIDA     = "excluida"   # exclusão manual pelo editor — oculta por padrão na fila

    # Filtro padrão da fila (excluídas ficam fora)
    TODOS = [CAPTADA, TRIADA, APROVADA, EM_REDACAO, REVISADA, PRONTA, PUBLICADA, REJEITADA, BLOQUEADA]
    # Lista completa incluindo excluídas (para o seletor específico)
    TODOS_COM_EXCLUIDAS = TODOS + [EXCLUIDA]


def recarregar():
    """Recarrega variáveis do .env em runtime (usado pelo painel de Config)."""
    load_dotenv(override=True)
    global OPENAI_API_KEY, LOGIN, SENHA, ASSINATURA_FIXA, MODELO_OPENAI
    global HEADLESS, SLOW_MO, INTERVALO_ENTRE_CICLOS_SEGUNDOS
    global MAX_CANDIDATAS_AVALIADAS, MAX_PUBLICACOES_POR_CICLO, MAX_PUBLICACOES_POR_CANAL
    global LIMIAR_RELEVANCIA_PUBLICAR, LIMIAR_RELEVANCIA_URGENTE, LIMIAR_RISCO_MAXIMO
    global JANELA_ANTIDUPLICACAO_HORAS, MAX_ITENS_URURAU_RECENTES
    global MIN_CARACTERES_MATERIA, ALVO_CARACTERES_MATERIA, MAX_CARACTERES_MATERIA
    global MAX_FONTES_APURACAO, QUALIDADE_JPEG_FINAL
    global MIN_LARGURA_IMAGEM_PUBLICAVEL, MIN_ALTURA_IMAGEM_PUBLICAVEL
    global USAR_PLAYWRIGHT_IMAGEM, USAR_BING_IMAGEM, MAX_CANDIDATAS_IMAGEM
    # Intel editorial
    global W_PORTO_DO_ACU, W_WATCHLIST_ALERJ, W_INTENCAO_BUSCA, W_SURTO_COBERTURA
    global W_CONTINUIDADE_EDITORIAL, W_OPORTUNIDADE_EDITORIAL, W_INVESTIGATIVO_TRANSPARENCIA
    global W_DISCOVER_UTILIDADE, W_TRIANGULACAO_REGIONAL, W_TEMAS_EXPLOSIVOS
    global W_REGIONAL_CAMPOS, W_REGIONAL_NORTE_FLUMINENSE, W_ENTIDADE_PORTO_DO_ACU
    global W_WATCHLIST_GERAL, W_PRE_CANDIDATOS
    global ENABLE_WATCHLISTS, ENABLE_ALIASES, ENABLE_LEITURA_FONTE
    global ENABLE_TRIANGULACAO_REGIONAL, ENABLE_OPORTUNIDADE_EDITORIAL
    global ENABLE_PROTOCOLO_VERDADE, ENABLE_FONTES_OFICIAIS_PRIORITARIAS
    global SCORE_MONITOR_DIRETO_IMEDIATO, SCORE_MONITOR_DIRETO_CONFIANCA
    global SCORE_MONITOR_PAINEL_PRIORIDADE
    global TIMEOUT_LEITURA_FONTE, CACHE_LEITURA_FONTE_MIN

    OPENAI_API_KEY  = _str("OPENAI_API_KEY", "")
    LOGIN           = _str("URURAU_LOGIN", "")
    SENHA           = _str("URURAU_SENHA", "")
    ASSINATURA_FIXA = _str("URURAU_ASSINATURA", "Fabrício Freitas")
    MODELO_OPENAI   = _str("OPENAI_MODEL", "gpt-4.1-mini")
    HEADLESS        = _bool("HEADLESS", False)
    SLOW_MO         = _int("SLOW_MO", 150)
    LIMIAR_RELEVANCIA_PUBLICAR = _int("LIMIAR_RELEVANCIA_PUBLICAR", 28)
    LIMIAR_RELEVANCIA_URGENTE  = _int("LIMIAR_RELEVANCIA_URGENTE", 52)
    LIMIAR_RISCO_MAXIMO        = _int("LIMIAR_RISCO_MAXIMO", 70)
    MIN_CARACTERES_MATERIA     = _int("MIN_CARACTERES_MATERIA", 2000)
    ALVO_CARACTERES_MATERIA    = _int("ALVO_CARACTERES_MATERIA", 3400)
    MAX_CARACTERES_MATERIA     = _int("MAX_CARACTERES_MATERIA", 6200)
    QUALIDADE_JPEG_FINAL       = _int("QUALIDADE_JPEG_FINAL", 95)
    MIN_LARGURA_IMAGEM_PUBLICAVEL = _int("MIN_LARGURA_IMAGEM_PUBLICAVEL", 500)
    MIN_ALTURA_IMAGEM_PUBLICAVEL  = _int("MIN_ALTURA_IMAGEM_PUBLICAVEL", 350)
    # Intel editorial
    W_PORTO_DO_ACU              = _int("W_PORTO_DO_ACU", 18)
    W_WATCHLIST_ALERJ           = _int("W_WATCHLIST_ALERJ", 10)
    W_INTENCAO_BUSCA            = _int("W_INTENCAO_BUSCA", 8)
    W_SURTO_COBERTURA           = _int("W_SURTO_COBERTURA", 6)
    W_CONTINUIDADE_EDITORIAL    = _int("W_CONTINUIDADE_EDITORIAL", 5)
    W_OPORTUNIDADE_EDITORIAL    = _int("W_OPORTUNIDADE_EDITORIAL", 7)
    W_INVESTIGATIVO_TRANSPARENCIA = _int("W_INVESTIGATIVO_TRANSPARENCIA", 12)
    W_DISCOVER_UTILIDADE        = _int("W_DISCOVER_UTILIDADE", 6)
    W_TRIANGULACAO_REGIONAL     = _int("W_TRIANGULACAO_REGIONAL", 15)
    W_TEMAS_EXPLOSIVOS          = _int("W_TEMAS_EXPLOSIVOS", 20)
    W_REGIONAL_CAMPOS           = _int("W_REGIONAL_CAMPOS", 20)
    W_REGIONAL_NORTE_FLUMINENSE = _int("W_REGIONAL_NORTE_FLUMINENSE", 15)
    W_ENTIDADE_PORTO_DO_ACU     = _int("W_ENTIDADE_PORTO_DO_ACU", 18)
    W_WATCHLIST_GERAL           = _int("W_WATCHLIST_GERAL", 8)
    W_PRE_CANDIDATOS            = _int("W_PRE_CANDIDATOS", 11)
    ENABLE_WATCHLISTS               = _bool("ENABLE_WATCHLISTS", True)
    ENABLE_ALIASES                  = _bool("ENABLE_ALIASES", True)
    ENABLE_LEITURA_FONTE            = _bool("ENABLE_LEITURA_FONTE", True)
    ENABLE_TRIANGULACAO_REGIONAL    = _bool("ENABLE_TRIANGULACAO_REGIONAL", True)
    ENABLE_OPORTUNIDADE_EDITORIAL   = _bool("ENABLE_OPORTUNIDADE_EDITORIAL", True)
    ENABLE_PROTOCOLO_VERDADE        = _bool("ENABLE_PROTOCOLO_VERDADE", True)
    ENABLE_FONTES_OFICIAIS_PRIORITARIAS = _bool("ENABLE_FONTES_OFICIAIS_PRIORITARIAS", True)
    SCORE_MONITOR_DIRETO_IMEDIATO   = _int("SCORE_MONITOR_DIRETO_IMEDIATO", 90)
    SCORE_MONITOR_DIRETO_CONFIANCA  = _int("SCORE_MONITOR_DIRETO_CONFIANCA", 80)
    SCORE_MONITOR_PAINEL_PRIORIDADE = _int("SCORE_MONITOR_PAINEL_PRIORIDADE", 65)
    TIMEOUT_LEITURA_FONTE   = _int("TIMEOUT_LEITURA_FONTE", 12)
    CACHE_LEITURA_FONTE_MIN = _int("CACHE_LEITURA_FONTE_MIN", 30)
