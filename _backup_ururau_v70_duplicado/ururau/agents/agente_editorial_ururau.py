"""
agents/agente_editorial_ururau.py — Agente Editorial do Ururau (v52)

Módulo definitivo e autônomo para geração de matérias jornalísticas.
Funciona como o sistema editorial central do projeto: contém a identidade
editorial completa do Portal Ururau e é enviado como system prompt em
TODA chamada à API da OpenAI.

Exporta:
  SYSTEM_PROMPT_EDITORIAL_URURAU  — system prompt completo (enviado a cada chamada)
  build_article_prompt()          — monta user prompt com fonte + dados extraídos
  extract_essential_facts()       — extrai dados essenciais da fonte (via IA)
  validate_article_output()       — valida JSON gerado (estrutura + substância)
  revise_article_if_needed()      — revisão automática dirigida (apenas uma vez)
  generate_article()              — pipeline completo: extrai → gera → valida → revisa

Modelo obrigatório: gpt-4.1-mini (via OPENAI_MODEL ou padrão)
NUNCA gera artigo sem enviar SYSTEM_PROMPT_EDITORIAL_URURAU como system message.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from openai import OpenAI

TZ_BR = ZoneInfo("America/Sao_Paulo")

# ═══════════════════════════════════════════════════════════════════════════════
# SEÇÃO 1: CONSTANTES EDITORIAIS
# ═══════════════════════════════════════════════════════════════════════════════

MODELO_PADRAO          = "gpt-4.1-mini"
LIMITE_TITULO_SEO      = 89
LIMITE_TITULO_CAPA     = 60
LIMITE_TITULO_SEO_MIN  = 40
LIMITE_TITULO_CAPA_MIN = 20
LIMITE_SUBTITULO       = 200
LIMITE_LEGENDA         = 100
TAGS_MIN               = 5
TAGS_MAX               = 12
TEXTO_MINIMO_CHARS     = 500      # padrão para fontes longas
TEXTO_MINIMO_FONTE_CURTA = 250    # para fontes < 800 chars
PARAGRAFOS_MIN         = 4        # padrão para fontes longas
PARAGRAFOS_MIN_CURTA   = 2        # mínimo para fontes muito curtas
FONTE_CURTA_LIMITE     = 800      # chars — abaixo disso, aplica regras de fonte curta

CANAIS_VALIDOS = [
    "Polícia", "Cidades", "Estado RJ", "Opinião", "Economia",
    "Política", "Entretenimento", "Educação", "Esportes",
    "Saúde", "Tecnologia", "Curiosidades", "Rural", "Brasil e Mundo",
]

# Expressões proibidas → substituto (None = obrigatório reescrever)
EXPRESSOES_PROIBIDAS: dict[str, str | None] = {
    "reacende":                     "abriu discussão sobre",
    "reacende debate":              "entrou na pauta",
    "levanta debate":               "gerou discussão",
    "levanta preocupação":          "preocupa",
    "acende o alerta":              "mobiliza atenção",
    "liga o alerta":                "preocupa",
    "acende alerta":                "preocupa",
    "expõe":                        "mostra",
    "expõe risco":                  "indica risco",
    "em meio a":                    "durante",
    "em meio ao":                   "durante",
    "desdobramento importante":     None,
    "cenário complexo":             None,
    "bastidores quentes":           None,
    "bastidores pegam fogo":        None,
    "coloca luz sobre":             None,
    "joga luz sobre":               None,
    "joga luz":                     None,
    "sinaliza que":                 None,
    "reforça o compromisso":        None,
    "reafirma o compromisso":       None,
    "demonstra o compromisso":      None,
    "vale lembrar":                 "vale registrar que",
    "vale destacar":                None,
    "é importante destacar":        None,
    "cabe destacar":                None,
    "cabe ressaltar":               None,
    "importante frisar":            None,
    "um novo capítulo":             None,
    "novo capítulo":                None,
    "gera preocupação":             "preocupa",
    "especialistas apontam":        None,
    "analistas avaliam":            None,
    "setores da sociedade":         None,
    "robusto":                      None,
    "robusta":                      None,
    "emblemático":                  None,
    "emblemática":                  None,
    "marco histórico":              None,
    "avanço significativo":         None,
    "não passou despercebido":      None,
    "ganhou as redes":              None,
    "em conclusão":                 None,
    "conclui-se que":               None,
    "fica evidente que":            None,
    "resta claro que":              None,
    "a lição que fica":             None,
    "o recado está dado":           None,
    "consolida tendência":          None,
    "traz à tona":                  "revela",
    "nesse contexto":               None,
    "neste cenário":                None,
    "diante desse cenário":         None,
    "evidencia":                    "mostra",
    "evidenciando":                 "mostrando",
    "deixa evidente":               "mostra",
    "conforme fontes":              "segundo fontes identificadas",
    "web reage":                    None,
    "internautas reagem":           None,
    "assunto viraliza":             None,
    "movimenta os bastidores":      None,
    "esquenta disputa":             None,
    "vira alvo de polêmica":        None,
}

FRASES_GENERICAS_PROIBIDAS = [
    "a situação exige atenção das autoridades",
    "o caso segue sendo acompanhado",
    "a decisão pode ter impactos importantes",
    "o debate deve continuar nos próximos dias",
    "a medida busca garantir equilíbrio",
    "o tema segue em discussão",
    "a população aguarda respostas",
    "o assunto continua gerando debate",
    "especialistas divergem sobre o tema",
    "o impacto ainda é incerto",
    "as investigações estão em andamento",
    "mais informações em breve",
    "o caso está sendo monitorado",
]

# Frases de expansão artificial (unsupported claims) — proibidas sem respaldo na fonte
FRASES_UNSUPPORTED_CLAIMS = [
    "o próximo passo será",
    "o próximo passo é",
    "as investigações seguem",
    "as investigações prosseguem",
    "as investigações continuam",
    "as autoridades continuarão",
    "a autoridade continuará",
    "a medida visa garantir",
    "a decisão busca assegurar",
    "a medida busca garantir",
    "novas etapas serão realizadas",
    "novas informações devem ser divulgadas",
    "novas informações serão divulgadas",
    "o caso deve ter novos desdobramentos",
    "o caso terá novos desdobramentos",
    "a população aguarda respostas",
    "o impacto jurídico",
    "o impacto econômico envolve",
    "a situação exige atenção das autoridades",
    "o caso segue sendo acompanhado",
    "o debate deve continuar nos próximos dias",
    "mais informações em breve",
    "o caso está sendo monitorado",
    "a investigação deve ser concluída",
    "o desfecho do caso",
    "em breve haverá",
]

# Padrão de data inventada: dia + mês por extenso + ano (não presente na fonte)
import re as _re_agente
PADRAO_DATA_INVENTADA = _re_agente.compile(
    r"\b\d{1,2}\s+de\s+"
    r"(?:janeiro|fevereiro|março|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)"
    r"\s+de\s+\d{4}\b",
    _re_agente.IGNORECASE,
)

SCHEMA_SAIDA: dict = {
    "titulo_seo": "",
    "subtitulo_curto": "",
    "retranca": "",
    "titulo_capa": "",
    "tags": "",
    "legenda_curta": "",
    "corpo_materia": "",
    "legenda_instagram": "",
    "status_validacao": "pendente",
    "erros_validacao": [],
    "observacoes_editoriais": [],
}


# ═══════════════════════════════════════════════════════════════════════════════
# SEÇÃO 2: SYSTEM PROMPT EDITORIAL (enviado em TODA chamada à API)
# ═══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT_EDITORIAL_URURAU = f"""
Você é o Agente Editorial do Portal Ururau, com sede em Campos dos Goytacazes (RJ), cobrindo o Norte Fluminense, Porto do Açu, a política estadual do Rio de Janeiro e pautas nacionais de alto impacto regional.

════════════════════════════════════════════════════════
IDENTIDADE E MISSÃO
════════════════════════════════════════════════════════
Você produz texto jornalístico profissional: claro, factual, preciso e indexável.
Você é um EXECUTOR dentro de um sistema rígido. Não decide por conta própria nenhum campo crítico.
Cada chamada é autossuficiente. Sem memória entre chamadas. Sem presunção do que não foi informado.
Se uma informação não estiver na fonte ou nos dados fornecidos, NÃO invente.
O resultado deve parecer escrito por repórter experiente de redação digital. Nunca parecer IA.

════════════════════════════════════════════════════════
OBJETIVO: SEO JORNALÍSTICO
════════════════════════════════════════════════════════
Esta matéria será publicada em portal de notícias e deve performar bem no Google Search e Google Discover.
Isso NÃO significa escrever para robô — significa precisão e clareza que humanos e algoritmos reconhecem como qualidade.

REGRAS DE SEO OBRIGATÓRIAS:
- titulo_seo: máximo {LIMITE_TITULO_SEO} caracteres. A palavra-chave ou fato principal deve estar NO INÍCIO.
  Inclua personagem, instituição, cidade ou tema central quando ajudar na busca.
  Sem clickbait. Sem interrogação/exclamação. Factual e direto.
- O PRIMEIRO PARÁGRAFO responde: quem, o quê, onde, quando, por quê/consequência.
  Isso é exigido pelo jornalismo e pelo Google (lead news).
- Nomes próprios, cargos, instituições, cidades, termos relevantes: aparecem naturalmente no texto.
- subtitulo_curto: complementa o título com fato concreto, consequência ou dado relevante.
  Não repete o título. Não é genérico. Não é uma frase vaga.
- tags: incluem personagens, instituições, cidade, estado, tema e termos que alguém digitaria no Google.
  NUNCA incluir nome do portal de origem como tag.
- O texto deve ser original. Nunca plágio. Nunca cópia da estrutura da fonte.
- Preservar dados objetivos: nomes, cargos, datas, órgãos, decisões, locais, valores, citações.

════════════════════════════════════════════════════════
REGRA CRÍTICA: PRESERVAÇÃO DE SUBSTÂNCIA
════════════════════════════════════════════════════════
O sistema NÃO ACEITA matérias genéricas. Antes de escrever, identifique os fatos essenciais.
Após escrever, verifique se esses fatos aparecem no texto.

Quando a fonte contiver qualquer dos elementos abaixo, a matéria DEVE incluí-los:
- Números, percentuais, valores, médias, índices
- Estudos, pesquisas, levantamentos, relatórios
- Artigos de lei, incisos, dispositivos constitucionais, números de processo
- Decisões judiciais, administrativas, institucionais
- Documentos, notas técnicas, notas públicas
- Órgãos públicos, tribunais, entidades, empresas
- Impactos econômicos, sociais, jurídicos, políticos
- Argumentos centrais das partes
- Pedidos, propostas, encaminhamentos
- Próximos passos declarados
- Declarações com aspas e atribuição
- Versões conflitantes

Matéria que omite dados centrais da fonte = REPROVADA.
Originalidade = reescrever a FORMA preservando a SUBSTÂNCIA.

════════════════════════════════════════════════════════
REGRAS DE FIDELIDADE FACTUAL
════════════════════════════════════════════════════════
- NUNCA invente fato, data, hora, cargo, nome, número, processo, decisão, documento, reação.
- NUNCA preencha lacuna com suposição ou inferência.
- NUNCA extrapolação: se a fonte diz "projeto", não escreva "tramita no Congresso" sem confirmação.
- NUNCA troque status: "debate" ≠ "lei aprovada"; "proposta" ≠ "lei"; "investigado" ≠ "condenado".
- NUNCA cite o veículo de origem dentro do corpo do texto.
- SEMPRE atribua falas, decisões, posições a quem as produziu.
- Quando houver dúvida: "segundo a decisão", "conforme informado", "de acordo com o relato".

════════════════════════════════════════════════════════
ESTRUTURA OBRIGATÓRIA DO TEXTO
════════════════════════════════════════════════════════
Parágrafo 1 — Lead: quem, o quê, onde, quando, consequência/por que importa.
Parágrafos 2-3 — Contexto: personagens, cargos, histórico do caso, números, documentos, argumentos.
Parágrafos 4+ — Desdobramento: posição oficial, próximos passos, efeito prático, impactos.
Fecho factual: estágio do caso, investigação, manifestação, próximo passo. NUNCA fecho ornamental.
SEPARAÇÃO OBRIGATÓRIA: use \\n\\n entre parágrafos no JSON. NUNCA bloco único corrido.

REGRA CRÍTICA DE TAMANHO PROPORCIONAL:
O artigo DEVE ter tamanho proporcional ao texto-fonte fornecido.
- Fonte muito curta (menos de 300 chars): 2-3 parágrafos. Sem expansão artificial.
- Fonte curta (menos de 800 chars): 3-5 parágrafos. Preserve todos os fatos disponíveis.
- Fonte completa (800 chars ou mais): 5-10 parágrafos com todos os dados essenciais.
NUNCA force parágrafos extras com informações não presentes na fonte.
Um artigo curto e preciso PASSA. Um artigo longo com dados inventados FALHA.

REGRA ABSOLUTA: ZERO CLAIMS NAO SUPORTADOS
NUNCA adicione estas frases sem respaldo explícito na fonte:
"o próximo passo será...", "as investigações seguem...", "as autoridades continuarão...",
"a medida visa garantir...", "a decisão busca assegurar...", "novas informações serão divulgadas...",
"o caso deve ter novos desdobramentos...", "a população aguarda respostas...",
"continuará coletando provas...", "monitorando os envolvidos...", "em breve haverá..."
Se não estiver explicitamente na fonte, NÃO escreva.

REGRA ABSOLUTA: NUNCA INVENTAR DATAS
Se a fonte diz "nesta quinta-feira (23)" — escreva "nesta quinta-feira (23)". NÃO invente mês ou ano.
Se a fonte diz "no dia 15" — escreva "no dia 15". NÃO invente "15 de maio" ou qualquer mês.
Só escreva data completa (dia + mês + ano) se a fonte apresentar os três explicitamente.

════════════════════════════════════════════════════════
REGRAS POR EDITORIA
════════════════════════════════════════════════════════

POLÍTICA:
- Identifique atores principais, partidos (quando relevantes), a disputa, quem pediu, quem decidiu, quem é afetado.
- Explique o efeito prático e o próximo passo institucional.
- Não tome partido, salvo editorial/artigo/nota de apoio explicitamente pedido.
- Evite adjetivos excessivos. Priorize precisão institucional.
- Preserve nomes, cargos, mandatos, órgãos, partidos.

JUSTIÇA:
- Cite tribunal, ministro, desembargador, juiz, relator ou autoridade.
- Explique a decisão, o efeito prático e o próximo passo processual.
- Preserve artigos de lei, da Constituição, números de processo.
- Não editorializar. Não simplificar a ponto de perder precisão jurídica.
- Informe estágio correto: investigado, indiciado, réu, condenado, absolvido.

POLÍCIA:
- Preserve nomes de autoridades.
- Abrevie nomes de vítimas quando necessário.
- Informe local, data, órgão responsável, situação da investigação.
- Use corretamente: suspeito, investigado, acusado, indiciado, preso preventivamente, condenado.
- Não faça julgamento antecipado. Não use linguagem sensacionalista.
- Q1 = principal suspeito/autor; Q2 = segundo envolvido conforme o caso.

ECONOMIA E TRABALHO:
- Cite entidade, empresa, órgão principal.
- Explique setor afetado.
- Preserve números, percentuais, estudos, projeções.
- Explique impacto sobre empresas, trabalhadores, consumidores, administração pública.
- Preserve base jurídica e legal quando presente.
- Informe proposta, crítica ou pedido central.
- Não transforme nota técnica em resumo genérico.

CIDADES:
- Mencione cidade, bairro ou localidade quando relevante.
- Explique impacto local.
- Preserve órgãos municipais/estaduais envolvidos.
- Informe claramente: serviço, obra, denúncia, incidente ou decisão.

NOTAS DE ENTIDADE E MANIFESTAÇÕES INSTITUCIONAIS:
Quando a fonte for nota pública, posicionamento de entidade, sindicato, federação, confederação,
órgão público, tribunal ou instituição, informe obrigatoriamente:
- Quem se manifestou (nome completo na primeira menção).
- Qual é a posição.
- Qual é o argumento principal.
- Quais dados sustentam a posição.
- Quais impactos foram citados.
- Qual a base jurídica, se houver.
- Qual solução ou encaminhamento a entidade defende.
- Se há crítica a Congresso, governo, tribunal, prefeitura, sindicato ou empresa.
- Se há pedido de cautela, providência, revisão ou mudança de conduta.

EDITORIAL, OPINIÃO, ARTIGO OU NOTA DE APOIO:
Apenas quando o usuário pedir explicitamente.
Pode ter posição clara, mas deve preservar base factual e citar fundamentos legais quando houver.

════════════════════════════════════════════════════════
REGRAS DE TRAVESSÃO E EXPRESSÕES PROIBIDAS
════════════════════════════════════════════════════════
NUNCA use travessão (— ou –). Substitua por vírgula, dois-pontos ou ponto.

NUNCA use estas expressões:
reacende, levanta debate, levanta preocupação, acende o alerta, acende alerta, liga o alerta,
expõe (sentido genérico), em meio a, desdobramento importante, cenário complexo,
bastidores pegam fogo, bastidores quentes, coloca luz sobre, joga luz, sinaliza (genérico),
reforça (genérico), destaca (repetitivo), vale lembrar, é importante destacar, cabe destacar,
cabe ressaltar, um novo capítulo, gera preocupação (sem sujeito claro), movimenta os bastidores,
esquenta disputa, vira alvo de polêmica (genérico), web reage, internautas reagem (sem relevância),
assunto viraliza (sem dado concreto), em conclusão, conclui-se que, fica evidente que,
resta claro que, a lição que fica, o recado está dado, consolida tendência,
não passou despercebido, nesse cenário, neste cenário, diante desse cenário,
especialistas apontam (sem identificar quem), analistas avaliam (sem identificar quem).

FRASES GENÉRICAS PROIBIDAS (sem dado concreto que as justifique):
"A situação exige atenção das autoridades."
"O caso segue sendo acompanhado."
"A decisão pode ter impactos importantes."
"O debate deve continuar nos próximos dias."
"O tema segue em discussão."
"A população aguarda respostas."
"O assunto continua gerando debate."
"O impacto ainda é incerto."
"Mais informações em breve."
Essas frases só são aceitáveis quando acompanhadas de fato concreto, órgão responsável, prazo ou documento.

════════════════════════════════════════════════════════
PADRÕES DE CAMPO OBRIGATÓRIOS
════════════════════════════════════════════════════════
titulo_seo: {LIMITE_TITULO_SEO_MIN}-{LIMITE_TITULO_SEO} chars. Fato/personagem/instituição no início.
titulo_capa: {LIMITE_TITULO_CAPA_MIN}-{LIMITE_TITULO_CAPA} chars. Forte para home do site. Máximo possível sem ultrapassar.
subtitulo_curto: frase única ≤{LIMITE_SUBTITULO} chars. Complementa com dado, impacto ou consequência. NÃO repete o título.
legenda_curta: ≤{LIMITE_LEGENDA} chars. Factual. Explica quem aparece, qual o fato ou contexto da imagem.
retranca: 1-3 palavras. Temática e específica. Exemplos: Política, Governo RJ, Polícia, Justiça, STF, Alerj, Economia, Trabalho, Saúde, Educação, Cidades, Esportes, Tecnologia, Brasil, Mundo.
tags: {TAGS_MIN}-{TAGS_MAX} strings separadas por vírgula. Sem hashtags. Incluem personagens, instituições, cidade, estado, tema e termos de busca. SEM nome do portal de origem.
corpo_materia: tamanho proporcional à fonte (fonte curta → artigo curto; fonte longa → artigo completo). Parágrafos separados por \\n\\n. Lead responde 5W. TODOS os dados essenciais da fonte preservados. ZERO claims não suportados.
legenda_instagram: gerar APENAS quando solicitado. Estrutura: título no topo + texto narrativo + "🔗Leia a matéria completa no site Ururau - Link na Bio e Stories ➡ Siga a página: @ururaunoticias"

════════════════════════════════════════════════════════
SAÍDA OBRIGATÓRIA
════════════════════════════════════════════════════════
Sempre JSON válido. ZERO texto fora do JSON. ZERO markdown ao redor do JSON.
Nenhum campo pode ser omitido. Tipos devem ser corretos.

CHECKLIST OBRIGATÓRIO ANTES DE ENTREGAR:
□ titulo_seo: {LIMITE_TITULO_SEO_MIN}-{LIMITE_TITULO_SEO} chars, fato/personagem/instituição no início?
□ titulo_capa: {LIMITE_TITULO_CAPA_MIN}-{LIMITE_TITULO_CAPA} chars, máximo possível?
□ subtitulo_curto: complementa com dado concreto, sem repetir o título?
□ legenda_curta: factual, ≤{LIMITE_LEGENDA} chars?
□ retranca: 1-3 palavras, específica?
□ tags: {TAGS_MIN}-{TAGS_MAX} strings, sem portal de origem?
□ corpo_materia: tamanho proporcional à fonte? Parágrafos separados com \\n\\n?
□ ZERO claims não suportados ("próximo passo será...", "investigações seguem...", etc.)?
□ ZERO datas inventadas (datas relativas preservadas como na fonte)?
□ Lead responde quem/o quê/onde/quando/por quê?
□ Todos os dados essenciais da fonte preservados?
□ ZERO travessão em qualquer campo?
□ ZERO expressões proibidas?
□ ZERO fatos inventados?
□ JSON válido e parseável?
□ ZERO confusão numérica: nenhum % virou R$, nenhum R$ virou %, estimativa ≠ fato confirmado?
□ Cada número preserva sua categoria semântica (receita ≠ participação, volume ≠ receita)?
□ Parágrafo final fecha com fato confirmado, status ou resposta — ZERO análise interpretativa?
□ ZERO parágrafos repetidos (mesmo fato descrito duas vezes sem informação nova)?
□ Citações diretas ≤ 40% do corpo? Citações secundárias foram parafraseadas?
□ Verbos "destacou", "reforçou", "ressaltou", "sinalizou", "pontuou", "frisou", "salientou"
  usados no máximo uma vez e com atribuição clara? Preferir: "afirmou", "disse", "informou"?
□ Estrutura reorganizada com lógica jornalística (fato principal primeiro)?
□ Todos os campos obrigatórios presentes: titulo_seo, subtitulo_curto, retranca, titulo_capa,
  tags, legenda_curta, corpo_materia, nome_da_fonte, creditos_da_foto, editoria, canal, slug?

REGRA DE PRECISÃO NUMÉRICA (CRÍTICA):
Todo número da fonte tem uma CATEGORIA semântica — preserve-a obrigatoriamente.
- RECEITA (R$)  ≠  PARTICIPAÇÃO (%)  ≠  VOLUME (ton/un)
- PONTO PERCENTUAL  ≠  PERCENTAGEM
- ESTIMATIVA  ≠  VALOR CONFIRMADO
- ALEGAÇÃO  ≠  FATO PROVADO
Se a fonte diz "participação de 23%", NUNCA escreva "receita de 23%" ou "R$ 23 milhões".
Se a fonte diz "estima-se que...", NUNCA apresente o número como confirmado.

REGRA DE FECHAMENTO FACTUAL:
O último parágrafo DEVE fechar com: fato confirmado, conclusão de documento, resposta ou status atual.
NUNCA encerre com análise interpretativa não suportada pela fonte:
"situação crítica", "medida emergencial", "cenário preocupante", "impacto severo",
"momento delicado", "estratégia para conter perdas", "efeito devastador" — PROIBIDOS sem respaldo.

REGRA ANTI-REPETIÇÃO:
Cada parágrafo deve acrescentar NOVA informação. Se o mesmo fato aparece duas vezes sem dado novo,
mescle os parágrafos ou elimine o redundante.

REGRA DE CITAÇÃO DIRETA:
Use no máximo 1-2 citações diretas longas por artigo. Parafrase as demais com atribuição.
Artigo com mais de 40% do corpo em aspas diretas será rejeitado.

REGRA DE VERBOS DE ATRIBUIÇÃO:
Prefira: "afirmou", "disse", "informou", "segundo", "de acordo com", "conforme".
Evite como muletas repetidas: "destacou", "reforçou", "ressaltou", "sinalizou", "pontuou".

REGRA DE REORGANIZAÇÃO EDITORIAL:
Não reproduza a ordem da fonte. Reorganize: fato principal → números → contexto →
posição institucional → impactos → resposta → próximo passo (somente se explícito na fonte).

REGRA DE CONSISTÊNCIA TÍTULO–CORPO:
O título SEO e o título de capa DEVEM descrever o mesmo fato central do corpo.
- Número no título DEVE aparecer no corpo
- Entidade/nome no título DEVE aparecer no corpo
- Subtítulo NÃO contradiz o título — complementa com dado novo
- NUNCA simplifique o título a ponto de criar erro conceitual
Exemplos proibidos:
- Título: "Empresa X fatura R$ 23 mi" quando a fonte diz "participação de 23%"
- Título: "Operação prende suspeito" quando a fonte diz "conduzido para depoimento"
- Título: "Governo aprova medida" quando a fonte diz "projeto enviado ao Congresso"

REGRA DE MÚLTIPLOS PERCENTUAIS:
Quando a fonte apresenta dois ou mais percentuais sobre o mesmo assunto:
- Explique o contexto de cada percentual (período, critério, órgão)
- OU use apenas o percentual central e omita o secundário
- NUNCA apresente dois percentuais de forma que pareçam contraditórios sem explicação
- NUNCA some dois percentuais de métricas diferentes implicitamente
Exemplo: "crescimento de 8% e participação de 23%" precisam de contextos distintos explícitos.
""".strip()


# ═══════════════════════════════════════════════════════════════════════════════
# SEÇÃO 3: RESULTADO DO AGENTE
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ResultadoAgente:
    """Resultado completo do Agente Editorial do Ururau."""
    sucesso: bool = False
    aprovado: bool = False
    status: str = "rascunho"         # aprovado | revisado | rascunho | falha
    dados: dict = field(default_factory=dict)
    fatos_essenciais: dict = field(default_factory=dict)
    erros_validacao: list[str] = field(default_factory=list)
    dados_ausentes: list[str] = field(default_factory=list)
    expressoes_encontradas: list[str] = field(default_factory=list)
    revisao_aplicada: bool = False
    modelo_usado: str = ""
    log: list[str] = field(default_factory=list)
    timestamp: str = ""

    def resumo_log(self) -> str:
        return "\n".join(self.log)


# ═══════════════════════════════════════════════════════════════════════════════
# SEÇÃO 4: EXTRAÇÃO DE FATOS ESSENCIAIS
# ═══════════════════════════════════════════════════════════════════════════════

def extract_essential_facts(
    source_text: str,
    title: str = "",
    summary: str = "",
    client: "OpenAI | None" = None,
    model: str = MODELO_PADRAO,
) -> dict:
    """
    extractEssentialFacts: extrai dados essenciais da fonte ANTES de gerar a matéria.

    Identifica: fato principal, personagens, instituições, números, percentuais,
    valores, estudos, artigos de lei/constituição, impactos, argumentos centrais,
    pedidos, base jurídica, citações, próximos passos, posições conflitantes.

    Se client=None, faz extração local via regex (fallback rápido).
    Se client fornecido, usa IA para extração mais precisa.
    """
    if client:
        return _extract_via_ia(source_text, title, summary, client, model)
    return _extract_local(source_text, title, summary)


def _extract_local(source_text: str, title: str = "", summary: str = "") -> dict:
    """Extração local por padrões regex — rápida, sem chamada de API."""
    texto_original = title + "\n" + summary + "\n" + source_text

    # Números e percentuais
    # Exclui idades de pessoas físicas: padrão "(27 anos)" é dado biográfico, não estatístico
    _texto_sem_idades_pessoais = re.sub(
        r'\(\s*\d{1,3}\s+anos?\s*\)',
        '',
        texto_original,
        flags=re.IGNORECASE,
    )
    numeros = re.findall(
        r'\b\d+[.,]?\d*\s*(?:%|por cento|reais?|mil|milhões?|bilhões?|horas?|dias?|anos?|meses?|R\$)\b',
        _texto_sem_idades_pessoais, re.IGNORECASE
    )
    # Artigos de lei
    artigos = re.findall(
        r'art(?:igo)?\.?\s*\d+[º°]?\s*(?:[,;]\s*(?:inciso|§|parágrafo)\s*[\wIVX]+)?'
        r'(?:\s*(?:da|do|de)\s+(?:Constituição|Lei|CLT|CF|CP|CPC|CDC|Lei\s+\d+))?',
        texto_original, re.IGNORECASE
    )
    # Estudos e pesquisas
    estudos = re.findall(
        r'(?:estudo|pesquisa|levantamento|relatório|nota técnica|dados?|índice|survey)\s+'
        r'(?:da|do|de|pelo|pela)?\s+[\w\s]{3,30}',
        texto_original, re.IGNORECASE
    )

    return {
        "fato_principal": (title or summary[:200] or source_text[:200]).strip(),
        "fatos_secundarios": [],
        "quem": [],
        "onde": "",
        "quando": "",
        "orgao_central": "",
        "status_atual": "",
        "proximos_passos": "",
        "fonte_primaria": "",
        "dados_numericos": list(dict.fromkeys(n.strip() for n in numeros[:12])),
        "estudos_citados": list(dict.fromkeys(e.strip() for e in estudos[:6])),
        "artigos_lei_citados": list(dict.fromkeys(a.strip() for a in artigos[:8])),
        "impactos_citados": [],
        "argumentos_centrais": [],
        "pedidos_ou_encaminhamentos": [],
        "base_juridica": "",
        "declaracoes_identificadas": [],
        "posicoes_conflitantes": [],
        "inferencias_a_evitar": [],
        "elementos_sem_fonte": [],
        "grau_confianca": "medio",
        "risco_editorial": "baixo",
        "fonte": "local",
    }


def _extract_via_ia(
    source_text: str,
    title: str,
    summary: str,
    client: "OpenAI",
    model: str,
) -> dict:
    """Extração via IA — mais precisa, usa o modelo configurado."""
    material = (title + "\n\n" + summary + "\n\n" + source_text)[:12000]

    prompt = f"""Você é um editor-chefe analisando material jornalístico antes da redação.
Extraia as evidências estruturadas do material abaixo. Devolva APENAS JSON válido.

REGRAS:
- Separe fato confirmado de declaração e de inferência.
- Registre TODOS os números, percentuais, valores presentes (ex: "17,2%", "39 horas", "R$ 5 mil").
- Registre TODOS os estudos, pesquisas e levantamentos mencionados.
- Registre TODOS os artigos de lei, incisos, dispositivos constitucionais, números de processo.
- Registre impactos econômicos, sociais, jurídicos ou políticos citados.
- Registre argumentos centrais de entidades, órgãos ou pessoas citadas.
- Registre o que a entidade/órgão pede, propõe ou exige.
- Registre declarações com aspas ou atribuição explícita.
- Registre versões conflitantes ou respostas das partes.
- Nunca invente informação ausente no material.
- Campo vazio = string vazia ou lista vazia.

MATERIAL:
{material}

SAÍDA (JSON exato, sem texto fora do JSON):
{{
  "fato_principal": "fato central confirmado com quem, onde, quando e o quê",
  "fatos_secundarios": ["outros fatos confirmados no material"],
  "quem": ["pessoas, cargos e organizações centrais"],
  "onde": "local principal",
  "quando": "data ou período",
  "orgao_central": "órgão ou instituição central do fato",
  "status_atual": "situação atual: votando, aprovado, em análise, preso, investigado, em vigor, etc.",
  "proximos_passos": "próxima etapa factual prevista ou declarada",
  "fonte_primaria": "nota oficial, tribunal, empresa, polícia, MP, etc.",
  "dados_numericos": ["todos os números, percentuais, valores, médias, índices — ex: '17,2% de aumento no custo', '39 horas semanais'"],
  "estudos_citados": ["nomes de estudos, pesquisas, levantamentos — ex: 'estudo da FGV'"],
  "artigos_lei_citados": ["artigos, incisos, leis, dispositivos constitucionais — ex: 'artigo 7º, XIII, CF'"],
  "impactos_citados": ["impactos econômicos, sociais, jurídicos ou políticos — ex: 'aumento de custos operacionais'"],
  "argumentos_centrais": ["argumentos principais da entidade, pessoa ou órgão central"],
  "pedidos_ou_encaminhamentos": ["o que a entidade, órgão ou pessoa pede ou propõe"],
  "base_juridica": "base constitucional, legal ou regulatória citada no material",
  "declaracoes_identificadas": ["falas atribuídas com aspas ou atribuição clara"],
  "posicoes_conflitantes": ["versões ou posições conflitantes de atores citados"],
  "elementos_sem_fonte": ["afirmações que aparecem no material sem fonte identificada"],
  "inferencias_a_evitar": ["conclusões que o material sugere mas não confirma explicitamente"],
  "grau_confianca": "alto | medio | baixo",
  "risco_editorial": "baixo | medio | alto",
  "fonte": "ia"
}}"""

    try:
        resposta = client.responses.create(
            model=model,
            instructions="Você é um extrator de fatos jornalísticos. Retorne apenas JSON válido.",
            input=prompt,
            temperature=0.1,
        )
        bruto = resposta.output_text.strip()
        bruto = re.sub(r"```(?:json)?", "", bruto).replace("```", "").strip()
        inicio = bruto.find("{")
        fim = bruto.rfind("}") + 1
        if inicio >= 0 and fim > inicio:
            dados = json.loads(bruto[inicio:fim])
            dados["fonte"] = "ia"
            return dados
    except Exception as e:
        print(f"[AGENTE] Falha na extração IA: {e} — usando extração local")

    return _extract_local(source_text, title, summary)


# ═══════════════════════════════════════════════════════════════════════════════
# SEÇÃO 5: CONSTRUÇÃO DO USER PROMPT
# ═══════════════════════════════════════════════════════════════════════════════

def build_article_prompt(
    source_text: str,
    essential_facts: dict,
    canal: str = "Cidades",
    options: dict | None = None,
) -> str:
    """
    buildArticlePrompt: monta o user prompt enviado ao modelo.

    Combina o texto-fonte, os fatos essenciais extraídos e as opções do canal
    em um prompt estruturado que força a preservação de todos os dados essenciais.
    """
    opts = options or {}
    model_name = opts.get("model", MODELO_PADRAO)
    pedir_instagram = opts.get("legenda_instagram", False)
    tipo_conteudo = opts.get("tipo", "materia")

    _dados_num   = essential_facts.get("dados_numericos") or []
    _estudos     = essential_facts.get("estudos_citados") or []
    _artigos     = essential_facts.get("artigos_lei_citados") or []
    _impactos    = essential_facts.get("impactos_citados") or []
    _argumentos  = essential_facts.get("argumentos_centrais") or []
    _pedidos     = essential_facts.get("pedidos_ou_encaminhamentos") or []
    _base_jur    = str(essential_facts.get("base_juridica") or "").strip()
    _declaracoes = essential_facts.get("declaracoes_identificadas") or []
    _conflitantes = essential_facts.get("posicoes_conflitantes") or []
    _evitar      = essential_facts.get("inferencias_a_evitar") or []

    # Bloco de dados obrigatórios
    linhas_obrig: list[str] = []
    tem_dados = any([_dados_num, _estudos, _artigos, _impactos, _argumentos, _pedidos, _base_jur])

    if tem_dados:
        linhas_obrig += [
            "╔══════════════════════════════════════════════════════╗",
            "║  DADOS ESSENCIAIS — OBRIGATÓRIOS NA MATÉRIA FINAL   ║",
            "║  CADA ITEM ABAIXO DEVE APARECER NO TEXTO.            ║",
            "║  MATÉRIA REPROVADA SE QUALQUER ITEM ESTIVER AUSENTE. ║",
            "╚══════════════════════════════════════════════════════╝",
            "",
        ]
        if _dados_num:
            linhas_obrig.append("📊 NÚMEROS E DADOS QUANTITATIVOS (citar TODOS no texto):")
            linhas_obrig += [f"   • {d}" for d in _dados_num[:12]]
        if _estudos:
            linhas_obrig.append("\n📚 ESTUDOS E PESQUISAS (citar com atribuição):")
            linhas_obrig += [f"   • {e}" for e in _estudos[:6]]
        if _artigos:
            linhas_obrig.append("\n⚖️  ARTIGOS DE LEI / CONSTITUIÇÃO (preservar exatamente):")
            linhas_obrig += [f"   • {a}" for a in _artigos[:6]]
        if _impactos:
            linhas_obrig.append("\n⚡ IMPACTOS CITADOS (explicar no texto):")
            linhas_obrig += [f"   • {i}" for i in _impactos[:8]]
        if _argumentos:
            linhas_obrig.append("\n💬 ARGUMENTOS CENTRAIS (preservar a substância):")
            linhas_obrig += [f"   • {a}" for a in _argumentos[:6]]
        if _pedidos:
            linhas_obrig.append("\n📋 PEDIDOS E ENCAMINHAMENTOS (incluir no texto):")
            linhas_obrig += [f"   • {p}" for p in _pedidos[:4]]
        if _base_jur:
            linhas_obrig.append(f"\n📜 BASE JURÍDICA (citar na matéria): {_base_jur}")

    bloco_obrig = "\n".join(linhas_obrig) if linhas_obrig else ""

    bloco_declaracoes = ""
    if _declaracoes:
        bloco_declaracoes = (
            "\n📣 DECLARAÇÕES COM ATRIBUIÇÃO (usar com aspas e atribuição):\n" +
            "\n".join(f"   • {d}" for d in _declaracoes[:4])
        )

    bloco_conflitantes = ""
    if _conflitantes:
        bloco_conflitantes = (
            "\n⚠️  POSIÇÕES CONFLITANTES (mencionar quando relevante):\n" +
            "\n".join(f"   • {c}" for c in _conflitantes[:3])
        )

    bloco_evitar = ""
    if _evitar:
        bloco_evitar = (
            "\n🚫 NÃO ESCREVA — inferências não confirmadas:\n" +
            "\n".join(f"   • {i}" for i in _evitar[:4])
        )

    # Contexto factual básico
    fato      = essential_facts.get("fato_principal", "")
    quem      = ", ".join((essential_facts.get("quem") or [])[:6])
    onde      = essential_facts.get("onde", "")
    quando    = essential_facts.get("quando", "")
    orgao     = essential_facts.get("orgao_central", "")
    proximos  = essential_facts.get("proximos_passos", "")
    status    = essential_facts.get("status_atual", "")
    fonte_prim = essential_facts.get("fonte_primaria", "")

    instrucao_tipo = {
        "materia":    "TIPO: Matéria jornalística informativa. Tom neutro, factual.",
        "editorial":  "TIPO: Editorial com posição clara do veículo. Permitido ter opinião. Preserve base factual.",
        "opiniao":    "TIPO: Artigo de opinião. Permitido ter posição. Preserve argumentos com base factual.",
        "nota_apoio": "TIPO: Nota de apoio institucional. Posição clara, tom jornalístico, base factual obrigatória.",
    }.get(tipo_conteudo, "TIPO: Matéria jornalística informativa.")

    instagram_instrucao = ""
    if pedir_instagram:
        instagram_instrucao = """
LEGENDA_INSTAGRAM: gerar obrigatoriamente com a seguinte estrutura:
  1. título no topo, sem emoji;
  2. texto narrativo longo com os principais dados;
  3. fechamento fixo: "🔗Leia a matéria completa no site Ururau - Link na Bio e Stories ➡ Siga a página: @ururaunoticias"
"""

    prompt = f"""
{instrucao_tipo}
Canal editorial de destino: {canal}
Modelo: {model_name}

══════════════════════════════════════════════════════
BASE FACTUAL CONFIRMADA (obrigatória — não extrapole)
══════════════════════════════════════════════════════
Fato principal: {fato}
Envolvidos: {quem}
Local: {onde}
Quando: {quando}
Órgão central: {orgao}
Status atual: {status}
Fonte primária: {fonte_prim}
Próximos passos: {proximos}

{bloco_obrig}
{bloco_declaracoes}
{bloco_conflitantes}
{bloco_evitar}

══════════════════════════════════════════════════════
TEXTO-FONTE COMPLETO
(Leia com atenção. Extraia dados. Não copie estrutura.)
══════════════════════════════════════════════════════
{source_text[:8000]}

══════════════════════════════════════════════════════
INSTRUÇÕES PARA O CORPO DA MATÉRIA
══════════════════════════════════════════════════════
1. Lead (1º parágrafo): responde quem, o quê, onde, quando, por quê/consequência.
   Não abra com "A matéria trata de..." Comece pelo fato, entidade ou personagem.
2. Parágrafos 2-3: contexto, personagens, dados, argumentos, documentos.
3. Parágrafos seguintes: desdobramentos, impactos, próximos passos, efeito prático.
4. Fecho: situação atual ou próxima etapa. NUNCA fecho ornamental.
5. Separação: use \\n\\n entre parágrafos. NUNCA bloco único.
6. TAMANHO PROPORCIONAL À FONTE: fonte_size={len(source_text)} chars.
   - Fonte muito curta (< 300 chars): 2-3 parágrafos. Sem expansão artificial.
   - Fonte curta (< 800 chars): 3-5 parágrafos. Preserve todos os fatos disponíveis.
   - Fonte completa (>= 800 chars): 5-10 parágrafos com todos os dados essenciais.
   NUNCA force parágrafos extras com informações não presentes na fonte.
7. TODOS os dados do bloco OBRIGATÓRIOS acima DEVEM aparecer no texto.
8. Não use travessão (— ou –). Use vírgula, dois-pontos ou ponto.
9. Não use expressões proibidas.
10. Não copie frases da fonte. Reescreva com apuração própria.
11. titulo_seo: palavra-chave/fato/personagem/instituição NO INÍCIO. Entre 40 e 89 chars.
12. titulo_capa: máximo 60 chars. Use o máximo possível do limite.
13. NUNCA invente datas: se a fonte diz "nesta quinta-feira (23)", escreva exatamente isso.
14. NUNCA adicione "próximo passo será...", "investigações seguem...", "autoridade continuará..."
    sem respaldo explícito na fonte.
{instagram_instrucao}

══════════════════════════════════════════════════════
SCHEMA DE SAÍDA (JSON obrigatório)
Retorne APENAS o JSON abaixo. Nenhum texto fora. Nenhum markdown.
══════════════════════════════════════════════════════
{json.dumps(SCHEMA_SAIDA, ensure_ascii=False, indent=2)}
""".strip()

    return prompt


# ═══════════════════════════════════════════════════════════════════════════════
# SEÇÃO 6: LIMPEZA AUTOMÁTICA
# ═══════════════════════════════════════════════════════════════════════════════

def _remover_travessao(texto: str) -> str:
    texto = re.sub(r"\s*[—–]\s*", ", ", texto)
    return re.sub(r"[—–]", ", ", texto)


def _limpar_expressoes(texto: str) -> str:
    if not texto:
        return texto
    resultado = texto
    for expr, substituto in sorted(EXPRESSOES_PROIBIDAS.items(), key=lambda x: len(x[0]), reverse=True):
        if substituto is not None:
            resultado = re.sub(re.escape(expr), substituto, resultado, flags=re.IGNORECASE)
    return resultado


def _corrigir_paragrafos(texto: str) -> str:
    """Garante \\n\\n entre parágrafos."""
    if not texto or not texto.strip():
        return texto
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    if "\n\n" in texto:
        return texto.strip()
    if "\n" in texto:
        return texto.replace("\n", "\n\n").strip()
    # Bloco único: divide por fim de frase + maiúscula
    # NÃO força número mínimo de parágrafos — deixa o conteúdo determinar o tamanho.
    sentencas = re.split(r"(?<=[.!?])\s+(?=[A-ZÁÀÃÂÉÊÍÓÔÕÚÜÇ])", texto)
    if len(sentencas) <= 1:
        return texto.strip()
    n = len(sentencas)
    # 2 frases por parágrafo. Textos curtos ficam com menos parágrafos — isso é correto.
    fpg = 2 if n >= 4 else 1
    paragrafos, grupo = [], []
    for i, s in enumerate(sentencas):
        grupo.append(s)
        if len(grupo) >= fpg or i == n - 1:
            paragrafos.append(" ".join(grupo))
            grupo = []
    return "\n\n".join(paragrafos).strip()


def _limpar_artigo(dados: dict) -> dict:
    """Aplica todas as limpezas ao JSON bruto da IA."""
    # Normaliza aliases
    for antigo, novo in [("texto_final", "corpo_materia"), ("subtitulo", "subtitulo_curto"),
                          ("legenda", "legenda_curta")]:
        if antigo in dados and not dados.get(novo):
            dados[novo] = dados.pop(antigo)
        elif antigo in dados:
            dados.pop(antigo, None)

    campos_texto = ["titulo_seo", "subtitulo_curto", "retranca", "titulo_capa",
                    "corpo_materia", "legenda_curta", "legenda_instagram"]
    for campo in campos_texto:
        v = dados.get(campo, "")
        if isinstance(v, str):
            v = _remover_travessao(v)
            if campo in ("corpo_materia", "titulo_seo", "subtitulo_curto"):
                v = _limpar_expressoes(v)
            dados[campo] = v

    if isinstance(dados.get("corpo_materia"), str):
        dados["corpo_materia"] = _corrigir_paragrafos(dados["corpo_materia"])

    # Tags: normaliza para string separada por vírgula
    tags = dados.get("tags", "")
    if isinstance(tags, list):
        dados["tags"] = ", ".join(str(t).strip() for t in tags if str(t).strip())

    return dados


# ═══════════════════════════════════════════════════════════════════════════════
# SEÇÃO 7: VALIDAÇÃO AUTOMÁTICA
# ═══════════════════════════════════════════════════════════════════════════════

def validate_article_output(
    article: dict,
    source_text: str = "",
    essential_facts: dict | None = None,
    model_name: str = MODELO_PADRAO,
    tamanho_fonte: int = 0,
) -> tuple[bool, list[str]]:
    """
    validateArticleOutput: valida programaticamente o JSON gerado.

    Retorna (aprovado: bool, erros: list[str]).
    Aprovado = True quando lista de erros está vazia.

    Parâmetros:
      - tamanho_fonte: número de chars da fonte original. Quando fornecido,
        ajusta os mínimos de corpo e parágrafos proporcionalmente.
        Fontes curtas (< 800 chars) aceitam artigos menores.

    Verifica:
    - Campos obrigatórios presentes e não vazios
    - Limites de caracteres (títulos, legenda, subtítulo)
    - Retranca 1-3 palavras
    - Tags separadas por vírgula, sem portal de origem
    - Corpo: tamanho proporcional à fonte, parágrafos, travessão, expressões proibidas
    - Frases de expansão artificial (unsupported claims)
    - Dados essenciais da fonte presentes no corpo
    - Modelo correto
    """
    erros: list[str] = []
    ef = essential_facts or {}

    # Determina tamanho de fonte a partir do texto se não informado explicitamente
    _tamanho_fonte = tamanho_fonte or len(source_text or "")

    # Calcula mínimos proporcionais
    _FONTE_MUITO_CURTA = 300
    _FONTE_CURTA = 800
    if _tamanho_fonte > 0 and _tamanho_fonte < _FONTE_MUITO_CURTA:
        _min_chars = max(100, _tamanho_fonte // 2)
        _min_pars = 2
    elif _tamanho_fonte > 0 and _tamanho_fonte < _FONTE_CURTA:
        _min_chars = TEXTO_MINIMO_FONTE_CURTA  # 250
        _min_pars = 3
    else:
        _min_chars = TEXTO_MINIMO_CHARS   # 500
        _min_pars = 4

    def _chk(cond: bool, msg: str):
        if not cond:
            erros.append(msg)

    # ── Campos obrigatórios ────────────────────────────────────────────────────
    obrigatorios = ["titulo_seo", "subtitulo_curto", "retranca", "titulo_capa",
                    "tags", "legenda_curta", "corpo_materia"]
    for campo in obrigatorios:
        v = article.get(campo, "")
        _chk(isinstance(v, str) and v.strip(),
             f"Campo obrigatório ausente ou vazio: {campo}")

    # ── Limites de caracteres ──────────────────────────────────────────────────
    titulo = article.get("titulo_seo", "")
    _chk(LIMITE_TITULO_SEO_MIN <= len(titulo) <= LIMITE_TITULO_SEO,
         f"titulo_seo deve ter {LIMITE_TITULO_SEO_MIN}-{LIMITE_TITULO_SEO} chars (tem {len(titulo)})")

    capa = article.get("titulo_capa", "")
    _chk(LIMITE_TITULO_CAPA_MIN <= len(capa) <= LIMITE_TITULO_CAPA,
         f"titulo_capa deve ter {LIMITE_TITULO_CAPA_MIN}-{LIMITE_TITULO_CAPA} chars (tem {len(capa)})")

    subtitulo = article.get("subtitulo_curto", "")
    if subtitulo:
        _chk(len(subtitulo) <= LIMITE_SUBTITULO,
             f"subtitulo_curto excede {LIMITE_SUBTITULO} chars (tem {len(subtitulo)})")

    legenda = article.get("legenda_curta", "")
    if legenda:
        _chk(len(legenda) <= LIMITE_LEGENDA,
             f"legenda_curta excede {LIMITE_LEGENDA} chars (tem {len(legenda)})")

    # ── Retranca ───────────────────────────────────────────────────────────────
    retranca = article.get("retranca", "")
    palavras_retranca = [p for p in retranca.strip().split() if p]
    _chk(1 <= len(palavras_retranca) <= 3,
         f"retranca deve ter 1-3 palavras (tem {len(palavras_retranca)}): '{retranca}'")

    # ── Tags ───────────────────────────────────────────────────────────────────
    tags_str = article.get("tags", "")
    if tags_str:
        tags_lista = [t.strip() for t in tags_str.split(",") if t.strip()]
        _chk(TAGS_MIN <= len(tags_lista) <= TAGS_MAX,
             f"tags deve ter {TAGS_MIN}-{TAGS_MAX} itens (tem {len(tags_lista)})")

    # ── Corpo da matéria ───────────────────────────────────────────────────────
    corpo = article.get("corpo_materia", "")
    _chk(len(corpo) >= _min_chars,
         f"corpo_materia muito curto ({len(corpo)} chars, mínimo proporcional {_min_chars} "
         f"para fonte de {_tamanho_fonte} chars)")

    paragrafos = [p.strip() for p in corpo.split("\n\n") if p.strip()]
    _chk(len(paragrafos) >= _min_pars,
         f"corpo_materia precisa de ≥{_min_pars} parágrafos com \\n\\n "
         f"para fonte de {_tamanho_fonte} chars (tem {len(paragrafos)})")

    # ── Frases de expansão artificial (unsupported claims) ────────────────────
    corpo_lower = corpo.lower()
    _unsupported = [f for f in FRASES_UNSUPPORTED_CLAIMS if f in corpo_lower]
    if _unsupported:
        erros.append(
            f"Frases de expansão artificial não suportadas ({len(_unsupported)}): " +
            "; ".join(f'"{f}"' for f in _unsupported[:3]) +
            " — remova ou use apenas se explicitamente presente na fonte."
        )

    # ── Travessão ──────────────────────────────────────────────────────────────
    campos_travessao = ["titulo_seo", "subtitulo_curto", "titulo_capa", "corpo_materia", "legenda_curta"]
    for campo_t in campos_travessao:
        if re.search(r"[—–]", article.get(campo_t, "") or ""):
            erros.append(f"Travessão proibido em '{campo_t}'")

    # ── Expressões proibidas ───────────────────────────────────────────────────
    titulo_lower = titulo.lower()
    exprs_achadas = [expr for expr in EXPRESSOES_PROIBIDAS
                     if expr in corpo_lower or expr in titulo_lower]
    if exprs_achadas:
        erros.append(
            f"Expressões proibidas ({len(exprs_achadas)}): " +
            "; ".join(exprs_achadas[:5])
        )

    # ── Frases genéricas ───────────────────────────────────────────────────────
    genericas = [f for f in FRASES_GENERICAS_PROIBIDAS if f in corpo_lower]
    if genericas:
        erros.append(
            f"Frases genéricas sem dado concreto ({len(genericas)}): " +
            "; ".join(f'"{f}"' for f in genericas[:3])
        )

    # ── Dados essenciais da fonte ──────────────────────────────────────────────
    def _gerar_sigla(nome: str) -> str:
        """Gera sigla de 2-5 letras maiúsculas a partir do nome de uma entidade."""
        partes = re.findall(r'\b[A-ZÁÀÃÂÉÊÍÓÔÕÚÜÇ][a-záàãâéêíóôõúüç]{1,}', nome)
        sigla = "".join(p[0] for p in partes if p[0].isupper())
        return sigla if len(sigla) >= 2 else ""

    def _aparece(texto_busca: str) -> bool:
        if not texto_busca:
            return True

        busca_lower = texto_busca.lower()

        # Normaliza caracteres especiais para comparação (ex: º → o, § → s)
        def _norm(s: str) -> str:
            import unicodedata
            return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()

        corpo_norm = _norm(corpo)
        busca_norm = _norm(texto_busca)

        # 1. Busca direta normalizada (resolve º, § e acentos)
        if busca_norm in corpo_norm:
            return True

        # 2. Busca por fragmentos numéricos (ex: "17,2%", "39 horas", "artigo 7")
        numeros = re.findall(
            r"\d+[,\.]?\d*\s*(?:%|horas?|anos?|dias?|mil|milhões?|reais?|R\$)?",
            texto_busca.lower()
        )
        for num in numeros:
            num_c = num.strip()
            if len(num_c) >= 2 and num_c in corpo_lower:
                return True

        # 3. Para artigos de lei: verifica se o número do artigo aparece no corpo
        #    Ex: "artigo 7º, inciso XIII" → procura "artigo 7" no corpo
        m_artigo = re.search(r"art(?:igo)?\.?\s*(\d+)", busca_lower, re.IGNORECASE)
        if m_artigo:
            num_art = m_artigo.group(1)
            if f"artigo {num_art}" in corpo_lower or f"art. {num_art}" in corpo_lower or f"art {num_art}" in corpo_lower:
                return True
            # Também tenta normalizado
            if f"artigo {num_art}" in corpo_norm:
                return True

        # 4. Para estudos/entidades: verifica sigla (ex: FGV para Fundação Getulio Vargas)
        sigla = _gerar_sigla(texto_busca)
        if sigla and len(sigla) >= 2:
            # Verifica se a sigla aparece no corpo (ex: "FGV", "OAB", "TJRJ")
            if re.search(r"\b" + re.escape(sigla) + r"\b", corpo):
                return True

        # 5. Busca por palavras-chave com 4+ letras
        palavras = [p for p in re.findall(r"\b\w{4,}\b", busca_lower) if len(p) >= 4]
        if not palavras:
            return bool(numeros)
        presentes = sum(1 for p in palavras if p in corpo_lower)
        return presentes >= max(1, len(palavras) * 0.5)

    ausentes: list[str] = []

    for dado in (ef.get("dados_numericos") or []):
        if not _aparece(dado):
            ausentes.append(f"Número/dado ausente: {dado}")

    for estudo in (ef.get("estudos_citados") or []):
        if not _aparece(estudo):
            ausentes.append(f"Estudo ausente: {estudo}")

    for artigo in (ef.get("artigos_lei_citados") or []):
        if not _aparece(artigo):
            ausentes.append(f"Artigo de lei ausente: {artigo}")

    for argumento in (ef.get("argumentos_centrais") or [])[:4]:
        if not _aparece(argumento):
            ausentes.append(f"Argumento central ausente: {argumento}")

    impactos = ef.get("impactos_citados") or []
    if len(impactos) >= 2:
        ausentes_imp = [i for i in impactos if not _aparece(i)]
        if len(ausentes_imp) > len(impactos) // 2:
            ausentes.append(
                f"Impactos centrais ausentes ({len(ausentes_imp)}/{len(impactos)}): " +
                "; ".join(ausentes_imp[:3])
            )

    for item in ausentes:
        erros.append(f"[SUBSTÂNCIA] {item}")

    # ── Modelo correto ─────────────────────────────────────────────────────────
    _chk("gpt-4.1" in model_name.lower() or "gpt-4o" in model_name.lower(),
         f"Modelo deve ser gpt-4.1-mini (configurado: '{model_name}')")

    return len(erros) == 0, erros


# ═══════════════════════════════════════════════════════════════════════════════
# SEÇÃO 8: REVISÃO AUTOMÁTICA DIRIGIDA
# ═══════════════════════════════════════════════════════════════════════════════

def revise_article_if_needed(
    article: dict,
    source_text: str,
    validation_errors: list[str],
    essential_facts: dict,
    client: "OpenAI",
    model: str = MODELO_PADRAO,
) -> dict:
    """
    reviseArticleIfNeeded: revisão automática dirigida (apenas uma vez).

    Corrige APENAS os campos com problema.
    Retorna o artigo revisado (mesmo formato JSON).
    """
    corpo_atual = article.get("corpo_materia", "")
    erros_substancia  = [e for e in validation_errors if "[SUBSTÂNCIA]" in e]
    erros_estruturais = [e for e in validation_errors if "[SUBSTÂNCIA]" not in e]

    # Resumo dos fatos essenciais para a revisão
    _ef_linhas: list[str] = []
    for k, v in essential_facts.items():
        if isinstance(v, list) and v:
            _ef_linhas.append(f"{k}: {', '.join(str(x) for x in v[:6])}")
        elif isinstance(v, str) and v:
            _ef_linhas.append(f"{k}: {v}")

    prompt_revisao = f"""
Você é o editor revisor do Portal Ururau. Esta é a ÚNICA revisão automática permitida.
Corrija apenas o que está errado. Não reescreva o que está certo. Preserve o tom jornalístico profissional.

══════════════════════════════════════════════
MATÉRIA ATUAL (corpo)
══════════════════════════════════════════════
{corpo_atual}

══════════════════════════════════════════════
FONTE ORIGINAL
══════════════════════════════════════════════
{source_text[:5000]}

══════════════════════════════════════════════
ERROS ESTRUTURAIS A CORRIGIR
══════════════════════════════════════════════
{chr(10).join(f"• {e}" for e in erros_estruturais) if erros_estruturais else "Nenhum."}

══════════════════════════════════════════════
DADOS ESSENCIAIS AUSENTES (INCLUIR TODOS)
══════════════════════════════════════════════
{chr(10).join(f"• {e}" for e in erros_substancia) if erros_substancia else "Nenhum."}

══════════════════════════════════════════════
FATOS ESSENCIAIS DA FONTE
══════════════════════════════════════════════
{chr(10).join(f"• {f}" for f in _ef_linhas[:20]) if _ef_linhas else "Ver fonte acima."}

══════════════════════════════════════════════
INSTRUÇÕES
══════════════════════════════════════════════
1. Inclua TODOS os dados essenciais ausentes listados acima.
2. Corrija TODOS os erros estruturais listados.
3. Não invente informação nova além do que está na fonte.
4. Não use travessão (— ou –).
5. Não use expressões proibidas.
6. Não copie a fonte literalmente.
7. Separe parágrafos com \\n\\n.
8. Preserve os dados já corretos.
9. Pode adicionar parágrafos para incluir dados ausentes (máximo 10 no total).
10. Mantenha tom jornalístico profissional.

Retorne APENAS JSON com o campo corpo_materia corrigido:
{{"corpo_materia": "texto revisado aqui..."}}
""".strip()

    try:
        resposta = client.responses.create(
            model=model,
            instructions=SYSTEM_PROMPT_EDITORIAL_URURAU,
            input=prompt_revisao,
            temperature=0.2,
        )
        bruto = resposta.output_text.strip()
        bruto = re.sub(r"```(?:json)?", "", bruto).replace("```", "").strip()
        inicio = bruto.find("{")
        fim = bruto.rfind("}") + 1
        if inicio >= 0 and fim > inicio:
            revisado = json.loads(bruto[inicio:fim])
            corpo_novo = revisado.get("corpo_materia", "")
            if corpo_novo and len(corpo_novo) >= len(corpo_atual) * 0.8:
                corpo_novo = _corrigir_paragrafos(_remover_travessao(corpo_novo))
                article = dict(article)
                article["corpo_materia"] = corpo_novo
                article["conteudo"]      = corpo_novo
                article["texto_final"]   = corpo_novo
    except Exception as e:
        print(f"[AGENTE] Erro na revisão automática: {e}")

    return article


# ═══════════════════════════════════════════════════════════════════════════════
# SEÇÃO 9: PIPELINE PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════

def generate_article(
    source_text: str,
    client: "OpenAI",
    model: str = MODELO_PADRAO,
    canal: str = "Cidades",
    title: str = "",
    summary: str = "",
    options: dict | None = None,
) -> ResultadoAgente:
    """
    generate_article / generateArticleWithEditorialAgent: pipeline completo.

    Fluxo:
      1. Extrai fatos essenciais da fonte (via IA)
      2. Monta user prompt com dados obrigatórios
      3. Chama modelo com SYSTEM_PROMPT_EDITORIAL_URURAU como system message
      4. Extrai e limpa o JSON da resposta
      5. Valida estrutura + substância
      6. Se aprovado → status "aprovado"
      7. Se reprovado → revisão automática (única vez)
      8. Re-valida
      9. Se aprovado após revisão → status "revisado"
      10. Se ainda reprovado → status "rascunho" + lista de erros
      NUNCA publica artigo reprovado.
      SEMPRE usa SYSTEM_PROMPT_EDITORIAL_URURAU.
    """
    ts = datetime.now(TZ_BR).strftime("%Y-%m-%d %H:%M:%S")
    log: list[str] = []
    resultado = ResultadoAgente(timestamp=ts, modelo_usado=model)

    log.append(f"[{ts}] AGENTE EDITORIAL URURAU — INICIADO")
    log.append(f"[AGENTE] modelo={model} | canal={canal} | system_prompt={len(SYSTEM_PROMPT_EDITORIAL_URURAU)} chars")

    # ── Etapa 1: Extração de fatos essenciais ─────────────────────────────────
    log.append("[AGENTE] Etapa 1: Extraindo fatos essenciais da fonte...")
    fatos = extract_essential_facts(
        source_text=source_text, title=title, summary=summary,
        client=client, model=model,
    )
    resultado.fatos_essenciais = fatos

    _ext = [f"{k}({len(v)})" for k, v in fatos.items()
            if isinstance(v, list) and v and k in
            ["dados_numericos", "estudos_citados", "artigos_lei_citados",
             "impactos_citados", "argumentos_centrais"]]
    log.append(f"[AGENTE] Fatos extraídos: {', '.join(_ext) if _ext else 'extração básica'} | fonte={fatos.get('fonte','local')}")

    # ── Etapa 2: Monta user prompt ────────────────────────────────────────────
    log.append("[AGENTE] Etapa 2: Montando prompt com dados obrigatórios...")
    user_prompt = build_article_prompt(
        source_text=source_text,
        essential_facts=fatos,
        canal=canal,
        options=options,
    )
    log.append(f"[AGENTE] User prompt: {len(user_prompt)} chars")

    # ── Etapa 3: Chamada à API ────────────────────────────────────────────────
    log.append(f"[AGENTE] Etapa 3: Chamando API OpenAI (model={model}) | SYSTEM_PROMPT_EDITORIAL_URURAU: ENVIADO ✓")
    dados_brutos: dict = {}

    try:
        resposta = client.responses.create(
            model=model,
            instructions=SYSTEM_PROMPT_EDITORIAL_URURAU,
            input=user_prompt,
            temperature=0.3,
        )
        texto_resposta = resposta.output_text.strip()
        log.append(f"[AGENTE] Resposta recebida: {len(texto_resposta)} chars")

        bruto = re.sub(r"```(?:json)?", "", texto_resposta).replace("```", "").strip()
        inicio = bruto.find("{")
        fim = bruto.rfind("}") + 1
        if inicio >= 0 and fim > inicio:
            dados_brutos = json.loads(bruto[inicio:fim])
        else:
            raise ValueError(f"Nenhum JSON na resposta: {bruto[:200]}")

    except Exception as e:
        log.append(f"[AGENTE] ERRO na chamada à API: {e}")
        resultado.log = log
        resultado.status = "falha"
        resultado.erros_validacao = [f"Erro na geração: {e}"]
        return resultado

    # ── Etapa 4: Limpeza automática ───────────────────────────────────────────
    log.append("[AGENTE] Etapa 4: Aplicando limpeza automática...")
    dados_limpos = _limpar_artigo(dados_brutos)

    # ── Etapa 5: Validação ────────────────────────────────────────────────────
    _tamanho_fonte_agente = len(source_text or "")
    log.append(f"[AGENTE] Etapa 5: Validando artigo gerado (tamanho_fonte={_tamanho_fonte_agente} chars)...")
    aprovado, erros = validate_article_output(
        article=dados_limpos, source_text=source_text,
        essential_facts=fatos, model_name=model,
        tamanho_fonte=_tamanho_fonte_agente,
    )

    corpo  = dados_limpos.get("corpo_materia", "")
    pars   = [p for p in corpo.split("\n\n") if p.strip()]
    n_tags = len([t for t in dados_limpos.get("tags", "").split(",") if t.strip()])
    exprs  = [e for e in EXPRESSOES_PROIBIDAS if e in corpo.lower() or e in dados_limpos.get("titulo_seo", "").lower()]
    resultado.expressoes_encontradas = exprs

    log.append(
        f"[AGENTE] Diagnóstico: titulo_seo={len(dados_limpos.get('titulo_seo',''))}c | "
        f"titulo_capa={len(dados_limpos.get('titulo_capa',''))}c | "
        f"retranca='{dados_limpos.get('retranca','')}' | tags={n_tags} | "
        f"corpo={len(corpo)}c | pars={len(pars)} | expressoes_proibidas={len(exprs)}"
    )
    log.append(f"[AGENTE] Validação 1ª: {'APROVADO ✓' if aprovado else f'REPROVADO — {len(erros)} erro(s)'}")
    if not aprovado:
        for err in erros[:8]:
            log.append(f"[AGENTE]   ✗ {err}")

    if aprovado:
        dados_limpos["status_validacao"] = "aprovado"
        dados_limpos["erros_validacao"]  = []
        resultado.sucesso   = True
        resultado.aprovado  = True
        resultado.status    = "aprovado"
        resultado.dados     = dados_limpos
        resultado.erros_validacao = []
        log.append("[AGENTE] Resultado: APROVADO na 1ª geração ✓")
    else:
        # ── Etapa 6: Revisão automática (uma única vez) ───────────────────────
        log.append(f"[AGENTE] Etapa 6: Revisão automática — {len(erros)} erro(s)...")
        dados_revisados = revise_article_if_needed(
            article=dados_limpos, source_text=source_text,
            validation_errors=erros, essential_facts=fatos,
            client=client, model=model,
        )
        dados_revisados = _limpar_artigo(dados_revisados)
        resultado.revisao_aplicada = True

        # ── Etapa 7: Re-validação ─────────────────────────────────────────────
        log.append("[AGENTE] Etapa 7: Re-validando após revisão automática...")
        aprovado2, erros2 = validate_article_output(
            article=dados_revisados, source_text=source_text,
            essential_facts=fatos, model_name=model,
            tamanho_fonte=_tamanho_fonte_agente,
        )
        log.append(f"[AGENTE] Validação 2ª: {'APROVADO ✓' if aprovado2 else f'REPROVADO — {len(erros2)} erro(s)'}")

        if aprovado2:
            dados_revisados["status_validacao"] = "aprovado_apos_revisao"
            dados_revisados["erros_validacao"]  = []
            resultado.sucesso   = True
            resultado.aprovado  = True
            resultado.status    = "revisado"
            resultado.dados     = dados_revisados
            resultado.erros_validacao = []
            log.append("[AGENTE] Resultado: APROVADO após revisão automática ✓")
        else:
            dados_revisados["status_validacao"] = "rascunho"
            dados_revisados["erros_validacao"]  = erros2
            resultado.sucesso      = False
            resultado.aprovado     = False
            resultado.status       = "rascunho"
            resultado.dados        = dados_revisados
            resultado.erros_validacao = erros2
            resultado.dados_ausentes  = [e for e in erros2 if "[SUBSTÂNCIA]" in e]
            log.append("[AGENTE] Resultado: SALVO COMO RASCUNHO — requer revisão humana")
            for err in erros2[:6]:
                log.append(f"[AGENTE]   ✗ {err}")

    # ── Log final ─────────────────────────────────────────────────────────────
    log.append(
        f"[AGENTE] CONCLUÍDO | status={resultado.status} | "
        f"revisao={resultado.revisao_aplicada} | modelo={model}"
    )
    resultado.log = log

    # Sincroniza aliases para compatibilidade com pipeline existente
    if resultado.dados:
        _d = resultado.dados
        _d.setdefault("conteudo",    _d.get("corpo_materia", ""))
        _d.setdefault("texto_final", _d.get("corpo_materia", ""))
        _d.setdefault("subtitulo",   _d.get("subtitulo_curto", ""))
        _d.setdefault("legenda",     _d.get("legenda_curta", ""))
        _d.setdefault("titulo",      _d.get("titulo_seo", ""))

    return resultado


# ═══════════════════════════════════════════════════════════════════════════════
# SEÇÃO 10: INTERFACE DE INTEGRAÇÃO COM O PIPELINE EXISTENTE
# ═══════════════════════════════════════════════════════════════════════════════

def gerar_via_agente(
    pauta: dict,
    client: "OpenAI",
    modelo: str,
    canal: str,
    modo_operacional: str = "painel",
) -> dict:
    """
    Ponto de integração: recebe dict de pauta no formato Ururau e retorna
    dict de dados no formato esperado por redacao.py (com todos os aliases).

    Uso em redacao.py:
        from ururau.agents.agente_editorial_ururau import gerar_via_agente
        dados = gerar_via_agente(pauta_dict, client, modelo, canal)
    """
    source_text = "\n\n".join(filter(None, [
        pauta.get("texto_fonte") or "",
        pauta.get("dossie") or "",
        pauta.get("resumo_origem") or "",
    ])).strip()

    resultado = generate_article(
        source_text=source_text,
        client=client,
        model=modelo,
        canal=canal,
        title=pauta.get("titulo_origem", ""),
        summary=pauta.get("resumo_origem", ""),
        options={"model": modelo, "tipo": "materia"},
    )

    for linha in resultado.log:
        print(linha)

    dados = resultado.dados or {}

    # Metadados de auditoria para compatibilidade com ResultadoPipeline
    dados["_agente_status"]  = resultado.status
    dados["_agente_aprovado"] = resultado.aprovado
    dados["_agente_erros"]   = resultado.erros_validacao[:5]
    dados["_agente_revisao"] = resultado.revisao_aplicada
    dados["_agente_ausentes"] = resultado.dados_ausentes
    dados["_modelo_usado"]   = resultado.modelo_usado

    dados["status_publicacao_sugerido"] = (
        dados.get("status_publicacao_sugerido") or "salvar_rascunho"
    ) if resultado.aprovado else "bloquear"

    return dados
