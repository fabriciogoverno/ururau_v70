"""
coleta/scoring.py — Motor editorial do Ururau v2.
Score composto multidimensional com pesos configuráveis por editoria.

ARQUITETURA:
  ScoreDetalhado — dataclass com todos os sub-scores e justificativas
  classificar_canal() — roteamento editorial rigoroso com prioridades
  calcular_score_completo() — score composto: base + regional + esporte + saúde/rural + penalidades
  filtrar_e_ordenar() — filtra, limita por canal, garante cobertura mínima Saúde/Rural
  PESOS — dict global de pesos ajustáveis por config

CANAIS OFICIAIS DO URURAU:
  Bizarro, Brasil e Mundo, Carnaval, Cidades, Curiosidades,
  Economia, Educação, Entretenimento, Esportes, Estado RJ,
  Opinião, Podcast, Polícia, Política, Rural, Saúde, Tecnologia
"""
from __future__ import annotations

import re
import os
from dataclasses import dataclass, field
from typing import Optional


# ══════════════════════════════════════════════════════════════════════════════
# CANAIS OFICIAIS DO URURAU
# ══════════════════════════════════════════════════════════════════════════════

CANAIS_URURAU: list[str] = [
    "Bizarro", "Brasil e Mundo", "Carnaval", "Cidades", "Curiosidades",
    "Economia", "Educação", "Entretenimento", "Esportes", "Estado RJ",
    "Opinião", "Podcast", "Polícia", "Política", "Rural", "Saúde", "Tecnologia",
]

# ══════════════════════════════════════════════════════════════════════════════
# PESOS EDITORIALS — configuráveis via variáveis de ambiente ou dict externo
# ══════════════════════════════════════════════════════════════════════════════

def _int_env(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except Exception:
        return default

PESOS: dict[str, int] = {
    # ── Prioridade editorial por canal (boost no score_base) ────────────────
    "w_politica_rj":         _int_env("W_POLITICA_RJ", 30),        # Política RJ/nacional com impacto
    "w_estado_rj":           _int_env("W_ESTADO_RJ", 25),          # Estado RJ / Campos / Norte Fluminense
    "w_policia":             _int_env("W_POLICIA", 22),             # Polícia / crime / operação
    "w_esportes":            _int_env("W_ESPORTES", 18),            # Esportes (futebol prioritário)
    "w_saude":               _int_env("W_SAUDE", 14),               # Saúde pública
    "w_rural":               _int_env("W_RURAL", 12),               # Rural / agronegócio
    "w_brasil_mundo":        _int_env("W_BRASIL_MUNDO", 10),        # Brasil e Mundo relevante
    "w_economia":            _int_env("W_ECONOMIA", 10),            # Economia
    "w_cidades":             _int_env("W_CIDADES", 10),             # Cidades (local)
    "w_educacao":            _int_env("W_EDUCACAO", 8),             # Educação
    "w_tecnologia":          _int_env("W_TECNOLOGIA", 8),           # Tecnologia
    "w_entretenimento":      _int_env("W_ENTRETENIMENTO", 7),       # Entretenimento
    "w_curiosidades":        _int_env("W_CURIOSIDADES", 6),         # Curiosidades
    "w_bizarro":             _int_env("W_BIZARRO", 5),              # Bizarro
    "w_carnaval":            _int_env("W_CARNAVAL", 5),             # Carnaval
    "w_opiniao":             _int_env("W_OPINIAO", 4),              # Opinião
    "w_podcast":             _int_env("W_PODCAST", 3),              # Podcast
    # ── Regionalidade ───────────────────────────────────────────────────────
    "w_campos_regiao":       _int_env("W_CAMPOS_REGIAO", 20),       # Campos dos Goytacazes e entorno
    "w_norte_fluminense":    _int_env("W_NORTE_FLUMINENSE", 15),    # Norte Fluminense
    "w_interior_rj":         _int_env("W_INTERIOR_RJ", 10),        # Interior do RJ
    "w_capital_rj":          _int_env("W_CAPITAL_RJ", 8),          # Rio capital
    # ── Esportes específicos ─────────────────────────────────────────────────
    "w_clube_prioritario":   _int_env("W_CLUBE_PRIORITARIO", 12),   # Fla/Vas/Bot/Flu
    "w_clube_regional":      _int_env("W_CLUBE_REGIONAL", 8),       # Americano/Goytacaz/etc
    # ── Score de confiança para autopublicação 24h ──────────────────────────
    "w_confianca_base":      _int_env("W_CONFIANCA_BASE", 50),      # base de confiança
    "w_confianca_canal_ok":  _int_env("W_CONFIANCA_CANAL_OK", 15),  # canal claramente identificado
    "w_confianca_data_ok":   _int_env("W_CONFIANCA_DATA_OK", 15),   # data dentro de 4h
    "w_confianca_fonte_ok":  _int_env("W_CONFIANCA_FONTE_OK", 10),  # fonte da lista confiável
    "w_confianca_resumo_ok": _int_env("W_CONFIANCA_RESUMO_OK", 10), # resumo substancial
    # ── Penalidades ──────────────────────────────────────────────────────────
    "pen_horario_excepcional":  _int_env("PEN_HORARIO_EXCEPCIONAL", -8),  # entre 4h e 8h
    "pen_fonte_excedente":      _int_env("PEN_FONTE_EXCEDENTE", -10),     # mesma fonte excedente
    "pen_repeticao_assunto":    _int_env("PEN_REPETICAO_ASSUNTO", -15),   # assunto já coberto
    "pen_baixa_aderencia":      _int_env("PEN_BAIXA_ADERENCIA", -12),     # canal genérico
    "pen_conteudo_fraco":       _int_env("PEN_CONTEUDO_FRACO", -20),      # receita/horóscopo/publi
    "pen_titulo_enganoso":      _int_env("PEN_TITULO_ENGANOSO", -15),     # clickbait detectado
    "pen_classificacao_insegura": _int_env("PEN_CLASS_INSEGURA", -10),    # canal com pouca certeza
    # ── Limites operacionais ─────────────────────────────────────────────────
    "score_min_rascunho":       _int_env("SCORE_MIN_RASCUNHO", 28),
    "score_min_autopublicacao": _int_env("SCORE_MIN_AUTOPUBLICACAO", 48), # limiar mais alto p/ 24h
    "confianca_min_autopub":    _int_env("CONFIANCA_MIN_AUTOPUB", 70),    # confiança mínima p/ autopub
    "max_por_fonte_por_ciclo":  _int_env("MAX_POR_FONTE_CICLO", 4),
    "max_por_canal":            _int_env("MAX_POR_CANAL", 4),
    "min_candidatos_saude":     _int_env("MIN_CANDIDATOS_SAUDE", 3),
    "min_candidatos_rural":     _int_env("MIN_CANDIDATOS_RURAL", 2),
    "max_pub_por_hora_monitor": _int_env("MAX_PUB_HORA_MONITOR", 4),
}


# ══════════════════════════════════════════════════════════════════════════════
# RESULTADO DETALHADO DE SCORE
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ScoreDetalhado:
    """Resultado completo do cálculo de score para uma pauta."""
    # Score final
    score_editorial: int = 0        # score para uso no painel (0-100)
    score_autopub: int = 0          # score de confiança para autopublicação 24h (0-100)

    # Sub-scores
    score_base: int = 0
    score_frescor: int = 0
    score_regionalidade: int = 0
    score_impacto_politico: int = 0
    score_impacto_estadual_rj: int = 0
    score_impacto_policial: int = 0
    score_prioridade_esportes: int = 0
    score_prioridade_saude: int = 0
    score_prioridade_rural: int = 0
    score_potencial_audiencia: int = 0
    score_aderencia_canal: int = 0
    score_diversidade_fonte: int = 0
    score_confianca_autopub: int = 0

    # Penalidades
    pen_horario: int = 0
    pen_fonte: int = 0
    pen_repeticao: int = 0
    pen_conteudo: int = 0
    pen_classificacao: int = 0

    # Metadados de decisão
    canal_sugerido: str = ""
    canal_confianca: str = "baixa"   # alta / media / baixa
    modo_destino: str = "rascunho"   # "autopublicacao" ou "rascunho"
    motivos_aprovacao: list = field(default_factory=list)
    motivos_rejeicao: list = field(default_factory=list)
    motivo_bloqueio: str = ""
    barrado_por_tempo: bool = False
    barrado_por_repeticao: bool = False
    barrado_por_fonte_excedente: bool = False
    barrado_por_baixa_confianca: bool = False
    candidato_saude_obrigatorio: bool = False
    candidato_rural_obrigatorio: bool = False
    aprovado_saude: bool = False
    aprovado_rural: bool = False

    # Intel editorial — camada aditiva (não quebra compatibilidade)
    score_intel_adicional: int = 0
    intel_log: str = ""
    intel_triangulacao: bool = False
    intel_urgencia: bool = False
    intel_protocolo_ok: bool = True
    intel_watchlists: list = field(default_factory=list)

    def resumo_log(self) -> str:
        linhas = [
            f"  score_editorial={self.score_editorial} | score_autopub={self.score_autopub}",
            f"  canal={self.canal_sugerido} ({self.canal_confianca}) | modo={self.modo_destino}",
            f"  sub-scores: base={self.score_base} frescor={self.score_frescor} "
            f"regional={self.score_regionalidade} politico={self.score_impacto_politico} "
            f"policial={self.score_impacto_policial} esportes={self.score_prioridade_esportes} "
            f"saude={self.score_prioridade_saude} rural={self.score_prioridade_rural}",
            f"  penalidades: horario={self.pen_horario} fonte={self.pen_fonte} "
            f"repeticao={self.pen_repeticao} conteudo={self.pen_conteudo}",
        ]
        if self.motivos_aprovacao:
            linhas.append(f"  APROVAÇÃO: {'; '.join(self.motivos_aprovacao[:4])}")
        if self.motivos_rejeicao:
            linhas.append(f"  REJEIÇÃO: {'; '.join(self.motivos_rejeicao[:4])}")
        if self.motivo_bloqueio:
            linhas.append(f"  BLOQUEIO: {self.motivo_bloqueio}")
        if self.candidato_saude_obrigatorio:
            linhas.append(f"  SAÚDE: candidato obrigatório | aprovado={self.aprovado_saude}")
        if self.candidato_rural_obrigatorio:
            linhas.append(f"  RURAL: candidato obrigatório | aprovado={self.aprovado_rural}")
        if self.score_intel_adicional > 0:
            linhas.append(f"  INTEL(+{self.score_intel_adicional}): {self.intel_log}")
        if self.intel_triangulacao:
            linhas.append("  ★ TRIANGULAÇÃO REGIONAL ATIVA")
        if self.intel_urgencia:
            linhas.append("  ⚡ URGÊNCIA DETECTADA")
        if not self.intel_protocolo_ok:
            linhas.append("  ⚠ PROTOCOLO DE VERDADE: REVISAR ANTES DE PUBLICAR")
        return "\n".join(linhas)


# ══════════════════════════════════════════════════════════════════════════════
# DICIONÁRIOS DE PALAVRAS-CHAVE POR CANAL (expandidos)
# ══════════════════════════════════════════════════════════════════════════════

# Cada canal tem uma lista de termos-chave com peso implícito (1 ponto cada)
_KW_CANAL: dict[str, list[str]] = {
    "Polícia": [
        "preso", "prisão", "policia", "polícia", "crime", "tráfico", "assassinato",
        "homicídio", "roubo", "furto", "operação policial", "bope", "civil", "militar",
        "delegacia", "inquérito", "flagrante", "arma", "drogas", "sequestro",
        "estupro", "violência", "ocorrência", "boletim de ocorrência", "suspeito",
        "investigado", "indiciado", "baleado", "morte violenta", "execução",
        "latrocínio", "tentativa de homicídio", "mandado de prisão", "foragido",
        "capturado", "pm", "pf", "polícia federal", "polícia civil", "polícia militar",
        "presídio", "cadeia", "detenção", "tiro", "bala",
        "acidente de trânsito grave", "atropelamento fatal", "colisão fatal",
        "patrulha", "viatura",
    ],
    "Política": [
        # Instituições e cargos — termos específicos (não genéricos)
        "presidente da república", "vice-presidente", "ministro de estado",
        "congresso nacional", "senado federal", "câmara dos deputados",
        "deputado federal", "senador", "vereador", "governador", "prefeito municipal",
        "partido político", "eleição municipal", "eleição estadual", "eleição federal",
        "votação no congresso", "reforma constitucional", "stf", "supremo tribunal federal",
        "pec ", "emenda constitucional", "decreto presidencial",
        "lula presidente", "bolsonaro", "legislativo federal", "executivo federal",
        "impeachment", "corrupção no governo", "desvio de verbas", "esquema de corrupção",
        "propina", "cpi ", "ministério público federal", "alerj", "câmara municipal",
        "cassação de mandato", "reeleição", "oposição ao governo", "governo federal",
        "governo estadual", "gestão pública", "decisão política", "articulação política",
        "aliança política", "coligação partidária",
        "tse", "tre", "tribunal superior eleitoral", "tribunal regional eleitoral",
        "stj", "superior tribunal de justiça",
        "haddad", "pacheco", "arthur lira", "flávio dino", "alexandre de moraes",
    ],
    "Estado RJ": [
        "rio de janeiro", "estado do rio", "governo do rio", " rj ", "rj,",
        "campos dos goytacazes", "campos", "goytacaz", "macaé", "niterói",
        "volta redonda", "petrópolis", "nova friburgo", "teresópolis",
        "angra dos reis", "cabo frio", "arraial do cabo", "porto do açu",
        "norte fluminense", "baixada fluminense", "duque de caxias",
        "nova iguaçu", "são gonçalo", "itaboraí", "queimados", "belford roxo",
        "mesquita", "nilópolis", "itaguaí", "seropédica", "três rios",
        "vassouras", "barra mansa", "resende", "pinheiral", "piraí",
        "rio bonito", "araruama", "saquarema", "maricá", "são pedro da aldeia",
        "iguaba grande", "búzios", "casimiro de abreu", "silva jardim",
        "alerj", "governo estadual rj", "secretaria estadual", "governo cláudio castro",
        "norte fluminense", "região serrana rj", "baixada litorânea",
        "médio paraíba", "costa verde", "interior fluminense",
    ],
    "Cidades": [
        "prefeitura", "secretaria municipal", "câmara municipal", "vereadores",
        "obra pública", "licitação", "serviço público", "transporte coletivo",
        "ônibus", "asfalto", "bueiro", "iluminação pública", "praça", "bairro",
        "moradores", "comunidade", "infraestrutura urbana", "saneamento básico",
        "abastecimento", "água", "esgoto", "coleta de lixo", "zeladoria",
        "parque", "escola municipal", "ubs", "posto de saúde municipal",
        "concurso público", "concurso municipal",
        "anac", "agência nacional", "anvisa", "anatel",
        "passageiro", "reclamação de consumidor", "procon", "inmetro",
    ],
    "Esportes": [
        "futebol", "flamengo", "vasco", "botafogo", "fluminense",
        "americano fc", "goytacaz", "roxinho", "campos atlético",
        "fifa", "cbf", "campeonato", "copa", "atleta", "jogador", "treinador",
        "técnico", "placar", "gol", "final", "semifinal", "rodada", "escalação",
        "olimpíadas", "paralimpíadas", "natação", "corrida", "tênis", "vôlei",
        "basquete", "handball", "atletismo", "ciclismo", "boxe", "mma",
        "série a", "série b", "série c", "libertadores", "sul-americana",
        "champions", "transferência", "contratação", "demissão de técnico",
        "lesão", "suspensão", "cartão", "árbitro", "var", "rebaixamento",
        "acesso", "título", "campeão", "vice-campeão", "classificação",
        "jogo de hoje", "onde assistir", "hora do jogo", "semifinal da copa",
    ],
    "Saúde": [
        "saúde", "hospital", "ubs", "sus", "médico", "médica", "vacina",
        "vacinação", "dengue", "zika", "chikungunya", "covid", "coronavírus",
        "doença", "epidemia", "pandemia", "surto", "morte por doença", "óbito",
        "internação", "leito", "remédio", "medicamento", "anvisa",
        "ministério da saúde", "secretaria de saúde", "câncer", "diabetes",
        "hipertensão", "ubs", "posto de saúde", "upa", "pronto-socorro",
        "emergência", "cirurgia", "tratamento", "prevenção", "campanha de saúde",
        "saúde pública", "vigilância epidemiológica", "infecção", "vírus",
        "bactéria", "contágio", "transmissão", "sintomas", "diagnóstico",
        "estudo médico", "pesquisa médica", "pesquisa clínica",
    ],
    "Rural": [
        "agro", "agropecuária", "agronegócio", "soja", "milho", "boi", "pecuária",
        "fazenda", "safra", "embrapa", "mapa", "ministério da agricultura",
        "cotação", "seca", "chuva", "irrigação", "colheita", "plantio",
        "fertilizante", "defensivo agrícola", "rural", "campo", "produtor rural",
        "lavoura", "grão", "exportação agrícola", "commodities", "preço do boi",
        "preço da soja", "arroba", "frigorífico", "abate", "cafeicultura",
        "cana-de-açúcar", "açúcar", "etanol", "citricultura", "pesca",
        "aquicultura", "pescador", "cooperativa", "mst", "assentamento",
        "reforma agrária", "funai", "ibama rural", "rastreamento animal",
        "vacinação animal", "febre aftosa",
    ],
    "Economia": [
        "inflação", "juros", "pib", "desemprego", "emprego", "renda",
        "salário", "mercado financeiro", "bolsa de valores", "dólar", "câmbio",
        "banco central", "ipca", "selic", "exportação", "importação",
        "balança comercial", "empresa", "falência", "recuperação judicial",
        "taxa de juros", "receita federal", "imposto", "tributário", "fiscal",
        "déficit", "superávit", "orçamento", "ldo", "loa", "pec fiscal",
        "reforma tributária", "comércio", "varejo", "consumo", "confiança",
        "pme", "pequena empresa", "microempreendedor", "mei", "startup",
        "ipo", "ação", "investimento", "banco", "crédito", "financiamento",
    ],
    "Educação": [
        "escola", "educação", "mec", "enem", "vestibular", "universidade",
        "faculdade", "ensino médio", "ensino fundamental", "professor",
        "aluno", "greve de professores", "secretaria de educação", "bolsa família",
        "prouni", "fies", "creche", "berçário", "alfabetização", "analfabetismo",
        "ideb", "pisa", "sisu", "pronatec", "ensino técnico",
        "ensino profissional", "formatura", "defasagem escolar",
        "evasão escolar", "capes", "cnpq", "pesquisa acadêmica",
    ],
    "Tecnologia": [
        "tecnologia", "inteligência artificial", "ia", "app", "aplicativo",
        "startup", "big tech", "google", "microsoft", "apple", "meta",
        "amazon", "x twitter", "redes sociais", "celular", "smartphone",
        "computador", "software", "hardware", "cibersegurança", "hacker",
        "vazamento de dados", "lgpd", "privacidade digital", "blockchain",
        "criptomoeda", "bitcoin", "nft", "metaverso", "cloud", "5g",
        "chatgpt", "openai", "robótica", "drone", "veículo elétrico",
        "tesla", "uber tech", "fintech", "edtech", "healthtech",
    ],
    "Entretenimento": [
        "novela", "globo", "sbt", "record", "série", "filme", "ator", "atriz",
        "cantor", "cantora", "show", "festival", "lollapalooza", "rock in rio",
        "premiação", "grammy", "oscar", "emmy", "bafta", "streaming",
        "netflix", "amazon prime", "disney", "spotify", "deezer",
        "celebridade", "famoso", "influenciador", "youtuber", "tiktoker",
        "reality", "bbb", "big brother", "masterchef", "the voice",
        "música sertaneja", "funk", "pagode", "samba", "axé", "forró",
        "ana paula", "bbb 25", "bbb 26", "brother", "sister", "confessionário",
        "líder", "paredão", "eliminado", "tadeu", "tadeu schmidt",
        "ana paula renault", "gkay", "whindersson", "virgínia", "jade picon",
        "deolane", "murilo huff", "marília mendonça", "xxxtentacion",
        "coachella", "shows internacionais",
    ],
    "Curiosidades": [
        "inusitado", "curioso", "viral", "raro", "recorde mundial",
        "surpreendente", "estranho", "insólito", "animal incomum", "natureza",
        "fenômeno natural", "patrimônio histórico", "descoberta científica",
        "arqueologia", "fóssil", "espécie nova", "comportamento animal",
        "evento astronômico", "eclipse", "meteoro", "aurora boreal",
    ],
    "Bizarro": [
        "bizarro", "absurdo", "inacreditável", "chocante", "polêmico",
        "escândalo", "vergonhoso", "indignação", "ridículo", "surreal",
        "exótico", "esquisito", "maluco", "doido",
    ],
    "Carnaval": [
        "carnaval", "samba", "escola de samba", "desfile", "sambódromo",
        "passista", "bateria", "mestre-sala", "porta-bandeira", "enredo",
        "fantasia", "bloco", "micareta", "trio elétrico", "axé", "frevo",
        "pré-carnaval", "ensaio", "quadra", "carnavalesco", "presidente da escola",
    ],
    "Brasil e Mundo": [
        "eua", "estados unidos", "china", "europa", "onu", "otan", "nato",
        "guerra", "conflito armado", "diplomacia", "embaixada", "acordo internacional",
        "cúpula", "summit", "sanção", "tratado", "fronteira", "venezuela",
        "argentina", "mercosul", "brics", "g7", "g20", "fmi", "banco mundial",
        "lula presidente", "biden", "trump", "macron", "putin", "xi jinping",
        "eleição nos eua", "eleição na europa", "parlamento europeu",
        "guerra na ucrânia", "oriente médio", "israel", "hamas", "irã",
        "petróleo", "barril", "opep", "navio iraniano", "oriente médio",
        "apreensão de navio", "ataque militar", "míssil", "bombardeio",
        "conflito", "milei", "netanyahu", "protest", "manifestação internacional",
        "acordo nuclear",
    ],
    "Opinião": [
        "artigo", "opinião", "coluna", "análise", "editorial", "carta ao leitor",
        "ponto de vista", "comentário", "reflexão", "debate",
    ],
    "Podcast": [
        "podcast", "episódio", "programa de áudio", "entrevista exclusiva",
        "rádio", "locução", "apresentador", "âncora",
    ],
}

# Termos de regionalidade — boost extra
_KW_CAMPOS = [
    "campos dos goytacazes", "campos", "goytacaz", "norte fluminense",
    "macaé", "são joão da barra", "são francisco de itabapoana", "quissamã",
    "carapebus", "conceição de macabu", "rio das ostras", "bom jesus do itabapoana",
    "italva", "natividade", "porciúncula", "miracema", "cardoso moreira",
    "cambuci", "são fidélis", "itaocara", "aperibé", "santo antônio de pádua",
    "laje do muriaé", "varre-sai", "porto do açu", "região norte fluminense",
]

_KW_INTERIOR_RJ = [
    "volta redonda", "barra mansa", "resende", "petrópolis", "nova friburgo",
    "teresópolis", "três rios", "vassouras", "piraí", "pinheiral", "valença",
    "médio paraíba", "região serrana", "sul fluminense",
]

_KW_CAPITAL_RJ = [
    "rio de janeiro", "rio capital", "bairros do rio", "zona sul", "zona norte",
    "zona oeste", "baixada", "centro do rio", "lapa", "santa teresa",
    "niterói", "são gonçalo",
]

_KW_CLUBES_PRIORITARIOS = [
    "flamengo", "vasco", "botafogo", "fluminense",
]

_KW_CLUBES_REGIONAIS = [
    "americano fc", "goytacaz", "campos atlético", "roxinho", "club fields",
]

# Termos de conteúdo fraco (penalidade)
_KW_CONTEUDO_FRACO = [
    r"\bhoróscopo\b|\bsigno\b",
    r"\breceit[a]?\b culinár",
    r"\bdica[s]?\b de beleza",
    r"\bpromoção\b|\bdesconto especial\b|\boferta\b",
    r"\bpublicidade\b|\bpublicitário\b|\bconteúdo patrocinado\b",
    r"\bparceiro\b|\bpatrocinado\b",
    r"\bcurso online\b|\binscriç[ãa]o aberta\b",
]

# Termos de clickbait / título enganoso (penalidade)
_KW_CLICKBAIT = [
    r"\bvocê não vai acreditar\b",
    r"\bchocou a internet\b",
    r"\bquebrando a internet\b",
    r"\bmuita gente não sabe\b",
    r"\bsegredo que ninguém conta\b",
    r"\b\d+ motivos para\b",
    r"\bconfira \d+ dicas\b",
]


# ══════════════════════════════════════════════════════════════════════════════
# CLASSIFICAÇÃO DE CANAL
# ══════════════════════════════════════════════════════════════════════════════

# Ordem de prioridade para desempate (canal mais específico primeiro)
_PRIORIDADE_CANAL: list[str] = [
    "Polícia", "Política", "Estado RJ", "Esportes", "Saúde",
    "Rural", "Cidades", "Economia", "Tecnologia", "Educação",
    "Entretenimento", "Brasil e Mundo", "Curiosidades", "Bizarro",
    "Carnaval", "Opinião", "Podcast",
]


def classificar_canal(titulo: str, resumo: str) -> tuple[str, str, int]:
    """
    Classifica a pauta no canal editorial mais adequado.

    Retorna: (canal: str, confianca: str, pontuacao: int)
    confianca: 'alta' (>=4 pts), 'media' (2-3 pts), 'baixa' (<2 pts)

    Usa matching de palavras-chave expandido com prioridade editorial.
    Aplica regras especiais para casos ambíguos.
    """
    texto = (titulo + " " + resumo).lower()
    texto_low = texto  # alias para compatibilidade com regras existentes

    pontuacao: dict[str, int] = {c: 0 for c in _KW_CANAL}

    for canal, termos in _KW_CANAL.items():
        for termo in termos:
            if termo.lower() in texto:
                pontuacao[canal] += 1

    # ── Regra determinística: política eleitoral RJ / pesquisa eleitoral ──────
    # Detecta pesquisas eleitorais, candidatos, intenção de voto etc.
    if any(t in texto_low for t in [
        "quaest", "genial investimentos", "pesquisa eleitoral",
        "intenção de voto", "intenções de voto", "governo do rj",
        "eduardo paes", "douglas ruas", "garotinho", "wilson witzel",
        "cláudio castro", "benedita da silva", "marcelo freixo",
        "flávio bolsonaro", "rodolfo paiva", "tarcísio", "tarcisio",
        "eleições 2026", "eleicao 2026", "candidato ao governo",
        "disputa pelo governo", "corrida eleitoral", "primeiro turno",
        "segundo turno", "margem de erro", "registrado na justiça eleitoral",
        "tse", "tre-rj", "justiça eleitoral",
    ]):
        return "Política", "alta", 8

    # ── Regra determinística: clima / previsão do tempo → Cidades ────────────
    if any(t in texto_low for t in [
        "previsão do tempo", "previsao do tempo", "chuvas", "temperaturas",
        "massa de ar", "frente fria", "calor intenso", "onda de calor",
        "tempo deve", "tempo vai", "semana com", "dias ensolarados",
        "alerta de temporais", "volume de chuva", "índice pluviométrico",
    ]):
        # Se menciona RJ especificamente → Estado RJ, senão Cidades
        if any(t in texto_low for t in ["rio de janeiro", "estado do rj", "rj ", "norte fluminense"]):
            return "Estado RJ", "alta", 5
        return "Cidades", "alta", 5

    # ── Regra determinística: Brasil e Mundo (geopolítica / EUA / Trump) ─────
    if any(t in texto_low for t in [
        "trump", "biden", "casa branca", "pentágono", "pentagono",
        "departamento de estado", "eua ", "estados unidos",
        "reino unido", "inglaterra", " frança ", " alemanha ", " rússia ",
        "china ", "irã ", "israel ", "ucrânia", "onu ", "nato", "otan",
        "g7", "g20", "oms", "opep", "conflito internacional",
        "guerra no oriente", "guerra na ucrânia", "ataque a tiros",
        "tiroteio", "assassinato de", "embassy", "embaixada",
    ]):
        return "Brasil e Mundo", "alta", 6

    # ── Regra determinística: polícia regional (Campos / Norte Fluminense) ────
    if any(t in texto_low for t in [
        "polícia encontra", "policia encontra", "operação policial",
        "operacao policial", "pinos de cocaína", "pinos de cocaina",
        "tonel enterrado", "tráfico em campos", "trafico em campos",
        "bope", "core", "draco", "denarc",
    ]) and any(t in texto_low for t in [
        "campos", "goytacaz", "norte fluminense", "macaé", "são joão da barra",
        "são francisco", "quissamã", "italva", "natividade",
    ]):
        return "Polícia", "alta", 6

    # Futebol, esporte → Esportes (anula Política completamente)
    if any(t in texto_low for t in [
            "flamengo", "vasco", "botafogo", "fluminense", "futebol", "gol",
            "placar", "escalação", "onde assistir", "campeonato brasileiro",
            "série a", "série b", "libertadores", "champions", "copa do brasil"]):
        pontuacao["Esportes"] = max(pontuacao["Esportes"], pontuacao.get("Política", 0) + 4)
        pontuacao["Política"] = 0

    # BBB, reality, entretenimento → Entretenimento (anula Esportes e Política)
    if any(t in texto_low for t in [
            "bbb", "big brother", "confessionário", "paredão", "reality show",
            "brother", "sister", "tadeu schmidt", "ana paula renault", "eliminado bbb",
            "berlinda", "prova do líder", "formação do paredão"]):
        pontuacao["Entretenimento"] = max(pontuacao["Entretenimento"], 8)
        pontuacao["Esportes"] = 0
        pontuacao["Política"] = 0

    # Economia/mercado → Economia (anula Política)
    if any(t in texto_low for t in [
            "petróleo", "barril de petróleo", "brent", "wti", "nafta",
            "bolsa de valores", "ibovespa", "dólar sobe", "dólar cai",
            "inflação", "ipca", "selic", "banco central", "taxa de juros",
            "pib", "mercado financeiro", "ações", "dividendos"]):
        pontuacao["Economia"] = max(pontuacao["Economia"], pontuacao.get("Política", 0) + 3)
        pontuacao["Política"] = min(pontuacao["Política"], 1)

    # Saúde → Saúde (anula outros se conteúdo médico claro)
    if any(t in texto_low for t in [
            "infarto", "acidente vascular", "avc", "câncer", "tumor",
            "cirurgia", "internação hospitalar", "uti", "vacina obrigatória",
            "surto de", "epidemia de", "óbito por doença", "morte por doença"]):
        pontuacao["Saúde"] = max(pontuacao["Saúde"], pontuacao.get("Política", 0) + 3)
        pontuacao["Política"] = min(pontuacao["Política"], 1)

    # Internacional/geopolítica → Brasil e Mundo (anula Polícia)
    if any(t in texto_low for t in [
            "navio de guerra", "ataque militar", "míssil", "bombardeio",
            "força aérea", "marinha de guerra", "irã", "israel",
            "ucrânia", "rússia", "nato", "otan", "sanção internacional",
            "embaixada", "diplomacia", "acordo nuclear"]):
        pontuacao["Brasil e Mundo"] = max(pontuacao["Brasil e Mundo"], pontuacao.get("Polícia", 0) + 3)
        pontuacao["Polícia"] = min(pontuacao["Polícia"], 1)

    # Tecnologia → Tecnologia (anula outros se conteúdo tech claro)
    if any(t in texto_low for t in [
            "inteligência artificial", "chatgpt", "openai", "google gemini",
            "check-in digital", "app lança", "plataforma digital", "cibersegurança",
            "vazamento de dados", "lgpd", "blockchain", "criptomoeda"]):
        pontuacao["Tecnologia"] = max(pontuacao["Tecnologia"], pontuacao.get("Política", 0) + 2)
        pontuacao["Política"] = min(pontuacao["Política"], 1)

    # Consumidor/serviço → Cidades (anula Política se não há política clara)
    if any(t in texto_low for t in [
            "passageiro", "reclamação de consumidor", "procon", "anac",
            "anvisa", "anatel", "inmetro", "direito do consumidor",
            "plataforma de reclamação", "nota fiscal"]):
        pontuacao["Cidades"] = max(pontuacao["Cidades"], pontuacao.get("Política", 0) + 2)
        # só penaliza Política se não tem termo político real
        if not any(t in texto_low for t in ["presidente", "senado", "câmara dos deputados", "stf", "lula", "bolsonaro"]):
            pontuacao["Política"] = min(pontuacao["Política"], 1)

    melhor_score = max(pontuacao.values())

    # Sem nenhuma correspondência → Brasil e Mundo como fallback
    if melhor_score == 0:
        return "Brasil e Mundo", "baixa", 0

    # Confiança baseada na pontuação
    if melhor_score >= 4:
        confianca = "alta"
    elif melhor_score >= 2:
        confianca = "media"
    else:
        confianca = "baixa"

    # Seleciona o canal vencedor com desempate por prioridade editorial
    candidatos = [c for c, v in pontuacao.items() if v == melhor_score]
    for c in _PRIORIDADE_CANAL:
        if c in candidatos:
            return c, confianca, melhor_score

    # Fallback improvável
    vencedor = max(pontuacao, key=lambda c: pontuacao[c])
    return vencedor, confianca, melhor_score


def classificar_canal_simples(titulo: str, resumo: str) -> str:
    """Versão simplificada que retorna apenas o nome do canal (compatibilidade)."""
    canal, _, _ = classificar_canal(titulo, resumo)
    return canal


# ══════════════════════════════════════════════════════════════════════════════
# SCORE COMPOSTO
# ══════════════════════════════════════════════════════════════════════════════

def calcular_score_completo(
    pauta: dict,
    contexto_fontes: Optional[dict] = None,
) -> ScoreDetalhado:
    """
    Calcula o score editorial composto de uma pauta.

    contexto_fontes: dict opcional com contagem de pautas por fonte no ciclo atual
                     { "G1 RJ": 3, "CNN Brasil": 1, ... }

    Retorna ScoreDetalhado com todos os sub-scores, penalidades e justificativas.
    """
    sd = ScoreDetalhado()
    motivos_ap: list[str] = []
    motivos_rej: list[str] = []

    titulo   = (pauta.get("titulo_origem") or "").strip()
    resumo   = (pauta.get("resumo_origem") or "").strip()
    fonte    = (pauta.get("fonte_nome") or "").strip()
    canal_f  = (pauta.get("canal_forcado") or "").strip()
    prioridade = pauta.get("prioridade", 1)  # 2=<4h, 1=4-8h, 0=velho

    texto = (titulo + " " + resumo).lower()

    # ── 1. Canal ──────────────────────────────────────────────────────────────
    if canal_f and canal_f in CANAIS_URURAU:
        canal, confianca, pts_canal = canal_f, "alta", 5
    else:
        canal, confianca, pts_canal = classificar_canal(titulo, resumo)

    sd.canal_sugerido   = canal
    sd.canal_confianca  = confianca
    pauta["canal_forcado"] = canal

    # ── 2. Score base por canal ───────────────────────────────────────────────
    mapa_peso_canal = {
        "Política":      PESOS["w_politica_rj"],
        "Estado RJ":     PESOS["w_estado_rj"],
        "Polícia":       PESOS["w_policia"],
        "Esportes":      PESOS["w_esportes"],
        "Saúde":         PESOS["w_saude"],
        "Rural":         PESOS["w_rural"],
        "Brasil e Mundo":PESOS["w_brasil_mundo"],
        "Economia":      PESOS["w_economia"],
        "Cidades":       PESOS["w_cidades"],
        "Educação":      PESOS["w_educacao"],
        "Tecnologia":    PESOS["w_tecnologia"],
        "Entretenimento":PESOS["w_entretenimento"],
        "Curiosidades":  PESOS["w_curiosidades"],
        "Bizarro":       PESOS["w_bizarro"],
        "Carnaval":      PESOS["w_carnaval"],
        "Opinião":       PESOS["w_opiniao"],
        "Podcast":       PESOS["w_podcast"],
    }
    sd.score_base = 20 + mapa_peso_canal.get(canal, 5)
    if canal in ("Política", "Estado RJ"):
        motivos_ap.append(f"Canal de alta prioridade: {canal}")
    elif canal in ("Polícia", "Esportes"):
        motivos_ap.append(f"Canal prioritário: {canal}")

    # ── 3. Impacto político ───────────────────────────────────────────────────
    termos_politica = [
        "stf", "tse", "alerj", "governador", "prefeito", "senado", "câmara",
        "eleição", "votação", "cassação", "mandato", "impeachment", "corrupção",
        "ministério", "reforma", "decreto", "lei aprovada", "pec",
    ]
    hits_pol = sum(1 for t in termos_politica if t in texto)
    sd.score_impacto_politico = min(20, hits_pol * 4)
    if hits_pol >= 2:
        motivos_ap.append(f"Impacto político ({hits_pol} termos-chave)")

    # ── 4. Impacto estadual RJ ────────────────────────────────────────────────
    hits_rj = sum(1 for t in _KW_CANAL.get("Estado RJ", []) if t in texto)
    sd.score_impacto_estadual_rj = min(15, hits_rj * 3)
    if hits_rj >= 2:
        motivos_ap.append(f"Impacto estadual RJ ({hits_rj} termos)")

    # ── 5. Impacto policial ───────────────────────────────────────────────────
    termos_pol_alto = ["preso", "prisão", "operação", "assassinato", "homicídio",
                       "apreensão", "flagrante", "bope", "drogas apreendido"]
    hits_policia = sum(1 for t in termos_pol_alto if t in texto)
    sd.score_impacto_policial = min(18, hits_policia * 5)
    if hits_policia >= 1:
        motivos_ap.append(f"Fato policial relevante ({hits_policia} termos)")

    # ── 6. Regionalidade ─────────────────────────────────────────────────────
    score_reg = 0
    for t in _KW_CAMPOS:
        if t in texto:
            score_reg += PESOS["w_campos_regiao"]
            motivos_ap.append(f"Regionalidade Campos/Norte Fluminense: '{t}'")
            break
    if score_reg == 0:
        for t in _KW_INTERIOR_RJ:
            if t in texto:
                score_reg += PESOS["w_interior_rj"]
                motivos_ap.append(f"Interior RJ: '{t}'")
                break
    if score_reg == 0:
        for t in _KW_CAPITAL_RJ:
            if t in texto:
                score_reg += PESOS["w_capital_rj"]
                break
    sd.score_regionalidade = min(30, score_reg)

    # ── 7. Prioridade esportes ────────────────────────────────────────────────
    score_esp = 0
    for t in _KW_CLUBES_PRIORITARIOS:
        if t in texto:
            score_esp += PESOS["w_clube_prioritario"]
            motivos_ap.append(f"Clube prioritário: {t}")
    for t in _KW_CLUBES_REGIONAIS:
        if t in texto:
            score_esp += PESOS["w_clube_regional"]
            motivos_ap.append(f"Clube regional: {t}")
    sd.score_prioridade_esportes = min(20, score_esp)

    # ── 8. Saúde ─────────────────────────────────────────────────────────────
    if canal == "Saúde":
        sd.score_prioridade_saude = PESOS["w_saude"]
        sd.candidato_saude_obrigatorio = True
        motivos_ap.append("Canal Saúde — cobertura mínima obrigatória")
    else:
        # Verifica se tem conteúdo de saúde mesmo não sendo o canal principal
        hits_saude = sum(1 for t in _KW_CANAL.get("Saúde", [])[:10] if t in texto)
        sd.score_prioridade_saude = min(10, hits_saude * 2)

    # ── 9. Rural ─────────────────────────────────────────────────────────────
    if canal == "Rural":
        sd.score_prioridade_rural = PESOS["w_rural"]
        sd.candidato_rural_obrigatorio = True
        motivos_ap.append("Canal Rural — cobertura mínima obrigatória")
    else:
        hits_rural = sum(1 for t in _KW_CANAL.get("Rural", [])[:10] if t in texto)
        sd.score_prioridade_rural = min(8, hits_rural * 2)

    # ── 10. Potencial de audiência ────────────────────────────────────────────
    termos_audiencia = [
        "morte", "óbito", "preso", "prisão", "operação", "acidente",
        "tragédia", "incêndio", "vazamento", "investigação", "corrupção",
        "flamengo", "vasco", "eleição", "lula", "stf", "dengue",
    ]
    hits_aud = sum(1 for t in termos_audiencia if t in texto)
    sd.score_potencial_audiencia = min(15, hits_aud * 3)

    # ── 11. Aderência ao canal (qualidade do match) ───────────────────────────
    if confianca == "alta":
        sd.score_aderencia_canal = 12
    elif confianca == "media":
        sd.score_aderencia_canal = 6
    else:
        sd.score_aderencia_canal = 0
        sd.pen_classificacao = PESOS["pen_classificacao_insegura"]
        motivos_rej.append("Classificação de canal com baixa confiança")

    # ── 12. Diversidade de fonte ──────────────────────────────────────────────
    sd.score_diversidade_fonte = 5  # neutro por padrão

    # ── 13. Frescor temporal ──────────────────────────────────────────────────
    if prioridade == 2:
        sd.score_frescor = 20
        motivos_ap.append("Publicada nas últimas 4h (prioridade máxima)")
    elif prioridade == 1:
        sd.score_frescor = 8
        sd.pen_horario = PESOS["pen_horario_excepcional"]
        motivos_rej.append("Entre 4h e 8h — frescor reduzido")
        sd.barrado_por_tempo = (sd.pen_horario < -5)
    else:
        sd.score_frescor = 0
        sd.pen_horario = -20
        sd.barrado_por_tempo = True
        motivos_rej.append("Notícia com mais de 8h — descartada por idade")

    # ── 14. Penalidade de conteúdo fraco ──────────────────────────────────────
    for padrao in _KW_CONTEUDO_FRACO:
        if re.search(padrao, texto, re.IGNORECASE):
            sd.pen_conteudo = PESOS["pen_conteudo_fraco"]
            motivos_rej.append("Conteúdo fraco detectado (receita/horóscopo/publi)")
            break

    # ── 15. Penalidade clickbait ──────────────────────────────────────────────
    for padrao in _KW_CLICKBAIT:
        if re.search(padrao, texto, re.IGNORECASE):
            sd.pen_classificacao += PESOS["pen_titulo_enganoso"]
            motivos_rej.append("Título com padrão clickbait")
            break

    # ── 16. Penalidade de fonte excedente (se contexto fornecido) ────────────
    if contexto_fontes and fonte:
        qtd = contexto_fontes.get(fonte, 0)
        if qtd >= PESOS["max_por_fonte_por_ciclo"]:
            sd.pen_fonte = PESOS["pen_fonte_excedente"]
            sd.barrado_por_fonte_excedente = True
            motivos_rej.append(f"Fonte excedente ({fonte}: {qtd} pautas no ciclo)")

    # ── 17. Score editorial final ─────────────────────────────────────────────
    raw_score = (
        sd.score_base
        + sd.score_frescor
        + sd.score_regionalidade
        + sd.score_impacto_politico
        + sd.score_impacto_estadual_rj
        + sd.score_impacto_policial
        + sd.score_prioridade_esportes
        + sd.score_prioridade_saude
        + sd.score_prioridade_rural
        + sd.score_potencial_audiencia
        + sd.score_aderencia_canal
        + sd.score_diversidade_fonte
        + sd.pen_horario
        + sd.pen_fonte
        + sd.pen_repeticao
        + sd.pen_conteudo
        + sd.pen_classificacao
    )
    sd.score_editorial = max(0, min(100, raw_score))

    # ── 17b. Intel editorial — camada aditiva (NÃO substitui, apenas soma) ────
    # Importação lazy para evitar circular imports
    try:
        from ururau.coleta.intel_editorial import enriquecer_pauta_com_intel
        pauta = enriquecer_pauta_com_intel(pauta)
        score_intel = pauta.get("_score_intel_adicional", 0)
        if score_intel > 0:
            sd.score_intel_adicional = score_intel
            sd.intel_log = pauta.get("_intel_log", "")
            sd.intel_triangulacao = bool(pauta.get("_intel_triangulacao", False))
            sd.intel_urgencia = bool(pauta.get("_intel_urgencia", False))
            sd.intel_protocolo_ok = bool(pauta.get("_intel_protocolo_ok", True))
            sd.intel_watchlists = pauta.get("_intel_watchlists", [])
            # Aplica boost aditivo (cap em 100 no final)
            sd.score_editorial = max(0, min(100, sd.score_editorial + score_intel))
            if score_intel >= 10:
                motivos_ap.append(f"Intel editorial +{score_intel}: {sd.intel_log[:60]}")
        # Protocolo de verdade: se falhou, não autopublica
        if not pauta.get("_intel_protocolo_ok", True):
            sd.intel_protocolo_ok = False
            motivos_rej.append("Protocolo de verdade: revisar cargo/fato antes de publicar")
    except Exception as _ex_intel:
        pass  # fallback silencioso: score inalterado

    # ── 18. Score de confiança para autopublicação ────────────────────────────
    confianca_score = PESOS["w_confianca_base"]
    if confianca == "alta":
        confianca_score += PESOS["w_confianca_canal_ok"]
    if prioridade == 2:
        confianca_score += PESOS["w_confianca_data_ok"]
    if resumo and len(resumo) > 200:
        confianca_score += PESOS["w_confianca_resumo_ok"]
    if fonte:
        confianca_score += PESOS["w_confianca_fonte_ok"]
    # Penalidades de confiança
    if sd.pen_conteudo < 0:
        confianca_score -= 20
    if sd.barrado_por_tempo:
        confianca_score -= 30
    if sd.barrado_por_fonte_excedente:
        confianca_score -= 15
    if confianca == "baixa":
        confianca_score -= 15
    sd.score_confianca_autopub = max(0, min(100, confianca_score))

    # ── 19. Modo de destino ───────────────────────────────────────────────────
    if (sd.score_editorial >= PESOS["score_min_autopublicacao"]
            and sd.score_confianca_autopub >= PESOS["confianca_min_autopub"]
            and not sd.barrado_por_tempo
            and not sd.barrado_por_fonte_excedente
            and sd.pen_conteudo == 0
            and sd.intel_protocolo_ok):      # protocolo de verdade obrigatório
        sd.modo_destino = "autopublicacao"
    else:
        sd.modo_destino = "rascunho"
        if sd.score_editorial < PESOS["score_min_autopublicacao"]:
            motivos_rej.append(
                f"Score editorial {sd.score_editorial} < mínimo autopub {PESOS['score_min_autopublicacao']}")
        if sd.score_confianca_autopub < PESOS["confianca_min_autopub"]:
            sd.barrado_por_baixa_confianca = True
            motivos_rej.append(
                f"Confiança {sd.score_confianca_autopub} < mínimo {PESOS['confianca_min_autopub']}")

    sd.motivos_aprovacao = motivos_ap
    sd.motivos_rejeicao  = motivos_rej
    return sd


# Compatibilidade: mantém assinatura antiga para não quebrar código existente
def calcular_score_editorial(pauta: dict) -> int:
    """Wrapper de compatibilidade — retorna apenas score_editorial (int)."""
    sd = calcular_score_completo(pauta)
    pauta.setdefault("canal_forcado", sd.canal_sugerido)
    pauta.setdefault("score_detalhe", {})
    return sd.score_editorial


# ══════════════════════════════════════════════════════════════════════════════
# FILTRO E ORDENAÇÃO EDITORIAL
# ══════════════════════════════════════════════════════════════════════════════

def filtrar_e_ordenar(
    pautas: list[dict],
    score_minimo: int = None,
    max_por_canal: int = None,
    modo: str = "painel",            # "painel" ou "monitor"
    contexto_fontes: dict = None,
) -> list[dict]:
    """
    Filtra, pontua, limita por canal e fonte, garante cobertura mínima.

    Parâmetros:
      score_minimo: mínimo para aprovação (padrão: score_min_rascunho para painel,
                    score_min_autopublicacao para monitor)
      max_por_canal: máximo de pautas por canal (padrão: max_por_canal dos PESOS)
      modo: "painel" = usa score_min_rascunho | "monitor" = usa score_min_autopublicacao
      contexto_fontes: dict de contagem por fonte no ciclo atual (para penalidade)

    Retorna lista ordenada de pautas com ScoreDetalhado embutido.
    """
    if score_minimo is None:
        if modo == "monitor":
            score_minimo = PESOS["score_min_autopublicacao"]
        else:
            score_minimo = PESOS["score_min_rascunho"]

    if max_por_canal is None:
        max_por_canal = PESOS["max_por_canal"]

    # Contexto de fontes para penalidade (contagem acumulada por fonte)
    if contexto_fontes is None:
        contexto_fontes = {}

    resultado: list[dict] = []
    saude_candidatos: list[dict] = []
    rural_candidatos: list[dict] = []

    for pauta in pautas:
        sd = calcular_score_completo(pauta, contexto_fontes)

        # Injeta score detalhado na pauta
        pauta["score_editorial"]        = sd.score_editorial
        pauta["score_autopub"]          = sd.score_confianca_autopub
        pauta["canal_forcado"]          = sd.canal_sugerido
        pauta["canal_confianca"]        = sd.canal_confianca
        pauta["modo_destino"]           = sd.modo_destino
        pauta["motivos_aprovacao"]      = sd.motivos_aprovacao
        pauta["motivos_rejeicao"]       = sd.motivos_rejeicao
        pauta["barrado_por_tempo"]      = sd.barrado_por_tempo
        pauta["barrado_por_repeticao"]  = sd.barrado_por_repeticao
        pauta["barrado_fonte_excedente"]= sd.barrado_por_fonte_excedente
        pauta["barrado_baixa_confianca"]= sd.barrado_por_baixa_confianca

        print(f"[SCORING] {pauta.get('titulo_origem','')[:60]}")
        print(sd.resumo_log())

        # Acumula candidatos obrigatórios de Saúde e Rural (independente de score)
        if sd.canal_sugerido == "Saúde":
            saude_candidatos.append(pauta)
        if sd.canal_sugerido == "Rural":
            rural_candidatos.append(pauta)

        if sd.score_editorial >= score_minimo and not sd.barrado_por_tempo:
            resultado.append(pauta)

    # ── Garante cobertura mínima de Saúde e Rural ─────────────────────────────
    min_saude = PESOS["min_candidatos_saude"]
    min_rural = PESOS["min_candidatos_rural"]

    saude_no_resultado = [p for p in resultado if p.get("canal_forcado") == "Saúde"]
    rural_no_resultado = [p for p in resultado if p.get("canal_forcado") == "Rural"]

    # Adiciona candidatos de Saúde que ficaram abaixo do limiar, até min_saude
    if len(saude_no_resultado) < min_saude:
        saude_faltando = min_saude - len(saude_no_resultado)
        saude_extras = [
            p for p in saude_candidatos
            if p not in resultado
            and not p.get("barrado_por_tempo")
        ]
        saude_extras.sort(key=lambda p: p.get("score_editorial", 0), reverse=True)
        for p in saude_extras[:saude_faltando]:
            p["motivos_aprovacao"] = (p.get("motivos_aprovacao") or []) + [
                f"Incluído como candidato mínimo de Saúde ({len(saude_no_resultado)+1}/{min_saude})"
            ]
            p["aprovado_saude_obrigatorio"] = True
            resultado.append(p)
            print(f"[SCORING] SAÚDE OBRIGATÓRIO: {p.get('titulo_origem','')[:60]}")

    if len(rural_no_resultado) < min_rural:
        rural_faltando = min_rural - len(rural_no_resultado)
        rural_extras = [
            p for p in rural_candidatos
            if p not in resultado
            and not p.get("barrado_por_tempo")
        ]
        rural_extras.sort(key=lambda p: p.get("score_editorial", 0), reverse=True)
        for p in rural_extras[:rural_faltando]:
            p["motivos_aprovacao"] = (p.get("motivos_aprovacao") or []) + [
                f"Incluído como candidato mínimo de Rural ({len(rural_no_resultado)+1}/{min_rural})"
            ]
            p["aprovado_rural_obrigatorio"] = True
            resultado.append(p)
            print(f"[SCORING] RURAL OBRIGATÓRIO: {p.get('titulo_origem','')[:60]}")

    # ── Ordena: prioridade temporal + score ───────────────────────────────────
    resultado.sort(
        key=lambda p: (p.get("prioridade", 1), p.get("score_editorial", 0)),
        reverse=True,
    )

    # ── Limita por canal ──────────────────────────────────────────────────────
    contagem_canal: dict[str, int] = {}
    resultado_final: list[dict] = []
    for p in resultado:
        canal = p.get("canal_forcado", "outros")
        contagem_canal.setdefault(canal, 0)
        # Candidatos obrigatórios de Saúde/Rural sempre passam
        if (p.get("aprovado_saude_obrigatorio") or p.get("aprovado_rural_obrigatorio")
                or contagem_canal[canal] < max_por_canal):
            resultado_final.append(p)
            contagem_canal[canal] += 1
        else:
            print(f"[SCORING] LIMITE CANAL {canal} ({max_por_canal}): "
                  f"descartado '{p.get('titulo_origem','')[:50]}'")

    # ── Limita por fonte ──────────────────────────────────────────────────────
    max_por_fonte = PESOS["max_por_fonte_por_ciclo"]  # padrão 4
    contagem_fonte: dict[str, int] = {}
    resultado_com_fonte: list[dict] = []
    for p in resultado_final:
        nome_fonte = p.get("fonte_nome") or p.get("nome_fonte") or "desconhecida"
        contagem_fonte.setdefault(nome_fonte, 0)
        if contagem_fonte[nome_fonte] < max_por_fonte:
            resultado_com_fonte.append(p)
            contagem_fonte[nome_fonte] += 1
        else:
            print(f"[SCORING] LIMITE FONTE {nome_fonte} ({max_por_fonte}): "
                  f"descartado '{p.get('titulo_origem','')[:50]}'")
    resultado_final = resultado_com_fonte

    print(
        f"[SCORING] Total: {len(pautas)} → {len(resultado_final)} aprovadas "
        f"(modo={modo}, score_min={score_minimo}, max_canal={max_por_canal})"
    )
    return resultado_final
