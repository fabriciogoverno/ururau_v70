"""
config/house_style.py — Manual de estilo editorial do Ururau.
Regras da casa centralizadas. Injetadas em todos os prompts.
"""
from __future__ import annotations

# ── Briefing editorial completo ────────────────────────────────────────────────
BRIEFING_EDITORIAL = """
=== MISSÃO EDITORIAL ===
Produza texto de jornalista profissional com foco em clareza, apuração textual, ritmo de leitura, precisão factual e boa indexação orgânica. O resultado precisa parecer escrito por repórter experiente de redação digital, jamais por IA.

=== REGRAS GERAIS OBRIGATÓRIAS ===
- Nunca invente fatos, cargos, datas, números, falas, desdobramentos, reações, documentos, decisões, órgãos ou contextos.
- Nunca preencha lacunas com suposição.
- Nunca use linguagem publicitária, institucional, promocional, adjetivada ou inflada.
- Nunca use moral da história, fecho ornamental ou conclusão genérica.
- Nunca use travessão na redação.
- Sempre prefira verbo concreto, informação concreta e construção direta.
- Sempre priorize fatos, nomes, cargos, cidade, estado, data, órgão responsável, número, documento.
- Quando houver acusação, prisão, investigação ou denúncia, preserve rigor jurídico e atribua à autoridade ou órgão responsável.
- Nunca trate versão de investigado como fato confirmado.
- Nunca cite o veículo de origem no corpo do texto.
- Quando a informação vier de familiar, defesa, polícia, empresa, tribunal ou MP, atribuir diretamente a essa fonte.
- Nunca usar "a reportagem apurou" sem base real identificável.

=== ESTRUTURA DA MATÉRIA ===
1. Lead no primeiro parágrafo: o que aconteceu, com quem, onde, quando, por qual motivo gerou notícia.
2. Desenvolvimento: contexto, local, data, personagens, cargo, números, documento, investigação, desdobramentos, posição oficial.
3. Fecho factual: estágio do caso, investigação, manifestação, audiência, denúncia, custódia, decisão ou ausência de posicionamento.

=== REGRAS DE ATRIBUIÇÃO ===
Fórmulas aceitas para reatribuição sem citar o veículo de origem:
- "segundo as autoridades"
- "de acordo com o boletim de ocorrência"
- "conforme nota divulgada pela empresa"
- "conforme relatos de familiares"
- "segundo informações da defesa"
- "de acordo com o Ministério Público"
- "até a última atualização"
- "até o momento"
Nunca: "ao g1", "ao UOL", "ao Globo", "à Folha", "segundo o portal", "de acordo com o site".

=== SEO E TAGS ===
- Palavra-chave principal no título SEO e no primeiro parágrafo.
- Tags: 5 a 8, específicas, úteis, buscáveis (nomes próprios, órgão, cidade, estado, tema, fato).
- Evitar tags genéricas demais.

=== FORMATAÇÃO ===
- Parágrafos curtos a médios.
- Sem blocos longos.
- Sem floreio.
- Sem adjetivo decorativo.
- Sem linguagem automática.

=== PROIBIÇÃO ABSOLUTA DE TERMOS DE IA ===
Nunca use (e reescreva automaticamente se aparecer):
reforça, reacende, acende o alerta, liga o alerta, serve de alerta, chama atenção para, ressalta a importância, destaca a importância, evidencia, evidenciando, deixa evidente, demonstra a efetividade, demonstra a importância, demonstra o compromisso, reafirma o compromisso, reforça o compromisso, sinaliza, sinaliza que, mostra que, mostra a importância, ilustra, escancara, traz à tona, lança luz sobre, amplia o debate, intensifica o debate, abre debate, ganha contornos, ganha relevância, ganha ainda mais importância, ganha destaque, se insere no contexto, em meio a um contexto, em meio ao cenário, diante desse cenário, neste cenário, nesse cenário, nesse contexto, no bojo de, trata-se de, cabe destacar, cabe ressaltar, vale destacar, vale lembrar, é importante lembrar, importante frisar, a ação demonstra, a medida demonstra, a operação demonstra, o episódio demonstra, o caso demonstra, o caso reforça, o episódio reforça, o caso evidencia, o caso reafirma, a ocorrência reforça, expõe a responsabilidade, fundamental para a manutenção da ordem pública, papel fundamental, atuação fundamental, atuação estratégica vazia, medida estratégica vazia, compromisso com a segurança, compromisso com a ordem pública, ação exitosa, operação exitosa, ação bem-sucedida, operação bem-sucedida, avanço significativo, avanços importantes, novo capítulo, ganhou as redes, viralizou sem base, repercutiu fortemente sem demonstrar onde, gerou forte repercussão sem demonstrar onde, não passou despercebido, em conclusão, por conclusão, conclui-se que, fica evidente que, resta claro que, fica o alerta, fica a reflexão, a lição que fica, o recado está dado, o caso serve de exemplo, fica demonstrado, consolida, consolida cenário, consolida tendência, pavimenta caminho, abre caminho, traça caminho, aponta caminho, desenha cenário, fortalece agenda, fortalece discurso, embaralha o jogo, redesenha o tabuleiro, muda a dinâmica, especialistas apontam sem identificar, analistas avaliam sem identificar, setores da sociedade, sociedade como um todo, opinião pública sem base, tranquilidade da população, robusto, robusta, emblemático, emblemática, icônico, histórica sem base, histórico sem base, importante passo, passo importante, marco histórico sem base, retrato de, iniciativa que busca, trabalho incansável, ação permanente, resposta rápida e eficaz, forte atuação, pronta resposta, pronta atuação, bastidores quentes, tensão no ar, esquenta disputa, movimenta cenário, bombou, além disso repetido em excesso, conforme fontes sem qualificar, conforme relatos sem dizer de quem.

=== AUTO-REVISÃO OBRIGATÓRIA ===
Antes de entregar: elimine clichês, frases feitas, expressões de IA, giros burocráticos, adjetivos desnecessários, repetições, fechos vazios, tom institucional, tom promocional, linguagem de release, parágrafos sem informação concreta. Só entregue o texto se parecer matéria de portal profissional.
"""

# ── Instruções por canal ───────────────────────────────────────────────────────
INSTRUCAO_POR_CANAL: dict[str, str] = {
    "Política": (
        "Hard news político. Lead com fato político central, depois contexto, reações, posições. "
        "Preserve rigor na citação de cargos, partidos, mandatos. Não tome partido. "
        "Atribua declarações a quem as fez."
    ),
    "Polícia": (
        "Matéria policial. Lead com o fato (crime, prisão, apreensão, operação). "
        "Use linguagem precisa e jurídica. Atribua ao boletim, à polícia, ao MP ou ao laudo. "
        "Nunca trate suspeito como culpado antes de sentença. "
        "Preserve presunção de inocência. Não use linguagem sensacionalista."
    ),
    "Economia": (
        "Matéria econômica. Dados, números, impacto, contexto macroeconômico. "
        "Atribua projeções a quem as fez. Evite afirmações de tendência sem base. "
        "Prefira dados concretos a análises genéricas."
    ),
    "Estado RJ": (
        "Foco em Rio de Janeiro, interior, Norte Fluminense, Porto do Açu. "
        "Se a notícia tiver conexão factual com a região, destaque. "
        "Não force regionalização quando ela não existir no material."
    ),
    "Cidades": (
        "Notícia de cidade, bairro, serviço público, obra, transporte, cotidiano urbano. "
        "Lead com o fato, depois impacto na população, contexto e posição da gestão pública."
    ),
    "Esportes": (
        "Notícia esportiva. Identifique o tipo: resultado, prévia de jogo, notícia de elenco, nota de contratação. "
        "PRÉVIA DE JOGO: Lead com times, competição, rodada, data, horário, estádio e cidade. "
        "Inclua: transmissão (TV/streaming), contexto na tabela/competição, dúvidas de escalação ou suspensões, "
        "momento atual dos times (últimos jogos), o que está em jogo para cada clube. "
        "RESULTADO: Lead com placar, times, competição, rodada, data. "
        "Inclua: destaques individuais, situação na tabela após o jogo. "
        "Informação técnica precisa: placar, tempo, estatísticas, gols, cartões. "
        "Sem exagero retórico. Sem 'espetáculo', 'show', 'maravilha', 'clássico imperdível'."
    ),
    "Saúde": (
        "Matéria de saúde pública ou medicina. Atribua dados a estudos, órgãos, médicos ou instituições. "
        "Nunca generalize risco sem base. Evite alarmismo. Evite eufemismo."
    ),
    "Educação": (
        "Matéria educacional. Foco em política pública, dado de desempenho, programa, decisão institucional. "
        "Atribua corretamente a MEC, secretarias, escola, pesquisa."
    ),
    "Tecnologia": (
        "Matéria de tecnologia. Factual, preciso, sem hype. "
        "Descreva o produto, decisão, empresa ou fenômeno de forma objetiva. "
        "Evite termos de marketing."
    ),
    "Rural": (
        "Matéria do setor rural. Foco em produção, preço, clima, gestão, política agrícola. "
        "Dados de safra, cotações e programas devem ser atribuídos a fonte."
    ),
    "Entretenimento": (
        "Matéria de entretenimento. Factual, objetivo. "
        "Evite tom fã. Evite superlativo sem base. "
        "Atribua declarações, prêmios, recordes a fonte."
    ),
    "Curiosidades": (
        "Matéria de curiosidades. Tom leve mas factual. "
        "Nada inventado. Fonte identificada para dados surpreendentes."
    ),
    "Brasil e Mundo": (
        "Matéria nacional ou internacional. Lead com o fato, contexto, impacto. "
        "Atribua posições a líderes, governos, organismos e fontes identificadas."
    ),
    "Opinião": (
        "Artigo opinativo. Voz clara, argumento fundado, sem militância disfarçada. "
        "Pode ter posição, mas deve ter base factual e honestidade intelectual."
    ),
}

# ── Templates por tipo de matéria ──────────────────────────────────────────────
TEMPLATE_POR_TIPO: dict[str, dict] = {
    "hard_news": {
        "abertura": "Lead direto com fato, agente, local, data.",
        "ordem": ["fato_principal", "contexto", "reacao_oficial", "proximo_passo"],
        "peso_contexto": "médio",
        "rigidez_atribuicao": "alta",
        "fechamento": "Factual: estágio atual ou próximos passos.",
    },
    "policia": {
        "abertura": "Lead com ação policial (prisão, apreensão, operação), local e circunstância.",
        "ordem": ["fato", "contexto_criminal", "versao_policia", "versao_defesa", "status_juridico"],
        "peso_contexto": "médio",
        "rigidez_atribuicao": "máxima",
        "fechamento": "Status do caso: em flagrante, indiciado, solto, investigado, aguarda audiência.",
    },
    "politica": {
        "abertura": "Lead com o fato político central (votação, decisão, declaração, disputa).",
        "ordem": ["fato", "contexto_politico", "posicoes_dos_lados", "reacao", "desdobramento"],
        "peso_contexto": "alto",
        "rigidez_atribuicao": "alta",
        "fechamento": "Próximos passos do processo político ou legislativo.",
    },
    "economia": {
        "abertura": "Lead com dado, decisão ou fenômeno econômico central.",
        "ordem": ["dado_central", "contexto_macro", "impacto_pratico", "projecoes_atribuidas"],
        "peso_contexto": "alto",
        "rigidez_atribuicao": "alta",
        "fechamento": "Tendência atribuída a órgão ou analista identificado.",
    },
    "judicial": {
        "abertura": "Lead com decisão, sentença ou fase processual.",
        "ordem": ["decisao", "partes", "contexto_processo", "reacao_partes", "proximo_passo_judicial"],
        "peso_contexto": "alto",
        "rigidez_atribuicao": "máxima",
        "fechamento": "Prazo, recurso ou próxima audiência.",
    },
    "governo": {
        "abertura": "Lead com ato administrativo, programa ou decisão de gestão.",
        "ordem": ["ato", "objetivo_declarado", "contexto_politico_publico", "impacto_pratico", "critica_ou_apoio"],
        "peso_contexto": "médio",
        "rigidez_atribuicao": "alta",
        "fechamento": "Prazo de implementação ou próxima etapa declarada.",
    },
    "servico": {
        "abertura": "Lead com o serviço, quem oferece, onde, quando e como acessar.",
        "ordem": ["servico", "quem_pode", "como_acessar", "prazo", "contato"],
        "peso_contexto": "baixo",
        "rigidez_atribuicao": "média",
        "fechamento": "Como e onde acessar o serviço.",
    },
    "analise": {
        "abertura": "Contexto do fenômeno antes do lead analítico.",
        "ordem": ["contexto", "tese_central", "argumentos", "contra_argumentos", "conclusao_fundada"],
        "peso_contexto": "muito_alto",
        "rigidez_atribuicao": "alta",
        "fechamento": "Perspectiva analítica fundada, sem certeza absoluta.",
    },
    "opiniao": {
        "abertura": "Apresentação clara do ponto de vista.",
        "ordem": ["tese", "argumento_principal", "contradicoes", "conclusao"],
        "peso_contexto": "alto",
        "rigidez_atribuicao": "média",
        "fechamento": "Posição clara, sem slogan.",
    },
    "bastidor": {
        "abertura": "Contexto da cena política ou institucional.",
        "ordem": ["cena", "atores", "motivacoes_declaradas", "consequencias_possiveis"],
        "peso_contexto": "alto",
        "rigidez_atribuicao": "alta",
        "fechamento": "O que esperar a seguir, segundo fontes identificadas.",
    },
    "previa_jogo": {
        "abertura": "Lead com times, competição, rodada/fase, data, horário, estádio e cidade.",
        "ordem": [
            "servico_jogo",        # times + data + hora + local + transmissão
            "contexto_competicao", # posição na tabela, fase, o que está em jogo
            "elenco_situacao",     # desfalques, retornos, dúvidas de escalação
            "momento_atual",       # últimos resultados de cada time
            "projecao_tatica",     # mudança tática esperada, se fonte confirmar
        ],
        "peso_contexto": "médio",
        "rigidez_atribuicao": "alta",
        "fechamento": "Informação de transmissão ou o que está em jogo na disputa.",
    },
    "resultado_jogo": {
        "abertura": "Lead com placar, times, competição, rodada, local e data.",
        "ordem": [
            "placar_gols",         # placar detalhado, gols, tempos
            "posicao_tabela",      # situação após o resultado
            "destaques",           # atuações individuais citadas na fonte
            "proximo_compromisso", # somente se a fonte informar
        ],
        "peso_contexto": "baixo",
        "rigidez_atribuicao": "alta",
        "fechamento": "Situação na tabela ou próximo jogo somente se a fonte informar.",
    },
}

def instrucao_canal(canal: str) -> str:
    """Retorna instrução editorial específica para o canal."""
    return INSTRUCAO_POR_CANAL.get(canal, "Escreva em formato de notícia jornalística objetiva.")

def template_para_canal(canal: str, tipo_artigo: str = "") -> dict:
    """
    Retorna o template mais adequado para o canal.
    tipo_artigo pode ser: "previa_jogo", "resultado_jogo" para Esportes.
    """
    # Esportes tem sub-tipos
    if canal == "Esportes":
        if tipo_artigo in ("previa_jogo", "sports_match_preview"):
            return TEMPLATE_POR_TIPO["previa_jogo"]
        if tipo_artigo in ("resultado_jogo", "sports_match_result"):
            return TEMPLATE_POR_TIPO["resultado_jogo"]
        return TEMPLATE_POR_TIPO["hard_news"]  # default esportes

    mapa = {
        "Polícia":       "policia",
        "Política":      "politica",
        "Economia":      "economia",
        "Cidades":       "governo",
        "Estado RJ":     "hard_news",
        "Brasil e Mundo":"hard_news",
        "Saúde":         "servico",
        "Educação":      "servico",
        "Tecnologia":    "hard_news",
        "Rural":         "economia",
        "Entretenimento":"hard_news",
        "Curiosidades":  "hard_news",
        "Opinião":       "opiniao",
        "Trabalho":      "economia",
        "Justiça":       "judicial",
    }
    chave = mapa.get(canal, "hard_news")
    return TEMPLATE_POR_TIPO.get(chave, TEMPLATE_POR_TIPO["hard_news"])

# ── Termos proibidos para detecção automática ──────────────────────────────────
TERMOS_IA_PROIBIDOS: list[str] = [
    "reforça", "reacende", "acende o alerta", "liga o alerta", "serve de alerta",
    "chama atenção para", "ressalta a importância", "destaca a importância",
    "evidencia", "evidenciando", "deixa evidente", "demonstra a efetividade",
    "demonstra a importância", "demonstra o compromisso", "reafirma o compromisso",
    "reforça o compromisso", "sinaliza que", "mostra a importância",
    "ilustra", "escancara", "traz à tona", "lança luz sobre", "amplia o debate",
    "intensifica o debate", "abre debate", "ganha contornos", "ganha relevância",
    "ganha destaque", "se insere no contexto", "em meio ao cenário",
    "diante desse cenário", "neste cenário", "nesse cenário", "nesse contexto",
    "no bojo de", "trata-se de", "cabe destacar", "cabe ressaltar", "vale destacar",
    "vale lembrar", "é importante lembrar", "importante frisar",
    "a ação demonstra", "a medida demonstra", "o episódio demonstra",
    "o caso demonstra", "o caso reforça", "o episódio reforça", "o caso evidencia",
    "o caso reafirma", "a ocorrência reforça", "expõe a responsabilidade",
    "fundamental para a manutenção da ordem pública", "papel fundamental",
    "atuação fundamental", "compromisso com a segurança",
    "ação exitosa", "operação exitosa", "ação bem-sucedida", "operação bem-sucedida",
    "avanço significativo", "avanços importantes", "novo capítulo",
    "ganhou as redes", "não passou despercebido",
    "em conclusão", "por conclusão", "conclui-se que", "fica evidente que",
    "resta claro que", "fica o alerta", "fica a reflexão", "a lição que fica",
    "o recado está dado", "o caso serve de exemplo", "fica demonstrado",
    "consolida cenário", "consolida tendência", "pavimenta caminho",
    "aponta caminho", "desenha cenário", "fortalece agenda", "embaralha o jogo",
    "redesenha o tabuleiro", "especialistas apontam", "analistas avaliam",
    "setores da sociedade", "sociedade como um todo", "tranquilidade da população",
    "robusto", "robusta", "emblemático", "emblemática",
    "importante passo", "passo importante", "marco histórico",
    "iniciativa que busca", "trabalho incansável", "ação permanente",
    "resposta rápida e eficaz", "forte atuação", "pronta resposta",
    "bastidores quentes", "tensão no ar", "esquenta disputa", "movimenta cenário",
    "conforme fontes", "conforme relatos",
]

def detectar_termos_ia(texto: str) -> list[str]:
    """Retorna lista de termos de IA encontrados no texto."""
    texto_lower = texto.lower()
    encontrados = []
    for termo in TERMOS_IA_PROIBIDOS:
        if termo.lower() in texto_lower:
            encontrados.append(termo)
    return encontrados

# ── Pacotes de regras para score de risco editorial ───────────────────────────
PADROES_RISCO_ALTO: list[str] = [
    r"é culpado", r"cometeu o crime", r"confessou", r"admitiu",
    r"certamente", r"comprovadamente", r"definitivamente acusado",
    r"sabidamente corrupto", r"notoriamente", r"foi condenado",
]
PADROES_RISCO_MEDIO: list[str] = [
    r"suspeito de ter", r"teria cometido", r"acusado de",
    r"investigado por", r"envolvido em esquema",
]
AUSENCIA_ATRIBUICAO: list[str] = [
    r"de acordo com fontes\b(?! (?:policiais|do|da|do MP|do tribunal))",
    r"segundo informações\b(?! (?:do|da|das|dos|oficiais|confirmadas))",
    r"conforme apurado\b",
]
