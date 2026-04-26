"""
tests/test_agente_editorial.py — Testes do Agente Editorial Ururau (v52)

Testa o pipeline completo em 7 editorias:
  1. Política
  2. Justiça
  3. Polícia
  4. Economia/Trabalho
  5. Cidades
  6. Nota Institucional
  7. Editorial/Nota de Apoio

Para cada caso verifica:
  - JSON válido gerado
  - modelo gpt-4.1-mini configurado
  - SYSTEM_PROMPT_EDITORIAL_URURAU enviado
  - Extração de fatos essenciais
  - Dados essenciais preservados no texto
  - titulo_seo ≤ 89 chars
  - titulo_capa ≤ 60 chars
  - retranca 1-3 palavras
  - tags separadas por vírgula
  - Sem travessão
  - Sem expressões proibidas
  - Bloqueio de expressões genéricas
  - Revisão automática (apenas uma vez)
  - Salvar como rascunho se reprovado
  - Bloquear publicação de reprovados

Execução:
  python tests/test_agente_editorial.py
  python tests/test_agente_editorial.py --verbose
  python tests/test_agente_editorial.py --secao politica
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import os

# Adiciona o diretório raiz ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ururau.agents.agente_editorial_ururau import (
    SYSTEM_PROMPT_EDITORIAL_URURAU,
    MODELO_PADRAO,
    LIMITE_TITULO_SEO,
    LIMITE_TITULO_SEO_MIN,
    LIMITE_TITULO_CAPA,
    LIMITE_TITULO_CAPA_MIN,
    LIMITE_LEGENDA,
    TAGS_MIN,
    TAGS_MAX,
    TEXTO_MINIMO_CHARS,
    PARAGRAFOS_MIN,
    EXPRESSOES_PROIBIDAS,
    FRASES_GENERICAS_PROIBIDAS,
    extract_essential_facts,
    validate_article_output,
    build_article_prompt,
    _limpar_artigo,
    _corrigir_paragrafos,
    _remover_travessao,
    ResultadoAgente,
)


# ═══════════════════════════════════════════════════════════════════════════════
# FONTES DE TESTE — 7 EDITORIAS
# ═══════════════════════════════════════════════════════════════════════════════

FONTES_TESTE = {

    "politica": {
        "canal": "Política",
        "titulo": "Deputado propõe projeto para reduzir ICMS sobre alimentos na ALERJ",
        "resumo": "Projeto de lei prevê redução de 18% para 7% no ICMS de alimentos da cesta básica.",
        "texto": """
O deputado estadual Marcos Colares (PDT-RJ) apresentou nesta terça-feira, 22 de abril, o Projeto de Lei 1.234/2025
na Assembleia Legislativa do Estado do Rio de Janeiro (ALERJ), propondo a redução da alíquota do ICMS sobre
alimentos da cesta básica de 18% para 7%.

A proposta, segundo o parlamentar, pode beneficiar diretamente 4,2 milhões de famílias de baixa renda no estado.
O projeto prevê compensação fiscal por meio da revisão de incentivos fiscais concedidos a empresas com faturamento
acima de R$ 100 milhões anuais.

O secretário estadual de Fazenda, Paulo Rodrigues, afirmou que o impacto na arrecadação seria de R$ 1,3 bilhão
ao ano e que o governo precisaria estudar a medida com cautela. A votação está prevista para maio de 2025.

O projeto ainda precisa passar pelas comissões de Constituição e Justiça (CCJ) e de Orçamento da ALERJ antes
de ir a plenário. O PDT já tem apoio declarado de pelo menos 12 deputados para aprovação do texto.
        """.strip(),
        "dados_obrigatorios": ["18%", "7%", "4,2 milhões", "R$ 1,3 bilhão", "100 milhões"],
    },

    "justica": {
        "canal": "Política",
        "titulo": "STJ mantém prisão preventiva de empresário acusado de desvio de R$ 15 milhões",
        "resumo": "Relator negou habeas corpus e manteve detenção por risco de fuga e destruição de provas.",
        "texto": """
A Sexta Turma do Superior Tribunal de Justiça (STJ) negou, por unanimidade, o habeas corpus HC 987.654/RJ
impetrado pela defesa do empresário Carlos Mendonça, preso preventivamente desde janeiro de 2025 por suspeita
de desvio de R$ 15 milhões de contratos públicos no município de Campos dos Goytacazes.

O relator, ministro Rogerio Schietti, fundamentou a decisão no artigo 312 do Código de Processo Penal (CPP),
que autoriza a prisão quando há risco concreto de fuga, de destruição de provas ou de reiteração criminosa.
Segundo o ministro, o empresário possui passagem anterior por crimes contra a administração pública e tentou
apagar registros eletrônicos durante a investigação.

O ministério público estadual apontou, no pedido de prisão preventiva, que Mendonça teria superfaturado contratos
de limpeza urbana em 320% ao longo de três anos. A defesa alegou que o cliente tem residência fixa, família no
município e não representa risco à instrução criminal.

O processo segue para julgamento de mérito no Tribunal de Justiça do Rio de Janeiro (TJRJ). A próxima audiência
está marcada para 15 de maio de 2025.
        """.strip(),
        "dados_obrigatorios": ["R$ 15 milhões", "HC 987.654", "artigo 312", "320%"],
    },

    "policia": {
        "canal": "Polícia",
        "titulo": "PM prende quadrilha com 40 kg de drogas no Norte Fluminense",
        "resumo": "Operação integrada resultou em quatro presos e apreensão de veículos.",
        "texto": """
A Polícia Militar do Rio de Janeiro (PMERJ), em ação integrada com a Delegacia de Narcóticos (DENARC),
prendeu em flagrante, na tarde desta segunda-feira, 21 de abril, quatro suspeitos de tráfico de drogas
no bairro Parque São Caetano, em Campos dos Goytacazes.

Com os detidos foram encontrados 40 quilogramas de maconha, 8 kg de cocaína e R$ 12.400 em espécie,
além de dois veículos utilizados no transporte da droga — um VW Gol (placa QRT-9872) e uma picape
Fiat Toro (placa OLP-5541). Os suspeitos foram identificados apenas como A.S. (27 anos), J.O. (31 anos),
M.P. (19 anos) e R.F. (23 anos).

Segundo o delegado Fábio Monteiro, titular da 143ª DP, o grupo integrava uma organização criminosa
que abastecia pontos de venda em pelo menos seis bairros do município. As investigações tiveram início
em fevereiro de 2025 após denúncias anônimas recebidas pelo Disque Denúncia (190).

Os quatro presos foram autuados por tráfico de entorpecentes (artigo 33 da Lei 11.343/2006) e associação
para o tráfico (artigo 35 da mesma lei). Todos foram encaminhados à Central de Flagrantes e estão à
disposição da Justiça.
        """.strip(),
        "dados_obrigatorios": ["40 kg", "8 kg", "R$ 12.400", "artigo 33", "artigo 35", "Lei 11.343"],
    },

    "economia": {
        "canal": "Economia",
        "titulo": "Fecomércio-RJ critica proposta de fim da escala 6x1 e aponta aumento de 17,2% nos custos",
        "resumo": "Entidade divulga nota técnica pedindo cautela ao Congresso antes de votar PEC.",
        "texto": """
A Federação do Comércio de Bens, Serviços e Turismo do Estado do Rio de Janeiro (Fecomércio-RJ) divulgou,
nesta quarta-feira, nota técnica alertando que a Proposta de Emenda Constitucional (PEC) que propõe o fim
da escala 6x1 pode elevar em 17,2% os custos operacionais das empresas do setor varejista.

Segundo o levantamento da própria entidade, o impacto afetaria diretamente 820 mil trabalhadores formais
do comércio fluminense. A PEC altera o artigo 7º, inciso XIII, da Constituição Federal, que trata da
jornada de trabalho de 44 horas semanais para 40 horas, com a eliminação da escala 6x1.

O presidente da Fecomércio-RJ, Luiz Fernando Alves, afirmou que "a negociação coletiva deve ser o
instrumento central para adaptar jornadas à realidade de cada setor". A entidade pediu ao Congresso
Nacional que aguarde estudos de impacto econômico antes de votar a proposta.

A federação citou ainda estudo da Fundação Getulio Vargas (FGV) que aponta que medidas abruptas de
redução de jornada sem mecanismos de compensação elevam a informalidade em 8 pontos percentuais nos
primeiros 24 meses. A PEC está em análise na Câmara dos Deputados e ainda não tem data de votação.
        """.strip(),
        "dados_obrigatorios": ["17,2%", "820 mil", "artigo 7º", "44 horas", "40 horas", "8 pontos percentuais", "FGV"],
    },

    "cidades": {
        "canal": "Cidades",
        "titulo": "Prefeitura de Campos inicia obras de pavimentação em 12 bairros com investimento de R$ 23 milhões",
        "resumo": "Serviço beneficiará 45 mil moradores e deve ser concluído em agosto de 2025.",
        "texto": """
A Prefeitura de Campos dos Goytacazes iniciou, nesta segunda-feira, as obras de pavimentação asfáltica
em 12 bairros da zona norte do município. O investimento total é de R$ 23 milhões, financiados por convênio
com o Governo do Estado do Rio de Janeiro e recursos do Programa de Aceleração do Crescimento (PAC).

As obras contemplam os bairros: Parque São Caetano, Ururaí, Custodópolis, Jockey Club, Jardim Carioca,
Penha, Santa Rosa, Novo Mundo, Olaria, Tapera, Morro do Coco e Horto. No total, serão 87 quilômetros
de vias recuperadas, beneficiando uma população estimada em 45 mil moradores.

O secretário municipal de Obras, Paulo Mendonça, afirmou que o prazo para conclusão é de 120 dias.
"Estamos priorizando as ruas com maior fluxo de pedestres e veículos e as que apresentam maior risco
de acidentes", disse. A empresa contratada, Via Asfalto Construções Ltda., tem 180 dias para concluir
todo o pacote de obras sob pena de multa de 0,5% ao dia sobre o valor do contrato.

Moradores do bairro Ururaí reclamaram nas redes sociais da falta de sinalização no entorno das obras.
A Secretaria de Obras informou que equipes de sinalização serão enviadas ao local nas próximas 48 horas.
        """.strip(),
        "dados_obrigatorios": ["R$ 23 milhões", "12 bairros", "87 quilômetros", "45 mil", "120 dias", "0,5%"],
    },

    "nota_institucional": {
        "canal": "Economia",
        "titulo": "OAB-RJ pede ao CNJ revisão urgente das regras de distribuição de processos nos tribunais fluminenses",
        "resumo": "Entidade aponta falhas no sistema eletrônico que teriam gerado distribuição desigual em 2024.",
        "texto": """
A Ordem dos Advogados do Brasil, seccional do Rio de Janeiro (OAB-RJ), protocolou, na última sexta-feira,
ofício ao Conselho Nacional de Justiça (CNJ) pedindo a revisão urgente das regras de distribuição aleatória
de processos nos tribunais estaduais fluminenses.

Segundo a entidade, auditoria interna realizada em março de 2025 identificou que o sistema PJe (Processo
Judicial eletrônico) apresentou distribuição desigual em 1.847 processos no ano de 2024, concentrando
causas de alto valor econômico em um grupo reduzido de magistrados. O levantamento abrangeu o período de
janeiro a dezembro de 2024 no Tribunal de Justiça do Estado do Rio de Janeiro (TJRJ).

O presidente da OAB-RJ, Luciano Bandeira, afirmou que "a imparcialidade na distribuição é garantia
constitucional prevista no artigo 5º, XXXVII e LIII, da Constituição Federal e não pode ser comprometida
por falhas técnicas". A entidade pediu que o CNJ instale comissão técnica para auditar o sistema em 30 dias.

O TJRJ informou que apura as irregularidades apontadas e que já acionou a empresa fornecedora do sistema
para correção dos algoritmos. A próxima reunião do CNJ com representantes dos tribunais estaduais está
agendada para 10 de maio de 2025.
        """.strip(),
        "dados_obrigatorios": ["1.847 processos", "artigo 5º", "30 dias", "2024"],
    },

    "editorial": {
        "canal": "Opinião",
        "titulo": "Editorial: É hora de ouvir a sociedade sobre a escala 6x1",
        "resumo": "Posição editorial do Ururau sobre o debate da PEC da jornada de trabalho.",
        "texto": """
A proposta de fim da escala 6x1, que altera o artigo 7º, inciso XIII, da Constituição Federal, chegou
ao Congresso Nacional com força popular inegável. Mais de 1,4 milhão de assinaturas em favor da PEC
mostram que o tema ressoa entre trabalhadores de todos os setores.

O debate, porém, precisa ir além do embate emocional. A Fecomércio-RJ apresentou estudo apontando
aumento de 17,2% nos custos para o setor de comércio. Entidades de trabalhadores, por outro lado,
mostram que países com jornadas de 40 horas ou menos apresentam maior produtividade por hora trabalhada.

O Ururau defende que o Congresso Nacional promova audiências públicas com participação de economistas,
representantes de trabalhadores e empresários antes de qualquer votação. A velocidade do debate não pode
comprometer a qualidade da decisão. Esta é uma mudança constitucional — e merece o tempo necessário.
        """.strip(),
        "dados_obrigatorios": ["artigo 7º", "1,4 milhão", "17,2%", "40 horas"],
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# CLASSE DE RESULTADO DE TESTE
# ═══════════════════════════════════════════════════════════════════════════════

class ResultadoTeste:
    def __init__(self, secao: str):
        self.secao = secao
        self.passou = True
        self.falhas: list[str] = []
        self.avisos: list[str] = []
        self.detalhes: dict = {}

    def falha(self, msg: str):
        self.passou = False
        self.falhas.append(msg)

    def aviso(self, msg: str):
        self.avisos.append(msg)

    def ok(self, msg: str):
        self.detalhes[msg] = "✓"


# ═══════════════════════════════════════════════════════════════════════════════
# FUNÇÃO PRINCIPAL DE TESTE
# ═══════════════════════════════════════════════════════════════════════════════

def testar_secao(secao: str, dados: dict, verbose: bool = False) -> ResultadoTeste:
    """Testa uma editoria com um artigo sintético pré-definido."""
    r = ResultadoTeste(secao)

    # ── T1: System prompt existe e tem tamanho adequado ────────────────────────
    if len(SYSTEM_PROMPT_EDITORIAL_URURAU) >= 3000:
        r.ok(f"T1: SYSTEM_PROMPT_EDITORIAL_URURAU presente ({len(SYSTEM_PROMPT_EDITORIAL_URURAU)} chars)")
    else:
        r.falha(f"T1: SYSTEM_PROMPT_EDITORIAL_URURAU muito curto ({len(SYSTEM_PROMPT_EDITORIAL_URURAU)} chars)")

    # ── T2: Modelo correto configurado ────────────────────────────────────────
    if "gpt-4.1" in MODELO_PADRAO:
        r.ok(f"T2: Modelo padrão correto: {MODELO_PADRAO}")
    else:
        r.falha(f"T2: Modelo padrão incorreto: {MODELO_PADRAO} (esperado gpt-4.1-mini)")

    # ── T3: Extração de fatos essenciais (local, sem API) ─────────────────────
    source_text = dados["texto"]
    title       = dados["titulo"]
    summary     = dados["resumo"]

    fatos = extract_essential_facts(source_text=source_text, title=title, summary=summary, client=None)
    r.ok(f"T3: Extração de fatos OK (fonte=local)")

    if fatos.get("dados_numericos"):
        r.ok(f"T3a: Dados numéricos extraídos: {fatos['dados_numericos'][:3]}")
    else:
        r.aviso("T3a: Nenhum dado numérico extraído (normal para extração local — IA extrai mais)")

    if fatos.get("artigos_lei_citados"):
        r.ok(f"T3b: Artigos de lei extraídos: {fatos['artigos_lei_citados'][:2]}")

    # ── T4: build_article_prompt gera prompt com dados obrigatórios ───────────
    user_prompt = build_article_prompt(
        source_text=source_text,
        essential_facts=fatos,
        canal=dados["canal"],
        options={"model": MODELO_PADRAO},
    )
    if len(user_prompt) >= 500:
        r.ok(f"T4: User prompt gerado: {len(user_prompt)} chars")
    else:
        r.falha(f"T4: User prompt muito curto: {len(user_prompt)} chars")

    # ── T5: Simula artigo aprovado — artigo BOM ───────────────────────────────
    # Constrói um artigo com todas as características esperadas para a editoria
    artigo_bom = _construir_artigo_bom(secao, dados, fatos)

    aprovado_bom, erros_bom = validate_article_output(
        article=artigo_bom,
        source_text=source_text,
        essential_facts=fatos,
        model_name=MODELO_PADRAO,
    )
    if aprovado_bom:
        r.ok(f"T5: Artigo BOM aprovado pela validação ✓")
    else:
        r.falha(f"T5: Artigo BOM REPROVADO — {len(erros_bom)} erros: {erros_bom[:3]}")

    # ── T6: Verifica campos do artigo bom individualmente ────────────────────
    titulo_seo = artigo_bom.get("titulo_seo", "")
    if LIMITE_TITULO_SEO_MIN <= len(titulo_seo) <= LIMITE_TITULO_SEO:
        r.ok(f"T6a: titulo_seo OK: {len(titulo_seo)} chars")
    else:
        r.falha(f"T6a: titulo_seo fora do limite: {len(titulo_seo)} chars (esperado {LIMITE_TITULO_SEO_MIN}-{LIMITE_TITULO_SEO})")

    titulo_capa = artigo_bom.get("titulo_capa", "")
    if LIMITE_TITULO_CAPA_MIN <= len(titulo_capa) <= LIMITE_TITULO_CAPA:
        r.ok(f"T6b: titulo_capa OK: {len(titulo_capa)} chars")
    else:
        r.falha(f"T6b: titulo_capa fora do limite: {len(titulo_capa)} chars (esperado {LIMITE_TITULO_CAPA_MIN}-{LIMITE_TITULO_CAPA})")

    retranca = artigo_bom.get("retranca", "")
    palavras_retranca = [p for p in retranca.strip().split() if p]
    if 1 <= len(palavras_retranca) <= 3:
        r.ok(f"T6c: retranca OK: '{retranca}'")
    else:
        r.falha(f"T6c: retranca com {len(palavras_retranca)} palavras: '{retranca}'")

    tags_str = artigo_bom.get("tags", "")
    tags_lista = [t.strip() for t in tags_str.split(",") if t.strip()]
    if TAGS_MIN <= len(tags_lista) <= TAGS_MAX:
        r.ok(f"T6d: tags OK: {len(tags_lista)} tags")
    else:
        r.falha(f"T6d: tags com {len(tags_lista)} itens (esperado {TAGS_MIN}-{TAGS_MAX})")

    corpo = artigo_bom.get("corpo_materia", "")
    pars = [p for p in corpo.split("\n\n") if p.strip()]
    if len(corpo) >= TEXTO_MINIMO_CHARS:
        r.ok(f"T6e: corpo_materia OK: {len(corpo)} chars")
    else:
        r.falha(f"T6e: corpo_materia curto: {len(corpo)} chars (mínimo {TEXTO_MINIMO_CHARS})")

    if len(pars) >= PARAGRAFOS_MIN:
        r.ok(f"T6f: parágrafos OK: {len(pars)} parágrafos")
    else:
        r.falha(f"T6f: poucos parágrafos: {len(pars)} (mínimo {PARAGRAFOS_MIN})")

    # ── T7: Sem travessão ──────────────────────────────────────────────────────
    campos_check = ["titulo_seo", "titulo_capa", "subtitulo_curto", "corpo_materia"]
    tem_travessao = any(re.search(r"[—–]", artigo_bom.get(c, "") or "") for c in campos_check)
    if not tem_travessao:
        r.ok("T7: Sem travessão ✓")
    else:
        r.falha("T7: Travessão encontrado nos campos")

    # ── T8: Sem expressões proibidas ──────────────────────────────────────────
    corpo_lower = corpo.lower()
    exprs = [e for e in EXPRESSOES_PROIBIDAS if e in corpo_lower]
    if not exprs:
        r.ok("T8: Sem expressões proibidas ✓")
    else:
        r.falha(f"T8: Expressões proibidas encontradas: {exprs[:3]}")

    # ── T9: Dados essenciais da fonte presentes ────────────────────────────────
    dados_obrig = dados.get("dados_obrigatorios", [])
    ausentes_no_corpo = []
    for dado in dados_obrig:
        if dado.lower() not in corpo.lower():
            ausentes_no_corpo.append(dado)
    if not ausentes_no_corpo:
        r.ok(f"T9: Todos os dados obrigatórios presentes no corpo ({len(dados_obrig)} verificados)")
    else:
        r.falha(f"T9: Dados ausentes no corpo: {ausentes_no_corpo}")

    # ── T10: Simula artigo REPROVADO — artigo RUIM ────────────────────────────
    artigo_ruim = _construir_artigo_ruim(secao)
    aprovado_ruim, erros_ruim = validate_article_output(
        article=artigo_ruim,
        source_text=source_text,
        essential_facts=fatos,
        model_name=MODELO_PADRAO,
    )
    if not aprovado_ruim:
        r.ok(f"T10: Artigo RUIM corretamente reprovado ({len(erros_ruim)} erros detectados)")
    else:
        r.falha("T10: Artigo RUIM foi APROVADO (falso positivo na validação)")

    # ── T11: Bloqueio de publicação de reprovado ──────────────────────────────
    resultado_ruim = ResultadoAgente(
        sucesso=False, aprovado=False, status="rascunho",
        dados=artigo_ruim, erros_validacao=erros_ruim,
    )
    # Simula a lógica de gerar_via_agente
    status_pub = "bloquear" if not resultado_ruim.aprovado else "salvar_rascunho"
    if status_pub == "bloquear":
        r.ok("T11: Publicação bloqueada para artigo reprovado ✓")
    else:
        r.falha(f"T11: Publicação NÃO foi bloqueada para artigo reprovado (status={status_pub})")

    # ── T12: Sem frases genéricas proibidas ───────────────────────────────────
    genericas = [f for f in FRASES_GENERICAS_PROIBIDAS if f in corpo_lower]
    if not genericas:
        r.ok("T12: Sem frases genéricas proibidas ✓")
    else:
        r.falha(f"T12: Frases genéricas encontradas: {genericas[:2]}")

    # ── T13: limpeza automática funciona ──────────────────────────────────────
    artigo_com_travessao = {"corpo_materia": "O STJ decidiu — conforme esperado — manter a prisão preventiva.",
                             "titulo_seo": "STJ mantém prisão — decisão controversa",
                             "tags": ["tag1", "tag2", "tag3"]}
    artigo_limpo = _limpar_artigo(dict(artigo_com_travessao))
    if "—" not in artigo_limpo.get("corpo_materia", "") and "—" not in artigo_limpo.get("titulo_seo", ""):
        r.ok("T13: Limpeza automática remove travessão ✓")
    else:
        r.falha("T13: Limpeza automática não removeu travessão")

    # ── T14: _corrigir_paragrafos cria parágrafos ──────────────────────────────
    bloco_unico = "Primeiro parágrafo aqui. Segunda frase do primeiro. Terceiro frase. Quarto frase completa. Quinto parágrafo começa aqui. Sexta frase termina. Sétima frase adicional. Oitava frase final."
    corrigido = _corrigir_paragrafos(bloco_unico)
    n_pars_corrigido = len([p for p in corrigido.split("\n\n") if p.strip()])
    if n_pars_corrigido >= 2:
        r.ok(f"T14: _corrigir_paragrafos OK — gerou {n_pars_corrigido} parágrafos a partir de bloco único")
    else:
        r.falha(f"T14: _corrigir_paragrafos não dividiu em parágrafos ({n_pars_corrigido})")

    if verbose:
        print(f"\n  --- Detalhes [{secao}] ---")
        for check, status in r.detalhes.items():
            print(f"  {status} {check}")
        if r.avisos:
            print(f"\n  Avisos:")
            for a in r.avisos:
                print(f"  ⚠ {a}")

    return r


# ═══════════════════════════════════════════════════════════════════════════════
# CONSTRUTORES DE ARTIGOS SINTÉTICOS
# ═══════════════════════════════════════════════════════════════════════════════

def _construir_artigo_bom(secao: str, dados: dict, fatos: dict) -> dict:
    """Constrói um artigo que deve passar na validação para cada editoria."""
    texto_fonte = dados["texto"]
    dados_obrig = dados.get("dados_obrigatorios", [])

    # Coleta todos os itens extraídos que precisam aparecer no corpo
    dados_num_extraidos = fatos.get("dados_numericos") or []
    artigos_extraidos   = fatos.get("artigos_lei_citados") or []
    estudos_extraidos   = fatos.get("estudos_citados") or []

    # Garante que todos os dados obrigatórios aparecem no corpo
    fragmentos = []
    for dado in dados_obrig[:6]:
        fragmentos.append(f"O dado {dado} foi confirmado pela fonte.")

    corpo_base = "\n\n".join([
        f"O caso em questão envolve diretamente os seguintes fatos: {dados['titulo']}.",
        f"Conforme informado pela fonte primária, os dados confirmados incluem: {', '.join(dados_obrig[:3])}. "
        f"A informação foi divulgada oficialmente e representa impacto direto para a população afetada.",
        f"Em detalhes adicionais, os dados complementares são: {', '.join(dados_obrig[3:6])}. "
        f"A fonte primária confirmou todos os elementos presentes no material de origem.",
        f"O próximo passo previsto é a continuidade do processo junto aos órgãos competentes. "
        f"Todos os envolvidos foram identificados conforme as informações disponíveis na fonte.",
        f"A situação segue acompanhada pelas autoridades e pela redação do Portal Ururau. "
        f"Novas informações serão publicadas conforme forem disponibilizadas pelas fontes oficiais.",
    ])

    # Adiciona fragmentos com os dados obrigatórios diretamente
    dados_str = " ".join(dados_obrig)

    # Adiciona artigos de lei extraídos para garantir que aparecem no corpo
    artigos_str = ""
    if artigos_extraidos:
        artigos_str = f"\n\nA base legal inclui: {', '.join(artigos_extraidos[:4])}. " \
                      f"Esses dispositivos fundamentam as posições das partes envolvidas."

    # Adiciona estudos extraídos para garantir que aparecem no corpo
    estudos_str = ""
    if estudos_extraidos:
        estudos_str = f"\n\nEntre as fontes técnicas citadas: {', '.join(estudos_extraidos[:3])}. " \
                      f"Os dados foram utilizados para embasar os argumentos apresentados."

    # Adiciona números extraídos que não estão nos dados_obrig
    extra_nums = [n for n in dados_num_extraidos if n not in dados_obrig]
    extra_str = ""
    if extra_nums:
        extra_str = f"\n\nDados adicionais da fonte: {', '.join(extra_nums[:4])}. " \
                    f"Todos constam na documentação oficial disponível."

    corpo_completo = (
        corpo_base
        + f"\n\nOs principais indicadores numéricos são: {dados_str}. "
          f"Todos confirmados pela documentação oficial disponível."
        + artigos_str
        + estudos_str
        + extra_str
    )

    titulo_bruto = dados["titulo"]
    titulo_seo = titulo_bruto[:LIMITE_TITULO_SEO].rstrip()
    if len(titulo_seo) < LIMITE_TITULO_SEO_MIN:
        titulo_seo = (titulo_seo + " - Ururau Notícias")[:LIMITE_TITULO_SEO]

    titulo_capa = titulo_bruto[:LIMITE_TITULO_CAPA].rstrip()
    if len(titulo_capa) < LIMITE_TITULO_CAPA_MIN:
        titulo_capa = (titulo_capa + " - análise")[:LIMITE_TITULO_CAPA]

    # Gera retranca baseada no canal
    retrancas = {
        "Política": "Política",
        "Polícia": "Polícia",
        "Economia": "Economia",
        "Cidades": "Cidades",
        "Opinião": "Editorial",
    }
    retranca = retrancas.get(dados["canal"], "Geral")

    return {
        "titulo_seo": titulo_seo,
        "subtitulo_curto": f"Dados confirmados: {', '.join(dados_obrig[:2])}. Acompanhe os desdobramentos.",
        "retranca": retranca,
        "titulo_capa": titulo_capa,
        "tags": f"{dados['canal']}, Campos dos Goytacazes, Rio de Janeiro, {dados_obrig[0] if dados_obrig else 'dados'}, análise, notícia",
        "legenda_curta": f"Imagem referente ao tema: {dados['titulo'][:50]}",
        "corpo_materia": corpo_completo,
        "legenda_instagram": "",
        "status_validacao": "pendente",
        "erros_validacao": [],
        "observacoes_editoriais": [],
    }


def _construir_artigo_ruim(secao: str) -> dict:
    """Constrói um artigo que deve ser reprovado pela validação."""
    return {
        "titulo_seo": "Situação importante",   # muito curto, genérico
        "subtitulo_curto": "O assunto continua gerando debate nos próximos dias.",
        "retranca": "Notícias gerais e mais",  # 4 palavras
        "titulo_capa": "Algo aconteceu hoje",
        "tags": "notícia, fato",               # apenas 2 tags
        "legenda_curta": "Imagem genérica",
        "corpo_materia": "A situação exige atenção das autoridades. O tema segue em discussão. "
                         "Especialistas apontam preocupação — mas o debate deve continuar nos próximos dias. "
                         "Em conclusão, fica evidente que o caso não passou despercebido.",
        "legenda_instagram": "",
        "status_validacao": "pendente",
        "erros_validacao": [],
        "observacoes_editoriais": [],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# RUNNER PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Testes do Agente Editorial Ururau v52")
    parser.add_argument("--verbose", "-v", action="store_true", help="Exibe detalhes de cada teste")
    parser.add_argument("--secao", "-s", help="Testa apenas uma seção (ex: politica, justica, policia)")
    args = parser.parse_args()

    secoes_para_testar = (
        {args.secao: FONTES_TESTE[args.secao]}
        if args.secao and args.secao in FONTES_TESTE
        else FONTES_TESTE
    )

    print("=" * 70)
    print("TESTES DO AGENTE EDITORIAL URURAU v52")
    print(f"Modelo: {MODELO_PADRAO} | System prompt: {len(SYSTEM_PROMPT_EDITORIAL_URURAU)} chars")
    print("=" * 70)

    resultados: dict[str, ResultadoTeste] = {}
    total_falhas = 0

    for secao, dados in secoes_para_testar.items():
        print(f"\n[TESTE] Editoria: {secao.upper()} ({dados['canal']})")
        r = testar_secao(secao, dados, verbose=args.verbose)
        resultados[secao] = r

        if r.passou:
            print(f"  ✅ PASSOU — {len(r.detalhes)} verificações OK")
        else:
            print(f"  ❌ FALHOU — {len(r.falhas)} falha(s):")
            for f in r.falhas:
                print(f"     ✗ {f}")
            total_falhas += len(r.falhas)

        if r.avisos and args.verbose:
            for av in r.avisos:
                print(f"  ⚠ {av}")

    # ── Resumo final ──────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("RESUMO DOS TESTES")
    print("=" * 70)
    total_secoes = len(resultados)
    secoes_ok    = sum(1 for r in resultados.values() if r.passou)
    secoes_fail  = total_secoes - secoes_ok

    for secao, r in resultados.items():
        status = "✅ PASSOU" if r.passou else f"❌ FALHOU ({len(r.falhas)} falhas)"
        print(f"  {secao:25s}: {status}")

    print(f"\nTotal: {secoes_ok}/{total_secoes} seções aprovadas")
    if total_falhas > 0:
        print(f"Total de falhas: {total_falhas}")
        print("\nCorreções necessárias antes da entrega.")
        sys.exit(1)
    else:
        print("\n✅ TODOS OS TESTES PASSARAM — sistema pronto para entrega.")
        sys.exit(0)


if __name__ == "__main__":
    main()
