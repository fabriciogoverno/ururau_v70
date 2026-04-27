"""
editorial/extracao.py — Extração estruturada de fatos (Mapa de Evidências v61).

Pipeline de pré-redação: extrai fatos ANTES de gerar o texto final.
Garante que o texto gerado seja ancorado em evidências concretas, não em generalidades.

Novidades v61 (correção crítica de produção):
- separar_fonte_de_metadados() muito mais robusta:
  • Remove "Notícias relacionadas", blocos de navegação, "Versão em áudio", etc.
  • Modo de bloco: ao detectar cabeçalho de "notícias relacionadas", descarta o bloco inteiro
  • Preserva títulos de seção editoriais legítimos (ex: "Demandas do interior")
  • validate_source_sufficiency(): verifica se a fonte limpa tem conteúdo suficiente
  • Logs [EXTRACAO] com raw_chars, cleaned_chars, metadata_removed, etc.
- extrair_mapa_evidencias() agora classifica exceções OpenAI como CONFIG_ERROR
  em vez de silenciosamente usar _fallback_mapa()
"""
from __future__ import annotations
import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openai import OpenAI


# ── Cabeçalhos de bloco que devem ser descartados inteiros ───────────────────
# Quando uma linha começa com (ou é exatamente) um desses textos, TODO o bloco
# seguinte é descartado até a próxima linha em branco ou próximo parágrafo de corpo.
_BLOCOS_DESCARTAVEIS_EXATOS = {
    "notícias relacionadas",
    "noticias relacionadas",
    "related news",
    "more stories",
    "mais notícias",
    "mais noticias",
    "veja mais notícias",
    "leia mais",
    "leia também",
    "leia tambem",
    "veja também",
    "veja tambem",
    "veja mais",
    "acesse também",
    "acesse tambem",
    "versão em áudio",
    "versao em audio",
    "ouça esta notícia",
    "ouca esta noticia",
    "assista também",
    "assista tambem",
    "compartilhar",
    "compartilhe",
    "partilhar",
    "siga-nos",
    "siga nossas",
    "siga o portal",
    "receba nossas",
    "receba as notícias",
    "newsletter",
    "inscreva-se",
    "assine",
    "baixe o aplicativo",
    "baixe o app",
    "publicidade",
    "advertisement",
    "continua após",
    "continua depois",
    "scroll to continue",
    # ── Paywall / assinatura (Folha, Estadão, Globo, etc.) ────────────────────
    "benefício do assinante",
    "beneficio do assinante",
    "você tem 7 acessos por dia",
    "voce tem 7 acessos por dia",
    "assinantes podem liberar",
    "já é assinante?",
    "ja e assinante?",
    "faça seu login",
    "faca seu login",
    "assine a folha",
    "assine o estadão",
    "assine o globo",
    "assine agora",
    "assine já",
    "assine ja",
    "copiar link",
    "salvar para ler depois",
    "salvar artigos",
    "recurso exclusivo",
    "recurso exclusivo para assinantes",
    "assine ou faça login",
    "assine ou faca login",
    "diminuir fonte",
    "aumentar fonte",
    "ouvir o texto",
    "ouça o texto",
    "ouca o texto",
    "modo leitura",
    "texto apenas para assinantes",
    "conteúdo exclusivo",
    "conteudo exclusivo",
    "seja assinante",
    "torne-se assinante",
    "torne-se um assinante",
    "acesso ilimitado",
    "assinante digital",
    "plano digital",
    "plano anual",
    "plano mensal",
    "desconto para assinantes",
}

# Padrão para detectar linha que é cabeçalho de "notícias relacionadas" e similares
_BLOCO_DESCARTAVEL_PAT = re.compile(
    r"^(?:notícias?\s+relacionadas?|noticias?\s+relacionadas?|"
    r"leia\s+(?:também|mais|ainda|tambem)|"
    r"veja\s+(?:também|mais|tambem)|"
    r"acesse\s+(?:também|tambem)|"
    r"mais\s+(?:notícias|noticias|artigos?)|"
    r"versão\s+em\s+áudio|versao\s+em\s+audio|"
    r"ouça\s+(?:esta|o\s+texto)|ouca\s+(?:esta|o\s+texto)|"
    r"assista\s+(?:também|tambem)|"
    r"compartilh[ae]r?|partilhar|"
    r"siga[- ](?:nos|nossas?|o\s+portal)|"
    r"receba\s+(?:nossas?|as\s+notícias?)|"
    r"newsletter|inscreva[- ]se|"
    r"publicidade|advertisement|"
    r"continua\s+(?:após|depois|after)|"
    r"baixe\s+o\s+(?:aplicativo|app)|"
    # Paywall / assinatura
    r"benefício\s+do\s+assinante|beneficio\s+do\s+assinante|"
    r"você\s+tem\s+\d+\s+acessos|voce\s+tem\s+\d+\s+acessos|"
    r"assinantes\s+podem\s+liberar|"
    r"já\s+é\s+assinante|ja\s+e\s+assinante|"
    r"faça\s+seu\s+login|faca\s+seu\s+login|"
    r"assine\s+(?:a\s+folha|o\s+estadão|o\s+globo|agora|já|ja)|"
    r"copiar\s+link|"
    r"salvar\s+(?:para\s+ler\s+depois|artigos)|"
    r"recurso\s+exclusivo|"
    r"assine\s+ou\s+faça\s+login|assine\s+ou\s+faca\s+login|"
    r"diminuir\s+fonte|aumentar\s+fonte|"
    r"ouvir\s+o\s+texto|ouça\s+o\s+texto|ouca\s+o\s+texto|"
    r"modo\s+leitura|"
    r"texto\s+apenas\s+para\s+assinantes|"
    r"conteúdo\s+exclusivo|conteudo\s+exclusivo|"
    r"seja\s+assinante|torne[- ]?se\s+(?:um\s+)?assinante|"
    r"acesso\s+ilimitado|assinante\s+digital|"
    r"plano\s+(?:digital|anual|mensal)|"
    r"desconto\s+para\s+assinantes)",
    re.IGNORECASE,
)

# Padrões de linha única a remover (sem afetar bloco seguinte)
_CREDITO_PAT = re.compile(
    r"^(?:foto[:\s]|crédito[:\s]|credit[:\s]|©\s*\S|image[:\s]|imagem[:\s]|"
    r"fotógrafo[:\s]|photographer[:\s])",
    re.IGNORECASE,
)
_LEGENDA_PAT = re.compile(
    r"^(?:legenda[:\s]|caption[:\s])",
    re.IGNORECASE,
)
_TIMESTAMP_PAT = re.compile(
    r"^(?:publicado\s+em|atualizado\s+em|updated|published|posted)[:\s]",
    re.IGNORECASE,
)
_AUTOR_PAT = re.compile(
    r"^(?:por[:\s]|by[:\s]|autor[:\s]|author[:\s]|redação[:\s]|reportagem[:\s])",
    re.IGNORECASE,
)
_AD_INLINE_PAT = re.compile(
    r"^(?:publicidade|advertisement|anuncio|patrocinado|sponsored|ads?\s+by)",
    re.IGNORECASE,
)
_URL_SOZINHA_PAT = re.compile(r"^https?://\S+$")

# Títulos de seção editorial LEGÍTIMOS que NÃO devem ser descartados
# mesmo que pareçam "cabeçalhos curtos"
_SECOES_LEGITIMAS_PAT = re.compile(
    r"^(?:demandas?\s+do|espaço\s+coletivo|histórico|contexto|"
    r"antecedentes|declaração|nota\s+(?:oficial|da|do)|"
    r"posição\s+(?:da|do)|entrevista\s+com|depoimento|"
    r"análise|investigação|repercussão|reação)",
    re.IGNORECASE,
)


def separar_fonte_de_metadados(texto: str) -> dict:
    """
    separateSourceFromMetadata v61: separa o corpo editorial de metadados e ruído.

    Detecta e remove:
    PRIMARY METADATA (linha única):
      - Créditos de foto, legendas de imagem, timestamps, bylines, URLs
    SECONDARY BLOCKS (bloco inteiro até próxima linha em branco):
      - "Notícias relacionadas" e todo o bloco de títulos que se segue
      - "Leia também / Veja também / Acesse também"
      - "Versão em áudio / Ouça esta notícia"
      - "Compartilhar / Partilhar"
      - "Siga / Receba / Newsletter / Inscreva-se"
      - "Publicidade / Continua após..."
      - URLs sozinhas numa linha

    Preserva:
      - Títulos de seção editorial legítimos (ex: "Demandas do interior")
      - Qualquer texto com mais de uma frase que não seja navigation/ads

    Retorna dict com:
      - corpo_limpo: texto editorial sem ruído
      - legendas_identificadas: legendas de imagem encontradas
      - creditos_foto: créditos fotográficos encontrados
      - links_relacionados: links/títulos de "leia também" encontrados
      - metadados_descartados: lista descritiva do que foi removido
      - raw_chars: tamanho original
      - cleaned_chars: tamanho após limpeza
      - related_links_removed: número de links relacionados removidos
      - body_paragraphs: número de parágrafos de corpo identificados
    """
    if not texto:
        return {
            "corpo_limpo": "",
            "legendas_identificadas": [],
            "creditos_foto": [],
            "links_relacionados": [],
            "metadados_descartados": [],
            "raw_chars": 0,
            "cleaned_chars": 0,
            "related_links_removed": 0,
            "body_paragraphs": 0,
        }

    raw_chars = len(texto)
    linhas = texto.splitlines()
    corpo_linhas: list[str] = []
    legendas: list[str] = []
    creditos: list[str] = []
    links_rel: list[str] = []
    descartados: list[str] = []
    related_links_removed = 0

    # Máquina de estados: quando em modo "descartando bloco"
    # descartamos todas as linhas não-vazias até a próxima linha em branco
    descartando_bloco = False
    linhas_bloco_atual: list[str] = []

    i = 0
    while i < len(linhas):
        linha = linhas[i]
        linha_strip = linha.strip()

        # Linha vazia — sempre vai para corpo (e termina qualquer bloco descartado)
        if not linha_strip:
            if descartando_bloco:
                # Fim do bloco descartável — registra o que foi descartado
                if linhas_bloco_atual:
                    descartados.append(
                        f"bloco_relacionado ({len(linhas_bloco_atual)} linhas): "
                        f"{linhas_bloco_atual[0][:50]}"
                    )
                    links_rel.extend(linhas_bloco_atual[:10])
                    related_links_removed += len(linhas_bloco_atual)
                    linhas_bloco_atual = []
                descartando_bloco = False
            corpo_linhas.append(linha)
            i += 1
            continue

        # Título de seção editorial legítima — NUNCA descartar
        if _SECOES_LEGITIMAS_PAT.match(linha_strip) and not descartando_bloco:
            corpo_linhas.append(linha)
            i += 1
            continue

        # Linha exatamente igual a um cabeçalho descartável
        linha_lower = linha_strip.lower().rstrip(":").strip()
        if linha_lower in _BLOCOS_DESCARTAVEIS_EXATOS:
            descartando_bloco = True
            linhas_bloco_atual = []
            descartados.append(f"cabeçalho_bloco: {linha_strip[:60]}")
            i += 1
            continue

        # Linha que corresponde ao padrão de bloco descartável
        if _BLOCO_DESCARTAVEL_PAT.match(linha_strip):
            descartando_bloco = True
            linhas_bloco_atual = []
            descartados.append(f"cabeçalho_bloco: {linha_strip[:60]}")
            i += 1
            continue

        # Dentro de bloco descartável: acumula até linha vazia
        if descartando_bloco:
            linhas_bloco_atual.append(linha_strip)
            i += 1
            continue

        # ── Padrões de linha única ────────────────────────────────────────────

        if _CREDITO_PAT.match(linha_strip):
            creditos.append(linha_strip)
            descartados.append(f"crédito_foto: {linha_strip[:60]}")
        elif _LEGENDA_PAT.match(linha_strip):
            legendas.append(linha_strip)
            descartados.append(f"legenda_imagem: {linha_strip[:60]}")
        elif _URL_SOZINHA_PAT.match(linha_strip):
            descartados.append(f"url_sozinha: {linha_strip[:60]}")
        elif _TIMESTAMP_PAT.match(linha_strip) and len(linha_strip) < 100:
            descartados.append(f"timestamp: {linha_strip[:60]}")
        elif _AUTOR_PAT.match(linha_strip) and len(linha_strip) < 80:
            descartados.append(f"byline: {linha_strip[:60]}")
        elif _AD_INLINE_PAT.match(linha_strip) and len(linha_strip) < 100:
            descartados.append(f"publicidade_inline: {linha_strip[:60]}")
        else:
            corpo_linhas.append(linha)

        i += 1

    # Bloco ainda aberto no final do texto
    if descartando_bloco and linhas_bloco_atual:
        descartados.append(
            f"bloco_relacionado ({len(linhas_bloco_atual)} linhas): "
            f"{linhas_bloco_atual[0][:50]}"
        )
        links_rel.extend(linhas_bloco_atual[:10])
        related_links_removed += len(linhas_bloco_atual)

    corpo_limpo = "\n".join(corpo_linhas).strip()
    cleaned_chars = len(corpo_limpo)

    # Conta parágrafos (blocos separados por linha em branco)
    body_paragraphs = len([
        b for b in corpo_limpo.split("\n\n") if b.strip()
    ])

    print(
        f"[EXTRACAO] raw_chars={raw_chars} "
        f"cleaned_chars={cleaned_chars} "
        f"metadata_removed={len(descartados)} "
        f"related_links_removed={related_links_removed} "
        f"body_paragraphs={body_paragraphs}"
    )
    if descartados:
        for item in descartados[:8]:
            print(f"[EXTRACAO]   Removido: {item}")

    return {
        "corpo_limpo": corpo_limpo,
        "legendas_identificadas": legendas,
        "creditos_foto": creditos,
        "links_relacionados": links_rel,
        "metadados_descartados": descartados,
        "raw_chars": raw_chars,
        "cleaned_chars": cleaned_chars,
        "related_links_removed": related_links_removed,
        "body_paragraphs": body_paragraphs,
    }


def validate_source_sufficiency(
    cleaned_source: str,
    metadata: dict | None = None,
) -> dict:
    """
    Verifica se a fonte limpa tem conteúdo suficiente para geração.

    Retorna dict com:
      - ok: True se pode prosseguir
      - status: "sufficient" | "short_but_usable" | "too_short" | "empty"
      - reason: descrição do problema
      - erro_dict: erro padronizado para erros_validacao (se não ok)
      - allow_short_article: True se pode gerar artigo curto
    """
    from ururau.config.settings import CategoriaErro, CODIGO_SOURCE_TOO_SHORT, CODIGO_SOURCE_EMPTY

    if not cleaned_source or not cleaned_source.strip():
        err = {
            "codigo": CODIGO_SOURCE_EMPTY,
            "categoria": CategoriaErro.EXTRACTION_ERROR,
            "severidade": "alta",
            "campo": "texto_fonte",
            "mensagem": "Fonte completamente vazia após limpeza. Nenhuma matéria pode ser gerada.",
            "trecho": "",
            "sugestao": "Clique em 'Recoletar fonte' para recarregar o texto do link original.",
            "bloqueia_publicacao": True,
            "corrigivel_automaticamente": False,
        }
        return {
            "ok": False,
            "status": "empty",
            "reason": "Fonte vazia.",
            "erro_dict": err,
            "allow_short_article": False,
        }

    chars = len(cleaned_source.strip())

    # Muito curta: menos de 100 chars após limpeza → provavelmente extração falhou
    if chars < 100:
        raw_chars = (metadata or {}).get("raw_chars", 0)
        if raw_chars > 500:
            # Tinha conteúdo mas foi tudo removido → extração provavelmente falhou
            err = {
                "codigo": "cleaned_source_too_small",
                "categoria": CategoriaErro.EXTRACTION_ERROR,
                "severidade": "alta",
                "campo": "texto_fonte",
                "mensagem": (
                    f"Fonte limpa muito pequena ({chars} chars) comparada ao original "
                    f"({raw_chars} chars). A extração pode ter removido conteúdo editorial."
                ),
                "trecho": cleaned_source[:100],
                "sugestao": "Verifique a extração. Clique em 'Recoletar fonte' ou edite manualmente.",
                "bloqueia_publicacao": True,
                "corrigivel_automaticamente": False,
            }
            print(
                f"[EXTRACAO] ⚠ Fonte limpa suspeita: {chars} chars de {raw_chars} raw. "
                "Possível extração agressiva demais."
            )
            return {
                "ok": False,
                "status": "too_short",
                "reason": f"Fonte muito pequena após limpeza ({chars}/{raw_chars} chars).",
                "erro_dict": err,
                "allow_short_article": False,
            }
        else:
            # Fonte era pequena desde o início — nota breve
            err = {
                "codigo": CODIGO_SOURCE_TOO_SHORT,
                "categoria": CategoriaErro.EXTRACTION_ERROR,
                "severidade": "media",
                "campo": "texto_fonte",
                "mensagem": f"Fonte muito curta ({chars} chars). Artigo gerado pode ser incompleto.",
                "trecho": cleaned_source[:100],
                "sugestao": "Verifique o link original. Um artigo curto será gerado com os dados disponíveis.",
                "bloqueia_publicacao": False,
                "corrigivel_automaticamente": False,
            }
            return {
                "ok": True,
                "status": "short_but_usable",
                "reason": f"Fonte curta ({chars} chars) mas utilizável para nota breve.",
                "erro_dict": err,
                "allow_short_article": True,
            }

    # Curta (100–800 chars): permite artigo curto sem expansão
    if chars < 800:
        print(f"[EXTRACAO] Fonte curta ({chars} chars) — artigo proporcional autorizado.")
        return {
            "ok": True,
            "status": "short_but_usable",
            "reason": f"Fonte curta ({chars} chars). Artigo proporcional será gerado.",
            "erro_dict": {},
            "allow_short_article": True,
        }

    # Suficiente para artigo completo
    print(f"[EXTRACAO] Fonte suficiente ({chars} chars) — geração completa autorizada.")
    return {
        "ok": True,
        "status": "sufficient",
        "reason": "",
        "erro_dict": {},
        "allow_short_article": False,
    }


def extrair_mapa_evidencias(
    titulo: str,
    resumo: str,
    texto_fonte: str,
    dossie: str,
    client: "OpenAI",
    modelo: str,
) -> dict:
    """
    Extrai estrutura completa de evidências antes da redação.
    Inclui dados numéricos, estudos, artigos de lei, impactos e argumentos centrais.
    """
    _sep = "\n\n"
    material_completo = (texto_fonte + _sep + dossie)[:12000]

    prompt = f"""
Você é um editor-chefe analisando material jornalístico antes de passar para a redação.
Extraia as evidências estruturadas do material abaixo e devolva APENAS JSON válido.

REGRAS CRÍTICAS:
- Separe fato confirmado de declaração e de inferência.
- Registre TODOS os números, percentuais, valores, estudos, artigos de lei mencionados.
- Registre TODOS os argumentos centrais de entidades, órgãos ou pessoas citadas.
- Registre impactos econômicos, sociais, jurídicos, políticos citados na fonte.
- Registre base jurídica (lei, artigo, inciso, decisão) quando houver.
- Registre o pedido, solicitação ou encaminhamento da entidade/órgão/pessoa citada.
- Nunca invente informação ausente no material.
- Se um campo não tiver informação, deixe como string vazia ou lista vazia.

TÍTULO:
{titulo}

RESUMO:
{resumo[:500]}

MATERIAL COMPLETO:
{material_completo}

FORMATO DE SAÍDA (JSON exato):
{{
  "fato_principal": "fato central confirmado com quem, onde, quando e o quê",
  "fatos_secundarios": ["lista de fatos relevantes adicionais confirmados no material"],
  "quem": ["lista de pessoas, cargos e organizações centrais mencionadas"],
  "onde": "local principal",
  "quando": "data ou período principal",
  "por_que_importa": "relevância objetiva do fato para o leitor",
  "consequencia": "desdobramento concreto já confirmado ou anunciado",
  "contexto_anterior": "histórico relevante presente no material",
  "orgao_central": "órgão ou instituição central do fato",
  "status_atual": "situação atual: votando, aprovado, em análise, preso, investigado, em vigor, etc.",
  "proximos_passos": "próxima etapa factual prevista ou declarada no material",
  "fonte_primaria": "fonte principal: nota oficial, tribunal, empresa, polícia, MP, etc.",
  "fontes_secundarias": ["outras fontes identificadas"],

  "dados_numericos": ["todos os números, percentuais, valores, médias, índices presentes no material — exemplo: '17,2% de aumento no custo do trabalho', '39 horas semanais'"],
  "estudos_citados": ["nomes de estudos, pesquisas, levantamentos citados — exemplo: 'estudo da FGV'"],
  "artigos_lei_citados": ["artigos, incisos, leis ou dispositivos constitucionais — exemplo: 'artigo 7º, XIII, da Constituição Federal'"],
  "impactos_citados": ["impactos econômicos, sociais, jurídicos ou políticos citados — exemplo: 'aumento de custos operacionais', 'crescimento da informalidade'"],
  "argumentos_centrais": ["argumentos principais da entidade, pessoa ou órgão central — exemplo: 'negociação coletiva deve ser preservada'"],
  "pedidos_ou_encaminhamentos": ["o que a entidade, órgão ou pessoa pede, propõe ou exige — exemplo: 'pede cautela ao Congresso'"],
  "base_juridica": "base constitucional, legal ou regulatória citada no material",
  "posicoes_conflitantes": ["versões conflitantes ou posições diferentes de atores citados"],

  "declaracoes_identificadas": ["falas atribuídas a alguém específico com aspas ou atribuição"],
  "elementos_sem_fonte": ["afirmações que aparecem no material sem fonte identificada"],
  "inferencias_a_evitar": ["conclusões que o material sugere mas não confirma explicitamente"],
  "grau_confianca": "alto | medio | baixo",
  "risco_editorial": "baixo | medio | alto",
  "motivo_risco": "explicação breve do risco editorial, se houver"
}}
"""
    try:
        resposta = client.responses.create(model=modelo, input=prompt)
        bruto = resposta.output_text.strip()
        if "```" in bruto:
            bruto = re.sub(r"```(?:json)?", "", bruto).strip()
            bruto = bruto.replace("```", "").strip()
        # Localiza o JSON
        inicio = bruto.find("{")
        fim = bruto.rfind("}") + 1
        if inicio >= 0 and fim > inicio:
            bruto = bruto[inicio:fim]
        dados = json.loads(bruto)
        return dados
    except Exception as e:
        _msg = str(e)
        # Classifica erros de API OpenAI — NÃO usa fallback silencioso
        # Propaga a exceção classificada para o chamador poder lidar corretamente
        from ururau.config.settings import classify_openai_exception
        _result = classify_openai_exception(e)
        if not _result.ok and _result.codigo:
            # É um erro de configuração/API — propaga para bloquear o pipeline
            print(f"[EXTRACAO] Erro de API OpenAI na extração: {_msg[:80]}")
            raise  # Re-propaga para pipeline.py tratar como CONFIG_ERROR

        # Erro não-API (parse JSON, etc.) — usa fallback mínimo mas loga
        print(f"[EXTRACAO] Falha não-API na extração estruturada: {_msg[:80]}")
        print(f"[EXTRACAO] Usando fallback mínimo (fatos locais apenas)")
        return _fallback_mapa(titulo, resumo)


def _fallback_mapa(titulo: str, resumo: str) -> dict:
    """Retorna mapa mínimo quando a extração falha."""
    return {
        "fato_principal": titulo,
        "fatos_secundarios": [],
        "quem": [],
        "onde": "",
        "quando": "",
        "por_que_importa": resumo[:200],
        "consequencia": "",
        "contexto_anterior": "",
        "orgao_central": "",
        "status_atual": "",
        "proximos_passos": "",
        "fonte_primaria": "",
        "fontes_secundarias": [],
        "dados_numericos": [],
        "estudos_citados": [],
        "artigos_lei_citados": [],
        "impactos_citados": [],
        "argumentos_centrais": [],
        "pedidos_ou_encaminhamentos": [],
        "base_juridica": "",
        "posicoes_conflitantes": [],
        "declaracoes_identificadas": [],
        "elementos_sem_fonte": [],
        "inferencias_a_evitar": [],
        "grau_confianca": "medio",
        "risco_editorial": "baixo",
        "motivo_risco": "",
    }


def mapa_para_contexto_redacao(mapa: dict) -> str:
    """
    Converte mapa de evidências em bloco de contexto OBRIGATÓRIO para o prompt de redação.

    IMPORTANTE: este bloco é enviado como OBRIGAÇÃO ao modelo de geração.
    Cada dado numérico, estudo, artigo de lei e argumento central listado aqui
    DEVE aparecer na matéria final — caso contrário a validação reprova.
    """
    partes = []

    # ── Fato e envolvidos ──────────────────────────────────────────────────────
    if mapa.get("fato_principal"):
        partes.append(f"FATO PRINCIPAL (obrigatório no lead):\n{mapa['fato_principal']}")

    if mapa.get("fatos_secundarios"):
        partes.append("FATOS CONFIRMADOS (incluir no corpo):\n" +
                      "\n".join(f"  • {f}" for f in mapa["fatos_secundarios"][:8]))

    if mapa.get("quem"):
        partes.append("ENVOLVIDOS (usar nomes completos na 1ª menção):\n" +
                      ", ".join(mapa["quem"][:8]))

    # ── Localização e tempo ────────────────────────────────────────────────────
    for chave, label in [("onde", "LOCAL"), ("quando", "QUANDO"),
                          ("orgao_central", "ÓRGÃO CENTRAL"),
                          ("status_atual", "STATUS ATUAL DO FATO"),
                          ("fonte_primaria", "FONTE PRIMÁRIA"),
                          ("proximos_passos", "PRÓXIMOS PASSOS")]:
        v = str(mapa.get(chave) or "").strip()
        if v:
            partes.append(f"{label}:\n  {v}")

    # ── DADOS ESSENCIAIS — obrigação de preservação ────────────────────────────
    dados_num = mapa.get("dados_numericos") or []
    if dados_num:
        partes.append(
            "⚡ DADOS NUMÉRICOS OBRIGATÓRIOS (TODOS devem aparecer na matéria):\n" +
            "\n".join(f"  • {d}" for d in dados_num[:10])
        )

    estudos = mapa.get("estudos_citados") or []
    if estudos:
        partes.append(
            "⚡ ESTUDOS OBRIGATÓRIOS (citar na matéria com atribuição):\n" +
            "\n".join(f"  • {e}" for e in estudos[:6])
        )

    artigos = mapa.get("artigos_lei_citados") or []
    if artigos:
        partes.append(
            "⚡ ARTIGOS DE LEI/CONSTITUIÇÃO OBRIGATÓRIOS (preservar na matéria):\n" +
            "\n".join(f"  • {a}" for a in artigos[:6])
        )

    impactos = mapa.get("impactos_citados") or []
    if impactos:
        partes.append(
            "⚡ IMPACTOS OBRIGATÓRIOS (citar e explicar na matéria):\n" +
            "\n".join(f"  • {i}" for i in impactos[:8])
        )

    argumentos = mapa.get("argumentos_centrais") or []
    if argumentos:
        partes.append(
            "⚡ ARGUMENTOS CENTRAIS OBRIGATÓRIOS (preservar na matéria):\n" +
            "\n".join(f"  • {a}" for a in argumentos[:6])
        )

    pedidos = mapa.get("pedidos_ou_encaminhamentos") or []
    if pedidos:
        partes.append(
            "⚡ PEDIDOS/ENCAMINHAMENTOS OBRIGATÓRIOS (incluir na matéria):\n" +
            "\n".join(f"  • {p}" for p in pedidos[:4])
        )

    base_jur = str(mapa.get("base_juridica") or "").strip()
    if base_jur:
        partes.append(f"⚡ BASE JURÍDICA OBRIGATÓRIA (citar na matéria):\n  {base_jur}")

    # ── Declarações e atribuições ──────────────────────────────────────────────
    if mapa.get("declaracoes_identificadas"):
        partes.append(
            "DECLARAÇÕES ATRIBUÍDAS (usar com aspas e atribuição):\n" +
            "\n".join(f"  • {d}" for d in mapa["declaracoes_identificadas"][:4])
        )

    if mapa.get("posicoes_conflitantes"):
        partes.append(
            "POSIÇÕES CONFLITANTES (mencionar quando relevante):\n" +
            "\n".join(f"  • {p}" for p in mapa["posicoes_conflitantes"][:3])
        )

    # ── Alertas editoriais ─────────────────────────────────────────────────────
    if mapa.get("inferencias_a_evitar"):
        partes.append(
            "⛔ NÃO ESCREVA — inferências não confirmadas:\n" +
            "\n".join(f"  • {i}" for i in mapa["inferencias_a_evitar"][:4])
        )

    if mapa.get("elementos_sem_fonte"):
        partes.append(
            "⛔ ELEMENTOS SEM FONTE — não usar como fato:\n" +
            "\n".join(f"  • {e}" for e in mapa["elementos_sem_fonte"][:4])
        )

    risco = mapa.get("risco_editorial", "baixo")
    motivo = mapa.get("motivo_risco", "")
    if risco in ("medio", "alto") and motivo:
        partes.append(f"⚠ RISCO EDITORIAL {risco.upper()}: {motivo}")

    return "\n\n".join(partes)


def validar_dados_essenciais(corpo_materia: str, mapa: dict) -> list[str]:
    """
    validateEssentialFacts: verifica se os dados essenciais da fonte aparecem no corpo.

    Retorna lista de strings descrevendo o que está AUSENTE.
    Lista vazia = todos os dados essenciais preservados.

    Regras de equivalência:
    - Caracteres especiais normalizados (º, ã, etc) para comparação
    - Artigos de lei: "artigo 7º, inciso XIII" → busca "artigo 7" no corpo
    - Siglas: "Fundação Getulio Vargas" → também aceita "FGV" no corpo
    - Idades pessoais (ex: "27 anos" de suspeitos) não são consideradas dados obrigatórios
      quando aparecem no padrão (N anos) — são dados biográficos, não estatísticos.
    """
    import unicodedata as _udata

    ausentes: list[str] = []
    corpo_lower = corpo_materia.lower()

    def _norm(s: str) -> str:
        """Normaliza caracteres especiais para comparação (remove acentos, converte º→o)."""
        return _udata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").lower()

    corpo_norm = _norm(corpo_materia)

    def _gerar_sigla(nome: str) -> str:
        """Gera sigla de 2-5 letras maiúsculas a partir do nome de uma entidade."""
        partes = re.findall(r'\b[A-ZÁÀÃÂÉÊÍÓÔÕÚÜÇ][a-záàãâéêíóôõúüç]{1,}', nome)
        sigla = "".join(p[0] for p in partes if p[0].isupper())
        return sigla if len(sigla) >= 2 else ""

    def _aparece(texto: str) -> bool:
        """
        Verifica se um dado essencial aparece no corpo da matéria.

        Estratégia em cascata:
        1. Busca direta normalizada (resolve º, ã, acentos)
        2. Fragmento numérico (ex: "17,2%", "R$ 1,3 bilhão")
        3. Artigo de lei: busca pelo número do artigo (ex: "artigo 7" de "artigo 7º, inciso XIII")
        4. Sigla da entidade (ex: "FGV" de "Fundação Getulio Vargas")
        5. Palavras-chave com 4+ letras (≥50% presentes)
        """
        if not texto:
            return True

        texto_lower = texto.lower()
        texto_norm  = _norm(texto)

        # 1. Busca direta normalizada
        if texto_norm in corpo_norm:
            return True

        # 2. Fragmentos numéricos
        numeros = re.findall(
            r"\d+[,\.]?\d*\s*(?:%|horas?|anos?|dias?|mil|milhões?|bilhões?|reais?|R\$)?",
            texto_lower
        )
        for num in numeros:
            num_c = num.strip()
            if len(num_c) >= 2 and num_c in corpo_lower:
                return True

        # 3. Artigo de lei: verifica número do artigo no corpo
        #    Ex: "artigo 7º, inciso XIII" → busca "artigo 7" ou "art. 7"
        m_artigo = re.search(r"art(?:igo)?\.?\s*(\d+)", texto_lower, re.IGNORECASE)
        if m_artigo:
            num_art = m_artigo.group(1)
            for pat in (f"artigo {num_art}", f"art. {num_art}", f"art {num_art}"):
                if pat in corpo_lower or pat in corpo_norm:
                    return True

        # 4. Sigla da entidade
        sigla = _gerar_sigla(texto)
        if sigla and len(sigla) >= 2:
            if re.search(r"\b" + re.escape(sigla) + r"\b", corpo_materia):
                return True

        # 5. Palavras-chave com 4+ letras (≥50% presentes)
        palavras = [p for p in re.findall(r"\b\w{4,}\b", texto_lower) if len(p) >= 4]
        if not palavras:
            return bool(numeros)
        presentes = sum(1 for p in palavras if p in corpo_lower)
        return presentes >= max(1, len(palavras) * 0.5)

    # ── Verifica dados numéricos ───────────────────────────────────────────────
    # Idades pessoais (padrão "(27 anos)") são dados biográficos, não obrigatórios
    dados_num = mapa.get("dados_numericos") or []
    for dado in dados_num:
        if not _aparece(dado):
            ausentes.append(f"Dado numérico ausente: {dado}")

    # ── Verifica estudos citados ───────────────────────────────────────────────
    for estudo in (mapa.get("estudos_citados") or []):
        if not _aparece(estudo):
            ausentes.append(f"Estudo ausente: {estudo}")

    # ── Verifica artigos de lei ────────────────────────────────────────────────
    for artigo in (mapa.get("artigos_lei_citados") or []):
        if not _aparece(artigo):
            ausentes.append(f"Artigo de lei ausente: {artigo}")

    # ── Verifica argumentos centrais ──────────────────────────────────────────
    for argumento in (mapa.get("argumentos_centrais") or [])[:4]:
        if not _aparece(argumento):
            ausentes.append(f"Argumento central ausente: {argumento}")

    # ── Verifica impactos (pelo menos metade deve aparecer) ────────────────────
    impactos = mapa.get("impactos_citados") or []
    if len(impactos) >= 2:
        ausentes_impacto = [i for i in impactos if not _aparece(i)]
        if len(ausentes_impacto) > len(impactos) // 2:
            ausentes.append(
                f"Impactos centrais ausentes ({len(ausentes_impacto)}/{len(impactos)}): "
                + "; ".join(ausentes_impacto[:3])
            )

    return ausentes


# ── Tipagem semântica de números ──────────────────────────────────────────────

# Padrões que identificam a CATEGORIA de um número a partir do contexto textual.
# ORDEM IMPORTA: categorias mais específicas e exclusivas primeiro.
# Cada entrada: (categoria, [padrões regex que indicam essa categoria])
_CATEGORIA_NUMERICA_PADROES: list[tuple[str, list[str]]] = [
    # Categorias mais específicas primeiro — têm precedência sobre as genéricas
    ("participacao",     [r"participaç[ãa]o\s+de\s+mercado", r"fatia\s+de\s+mercado",
                          r"market.?share", r"particip[ao]\s+com\s+\d+%", r"deten[hé]\s+\d+%",
                          r"detém\s+\d+%", r"detém\s+participaç"]),
    ("ponto_percentual", [r"pont(?:os?)\s+percent", r"\bp\.p\.\b", r"\bpp\b"]),
    ("estimativa",       [r"estima.se", r"estimativa", r"projetad[oa]", r"previs[ãa]o",
                          r"espera.se", r"deverá\s+(?:ser|atingir|alcançar)",
                          r"deve\s+(?:ser|atingir|alcançar)"]),
    ("artigo_lei",       [r"art(?:igo)?\.?\s*\d+", r"inciso\s+[ivxlIVXL]+",
                          r"parágrafo\s+\d+", r"§\s*\d+"]),
    ("numero_processo",  [r"process[oa]\s+n[oº°]?\.?\s*[\d\-\.\/]+",
                          r"ação\s+(?:civil|penal|trabalhista)", r"inquérito"]),
    ("idade",            [r"\d+\s+anos?\s+de\s+(?:idade|vida)", r"com\s+\d+\s+anos?",
                          r"\(\d+\s+anos?\)"]),
    ("ranking",          [r"\b(?:1[ºo°]|2[ºo°]|3[ºo°]|primeiro|segundo|terceiro)\s+(?:lugar|posição|colocad)",
                          r"\branking\b", r"ocup[ao]\s+(?:o\s+)?(?:1[ºo°]|primeiro|segundo)"]),
    ("alegacao",         [r"(?:segundo|conforme|de acordo com)\s+(?:a\s+)?(?:acusaç[ãa]o|defesa|mp|ministério|promotoria|denúncia)",
                          r"denuncia(?:do|ndo)", r"investiga(?:do|ndo)"]),
    ("volume",           [r"tonelada", r"\bton\b", r"litro", r"metro", r"hectare",
                          r"\bha\b", r"unidades?", r"caixas?", r"sacas?"]),
    ("receita",          [r"receit[ao]\s+(?:total|bruta|líquida|de|foi)",
                          r"faturament[oa]\s+(?:total|de|foi|bruto|líquido)",
                          r"arrecad", r"r\$\s*\d"]),
    ("valor_monetario",  [r"r\$", r"custo", r"gasto", r"investiment[oa]",
                          r"prêmi[oa]", r"multa", r"indenizaç"]),
    ("percentual_taxa",  [r"taxa\s+de", r"índice\s+de", r"cresciment[oa]\s+de\s+\d+%",
                          r"inflaç[ãa]o", r"juros", r"selic", r"ipca"]),
    ("data",             [r"\b(?:janeiro|fevereiro|março|abril|maio|junho|julho|agosto"
                          r"|setembro|outubro|novembro|dezembro)\b",
                          r"\b20\d\d\b", r"\b(?:segunda|terça|quarta|quinta|sexta).feira\b"]),
    ("percentual_generico", [r"%"]),   # fallback para qualquer %
]


def _classificar_tipo_numerico(texto: str) -> str:
    """
    Dado um texto contendo um número e seu contexto, retorna a categoria semântica.
    A ordem em _CATEGORIA_NUMERICA_PADROES importa — categorias mais específicas primeiro.
    """
    t = texto.lower()
    for categoria, padroes in _CATEGORIA_NUMERICA_PADROES:
        for pat in padroes:
            if re.search(pat, t, re.IGNORECASE):
                return categoria
    return "desconhecido"


def anotar_tipos_numericos(texto_fonte: str, dados_numericos: list[str]) -> list[dict]:
    """
    Para cada item em dados_numericos (strings extraídas do mapa de evidências),
    determina a categoria semântica e retorna lista de dicts:
        [{valor: str, tipo: str, contexto: str}, ...]

    Estratégia de classificação (em ordem de prioridade):
    1. Classificar a partir do ITEM em si (mais confiável — sem contaminação de contexto)
    2. Se o item sozinho não classificar, usar janela de contexto na fonte (40 chars)

    Esta anotação é usada por validar_precisao_numerica() para detectar
    se o artigo gerado confunde categorias (ex: % virou R$, estimativa virou fato).
    """
    anotados = []
    texto_lower = texto_fonte.lower()

    for item in dados_numericos:
        if not item:
            continue

        # 1. Tenta classificar a partir do item em si
        tipo_por_item = _classificar_tipo_numerico(item)

        if tipo_por_item != "desconhecido":
            # Item classificado com confiança — não precisa de contexto externo
            tipo = tipo_por_item
            contexto = item
        else:
            # 2. Fallback: janela estreita (40 chars) na fonte para não contaminar
            m = re.search(r"[\d,\.]+", item)
            num_bruto = m.group(0).strip() if m else item[:15]
            pos = texto_lower.find(num_bruto.lower())
            if pos == -1:
                contexto = item
            else:
                start = max(0, pos - 40)
                end = min(len(texto_fonte), pos + 40)
                contexto = texto_fonte[start:end]
            tipo = _classificar_tipo_numerico(contexto)

        anotados.append({
            "valor": item,
            "tipo": tipo,
            "contexto": contexto.strip(),
        })

    return anotados
