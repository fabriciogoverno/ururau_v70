"""
editorial/receita_editorial.py — Receita Editorial Canônica do Ururau (v60)

Módulo de receita editorial: fonte única de verdade sobre como o Ururau
gera matérias jornalísticas. Expõe funções puras e reutilizáveis em todo
o pipeline de produção.

Fluxo canônico:
  1. clean_source_material()         — limpa a fonte de metadados e ruído
  2. separate_source_metadata()      — separa texto editorial de metadados
  3. extract_essential_facts()       — extrai fatos, números, citações, etc.
  4. classify_article_type()         — classifica o tipo de artigo
  5. choose_editorial_angle()        — escolhe o ângulo jornalístico
  6. build_editorial_brief()         — monta o briefing editorial
  7. build_paragraph_plan()          — planeja os parágrafos antes de escrever
  8. build_article_prompt()          — monta o user prompt para o modelo
  9. generate_article_package()      — executa geração completa via IA
  10. validate_article_package()     — valida o resultado gerado
  11. classify_validation_errors()   — classifica erros em 3 níveis
  12. revise_only_failed_fields()    — revisão automática dirigida
  13. can_publish()                  — gate de publicação

Modelo obrigatório: gpt-4.1-mini (via OPENAI_MODEL env var ou padrão)
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from openai import OpenAI

# ── Tipos de artigo suportados ────────────────────────────────────────────────

TIPOS_ARTIGO = [
    "hard_news",
    "politica",
    "justica",
    "policia",
    "economia",
    "trabalho",
    "cidade",
    "servico",
    "previa_jogo",
    "resultado_jogo",
    "nota_institucional",
    "declaracao_oficial",
    "investigacao",
    "decisao_judicial",
    "previa_evento",
    "cultura",
    "saude",
    "educacao",
    "tecnologia",
    "editorial",        # apenas quando explicitamente solicitado
]

# ── Palavras-chave para classificação automática de tipo ──────────────────────

_PISTAS_TIPO = {
    "previa_jogo": [
        "x ", "vs ", " vs ", "enfrenta", "decide", "duela", "mede forças",
        "semifinal", "final", "rodada", "campeonato", "copa", "playoffs",
        "escala", "escalação", "dúvida", "treinou", "retorna", "suspensão",
        "horário", "transmiss", "arena", "estádio",
    ],
    "resultado_jogo": [
        "venceu", "perdeu", "empatou", "goleou", "placar", "gols marcados",
        "derrota", "vitória", "empate", "classificou", "eliminado",
        "artilheiro", "autor do gol",
    ],
    "justica": [
        "tjrj", "stf", "stj", "trf", "tribunal", "juiz", "desembargador",
        "ministro do supremo", "liminar", "habeas corpus", "mandado de segurança",
        "sentença", "condenado", "absolvido", "réu", "ação penal", "inquérito",
        "recurso", "acórdão", "prisão preventiva", "prisão temporária",
    ],
    "policia": [
        "preso", "detido", "apreensão", "apreendeu", "operação policial",
        "delegacia", "civil", "militar", "federal", "ocorrência",
        "suspeito", "investigado", "flagrante", "mandado de busca",
        "homicídio", "latrocínio", "furto", "roubo", "estelionato",
    ],
    "economia": [
        "pib", "inflação", "ipca", "dólar", "câmbio", "banco central", "selic",
        "desemprego", "caged", "mercado", "bolsa", "ação", "dividendos",
        "faturamento", "receita", "lucro", "prejuízo", "exportação",
    ],
    "trabalho": [
        "trabalhador", "funcionário", "sindicato", "clt", "carteira assinada",
        "demissão", "contratação", "salário", "reajuste", "greve", "negociação",
        "convenção coletiva", "acordo coletivo", "mpt", "mte",
    ],
    "saude": [
        "hospital", "uti", "leito", "médico", "cirurgia", "vacina", "sus",
        "epidemia", "surto", "anvisa", "ministério da saúde", "secretaria de saúde",
        "doença", "tratamento", "medicamento",
    ],
    "educacao": [
        "escola", "aluno", "professor", "mec", "enem", "vestibular",
        "secretaria de educação", "universidade", "bolsa", "prouni", "fies",
        "matrículas", "aprovação",
    ],
    "politica": [
        "deputado", "senador", "vereador", "prefeito", "governador", "presidente",
        "partido", "alerj", "câmara", "senado", "congresso", "assembleia",
        "pl ", "pec", "mpv", "decreto", "projeto de lei",
    ],
    "servico": [
        "como se inscrever", "prazo de inscrição", "a partir de", "horário de atendimento",
        "gratuito", "gratuita", "taxa de inscrição", "como acessar",
        "agendamento", "vagas disponíveis", "documentos necessários",
    ],
    "nota_institucional": [
        "em nota", "por meio de nota", "nota oficial", "comunicado", "nota à imprensa",
        "sindicato informa", "federação esclarece", "entidade se posiciona",
        "confederação defende", "associação pede",
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# 1. LIMPEZA DA FONTE
# ─────────────────────────────────────────────────────────────────────────────

def clean_source_material(raw_source: str) -> str:
    """
    Limpa o texto-fonte de ruído que não pertence ao conteúdo editorial:
    - Partes de navegação e menus
    - Chamadas para ação (newsletter, subscribe, etc.)
    - Timestamps genéricos de site
    - Publicidade
    - Metadados de SEO
    - Contador de palavras/leitura
    """
    if not raw_source:
        return ""

    linhas = raw_source.splitlines()
    limpas = []

    _RUIDO_EXATO = {
        "assine o ururau", "assine agora", "newsletter",
        "clique aqui", "saiba mais", "leia também",
        "veja também", "veja mais", "acesse também",
        "compartilhe", "siga nossas redes", "curta nossa página",
        "baixe o aplicativo", "publicidade", "anúncio",
        "continua após o anúncio", "continua após publicidade",
    }
    _RUIDO_PARCIAL = [
        r"^\s*publicidade\s*$",
        r"^\s*\d+\s+min(uto)?s?\s+(de leitura|para ler)\s*$",
        r"^\s*leia também:?\s*$",
        r"^\s*veja (também|mais):?\s*$",
        r"^\s*(foto|imagem|galeria):\s*reprodução\s*$",
        r"^\s*foto:\s*\w",           # "Foto: NomeFotógrafo" sozinho na linha
        r"^\s*crédito:\s*",          # "Crédito: ..."
        r"^\s*legenda:\s*",          # "Legenda: ..."
        r"^\s*caption:\s*",          # "Caption: ..."
        r"^\s*©\s*\w",              # "© Portal Tal"
        r"^\s*todos os direitos",
        r"https?://\S+$",            # linha que é só URL
    ]
    _RUIDO_PARCIAL_C = [re.compile(p, re.IGNORECASE) for p in _RUIDO_PARCIAL]

    for linha in linhas:
        lb = linha.strip().lower()
        if lb in _RUIDO_EXATO:
            continue
        if any(p.search(linha) for p in _RUIDO_PARCIAL_C):
            continue
        limpas.append(linha)

    return "\n".join(limpas).strip()


# ─────────────────────────────────────────────────────────────────────────────
# 2. SEPARAÇÃO DE METADADOS
# ─────────────────────────────────────────────────────────────────────────────

def separate_source_metadata(raw_source: str) -> dict:
    """
    Separa o texto editorial dos metadados da fonte.

    Retorna dict com:
    - corpo_limpo: texto sem metadados
    - legendas_identificadas: legendas de imagem encontradas
    - creditos_foto: créditos de fotografia
    - links_relacionados: links/textos de "leia também"
    - metadados_descartados: lista de itens removidos
    """
    corpo_limpo = clean_source_material(raw_source)

    # Extrai legendas de imagem (padrões comuns)
    legendas = re.findall(
        r"(?:legenda|caption|foto|crédito foto):\s*(.+?)(?:\n|$)",
        raw_source, re.IGNORECASE
    )
    creditos = re.findall(
        r"(?:crédito|foto|imagem|reprodução):\s*([^\n]{5,80})",
        raw_source, re.IGNORECASE
    )
    links = re.findall(
        r"(?:leia também|veja também|relacionado):\s*(.+?)(?:\n|$)",
        raw_source, re.IGNORECASE
    )

    return {
        "corpo_limpo": corpo_limpo,
        "legendas_identificadas": [l.strip() for l in legendas if l.strip()],
        "creditos_foto": [c.strip() for c in creditos if c.strip()],
        "links_relacionados": [l.strip() for l in links if l.strip()],
        "metadados_descartados": legendas + creditos + links,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. EXTRAÇÃO DE FATOS ESSENCIAIS
# ─────────────────────────────────────────────────────────────────────────────

def extract_essential_facts(
    cleaned_source: str,
    metadata: dict | None = None,
    title: str = "",
    summary: str = "",
) -> dict:
    """
    Extrai fatos essenciais da fonte limpa sem chamar IA.
    Versão local/regex — para uso em testes e como fallback rápido.

    Para extração via IA, use agente_editorial_ururau.extract_essential_facts().
    """
    texto = (title + "\n" + summary + "\n" + cleaned_source).strip()
    texto_lower = texto.lower()

    # Números, percentuais, valores
    numeros = re.findall(
        r"\b\d+[.,]?\d*\s*(?:%|por cento|R\$|reais?|mil|milhões?|bilhões?|"
        r"horas?|dias?|anos?|meses?|vagas?|toneladas?|unidades?|km|metros?)\b",
        texto, re.IGNORECASE
    )
    # Remove duplicatas mantendo a ordem
    numeros = list(dict.fromkeys(n.strip() for n in numeros))[:15]

    # Artigos de lei e normas
    artigos = re.findall(
        r"art(?:igo)?\.?\s*\d+[º°]?\s*(?:[,;]?\s*(?:inciso|§|parágrafo)\s*[\wIVX]+)?"
        r"(?:\s+(?:da|do|de)\s+(?:Constituição|Lei|CLT|CF|CP|CPC|CDC|Lei\s+\d+))?",
        texto, re.IGNORECASE
    )
    artigos = list(dict.fromkeys(a.strip() for a in artigos))[:8]

    # Estudos e pesquisas
    estudos = re.findall(
        r"(?:estudo|pesquisa|levantamento|relatório|nota técnica|índice|survey|dados?)"
        r"\s+(?:da|do|de|pelo|pela)?\s+[\w\s]{3,30}",
        texto, re.IGNORECASE
    )
    estudos = list(dict.fromkeys(e.strip() for e in estudos))[:6]

    # Datas relativas preservadas exatamente como na fonte
    datas = re.findall(
        r"(?:nesta?|no|na)\s+(?:segunda|terça|quarta|quinta|sexta|sábado|domingo)"
        r"(?:-feira)?\s*(?:\(\d{1,2}\))?|"
        r"(?:ontem|hoje|amanhã|nesta semana|na semana passada|no próximo|no último)",
        texto, re.IGNORECASE
    )
    datas = list(dict.fromkeys(d.strip() for d in datas))[:5]

    # Citações com aspas
    citacoes = re.findall(r'"([^"]{20,200})"', texto)[:4]

    # Fato principal: primeira sentença do título ou summary
    fato_principal = (title or summary or cleaned_source[:200]).strip()
    if "." in fato_principal:
        fato_principal = fato_principal[:fato_principal.find(".") + 1]

    return {
        "fato_principal": fato_principal,
        "fatos_secundarios": [],
        "quem": [],
        "onde": "",
        "quando": "; ".join(datas[:3]) if datas else "",
        "orgao_central": "",
        "status_atual": "",
        "proximos_passos": "",
        "fonte_primaria": metadata.get("fonte_primaria", "") if metadata else "",
        "dados_numericos": numeros,
        "estudos_citados": estudos,
        "artigos_lei_citados": artigos,
        "impactos_citados": [],
        "argumentos_centrais": [],
        "pedidos_ou_encaminhamentos": [],
        "base_juridica": "",
        "declaracoes_identificadas": citacoes,
        "posicoes_conflitantes": [],
        "elementos_sem_fonte": [],
        "inferencias_a_evitar": [],
        "grau_confianca": "medio",
        "risco_editorial": "baixo",
        "fonte": "local",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. CLASSIFICAÇÃO DO TIPO DE ARTIGO
# ─────────────────────────────────────────────────────────────────────────────

def classify_article_type(
    essential_facts: dict,
    channel: str = "",
    source: str = "",
    title: str = "",
) -> str:
    """
    Classifica o tipo de artigo com base nos fatos essenciais, canal e fonte.

    Retorna um dos tipos em TIPOS_ARTIGO.
    A classificação guia a estrutura do artigo.
    """
    texto_busca = (
        (title or essential_facts.get("fato_principal", "")) + " " +
        source[:500]
    ).lower()

    # Canal já define o tipo em alguns casos
    if channel in ("Esportes",):
        for palavra in _PISTAS_TIPO["previa_jogo"]:
            if palavra.lower() in texto_busca:
                return "previa_jogo"
        for palavra in _PISTAS_TIPO["resultado_jogo"]:
            if palavra.lower() in texto_busca:
                return "resultado_jogo"
        return "hard_news"

    if channel == "Opinião":
        return "editorial"

    # Detecta tipo por palavras-chave na fonte
    tipo_scores: dict[str, int] = {}
    for tipo, pistas in _PISTAS_TIPO.items():
        score = sum(1 for p in pistas if p.lower() in texto_busca)
        if score > 0:
            tipo_scores[tipo] = score

    if tipo_scores:
        melhor = max(tipo_scores, key=tipo_scores.get)
        return melhor

    # Mapeamento canal → tipo padrão
    _mapa_canal = {
        "Polícia":       "policia",
        "Política":      "politica",
        "Economia":      "economia",
        "Cidades":       "cidade",
        "Estado RJ":     "hard_news",
        "Brasil e Mundo":"hard_news",
        "Saúde":         "saude",
        "Educação":      "educacao",
        "Tecnologia":    "tecnologia",
        "Rural":         "economia",
        "Entretenimento":"hard_news",
    }
    return _mapa_canal.get(channel, "hard_news")


# ─────────────────────────────────────────────────────────────────────────────
# 5. ESCOLHA DO ÂNGULO EDITORIAL
# ─────────────────────────────────────────────────────────────────────────────

def choose_editorial_angle(
    essential_facts: dict,
    article_type: str,
    channel: str = "",
) -> str:
    """
    Escolhe o ângulo jornalístico principal com base nos fatos extraídos.

    O ângulo é sempre baseado em fatos da fonte, nunca em tema genérico.
    Retorna string descrevendo o ângulo editorial.
    """
    fato = essential_facts.get("fato_principal", "")
    orgao = essential_facts.get("orgao_central", "")
    status = essential_facts.get("status_atual", "")
    proximos = essential_facts.get("proximos_passos", "")
    numeros = essential_facts.get("dados_numericos", [])
    impactos = essential_facts.get("impactos_citados", [])

    # Ângulos por tipo
    _angulos = {
        "policia":    "fato policial → investigação → status jurídico → versão da defesa",
        "justica":    "decisão judicial → partes afetadas → base legal → próximo passo processual",
        "decisao_judicial": "decisão judicial → efeito prático → base legal → recurso",
        "politica":   "fato político → disputa → quem decidiu → quem reagiu → efeito institucional",
        "economia":   "dado/decisão econômica → setor afetado → causa → impacto prático",
        "trabalho":   "relação trabalhista → partes → impacto sobre trabalhadores → base legal",
        "previa_jogo": "serviço do jogo → situação na competição → escalação → momento dos times",
        "resultado_jogo": "placar → situação na tabela → destaques individuais",
        "servico":    "o quê/quando/onde → quem pode → como acessar → prazo",
        "nota_institucional": "posição da entidade → argumento → dado de suporte → pedido",
        "saude":      "fato de saúde → órgão → população afetada → medida recomendada",
        "educacao":   "decisão educacional → instituição → alunos/professores afetados → prazo",
    }

    angulo_base = _angulos.get(article_type, "fato principal → contexto → consequência → próximo passo")

    # Enriquece com dados específicos da fonte
    detalhes = []
    if fato:
        detalhes.append(f"Fato: {fato[:120]}")
    if orgao:
        detalhes.append(f"Órgão central: {orgao}")
    if status:
        detalhes.append(f"Status: {status}")
    if numeros:
        detalhes.append(f"Número central: {numeros[0]}")
    if impactos:
        detalhes.append(f"Impacto principal: {impactos[0]}")
    if proximos:
        detalhes.append(f"Próximos passos (fonte): {proximos[:80]}")

    if detalhes:
        return angulo_base + "\n" + "\n".join(detalhes)
    return angulo_base


# ─────────────────────────────────────────────────────────────────────────────
# 6. BRIEFING EDITORIAL
# ─────────────────────────────────────────────────────────────────────────────

def build_editorial_brief(
    essential_facts: dict,
    article_type: str,
    angle: str,
) -> dict:
    """
    Monta o briefing editorial estruturado que guiará a redação.

    Retorna dict com todos os elementos que o redator/IA deve usar.
    """
    return {
        "tipo": article_type,
        "angulo": angle,
        "fato_principal": essential_facts.get("fato_principal", ""),
        "personagens_principais": essential_facts.get("quem", [])[:6],
        "local": essential_facts.get("onde", ""),
        "tempo": essential_facts.get("quando", ""),
        "orgao_central": essential_facts.get("orgao_central", ""),
        "status_atual": essential_facts.get("status_atual", ""),
        "dados_obrigatorios": essential_facts.get("dados_numericos", [])[:12],
        "estudos_a_citar": essential_facts.get("estudos_citados", [])[:6],
        "artigos_lei": essential_facts.get("artigos_lei_citados", [])[:6],
        "impactos": essential_facts.get("impactos_citados", [])[:8],
        "argumentos": essential_facts.get("argumentos_centrais", [])[:6],
        "pedidos": essential_facts.get("pedidos_ou_encaminhamentos", [])[:4],
        "base_juridica": essential_facts.get("base_juridica", ""),
        "citacoes": essential_facts.get("declaracoes_identificadas", [])[:4],
        "posicoes_conflitantes": essential_facts.get("posicoes_conflitantes", [])[:3],
        "inferencias_a_evitar": essential_facts.get("inferencias_a_evitar", [])[:4],
        "proximos_passos": essential_facts.get("proximos_passos", ""),
        "grau_confianca": essential_facts.get("grau_confianca", "medio"),
        "risco_editorial": essential_facts.get("risco_editorial", "baixo"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 7. PLANO DE PARÁGRAFOS
# ─────────────────────────────────────────────────────────────────────────────

def build_paragraph_plan(
    editorial_brief: dict,
    source_size: int = 0,
) -> list[dict]:
    """
    Constrói o plano de parágrafos antes de escrever o artigo.

    Tamanho proporcional ao texto-fonte:
    - Muito curta (< 300 chars): 2-3 parágrafos
    - Curta (< 800 chars): 3-5 parágrafos
    - Completa (>= 800 chars): 5-10 parágrafos

    Retorna lista de dicts com:
    - numero: int
    - funcao: string descrevendo o papel do parágrafo
    - conteudo_esperado: o que deve aparecer nele
    - obrigatorio: bool
    """
    tipo = editorial_brief.get("tipo", "hard_news")
    dados = editorial_brief.get("dados_obrigatorios", [])
    artigos = editorial_brief.get("artigos_lei", [])
    citacoes = editorial_brief.get("citacoes", [])
    impactos = editorial_brief.get("impactos", [])
    pedidos = editorial_brief.get("pedidos", [])
    proximos = editorial_brief.get("proximos_passos", "")
    conflitantes = editorial_brief.get("posicoes_conflitantes", [])

    # Define n_pars baseado no tamanho da fonte
    if source_size > 0 and source_size < 300:
        n_pars_max = 3
    elif source_size > 0 and source_size < 800:
        n_pars_max = 5
    else:
        n_pars_max = 8  # padrão para fonte completa

    # Plano base por tipo
    if tipo == "previa_jogo":
        plano = [
            {"numero": 1, "funcao": "SERVIÇO",
             "conteudo_esperado": "Times, competição, rodada/fase, data, horário, estádio, cidade",
             "obrigatorio": True},
            {"numero": 2, "funcao": "TRANSMISSÃO E CONTEXTO",
             "conteudo_esperado": "Onde assistir (TV/streaming), posição na tabela, o que está em jogo",
             "obrigatorio": True},
            {"numero": 3, "funcao": "SITUAÇÃO DO ELENCO",
             "conteudo_esperado": "Desfalques, retornos, dúvidas de escalação, suspensões",
             "obrigatorio": bool(dados or citacoes)},
            {"numero": 4, "funcao": "MOMENTO DOS TIMES",
             "conteudo_esperado": "Últimos resultados de cada time, sequência, fase do jogo",
             "obrigatorio": False},
            {"numero": 5, "funcao": "PERSPECTIVA TÁTICA",
             "conteudo_esperado": "Mudança tática ou declaração técnica, somente se fonte confirmar",
             "obrigatorio": False},
        ]

    elif tipo == "resultado_jogo":
        plano = [
            {"numero": 1, "funcao": "PLACAR E FATO PRINCIPAL",
             "conteudo_esperado": "Placar, times, competição, rodada, data, gols e tempos",
             "obrigatorio": True},
            {"numero": 2, "funcao": "SITUAÇÃO NA TABELA",
             "conteudo_esperado": "Posição dos times após o resultado, distância para outros",
             "obrigatorio": True},
            {"numero": 3, "funcao": "DESTAQUES",
             "conteudo_esperado": "Atuações individuais, gols, estatísticas citadas na fonte",
             "obrigatorio": bool(dados or citacoes)},
        ]

    elif tipo in ("policia", "investigacao"):
        plano = [
            {"numero": 1, "funcao": "LEAD POLICIAL",
             "conteudo_esperado": "Fato, local, data, órgão responsável, situação atual",
             "obrigatorio": True},
            {"numero": 2, "funcao": "CONTEXTO DO CASO",
             "conteudo_esperado": "Histórico da investigação, suspeitos, vítimas, circunstâncias",
             "obrigatorio": True},
            {"numero": 3, "funcao": "DADOS DA APURAÇÃO",
             "conteudo_esperado": "Valores apreendidos, itens, modalidade, base legal",
             "obrigatorio": bool(dados or artigos)},
            {"numero": 4, "funcao": "VERSÃO OFICIAL",
             "conteudo_esperado": "Declaração da polícia, MP ou autoridade competente",
             "obrigatorio": bool(citacoes)},
            {"numero": 5, "funcao": "STATUS JURÍDICO",
             "conteudo_esperado": "Situação do suspeito: preso, liberado, indiciado, investigado",
             "obrigatorio": True},
        ]

    elif tipo in ("justica", "decisao_judicial"):
        plano = [
            {"numero": 1, "funcao": "LEAD JUDICIAL",
             "conteudo_esperado": "Decisão, tribunal, relator/juiz, partes, efeito imediato",
             "obrigatorio": True},
            {"numero": 2, "funcao": "CONTEXTO DO PROCESSO",
             "conteudo_esperado": "Histórico do caso, partes envolvidas, pedidos anteriores",
             "obrigatorio": True},
            {"numero": 3, "funcao": "BASE LEGAL",
             "conteudo_esperado": "Artigos de lei, dispositivos constitucionais, precedentes",
             "obrigatorio": bool(artigos or editorial_brief.get("base_juridica"))},
            {"numero": 4, "funcao": "REAÇÕES",
             "conteudo_esperado": "Posição das partes, defesa, acusação, citações",
             "obrigatorio": bool(citacoes or conflitantes)},
            {"numero": 5, "funcao": "PRÓXIMOS PASSOS",
             "conteudo_esperado": "Recurso, prazo, próxima audiência (apenas se fonte confirmar)",
             "obrigatorio": bool(proximos)},
        ]

    elif tipo == "nota_institucional":
        plano = [
            {"numero": 1, "funcao": "QUEM E QUAL POSIÇÃO",
             "conteudo_esperado": "Entidade, posição tomada, tema central",
             "obrigatorio": True},
            {"numero": 2, "funcao": "ARGUMENTO PRINCIPAL",
             "conteudo_esperado": "Argumento central e dados que o sustentam",
             "obrigatorio": True},
            {"numero": 3, "funcao": "BASE LEGAL E DADOS",
             "conteudo_esperado": "Base jurídica, números, estudos citados pela entidade",
             "obrigatorio": bool(dados or artigos)},
            {"numero": 4, "funcao": "IMPACTOS CITADOS",
             "conteudo_esperado": "Impactos que a entidade cita para sustentar posição",
             "obrigatorio": bool(impactos)},
            {"numero": 5, "funcao": "PEDIDO OU ENCAMINHAMENTO",
             "conteudo_esperado": "O que a entidade pede, propõe ou exige",
             "obrigatorio": bool(pedidos)},
        ]

    elif tipo == "servico":
        plano = [
            {"numero": 1, "funcao": "O QUÊ/QUANDO/ONDE",
             "conteudo_esperado": "O que acontece/está disponível, quando, onde",
             "obrigatorio": True},
            {"numero": 2, "funcao": "COMO ACESSAR",
             "conteudo_esperado": "Quem pode, como fazer, custo, documentos necessários",
             "obrigatorio": True},
            {"numero": 3, "funcao": "DETALHES DO SERVIÇO",
             "conteudo_esperado": "Informações adicionais, organizador, contato",
             "obrigatorio": False},
        ]

    else:
        # Hard news / genérico
        plano = [
            {"numero": 1, "funcao": "LEAD",
             "conteudo_esperado": "Quem, o quê, onde, quando, por quê/consequência",
             "obrigatorio": True},
            {"numero": 2, "funcao": "CONTEXTO IMEDIATO",
             "conteudo_esperado": "Causa, antecedentes, histórico relevante",
             "obrigatorio": True},
            {"numero": 3, "funcao": "DADOS E DETALHES",
             "conteudo_esperado": "Números, nomes, instituições, decisões, documentos",
             "obrigatorio": bool(dados or artigos)},
            {"numero": 4, "funcao": "CONSEQUÊNCIAS",
             "conteudo_esperado": "Efeito prático, grupo afetado, impacto",
             "obrigatorio": bool(impactos)},
            {"numero": 5, "funcao": "CITAÇÃO OU POSIÇÃO OFICIAL",
             "conteudo_esperado": "Declaração atribuída, resposta, posição institucional",
             "obrigatorio": bool(citacoes)},
            {"numero": 6, "funcao": "CONTEXTO ADICIONAL",
             "conteudo_esperado": "Partes afetadas secundárias, impactos setoriais",
             "obrigatorio": False},
            {"numero": 7, "funcao": "FECHO FACTUAL",
             "conteudo_esperado": "Próximos passos, status, resposta ou ausência de resposta",
             "obrigatorio": bool(proximos)},
        ]

    # Limita ao máximo proporcional
    plano = plano[:n_pars_max]

    # Remove parágrafos opcionais se a fonte for curta
    if source_size > 0 and source_size < 800:
        plano = [p for p in plano if p["obrigatorio"]]
        # Garante pelo menos 2 parágrafos
        if len(plano) < 2 and n_pars_max >= 2:
            # Inclui parágrafos opcionais até completar 2
            todos_plano = build_paragraph_plan(editorial_brief, source_size=999)
            for p in todos_plano:
                if len(plano) >= n_pars_max:
                    break
                if not any(x["numero"] == p["numero"] for x in plano):
                    plano.append(p)
            plano.sort(key=lambda x: x["numero"])

    return plano


# ─────────────────────────────────────────────────────────────────────────────
# 8. CONSTRUÇÃO DO PROMPT DO ARTIGO
# ─────────────────────────────────────────────────────────────────────────────

def build_article_prompt(
    editorial_brief: dict,
    paragraph_plan: list[dict],
    options: dict | None = None,
) -> str:
    """
    Monta o user prompt estruturado para envio ao modelo de IA.

    O prompt inclui:
    - Tipo e ângulo do artigo
    - Fatos obrigatórios
    - Plano de parágrafos
    - Instruções de tamanho proporcional
    - Schema de saída
    """
    opts = options or {}
    source_text = opts.get("source_text", "")
    canal = opts.get("canal", "Brasil e Mundo")
    modelo = opts.get("modelo", "gpt-4.1-mini")
    pedir_instagram = opts.get("legenda_instagram", False)

    tipo = editorial_brief.get("tipo", "hard_news")
    angulo = editorial_brief.get("angulo", "")
    fato = editorial_brief.get("fato_principal", "")
    dados_obrig = editorial_brief.get("dados_obrigatorios", [])
    artigos = editorial_brief.get("artigos_lei", [])
    estudos = editorial_brief.get("estudos_a_citar", [])
    impactos = editorial_brief.get("impactos", [])
    argumentos = editorial_brief.get("argumentos", [])
    pedidos = editorial_brief.get("pedidos", [])
    citacoes = editorial_brief.get("citacoes", [])
    base_jur = editorial_brief.get("base_juridica", "")
    inferencias_evitar = editorial_brief.get("inferencias_a_evitar", [])

    source_size = len(source_text)
    if source_size < 300:
        instrucao_tamanho = "FONTE MUITO CURTA: gere 2-3 parágrafos. Não expanda sem respaldo."
        n_pars = "2-3"
    elif source_size < 800:
        instrucao_tamanho = "FONTE CURTA: gere 3-5 parágrafos. Preserve todos os fatos."
        n_pars = "3-5"
    else:
        instrucao_tamanho = "FONTE COMPLETA: gere 5-8 parágrafos com todos os dados essenciais."
        n_pars = "5-8"

    # Bloco de dados obrigatórios
    linhas_obrig = []
    tem_dados = any([dados_obrig, estudos, artigos, impactos, argumentos, pedidos, base_jur])
    if tem_dados:
        linhas_obrig = [
            "╔══════════════════════════════════════════════════════╗",
            "║  DADOS ESSENCIAIS — OBRIGATÓRIOS NA MATÉRIA FINAL   ║",
            "╚══════════════════════════════════════════════════════╝",
        ]
        if dados_obrig:
            linhas_obrig.append("📊 NÚMEROS E DADOS:")
            linhas_obrig += [f"   • {d}" for d in dados_obrig[:12]]
        if estudos:
            linhas_obrig.append("📚 ESTUDOS E PESQUISAS:")
            linhas_obrig += [f"   • {e}" for e in estudos[:6]]
        if artigos:
            linhas_obrig.append("⚖️  ARTIGOS DE LEI:")
            linhas_obrig += [f"   • {a}" for a in artigos[:6]]
        if impactos:
            linhas_obrig.append("⚡ IMPACTOS:")
            linhas_obrig += [f"   • {i}" for i in impactos[:6]]
        if argumentos:
            linhas_obrig.append("💬 ARGUMENTOS CENTRAIS:")
            linhas_obrig += [f"   • {a}" for a in argumentos[:6]]
        if pedidos:
            linhas_obrig.append("📋 PEDIDOS/ENCAMINHAMENTOS:")
            linhas_obrig += [f"   • {p}" for p in pedidos[:4]]
        if base_jur:
            linhas_obrig.append(f"📜 BASE JURÍDICA: {base_jur}")

    bloco_obrig = "\n".join(linhas_obrig)

    # Plano de parágrafos como instrução
    linhas_plano = ["== PLANO DE PARÁGRAFOS (siga esta estrutura) =="]
    for p in paragraph_plan:
        obrig_txt = "OBRIGATÓRIO" if p["obrigatorio"] else "se houver na fonte"
        linhas_plano.append(
            f"§{p['numero']} [{p['funcao']}] ({obrig_txt}): {p['conteudo_esperado']}"
        )
    bloco_plano = "\n".join(linhas_plano)

    # Citações
    bloco_citacoes = ""
    if citacoes:
        bloco_citacoes = (
            "📣 DECLARAÇÕES COM ATRIBUIÇÃO:\n" +
            "\n".join(f"   • {c}" for c in citacoes[:4])
        )

    # Inferências a evitar
    bloco_evitar = ""
    if inferencias_evitar:
        bloco_evitar = (
            "🚫 NÃO ESCREVA (inferências não confirmadas):\n" +
            "\n".join(f"   • {i}" for i in inferencias_evitar[:4])
        )

    instagram_instrucao = ""
    if pedir_instagram:
        instagram_instrucao = """
LEGENDA_INSTAGRAM: gerar com estrutura:
  1. título no topo (sem emoji)
  2. texto narrativo longo com dados principais
  3. fechamento fixo: "🔗Leia a matéria completa no site Ururau - Link na Bio e Stories ➡ Siga a página: @ururaunoticias"
"""

    schema_saida = {
        "titulo_seo": "",
        "subtitulo_curto": "",
        "retranca": "",
        "titulo_capa": "",
        "tags": [],
        "legenda_curta": "",
        "corpo_materia": "",
        "legenda_instagram": "",
        "meta_description": "",
        "nome_da_fonte": "",
        "link_da_fonte": "",
        "creditos_da_foto": "",
        "status_validacao": "pendente",
        "erros_validacao": [],
        "observacoes_editoriais": [],
    }

    import json
    prompt = f"""
== PORTAL URURAU — GERAÇÃO EDITORIAL (modelo: {modelo}) ==
Canal: {canal} | Tipo de artigo: {tipo}
Ângulo editorial: {angulo}

== TEXTO-FONTE COMPLETO (leia ANTES de escrever) ==
{source_text[:7000]}

{bloco_obrig}

{bloco_citacoes}

{bloco_evitar}

{bloco_plano}

== REGRAS ABSOLUTAS ==
1. {instrucao_tamanho}
2. Número de parágrafos: {n_pars}. Separação: \\n\\n entre parágrafos.
3. Lead (§1): quem, o quê, onde, quando, por quê/consequência. Sem abertura genérica.
4. NUNCA invente data. Datas relativas ("nesta quinta-feira (23)") preservar EXATAMENTE.
5. NUNCA use travessão (— ou –). Use vírgula, dois-pontos ou ponto.
6. NUNCA adicione frases sem respaldo: "investigações seguem", "próximo passo será",
   "autoridades continuarão", "novas informações serão divulgadas".
7. NUNCA copie frases da fonte. Reescreva com apuração própria.
8. NUNCA cite o veículo de origem no corpo.
9. titulo_seo: 40-89 chars, fato/personagem/instituição no INÍCIO.
10. titulo_capa: 20-60 chars, forte para home.
11. tags: 5-12 strings sem portal de origem.
12. ZERO expressões de IA proibidas.
{instagram_instrucao}

== SCHEMA DE SAÍDA (JSON obrigatório — nenhum texto fora do JSON) ==
{json.dumps(schema_saida, ensure_ascii=False, indent=2)}
""".strip()

    return prompt


# ─────────────────────────────────────────────────────────────────────────────
# 12. CLASSIFICAÇÃO DE ERROS DE VALIDAÇÃO
# ─────────────────────────────────────────────────────────────────────────────

# Mapeamento de código de erro → categoria e se bloqueia publicação
_MAPA_CATEGORIAS_ERRO = {
    # EDITORIAL_BLOCKER — bloqueia publicação
    "invented_date":            ("EDITORIAL_BLOCKER", True),
    "unsupported_claim":        ("EDITORIAL_BLOCKER", True),
    "unsupported_next_step":    ("EDITORIAL_BLOCKER", True),
    "title_meaning_changed":    ("EDITORIAL_BLOCKER", True),
    "numeric_meaning_changed":  ("EDITORIAL_BLOCKER", True),
    "missing_central_fact":     ("EDITORIAL_BLOCKER", True),
    "source_too_weak":          ("EDITORIAL_BLOCKER", True),
    "wrong_source":             ("EDITORIAL_BLOCKER", True),
    "plagiarism_risk":          ("EDITORIAL_BLOCKER", True),
    "prohibited_expression":    ("EDITORIAL_BLOCKER", True),
    "em_dash":                  ("EDITORIAL_BLOCKER", True),
    "truncated_title":          ("EDITORIAL_BLOCKER", True),
    "factual_contradiction":    ("EDITORIAL_BLOCKER", True),
    "metadata_used_as_conclusion": ("EDITORIAL_BLOCKER", True),
    "date_invented":            ("EDITORIAL_BLOCKER", True),
    "expansao_artificial":      ("EDITORIAL_BLOCKER", True),
    "frases_unsupported":       ("EDITORIAL_BLOCKER", True),
    "caption_misuse":           ("EDITORIAL_BLOCKER", True),
    "dado_essencial":           ("EDITORIAL_BLOCKER", True),
    "precisao_numerica":        ("EDITORIAL_BLOCKER", True),
    "precisao_titulo":          ("EDITORIAL_BLOCKER", True),
    "consistencia_titulo_corpo": ("EDITORIAL_BLOCKER", True),
    "violacao_factual":         ("EDITORIAL_BLOCKER", True),
    "violacao_editorial":       ("EDITORIAL_BLOCKER", True),

    # FIXABLE_FIELD — não bloqueia, mas precisa de correção
    "missing_source_name":      ("FIXABLE_FIELD", False),
    "missing_photo_credit":     ("FIXABLE_FIELD", False),
    "photo_credit_needs_normalization": ("FIXABLE_FIELD", False),
    "too_many_tags":            ("FIXABLE_FIELD", False),
    "missing_meta_description": ("FIXABLE_FIELD", False),
    "short_meta_description":   ("FIXABLE_FIELD", False),
    "missing_instagram_caption": ("FIXABLE_FIELD", False),
    "missing_short_caption":    ("FIXABLE_FIELD", False),
    "invalid_image_strategy":   ("FIXABLE_FIELD", False),
    "source_name_too_long":     ("FIXABLE_FIELD", False),
    "publication_status_inconsistent": ("FIXABLE_FIELD", False),
    "missing_cover_title":      ("FIXABLE_FIELD", False),
    "tags_need_trim":           ("FIXABLE_FIELD", False),
    "nome_da_fonte":            ("FIXABLE_FIELD", False),
    "creditos_da_foto":         ("FIXABLE_FIELD", False),
    "meta_description":         ("FIXABLE_FIELD", False),
    "legenda_curta":            ("FIXABLE_FIELD", False),
    "legenda_instagram":        ("FIXABLE_FIELD", False),
    "titulo_capa":              ("FIXABLE_FIELD", False),  # quando é apenas comprimento
    "tags":                     ("FIXABLE_FIELD", False),

    # WARNING — avisos, não bloqueiam
    "title_can_improve":        ("WARNING", False),
    "many_direct_quotes":       ("WARNING", False),
    "structure_close_to_source": ("WARNING", False),
    "article_short_but_source_short": ("WARNING", False),
    "optional_social_package_missing": ("WARNING", False),
    "weak_image":               ("WARNING", False),
    "source_short_but_usable":  ("WARNING", False),
    "fechamento_interpretativo": ("WARNING", False),
    "repeticao_paragrafos":     ("WARNING", False),
    "citacao_excessiva":        ("WARNING", False),
    "verbo_crutch":             ("WARNING", False),
    "pacote_incompleto":        ("FIXABLE_FIELD", False),
    "multiplos_percentuais":    ("WARNING", False),
}


def classify_validation_errors(
    validation_errors: list,
) -> list[dict]:
    """
    Classifica uma lista de erros de validação em 3 categorias:
    - EDITORIAL_BLOCKER: bloqueia publicação (invented date, unsupported claim, etc.)
    - FIXABLE_FIELD: pode ser corrigido automaticamente (meta, tags, crédito, etc.)
    - WARNING: aviso, não bloqueia (estilo, estrutura próxima da fonte, etc.)

    Aceita erros como:
    - str: "campo: motivo" ou "tipo: mensagem"
    - dict com campos "campo", "categoria", "mensagem", etc. (do pipeline)
    - ErrorValidacao dataclass (com .campo e .motivo)

    Retorna lista de dicts padronizados com:
    {
        "codigo": str,
        "categoria": "EDITORIAL_BLOCKER" | "FIXABLE_FIELD" | "WARNING",
        "severidade": "alta" | "media" | "baixa",
        "campo": str,
        "mensagem": str,
        "trecho": str,
        "sugestao": str,
        "bloqueia_publicacao": bool,
        "corrigivel_automaticamente": bool,
    }
    """
    resultado = []

    for erro in validation_errors:
        # Erro já está no formato dict padronizado
        if isinstance(erro, dict):
            if "categoria" in erro:
                # Já classificado — normaliza e retorna
                cat = erro.get("categoria", "EDITORIAL_BLOCKER")
                bloqueador = cat == "EDITORIAL_BLOCKER"
                fixavel = cat == "FIXABLE_FIELD"
                resultado.append({
                    "codigo": erro.get("codigo", ""),
                    "categoria": cat,
                    "severidade": erro.get("severidade", "alta" if bloqueador else "media"),
                    "campo": erro.get("campo", ""),
                    "mensagem": erro.get("mensagem", str(erro)),
                    "trecho": erro.get("trecho", ""),
                    "sugestao": erro.get("sugestao", ""),
                    "bloqueia_publicacao": erro.get("bloqueia_publicacao", bloqueador),
                    "corrigivel_automaticamente": erro.get("corrigivel_automaticamente", fixavel),
                })
                continue

        # Converte string para dict
        if isinstance(erro, str):
            campo_raw = ""
            msg_raw = erro
            if ": " in erro:
                partes = erro.split(": ", 1)
                campo_raw = partes[0].strip().lower().replace(" ", "_")
                msg_raw = partes[1].strip()
        elif hasattr(erro, "campo") and hasattr(erro, "motivo"):
            # ErrorValidacao dataclass
            campo_raw = (getattr(erro, "campo", "") or "").lower().replace(" ", "_")
            msg_raw = getattr(erro, "motivo", str(erro))
        else:
            campo_raw = ""
            msg_raw = str(erro)

        # Determina categoria pelo campo ou palavras-chave da mensagem
        categoria, bloqueia = _inferir_categoria(campo_raw, msg_raw)

        fixavel = categoria == "FIXABLE_FIELD"
        sev = "alta" if bloqueia else ("media" if categoria == "FIXABLE_FIELD" else "baixa")

        resultado.append({
            "codigo": campo_raw,
            "categoria": categoria,
            "severidade": sev,
            "campo": campo_raw,
            "mensagem": msg_raw,
            "trecho": "",
            "sugestao": _sugestao_padrao(categoria, campo_raw),
            "bloqueia_publicacao": bloqueia,
            "corrigivel_automaticamente": fixavel,
        })

    return resultado


def _inferir_categoria(campo: str, mensagem: str) -> tuple[str, bool]:
    """Infere categoria e se bloqueia a partir do campo e mensagem."""
    # Procura correspondência direta no mapa
    for codigo, (cat, bloq) in _MAPA_CATEGORIAS_ERRO.items():
        if codigo in campo or codigo in mensagem.lower():
            return cat, bloq

    # Heurísticas por palavras-chave na mensagem
    msg_lower = mensagem.lower()
    _blocker_keywords = [
        "inventad", "invent", "não suportad", "unsupported", "contradição",
        "violação factual", "data inválida", "data inventada", "significado",
        "categoria semântica", "travessão", "proibida", "plagiar", "expressão proibida",
        "dado essencial ausente", "fato central ausente", "truncad",
    ]
    _fixable_keywords = [
        "fonte ausente", "crédito ausente", "meta_description", "legenda curta",
        "tags", "titulo_capa vazio", "nome_da_fonte", "creditos_da_foto",
        "instagram", "imagem", "slug",
    ]
    _warning_keywords = [
        "fechamento interpretativo", "repetição", "citação excessiva",
        "verbo muleta", "múltiplos percentuais", "estrutura próxima",
        "artigo curto", "fonte curta",
    ]

    for kw in _blocker_keywords:
        if kw in msg_lower:
            return "EDITORIAL_BLOCKER", True
    for kw in _fixable_keywords:
        if kw in msg_lower:
            return "FIXABLE_FIELD", False
    for kw in _warning_keywords:
        if kw in msg_lower:
            return "WARNING", False

    # Default: blocker (conservador)
    return "EDITORIAL_BLOCKER", True


def _sugestao_padrao(categoria: str, campo: str) -> str:
    """Gera sugestão padrão para o campo e categoria."""
    if categoria == "FIXABLE_FIELD":
        _sugestoes = {
            "nome_da_fonte": "Preencha o campo nome_da_fonte com o veículo de origem.",
            "creditos_da_foto": "Preencha o campo creditos_da_foto (ex: 'Reprodução', 'Agência Brasil').",
            "meta_description": "Gere uma meta_description com 120-160 chars baseada no lead.",
            "legenda_curta": "Preencha a legenda_curta com descrição factual da imagem (≤100 chars).",
            "tags": "Ajuste as tags: 5-12 itens, sem portal de origem.",
            "titulo_capa": "Ajuste o titulo_capa: 20-60 chars.",
            "legenda_instagram": "Gere legenda_instagram se distribuição social for necessária.",
        }
        return _sugestoes.get(campo, f"Corrija o campo {campo}.")
    elif categoria == "WARNING":
        return "Verifique o texto para melhoria editorial."
    return "Corrija o erro antes de publicar."


# ─────────────────────────────────────────────────────────────────────────────
# 13. GATE DE PUBLICAÇÃO
# ─────────────────────────────────────────────────────────────────────────────

def can_publish(article: dict) -> tuple[bool, str]:
    """
    Gate de publicação: determina se um artigo pode ser publicado.

    Retorna (True, "") se pode publicar.
    Retorna (False, motivo) se não pode.

    Regras (em ordem):
    1. Aprovação manual válida → pode publicar mesmo com erros
    2. status_validacao == "aprovado" AND auditoria_bloqueada == False
       AND sem EDITORIAL_BLOCKER → pode publicar
    3. Qualquer outro caso → bloqueado
    """
    # Importa a função canônica do workflow para evitar duplicação
    try:
        from ururau.publisher.workflow import can_publish as _gate
        return _gate(article)
    except ImportError:
        pass

    # Fallback local (para testes sem o workflow)
    if not article:
        return False, "Artigo nulo ou vazio."

    # CONFIG_ERROR e EXTRACTION_ERROR bloqueiam SEMPRE — antes de qualquer outra verificação
    if article.get("_is_config_error"):
        return False, "CONFIG_ERROR: pipeline abortou por falha de API. Artigo não gerado."

    sv_raw = article.get("status_validacao") or ""
    sv_str = sv_raw if isinstance(sv_raw, str) else ""
    if sv_str == "erro_configuracao":
        return False, "CONFIG_ERROR: status_validacao='erro_configuracao'. Artigo não gerado."
    if sv_str == "erro_extracao":
        return False, "EXTRACTION_ERROR: status_validacao='erro_extracao'. Artigo não gerado."

    erros = article.get("erros_validacao", []) or []
    cfg_erros = [e for e in erros if isinstance(e, dict) and e.get("categoria") == "CONFIG_ERROR"]
    if cfg_erros:
        return False, f"CONFIG_ERROR: {cfg_erros[0].get('mensagem','Falha de API')}."
    ext_erros = [e for e in erros if isinstance(e, dict) and e.get("categoria") == "EXTRACTION_ERROR"]
    if ext_erros:
        return False, f"EXTRACTION_ERROR: {ext_erros[0].get('mensagem','Fonte inválida')}."

    corpo = (article.get("corpo_materia") or article.get("conteudo") or "").strip()
    if not corpo:
        return False, "Artigo sem corpo — pipeline não gerou conteúdo."

    approved_by = (article.get("approved_by") or "").strip()
    approved_at = (article.get("approved_at") or "").strip()
    reason = (article.get("manual_approval_reason") or "").strip()
    if approved_by and approved_at and reason:
        return True, ""

    sv = sv_str.lower() if sv_str else str(sv_raw).lower()
    if isinstance(sv_raw, dict):
        sv = "aprovado" if sv_raw.get("aprovado") else "reprovado"

    if sv != "aprovado":
        return False, f"status_validacao='{sv}' (esperado: 'aprovado')."

    if article.get("auditoria_bloqueada", True):
        return False, "Auditoria bloqueou o artigo."

    blockers = [
        e for e in erros
        if isinstance(e, dict) and e.get("categoria") == "EDITORIAL_BLOCKER"
    ]
    if blockers:
        return False, f"{len(blockers)} EDITORIAL_BLOCKER(s) não resolvido(s)."

    return True, ""


# ─────────────────────────────────────────────────────────────────────────────
# FUNÇÕES DE STATUS DERIVADO (baseadas na classificação de erros)
# ─────────────────────────────────────────────────────────────────────────────

def derive_validation_status(classified_errors: list[dict]) -> dict:
    """
    Deriva o status de validação a partir dos erros classificados.

    Retorna dict com:
    - status_validacao: "aprovado" | "pendente" | "reprovado"
    - status_publicacao_sugerido: "publicar" | "salvar_rascunho" | "bloquear"
    - auditoria_bloqueada: bool
    - revisao_humana_necessaria: bool
    """
    tem_blocker = any(
        e.get("categoria") == "EDITORIAL_BLOCKER" for e in classified_errors
    )
    tem_fixable = any(
        e.get("categoria") == "FIXABLE_FIELD" for e in classified_errors
    )

    if tem_blocker:
        return {
            "status_validacao": "reprovado",
            "status_publicacao_sugerido": "bloquear",
            "auditoria_bloqueada": True,
            "revisao_humana_necessaria": True,
        }
    elif tem_fixable:
        return {
            "status_validacao": "pendente",
            "status_publicacao_sugerido": "salvar_rascunho",
            "auditoria_bloqueada": False,
            "revisao_humana_necessaria": True,
        }
    else:
        return {
            "status_validacao": "aprovado",
            "status_publicacao_sugerido": "publicar",
            "auditoria_bloqueada": False,
            "revisao_humana_necessaria": False,
        }
