"""
ia/schemas.py — CAMADA 7/8: Schemas JSON fixos para geração e auditoria (v45).

Define os contratos de entrada/saída exatos para cada chamada editorial.
Valida programaticamente antes de aceitar qualquer JSON da IA.
Nunca aceita JSON inválido, incompleto ou com tipos errados.

Novidades v45:
- subtitulo renomeado para subtitulo_curto
- legenda_instagram campo opcional adicionado
- corpo_materia como alias de texto_final para compatibilidade com CMS
- status_validacao gerado programaticamente
- validar_geracao() verifica travessões e expressões proibidas
- TEXTO_MINIMO_CHARS atualizado para 500
"""
from __future__ import annotations

import json
import re
from typing import Any

from ururau.ia.politica_editorial import (
    CANAIS_VALIDOS,
    STATUS_PUBLICACAO_VALIDOS,
    ESTRATEGIAS_ENQUADRAMENTO_VALIDAS,
    DIMENSAO_IMAGEM_PADRAO,
    LIMITE_TITULO_SEO,
    LIMITE_TITULO_SEO_MIN,
    LIMITE_TITULO_CAPA,
    LIMITE_TITULO_CAPA_MIN,
    LIMITE_META_DESCRIPTION_MIN,
    LIMITE_META_DESCRIPTION_MAX,
    LIMITE_LEGENDA,
    LIMITE_SUBTITULO_CURTO,
    LIMITE_RETRANCA_PALAVRAS,
    LIMITE_NOME_FONTE_PALAVRAS,
    LIMITE_CREDITO_FOTO_PALAVRAS,
    TAGS_MIN,
    TAGS_MAX,
    TEXTO_MINIMO_CHARS,
    TEXTO_MINIMO_CHARS_FONTE_CURTA,
    FRASES_UNSUPPORTED,
    FRASES_GENERICAS_PROIBIDAS,
    EXPRESSOES_PROIBIDAS,
    VERBOS_CRUTCH,
    FRASES_FECHAMENTO_INTERPRETATIVO,
)


# ── Schema de geração ─────────────────────────────────────────────────────────
# Ordem dos campos segue a especificação editorial v45:
# titulo_seo → subtitulo_curto → retranca → titulo_capa → tags →
# legenda_curta → corpo_materia → legenda_instagram → status_validacao

SCHEMA_GERACAO = {
    "titulo_seo": "",
    "subtitulo_curto": "",          # renomeado de 'subtitulo' na v45
    "retranca": "",
    "titulo_capa": "",
    "tags": [],
    "legenda_curta": "",            # legenda da foto/imagem (≤100 chars)
    "corpo_materia": "",            # campo principal do texto (alias: texto_final)
    "legenda_instagram": "",        # opcional — legenda para post no Instagram
    # ── campos auxiliares CMS ──────────────────────────────────────
    "nome_da_fonte": "",
    "creditos_da_foto": "",
    "editoria": "",
    "canal": "",
    "status_publicacao_sugerido": "",
    "justificativa_status": "",
    "slug": "",
    "meta_description": "",
    "resumo_curto": "",
    "chamada_social": "",
    "estrutura_decisao": "",
    "imagem": {
        "tipo": "",
        "origem": "",
        "url_ou_referencia": "",
        "licenca_verificada": False,
        "eh_paga": False,
        "foi_substituida": False,
        "motivo_substituicao": "",
        "descricao_editorial": "",
        "dimensao_final": DIMENSAO_IMAGEM_PADRAO,
        "estrategia_enquadramento": "",
    },
    "metadados_apurados": {
        "data_publicacao_fonte": "",
        "hora_publicacao_fonte": "",
        "autor_fonte": "",
        "veiculos_identificados": [],
        "tema_central": "",
        "status_real_do_fato": "",
        "personagens": [],
        "numeros_relevantes": [],
    },
    "memoria_aplicada": {
        "regras_criticas_usadas": [],
        "erros_recentes_evitar": [],
        "exemplos_base_usados": [],
        "pesos_regionais_acionados": [],
    },
}

# ── Schema de auditoria ───────────────────────────────────────────────────────

SCHEMA_AUDITORIA = {
    "aprovado": False,
    "erros_encontrados": [],
    "campos_com_problema": [],
    "violacoes_editoriais": [],
    "violacoes_factuais": [],
    "violacoes_de_fluxo": [],
    "violacoes_de_memoria": [],
    "corrigir_e_regerar": False,
    "bloquear_publicacao": True,
    "atualizar_memoria": {
        "novos_erros": [],
        "novas_regras": [],
        "novos_alertas": [],
        "novos_exemplos_ruins": [],
    },
    "versao_corrigida": {
        "titulo_seo": "",
        "subtitulo_curto": "",
        "retranca": "",
        "titulo_capa": "",
        "tags": [],
        "legenda_curta": "",
        "corpo_materia": "",
        "legenda_instagram": "",
        "nome_da_fonte": "",
        "creditos_da_foto": "",
        "editoria": "",
        "canal": "",
        "status_publicacao_sugerido": "",
        "justificativa_status": "",
        "imagem": {
            "tipo": "",
            "origem": "",
            "url_ou_referencia": "",
            "licenca_verificada": False,
            "eh_paga": False,
            "foi_substituida": False,
            "motivo_substituicao": "",
            "descricao_editorial": "",
            "dimensao_final": DIMENSAO_IMAGEM_PADRAO,
            "estrategia_enquadramento": "",
        },
    },
}


# ── Extração de JSON bruto da resposta da IA ──────────────────────────────────

def extrair_json(texto: str) -> dict:
    """
    Extrai e parseia JSON de resposta da IA.
    Remove markdown, busca o primeiro objeto JSON válido.
    Levanta ValueError se não conseguir parsear.
    """
    bruto = texto.strip()

    # Remove blocos markdown ```json ... ```
    if "```" in bruto:
        bruto = re.sub(r"```(?:json)?", "", bruto).strip()
        bruto = bruto.replace("```", "").strip()

    # Tenta localizar o objeto JSON
    inicio = bruto.find("{")
    fim = bruto.rfind("}") + 1
    if inicio == -1 or fim <= inicio:
        raise ValueError(f"Nenhum objeto JSON encontrado na resposta: {bruto[:200]}")

    bruto = bruto[inicio:fim]

    try:
        return json.loads(bruto)
    except json.JSONDecodeError as e:
        # Tenta limpeza básica
        bruto_limpo = re.sub(r",\s*([}\]])", r"\1", bruto)  # trailing commas
        try:
            return json.loads(bruto_limpo)
        except Exception:
            raise ValueError(f"JSON inválido após limpeza: {e}. Trecho: {bruto[:300]}")


# ── Validação programática de JSON de geração ─────────────────────────────────

class ErroValidacao(Exception):
    """Erro de validação de JSON editorial."""
    def __init__(self, campo: str, motivo: str):
        self.campo = campo
        self.motivo = motivo
        super().__init__(f"[{campo}] {motivo}")


def validar_geracao(dados: dict, tamanho_fonte: int = 0) -> list[ErroValidacao]:
    """
    Valida programaticamente o JSON de geração (v53).
    Retorna lista de erros encontrados. Lista vazia = aprovado.

    Parâmetros:
      - dados: JSON gerado pela IA
      - tamanho_fonte: número de chars do texto-fonte original.
        Se informado, ajusta o mínimo de corpo_materia proporcionalmente.
        Fontes curtas (< 800 chars) aceitam corpo menor.

    Validações incluídas:
    - Campos obrigatórios presentes e com tipo correto
    - Limites de caracteres (titulo_seo ≤89, titulo_capa ≤60, subtitulo_curto ≤200)
    - corpo_materia ≥ mínimo proporcional à fonte (250 para fonte curta, 500 para longa)
    - Travessão (— ou –) proibido em qualquer campo textual
    - Expressões proibidas (EXPRESSOES_PROIBIDAS) no corpo_materia e título
    - Frases de expansão artificial (FRASES_UNSUPPORTED) — unsupported claims
    - Tags: array, 5-12 elementos
    - Canal/editoria dentro da taxonomia
    - Slug: formato URL válido
    - Títulos truncados
    """
    erros: list[ErroValidacao] = []

    # Determina mínimo de corpo proporcional à fonte
    _FONTE_CURTA_LIMITE = 800  # fontes com menos de 800 chars são "curtas"
    _FONTE_MUITO_CURTA  = 300  # fontes com menos de 300 chars são "muito curtas"
    if tamanho_fonte > 0 and tamanho_fonte < _FONTE_MUITO_CURTA:
        _min_corpo = max(100, tamanho_fonte // 2)  # artigo pode ser bem curto
        _min_paragrafos = 2
    elif tamanho_fonte > 0 and tamanho_fonte < _FONTE_CURTA_LIMITE:
        _min_corpo = TEXTO_MINIMO_CHARS_FONTE_CURTA  # 250
        _min_paragrafos = 3
    else:
        _min_corpo = TEXTO_MINIMO_CHARS  # 500 padrão
        _min_paragrafos = 4

    def _chk(condicao: bool, campo: str, motivo: str):
        if not condicao:
            erros.append(ErroValidacao(campo, motivo))

    # ── Compatibilidade: aceita corpo_materia ou texto_final ─────────────────
    # Prefere corpo_materia (v45); fallback para texto_final (versões anteriores)
    corpo = dados.get("corpo_materia") or dados.get("texto_final", "")
    if not dados.get("corpo_materia") and dados.get("texto_final"):
        dados["corpo_materia"] = dados["texto_final"]

    # ── Campos obrigatórios de tipo string ───────────────────────────────────
    campos_obrigatorios = [
        "titulo_seo", "subtitulo_curto", "retranca", "titulo_capa",
        "legenda_curta", "corpo_materia", "nome_da_fonte", "creditos_da_foto",
        "editoria", "canal", "status_publicacao_sugerido", "slug",
    ]
    for campo in campos_obrigatorios:
        val = dados.get(campo)
        _chk(isinstance(val, str) and val.strip() != "",
             campo, "campo obrigatório ausente, vazio ou tipo incorreto (esperado string)")

    # ── Limites de caracteres ────────────────────────────────────────────────
    titulo = dados.get("titulo_seo", "")
    _chk(LIMITE_TITULO_SEO_MIN <= len(titulo) <= LIMITE_TITULO_SEO,
         "titulo_seo",
         f"deve ter {LIMITE_TITULO_SEO_MIN}-{LIMITE_TITULO_SEO} chars, tem {len(titulo)}")

    capa = dados.get("titulo_capa", "")
    _chk(LIMITE_TITULO_CAPA_MIN <= len(capa) <= LIMITE_TITULO_CAPA,
         "titulo_capa",
         f"deve ter {LIMITE_TITULO_CAPA_MIN}-{LIMITE_TITULO_CAPA} chars, tem {len(capa)}")

    subtitulo = dados.get("subtitulo_curto", "")
    if subtitulo:
        _chk(len(subtitulo) <= LIMITE_SUBTITULO_CURTO,
             "subtitulo_curto",
             f"deve ter no máximo {LIMITE_SUBTITULO_CURTO} chars, tem {len(subtitulo)}")

    meta = dados.get("meta_description", "")
    if meta:
        _chk(LIMITE_META_DESCRIPTION_MIN <= len(meta) <= LIMITE_META_DESCRIPTION_MAX,
             "meta_description",
             f"deve ter {LIMITE_META_DESCRIPTION_MIN}-{LIMITE_META_DESCRIPTION_MAX} chars, tem {len(meta)}")

    legenda = dados.get("legenda_curta", "")
    _chk(len(legenda) <= LIMITE_LEGENDA,
         "legenda_curta", f"deve ter no máximo {LIMITE_LEGENDA} chars, tem {len(legenda)}")

    retranca = dados.get("retranca", "")
    _chk(len(retranca.split()) <= LIMITE_RETRANCA_PALAVRAS,
         "retranca",
         f"deve ter no máximo {LIMITE_RETRANCA_PALAVRAS} palavras, tem {len(retranca.split())}")

    nome_fonte = dados.get("nome_da_fonte", "")
    _chk(len(nome_fonte.split()) <= LIMITE_NOME_FONTE_PALAVRAS,
         "nome_da_fonte",
         f"deve ter no máximo {LIMITE_NOME_FONTE_PALAVRAS} palavras, tem {len(nome_fonte.split())}")

    credito = dados.get("creditos_da_foto", "")
    _chk(len(credito.split()) <= LIMITE_CREDITO_FOTO_PALAVRAS,
         "creditos_da_foto",
         f"deve ter no máximo {LIMITE_CREDITO_FOTO_PALAVRAS} palavras, tem {len(credito.split())}")

    # ── Tags: array ──────────────────────────────────────────────────────────
    tags = dados.get("tags", [])
    _chk(isinstance(tags, list),
         "tags", "deve ser array (lista), não string")
    if isinstance(tags, list):
        _chk(TAGS_MIN <= len(tags) <= TAGS_MAX,
             "tags", f"deve ter {TAGS_MIN}-{TAGS_MAX} elementos, tem {len(tags)}")

    # ── Canal e editoria dentro da taxonomia ─────────────────────────────────
    canal = dados.get("canal", "")
    _chk(canal in CANAIS_VALIDOS,
         "canal", f"'{canal}' não é canal válido. Válidos: {CANAIS_VALIDOS}")

    editoria = dados.get("editoria", "")
    _chk(editoria in CANAIS_VALIDOS,
         "editoria", f"'{editoria}' não é editoria válida. Válidas: {CANAIS_VALIDOS}")

    # ── Status de publicação ──────────────────────────────────────────────────
    status = dados.get("status_publicacao_sugerido", "")
    _chk(status in STATUS_PUBLICACAO_VALIDOS,
         "status_publicacao_sugerido",
         f"'{status}' inválido. Válidos: {STATUS_PUBLICACAO_VALIDOS}")

    # ── Texto do corpo: mínimo proporcional à fonte ───────────────────────────
    _chk(len(corpo) >= _min_corpo,
         "corpo_materia",
         f"texto muito curto ({len(corpo)} chars). Mínimo {_min_corpo} chars "
         f"(proporcional à fonte: {tamanho_fonte} chars).")

    # ── Parágrafos: mínimo proporcional à fonte ────────────────────────────────
    if corpo:
        _paragrafos = [p.strip() for p in corpo.split("\n\n") if p.strip()]
        _chk(len(_paragrafos) >= _min_paragrafos,
             "corpo_materia",
             f"texto sem divisão em parágrafos ({len(_paragrafos)} parágrafo(s)). "
             f"Use \\n\\n entre parágrafos. Mínimo {_min_paragrafos} para esta fonte.")

    # ── Detecção de frases de expansão artificial (unsupported claims) ────────
    # Rejeita artigos que adicionam afirmações não suportadas pela fonte.
    # Estas frases são proibidas a menos que estejam explicitamente na fonte.
    # (A verificação definitiva é feita pelo auditor IA; aqui detectamos os padrões mais óbvios)
    corpo_lower_full = corpo.lower()
    _unsupported_achadas = [f for f in FRASES_UNSUPPORTED if f in corpo_lower_full]
    if _unsupported_achadas:
        erros.append(ErroValidacao(
            "corpo_materia",
            f"contém {len(_unsupported_achadas)} frase(s) de expansão artificial não suportada(s) "
            f"pela fonte: {'; '.join(_unsupported_achadas[:3])}. "
            "Remova ou reescreva usando apenas informações presentes na fonte."
        ))

    # ── Travessão proibido (— U+2014 e – U+2013) ─────────────────────────────
    _TRAVESSAO_PATTERN = re.compile(r"[—–]")
    campos_texto = ["titulo_seo", "subtitulo_curto", "titulo_capa", "corpo_materia",
                    "legenda_curta", "legenda_instagram", "meta_description"]
    for campo_t in campos_texto:
        val_t = dados.get(campo_t, "") or ""
        if _TRAVESSAO_PATTERN.search(val_t):
            erros.append(ErroValidacao(
                campo_t,
                "contém travessão (— ou –), que é PROIBIDO. "
                "Substitua por vírgula, dois-pontos ou reformule a frase."
            ))

    # ── Expressões proibidas no corpo_materia e título ────────────────────────
    _campos_expr = {
        "corpo_materia": corpo,
        "titulo_seo": titulo,
    }
    for campo_e, texto_e in _campos_expr.items():
        texto_lower = texto_e.lower()
        achadas = [expr for expr in EXPRESSOES_PROIBIDAS if expr in texto_lower]
        if achadas:
            substituicoes = []
            for expr in achadas[:5]:  # máximo 5 no erro para não truncar
                subs = EXPRESSOES_PROIBIDAS[expr]
                if subs:
                    substituicoes.append(f'"{expr}" → "{subs}"')
                else:
                    substituicoes.append(f'"{expr}" → [reescreva]')
            erros.append(ErroValidacao(
                campo_e,
                f"contém {len(achadas)} expressão(ões) proibida(s): "
                + "; ".join(substituicoes)
            ))

    # ── Imagem ────────────────────────────────────────────────────────────────
    img = dados.get("imagem", {})
    if isinstance(img, dict):
        _chk(img.get("dimensao_final") == DIMENSAO_IMAGEM_PADRAO,
             "imagem.dimensao_final",
             f"deve ser '{DIMENSAO_IMAGEM_PADRAO}', é '{img.get('dimensao_final')}'")

        estrategia = img.get("estrategia_enquadramento", "")
        _chk(not estrategia or estrategia in ESTRATEGIAS_ENQUADRAMENTO_VALIDAS,
             "imagem.estrategia_enquadramento",
             f"'{estrategia}' inválida. Válidas: {ESTRATEGIAS_ENQUADRAMENTO_VALIDAS}")

        _chk(isinstance(img.get("licenca_verificada"), bool),
             "imagem.licenca_verificada", "deve ser booleano")
        _chk(isinstance(img.get("eh_paga"), bool),
             "imagem.eh_paga", "deve ser booleano")
        _chk(isinstance(img.get("foi_substituida"), bool),
             "imagem.foi_substituida", "deve ser booleano")

    # ── Slug: sem espaços, sem acentos, apenas chars válidos ─────────────────
    slug = dados.get("slug", "")
    if slug:
        _chk(re.match(r"^[a-z0-9\-]+$", slug),
             "slug", "deve conter apenas letras minúsculas, números e hífens")

    # ── Título truncado: rejeita título ou capa que termina com palavra cortada ──
    # Padrão: palavra final com 4+ letras que não é um sufixo válido de palavra
    # completa (baseado em fins de palavras comuns em português)
    _SUFIXOS_INVALIDOS = re.compile(
        r"\b(?:outr|investig|govern|secret|minist|preside|deput|senado"
        r"|tribun|eleit|legisl|execut|judici|polici|operat|prisã|detent"
        r"|habeas|recurs|mandad|denunc|acusad|culpad|inocent|condena"
        r"|aprova|propõe|apreci|votaçã|tramit|consult|audiênc"
        r"|empreg|trabalh|econom|mercad|inflat|desempreg|produç"
        r"|ambient|climát|tempest|inundaç|enchent)\s*$",
        re.IGNORECASE,
    )

    for campo_titulo, val_titulo in [("titulo_seo", titulo), ("titulo_capa", capa)]:
        if val_titulo and _SUFIXOS_INVALIDOS.search(val_titulo.strip()):
            erros.append(ErroValidacao(
                campo_titulo,
                f"título aparenta estar truncado (termina com palavra incompleta): "
                f"'{val_titulo[-30:]}'. Reescreva usando o limite de caracteres sem cortar palavras."
            ))

    # ── Frases genéricas proibidas ────────────────────────────────────────────
    # Rejeita artigos que usam frases de preenchimento genérico sem dado concreto.
    _genericas_achadas = [f for f in FRASES_GENERICAS_PROIBIDAS if f in corpo_lower_full]
    if _genericas_achadas:
        erros.append(ErroValidacao(
            "corpo_materia",
            f"contém {len(_genericas_achadas)} frase(s) genérica(s) proibida(s) sem dado concreto: "
            f"{'; '.join(_genericas_achadas[:3])}. "
            "Reescreva com fato específico, órgão responsável, prazo ou documento."
        ))

    # ── Detecção de data inventada ────────────────────────────────────────────
    # Verifica se o corpo usa datas completas (dia + mês + ano) que podem ter sido inventadas.
    # A regra: se o corpo contém uma data completa (ex: "23 de março de 2023"),
    # o sistema registra aviso — mas não bloqueia automaticamente pois o auditor IA é responsável.
    # O que é BLOQUEADO: datas com formatos claramente incorretos ou anacrônicos.
    # (A validação principal de datas fica no auditor IA que conhece a fonte)

    # ── Fechamento interpretativo proibido ────────────────────────────────────
    erros.extend(validar_fechamento_interpretativo(dados))

    # ── Repetição de parágrafos ───────────────────────────────────────────────
    erros.extend(validar_repeticao_paragrafos(dados))

    # ── Citação direta excessiva ──────────────────────────────────────────────
    erros.extend(validar_citacao_excessiva(dados))

    # ── Verbos de atribuição genéricos repetidos ──────────────────────────────
    erros.extend(validar_verbos_crutch(dados))

    # ── Pacote editorial completo ─────────────────────────────────────────────
    erros.extend(validar_pacote_editorial_completo(dados))

    # ── Consistência título–corpo ─────────────────────────────────────────────
    erros.extend(validar_consistencia_titulo_corpo(dados))

    return erros


def validar_precisao_numerica(
    dados: dict,
    numeros_tipados: list[dict],
) -> list[ErroValidacao]:
    """
    Verifica se o artigo gerado preserva a categoria semântica dos números da fonte.

    numeros_tipados: lista de dicts {valor, tipo, contexto} produzida por
                     extracao.anotar_tipos_numericos().

    Detecta confusões entre categorias como:
    - participação (%) descrita como receita (R$)
    - receita (R$) descrita como percentual
    - estimativa apresentada como fato confirmado
    - volume (ton/un) confundido com receita (R$)

    Retorna lista de ErroValidacao (vazia = nenhum problema detectado).
    """
    erros: list[ErroValidacao] = []
    if not numeros_tipados:
        return erros

    # Verifica apenas no corpo (não no título) para evitar falsos positivos
    # quando o título apresenta corretamente mais de um número em categorias distintas.
    corpo = (dados.get("corpo_materia") or dados.get("texto_final", "")).lower()
    if not corpo:
        return erros

    # Padrões que indicam confusão de categoria no artigo gerado
    # Chave = tipo da fonte; valor = padrões que indicam uso incorreto no artigo
    _PADROES_CONFUSAO: dict[str, list[tuple[str, str]]] = {
        # Se na fonte o número é PARTICIPAÇÃO DE MERCADO (%), não pode virar R$ no artigo
        "participacao": [
            (r"r\$\s*[\d,.]+\s*(?:mil(?:hões?)?|bilhões?)?", "participação de mercado (%) descrita como valor monetário (R$)"),
            (r"receita\s+de\s+[\d,.]+", "participação de mercado descrita como receita"),
            (r"faturament[oa]\s+de\s+[\d,.]+", "participação de mercado descrita como faturamento"),
        ],
        # Se na fonte é RECEITA (R$), não pode virar participação (%) no artigo
        "receita": [
            (r"[\d,.]+\s*%\s+(?:do|de|da)\s+mercado", "receita (R$) descrita como percentual de mercado"),
            (r"fatia\s+de\s+[\d,.]+\s*%", "receita (R$) descrita como fatia percentual"),
        ],
        # ESTIMATIVA não pode virar fato confirmado
        "estimativa": [
            (r"(?:^|[^a-záéíóúâêîôûãõç])(?:é|foi|são|foram)\s+[\d,.]+", "estimativa apresentada como fato confirmado (sem 'estima-se', 'previsto' ou similar)"),
        ],
        # PERCENTUAL GENÉRICO não pode virar valor absoluto
        "percentual_generico": [
            (r"r\$\s*[\d,.]+\s*(?:mil(?:hões?)?|bilhões?)?(?!\s*(?:mil(?:hões?)?|bilhões?)?\s*%)", "percentual (%) descrito como valor monetário (R$)"),
        ],
        # VOLUME (ton/un) não pode ser confundido com receita
        "volume": [
            (r"receita\s+de\s+[\d,.]+\s*(?:ton|kg|litro|unidade)", "volume (toneladas/unidades) descrito como receita"),
        ],
    }

    for num in numeros_tipados:
        tipo = num.get("tipo", "desconhecido")
        valor_str = num.get("valor", "")
        if tipo not in _PADROES_CONFUSAO:
            continue

        # Extrai apenas os dígitos do valor para busca no artigo
        m = re.search(r"[\d,.]+", valor_str)
        if not m:
            continue
        num_digits = m.group(0)

        # Para participação (%): verifica se o número aparece com CONTEXTO INCORRETO
        # Localiza todas as ocorrências do número no corpo
        for match in re.finditer(re.escape(num_digits), corpo):
            pos = match.start()
            # Contexto de 80 chars antes e depois do número
            start = max(0, pos - 80)
            end = min(len(corpo), pos + 80)
            ctx_artigo = corpo[start:end]

            # Para tipo participação: o número deve aparecer com % em torno
            # Se o número está com %, está na categoria certa — pula
            if tipo == "participacao":
                # Contexto imediato (±30 chars) ao redor do número
                ctx_imediato = corpo[max(0, pos - 30):min(len(corpo), pos + 30)]
                if re.search(r"\d+\s*%", ctx_imediato):
                    continue  # número aparece com % — contexto correto para participação
            elif tipo == "receita":
                # Contexto imediato para receita: deve estar junto de R$
                ctx_imediato = corpo[max(0, pos - 40):min(len(corpo), pos + 40)]
                if re.search(r"r\$", ctx_imediato):
                    continue  # número aparece com R$ — contexto correto para receita

            for padrao, descricao in _PADROES_CONFUSAO[tipo]:
                if re.search(padrao, ctx_artigo, re.IGNORECASE):
                    erros.append(ErroValidacao(
                        "corpo_materia",
                        f"PRECISÃO NUMÉRICA: {descricao}. "
                        f"Valor da fonte: '{valor_str}' (tipo: {tipo}). "
                        f"Contexto no artigo: '...{ctx_artigo.strip()[:80]}...'"
                    ))
                    break  # um erro por ocorrência é suficiente
            break  # verifica apenas a primeira ocorrência do número

    return erros


def gerar_status_validacao(dados: dict, erros: list[ErroValidacao]) -> dict:
    """
    Gera o campo status_validacao programaticamente após validação.
    Este campo NÃO é gerado pela IA — é calculado aqui, no sistema.

    Retorna dict com:
      - aprovado: bool
      - total_erros: int
      - campos_com_erro: list[str]
      - detalhes: list[str]
      - pode_publicar: bool
      - pode_salvar_rascunho: bool
    """
    campos_com_erro = list({e.campo for e in erros})
    detalhes = [f"[{e.campo}] {e.motivo}" for e in erros]

    # Erros críticos que bloqueiam até o rascunho
    _CRITICOS = {
        "titulo_seo", "corpo_materia", "titulo_capa",
        "canal", "editoria", "status_publicacao_sugerido",
    }
    tem_critico = any(e.campo in _CRITICOS for e in erros)

    aprovado = len(erros) == 0
    pode_publicar = aprovado
    pode_salvar_rascunho = not tem_critico

    return {
        "aprovado": aprovado,
        "total_erros": len(erros),
        "campos_com_erro": campos_com_erro,
        "detalhes": detalhes,
        "pode_publicar": pode_publicar,
        "pode_salvar_rascunho": pode_salvar_rascunho,
    }


def validar_auditoria(dados: dict) -> list[ErroValidacao]:
    """
    Valida o JSON de auditoria retornado pela IA.
    Retorna lista de erros estruturais.
    """
    erros: list[ErroValidacao] = []

    def _chk(condicao: bool, campo: str, motivo: str):
        if not condicao:
            erros.append(ErroValidacao(campo, motivo))

    _chk(isinstance(dados.get("aprovado"), bool),
         "aprovado", "deve ser booleano")
    _chk(isinstance(dados.get("bloquear_publicacao"), bool),
         "bloquear_publicacao", "deve ser booleano")
    _chk(isinstance(dados.get("corrigir_e_regerar"), bool),
         "corrigir_e_regerar", "deve ser booleano")
    _chk(isinstance(dados.get("erros_encontrados"), list),
         "erros_encontrados", "deve ser array")
    _chk(isinstance(dados.get("violacoes_factuais"), list),
         "violacoes_factuais", "deve ser array")
    _chk(isinstance(dados.get("violacoes_editoriais"), list),
         "violacoes_editoriais", "deve ser array")

    return erros


def validar_fechamento_interpretativo(dados: dict) -> list[ErroValidacao]:
    """
    Verifica se o último parágrafo do corpo contém análise interpretativa
    não suportada pela fonte (frases de fechamento proibidas).

    Retorna lista de ErroValidacao. Lista vazia = aprovado.
    """
    erros: list[ErroValidacao] = []
    corpo = (dados.get("corpo_materia") or dados.get("texto_final", "")).strip()
    if not corpo:
        return erros

    paragrafos = [p.strip() for p in corpo.split("\n\n") if p.strip()]
    if not paragrafos:
        return erros

    ultimo = paragrafos[-1].lower()
    achadas = [f for f in FRASES_FECHAMENTO_INTERPRETATIVO if f.lower() in ultimo]
    if achadas:
        erros.append(ErroValidacao(
            "corpo_materia",
            f"parágrafo final contém {len(achadas)} frase(s) interpretativa(s) não suportada(s): "
            f"{'; '.join(achadas[:3])}. "
            "O fechamento deve ser factual: status atual, resposta documentada ou fato confirmado."
        ))
    return erros


def validar_repeticao_paragrafos(dados: dict) -> list[ErroValidacao]:
    """
    Detecta parágrafos que repetem o mesmo conteúdo factual sem nova informação.
    Usa similaridade de n-gramas: dois parágrafos são considerados repetitivos
    se compartilham ≥ 60% das palavras de 4+ letras entre si.

    Retorna lista de ErroValidacao. Lista vazia = aprovado.
    """
    erros: list[ErroValidacao] = []
    corpo = (dados.get("corpo_materia") or dados.get("texto_final", "")).strip()
    if not corpo:
        return erros

    paragrafos = [p.strip() for p in corpo.split("\n\n") if p.strip()]
    if len(paragrafos) < 2:
        return erros

    def _palavras_chave(texto: str) -> set[str]:
        return set(re.findall(r"\b\w{4,}\b", texto.lower()))

    for i in range(len(paragrafos)):
        for j in range(i + 1, len(paragrafos)):
            p1_kw = _palavras_chave(paragrafos[i])
            p2_kw = _palavras_chave(paragrafos[j])
            if not p1_kw or not p2_kw:
                continue
            intersecao = p1_kw & p2_kw
            menor = min(len(p1_kw), len(p2_kw))
            similaridade = len(intersecao) / menor if menor > 0 else 0
            if similaridade >= 0.65 and len(intersecao) >= 8:
                erros.append(ErroValidacao(
                    "corpo_materia",
                    f"parágrafos {i+1} e {j+1} são repetitivos "
                    f"({len(intersecao)} palavras em comum, {similaridade:.0%} similaridade). "
                    f"Cada parágrafo deve adicionar informação nova. "
                    f"Início P{i+1}: '{paragrafos[i][:50]}...'"
                ))
                break  # um erro por parágrafo duplicado é suficiente
        if erros:
            break  # não acumula muitos erros de repetição na primeira rodada

    return erros


def validar_citacao_excessiva(dados: dict) -> list[ErroValidacao]:
    """
    Detecta se o artigo usa citações diretas excessivas (> 40% do corpo em aspas).
    Conta caracteres entre aspas (\" ou \") vs. total do corpo.

    Retorna lista de ErroValidacao. Lista vazia = aprovado.
    """
    erros: list[ErroValidacao] = []
    corpo = (dados.get("corpo_materia") or dados.get("texto_final", "")).strip()
    if not corpo or len(corpo) < 200:
        return erros

    # Conta caracteres dentro de aspas (qualquer tipo)
    chars_em_aspas = 0
    for m in re.finditer(r'["\u201c\u201d\u2018\u2019]([^"\u201c\u201d\u2018\u2019]{20,})["\u201c\u201d\u2018\u2019]', corpo):
        chars_em_aspas += len(m.group(1))

    proporcao = chars_em_aspas / len(corpo) if corpo else 0
    if proporcao > 0.40:
        erros.append(ErroValidacao(
            "corpo_materia",
            f"artigo contém {proporcao:.0%} do corpo em citações diretas "
            f"({chars_em_aspas} de {len(corpo)} chars). "
            "Limite: 40%. Parafrase citações secundárias com atribuição."
        ))
    return erros


def validar_verbos_crutch(dados: dict) -> list[ErroValidacao]:
    """
    Detecta uso repetido ou desnecessário de verbos de atribuição genéricos
    ("destacou", "reforçou", "ressaltou", "sinalizou", "pontuou", "frisou", "salientou").
    Um uso isolado é aceito; dois ou mais usos do mesmo verbo é rejeitado.

    Retorna lista de ErroValidacao. Lista vazia = aprovado.
    """
    erros: list[ErroValidacao] = []
    corpo = (dados.get("corpo_materia") or dados.get("texto_final", "")).strip()
    if not corpo:
        return erros

    corpo_lower = corpo.lower()
    repetidos = []
    for verbo in VERBOS_CRUTCH:
        # Conta ocorrências do verbo como palavra inteira
        ocorrencias = len(re.findall(r"\b" + re.escape(verbo) + r"\b", corpo_lower))
        if ocorrencias >= 2:
            repetidos.append(f'"{verbo}" ({ocorrencias}×)')

    if repetidos:
        erros.append(ErroValidacao(
            "corpo_materia",
            f"verbos de atribuição genéricos usados repetidamente: {'; '.join(repetidos)}. "
            "Prefira: 'afirmou', 'disse', 'informou', 'segundo', 'de acordo com', 'conforme'."
        ))
    return erros


def validar_pacote_editorial_completo(dados: dict) -> list[ErroValidacao]:
    """
    Verifica se o pacote editorial está completo.
    Campos obrigatórios com conteúdo não vazio e não genérico.

    Retorna lista de ErroValidacao. Lista vazia = aprovado.
    """
    erros: list[ErroValidacao] = []
    campos_obrigatorios_pacote = [
        "titulo_seo", "subtitulo_curto", "retranca", "titulo_capa",
        "legenda_curta", "corpo_materia", "nome_da_fonte",
        "creditos_da_foto", "editoria", "canal", "slug",
    ]
    for campo in campos_obrigatorios_pacote:
        val = dados.get(campo)
        if not isinstance(val, str) or not val.strip():
            erros.append(ErroValidacao(
                campo,
                f"campo obrigatório do pacote editorial ausente ou vazio. "
                "O sistema não aceita output com campos faltando."
            ))

    # Tags devem existir e ter conteúdo
    tags = dados.get("tags")
    if not isinstance(tags, list) or len(tags) < TAGS_MIN:
        erros.append(ErroValidacao(
            "tags",
            f"campo 'tags' ausente, não é lista ou tem menos de {TAGS_MIN} elementos. "
            "O pacote editorial exige tags completas."
        ))

    return erros


def validar_precisao_titulo(
    dados: dict,
    numeros_tipados: list[dict],
) -> list[ErroValidacao]:
    """
    Verifica se o titulo_seo e titulo_capa preservam a categoria semântica dos
    números centrais da fonte — mesma lógica de validar_precisao_numerica() mas
    aplicada especificamente aos títulos.

    numeros_tipados: lista produzida por extracao.anotar_tipos_numericos().
    Retorna lista de ErroValidacao.
    """
    erros: list[ErroValidacao] = []
    if not numeros_tipados:
        return erros

    titulo_seo  = (dados.get("titulo_seo",  "") or "").lower()
    titulo_capa = (dados.get("titulo_capa", "") or "").lower()
    texto_titulos = titulo_seo + " " + titulo_capa

    # Mesmos padrões de confusão da validação de corpo
    _PADROES_CONFUSAO_TITULO: dict[str, list[tuple[str, str]]] = {
        "participacao": [
            (r"r\$\s*[\d,.]+", "participação de mercado (%) descrita como valor R$ no título"),
            (r"receita\s+de\s+[\d,.]+", "participação descrita como receita no título"),
        ],
        "receita": [
            (r"[\d,.]+\s*%\s+(?:do|de|da)\s+mercado", "receita (R$) descrita como % de mercado no título"),
        ],
        "estimativa": [
            (r"\b(?:é|foi|atingiu|alcançou|chegou\s+a)\s+[\d,.]+", "estimativa apresentada como fato no título"),
        ],
        "percentual_generico": [
            (r"r\$\s*[\d,.]+\s*(?:mil(?:hões?)?|bilhões?)?", "percentual (%) descrito como valor R$ no título"),
        ],
    }

    for num in numeros_tipados:
        tipo = num.get("tipo", "desconhecido")
        valor_str = num.get("valor", "")
        if tipo not in _PADROES_CONFUSAO_TITULO:
            continue

        m = re.search(r"[\d,.]+", valor_str)
        if not m:
            continue
        num_digits = m.group(0)

        if num_digits not in texto_titulos:
            continue  # número não está no título — sem confusão a verificar

        pos = texto_titulos.find(num_digits)
        start = max(0, pos - 60)
        end   = min(len(texto_titulos), pos + 60)
        ctx   = texto_titulos[start:end]

        # Para participação (%): se o número aparece com % no contexto imediato,
        # está na categoria correta — não reportar como confusão mesmo que o título
        # também mencione valores R$ de outra variável (ex: receita).
        if tipo == "participacao":
            ctx_imediato = texto_titulos[max(0, pos - 20):min(len(texto_titulos), pos + 20)]
            if re.search(r"\d+\s*%", ctx_imediato):
                continue  # número está com % no título — contexto correto

        # Para receita (R$): se o número está próximo de R$, está correto
        if tipo == "receita":
            ctx_imediato = texto_titulos[max(0, pos - 30):min(len(texto_titulos), pos + 30)]
            if re.search(r"r\$", ctx_imediato):
                continue  # número está com R$ no título — contexto correto

        for padrao, descricao in _PADROES_CONFUSAO_TITULO[tipo]:
            if re.search(padrao, ctx, re.IGNORECASE):
                erros.append(ErroValidacao(
                    "titulo_seo",
                    f"PRECISÃO TÍTULO: {descricao}. "
                    f"Valor da fonte: '{valor_str}' (tipo: {tipo}). "
                    f"Contexto no título: '...{ctx.strip()[:60]}...'"
                ))
                break

    return erros


def validar_multiplos_percentuais(
    dados: dict,
    numeros_tipados: list[dict],
) -> list[ErroValidacao]:
    """
    Quando a fonte contém dois ou mais percentuais relacionados ao mesmo assunto,
    verifica se o artigo os apresenta de forma que possa confundir o leitor.

    Detecta:
    - dois percentuais numéricos próximos no texto sem explicação de contexto
    - percentuais que se somam a mais de 100% sem explicação
    - percentuais que parecem contraditórios (um alto, um baixo) sem atribuição distinta

    Retorna lista de ErroValidacao.
    """
    erros: list[ErroValidacao] = []
    corpo = (dados.get("corpo_materia") or dados.get("texto_final", "")).strip()
    if not corpo or not numeros_tipados:
        return erros

    # Extrai todos os percentuais que aparecem no corpo
    _percentuais_no_corpo = re.findall(
        r"(\d+(?:[,\.]\d+)?)\s*%(?:\s+(?:do|de|da|dos|das)\s+\w+)?",
        corpo,
        re.IGNORECASE
    )
    if len(_percentuais_no_corpo) < 2:
        return erros  # zero ou um percentual — sem risco de confusão

    # Conta percentuais da fonte que têm tipos distintos de participação
    percentuais_fonte = [
        n for n in numeros_tipados
        if n.get("tipo") in ("participacao", "percentual_generico", "percentual_taxa", "ponto_percentual")
    ]
    if len(percentuais_fonte) < 2:
        return erros  # fonte tem apenas um percentual — não há confusão a verificar

    # Verifica se os percentuais numéricos no artigo somam > 100% sem contexto de adição
    valores_numericos = []
    for p in _percentuais_no_corpo:
        try:
            v = float(p.replace(",", "."))
            if 0 < v <= 100:
                valores_numericos.append(v)
        except ValueError:
            pass

    if len(valores_numericos) >= 2:
        soma = sum(valores_numericos)
        # Dois percentuais distintos com soma > 100% e sem palavras de adição = suspeito
        texto_lower = corpo.lower()
        # "total de" só conta como contexto de soma quando seguido de % (não de R$, bilhões, etc.)
        _tem_contexto_soma = any(
            term in texto_lower
            for term in ["somam", "juntos", "combinados", "ao todo",
                         "adicionando", "além de", "e mais"]
        ) or bool(re.search(r"total de\s+\d+(?:[,\.]\d+)?\s*%", texto_lower))
        _tem_atribuicao_distinta = len(re.findall(
            r"(?:segundo|de acordo com|conforme|afirmou|disse|informou)\s+\w+",
            texto_lower
        )) >= 2

        if soma > 100 and not _tem_contexto_soma and not _tem_atribuicao_distinta:
            erros.append(ErroValidacao(
                "corpo_materia",
                f"PERCENTUAIS MÚLTIPLOS: o artigo apresenta {len(valores_numericos)} percentuais "
                f"({', '.join(str(v)+'%' for v in valores_numericos[:4])}) que somam {soma:.1f}%, "
                "sem explicação de contexto ou atribuição distinta. "
                "Mantenha apenas o percentual central ou explique a diferença."
            ))
        elif len(valores_numericos) >= 3 and not _tem_contexto_soma:
            # 3+ percentuais sem contexto de adição é sempre suspeito
            erros.append(ErroValidacao(
                "corpo_materia",
                f"PERCENTUAIS MÚLTIPLOS: o artigo apresenta {len(valores_numericos)} percentuais "
                f"({', '.join(str(v)+'%' for v in valores_numericos[:5])}). "
                "Certifique-se de que cada percentual está contextualizado e não parece contraditório."
            ))

    return erros


def validar_consistencia_titulo_corpo(dados: dict) -> list[ErroValidacao]:
    """
    Verifica se o título e o corpo descrevem o mesmo fato principal.

    Detecta inconsistências grosseiras:
    - número mencionado no título não aparece no corpo
    - título menciona entidade/pessoa central que o corpo não menciona
    - subtítulo contradiz o título (palavras negativas no subtítulo quando
      título é positivo, ou vice-versa)

    Retorna lista de ErroValidacao.
    """
    erros: list[ErroValidacao] = []

    titulo   = (dados.get("titulo_seo",       "") or "").strip()
    subtit   = (dados.get("subtitulo_curto",  "") or "").strip()
    corpo    = (dados.get("corpo_materia") or dados.get("texto_final", "")).strip()

    if not titulo or not corpo:
        return erros

    titulo_lower = titulo.lower()
    corpo_lower  = corpo.lower()

    # 1. Números no título devem aparecer no corpo
    numeros_titulo = re.findall(r"\d+(?:[,\.]\d+)?(?:\s*%|\s*mil(?:hões?)?|\s*bilhões?)?", titulo)
    for num in numeros_titulo:
        num_base = re.sub(r"[^\d,\.]", "", num).rstrip(",.")
        if len(num_base) >= 2 and num_base not in corpo_lower:
            erros.append(ErroValidacao(
                "titulo_seo",
                f"CONSISTÊNCIA TÍTULO-CORPO: o número '{num}' aparece no título "
                f"mas não foi encontrado no corpo da matéria. "
                "Título e corpo devem descrever o mesmo fato com os mesmos dados."
            ))

    # 2. Entidades/nomes próprios centrais no título devem aparecer no corpo.
    # Palavras com 4+ letras e iniciais maiúsculas no título (prováveis nomes/siglas).
    # REGRA: siglas all-uppercase (ex: TJRJ, STJ, PF) são aceitas se qualquer parte
    # do nome expandido aparecer no corpo (ex: "Tribunal" aceita "TJRJ" no título).
    palavras_titulo = titulo.split()
    # Stopwords de início de frase (primeira letra maiúscula, não é entidade)
    _stopwords_titulo = {
        "esse", "este", "esta", "esses", "estes", "estas",
        "para", "pela", "pelo", "pelos", "pelas",
        "como", "mais", "menos", "com", "que", "por",
        "nos", "nas", "dos", "das", "num", "numa",
        "além", "após", "desde", "sobre", "entre",
        "caso", "onde", "quando", "ainda", "também",
        # Conectivos e verbos comuns que podem iniciar com maiúscula
        "após", "ante", "ante", "durante", "mediante",
    }
    entidades_titulo = [
        p.rstrip(".,;:!?") for p in palavras_titulo
        if len(p.rstrip(".,;:!?")) >= 4
        and p[0].isupper()
        and p.rstrip(".,;:!?").lower() not in _stopwords_titulo
    ]
    for entidade in entidades_titulo:
        ent_lower = entidade.lower()
        # Se a entidade está diretamente no corpo, OK
        if ent_lower in corpo_lower:
            continue
        # Se é uma sigla (todas maiúsculas), verifica se parte do nome expandido aparece
        # Ex: "TJRJ" aceita "tribunal" no corpo; "PF" aceita "federal" ou "polícia"
        _eh_sigla = entidade.isupper() and len(entidade) >= 2
        if _eh_sigla:
            # Aceita se qualquer palavra de 4+ letras da sigla aparece no corpo
            # (heurística: partes do nome expandido costumam estar no corpo)
            _partes_conhecidas = {
                "TJRJ":  ["tribunal", "justiça", "rio de janeiro"],
                "STJ":   ["superior", "tribunal", "justiça"],
                "STF":   ["supremo", "tribunal", "federal"],
                "PF":    ["polícia", "federal"],
                "PMERJ": ["polícia", "militar"],
                "ALERJ": ["assembleia", "legislativa", "rio"],
                "OAB":   ["ordem", "advogados"],
                "MP":    ["ministério", "público", "promotor", "procurador"],
                "CNJ":   ["conselho", "nacional", "justiça"],
                "TCU":   ["tribunal", "contas", "união"],
                "AGU":   ["advocacia", "geral", "união"],
                "TSE":   ["tribunal", "superior", "eleitoral"],
                "TST":   ["tribunal", "superior", "trabalho"],
                "TJSP":  ["tribunal", "justiça", "paulo"],
                "PCERJ": ["polícia", "civil"],
                "SEOP":  ["secretaria", "obras"],
            }
            partes = _partes_conhecidas.get(entidade, [])
            if partes and any(p in corpo_lower for p in partes):
                continue  # sigla reconhecida e expandida no corpo — OK
            # Sigla desconhecida: verifica se pelo menos 2 chars da sigla aparecem como parte de palavra
            # (evita falsos positivos para siglas genéricas)
            _chars_sigla = entidade.lower()
            _match_parcial = any(
                _chars_sigla[:3] in palavra.lower() or _chars_sigla[-3:] in palavra.lower()
                for palavra in corpo_lower.split()
                if len(palavra) >= 4
            )
            if _match_parcial:
                continue
            # Sigla desconhecida e sem match parcial — pode ser entidade ausente
            # Mas apenas reporta se a sigla tem 4+ chars (evita "PM", "PL", etc.)
            if len(entidade) >= 4:
                erros.append(ErroValidacao(
                    "titulo_seo",
                    f"CONSISTÊNCIA TÍTULO-CORPO: '{entidade}' aparece no título "
                    f"mas não foi encontrado no corpo (nem sua forma expandida). "
                    "Verificar se o título descreve o mesmo fato que o corpo."
                ))
        else:
            # Palavra capitalizada (não sigla) — verifica presença literal
            # Aceita se pelo menos 5 chars iniciais da palavra aparecem no corpo
            _stem = ent_lower[:5] if len(ent_lower) >= 5 else ent_lower
            if _stem not in corpo_lower:
                erros.append(ErroValidacao(
                    "titulo_seo",
                    f"CONSISTÊNCIA TÍTULO-CORPO: '{entidade}' aparece no título "
                    f"mas não foi encontrado no corpo. "
                    "Verificar se o título descreve o mesmo fato que o corpo."
                ))

    return erros


def enriquecer_com_observacoes(dados: dict, erros: list[ErroValidacao]) -> dict:
    """
    Adiciona os campos 'observacoes_editoriais' e 'erros_validacao' ao dict do artigo.
    Estes campos são exigidos pelo pacote editorial completo (regra 9).

    - erros_validacao: lista de strings descrevendo cada erro programático encontrado
    - observacoes_editoriais: lista de observações não-bloqueantes (avisos, sugestões)

    Retorna o dict enriquecido (modifica in-place e retorna).
    """
    dados["erros_validacao"] = [
        f"{e.campo}: {e.motivo}" for e in erros
    ] if erros else []

    # observacoes_editoriais: avisos não-bloqueantes baseados nos campos
    obs: list[str] = []
    corpo = (dados.get("corpo_materia") or dados.get("texto_final", "")).strip()
    titulo = (dados.get("titulo_seo", "") or "").strip()

    if corpo and len(corpo) < 300:
        obs.append("Corpo da matéria curto — verifique se todos os fatos essenciais foram preservados.")

    if titulo and len(titulo) < 45:
        obs.append("Título SEO curto — considere expandir com nome do órgão, localidade ou consequência.")

    n_pars = len([p for p in corpo.split("\n\n") if p.strip()]) if corpo else 0
    if n_pars == 1 and len(corpo) > 300:
        obs.append("Corpo sem divisão em parágrafos — verifique se os \\n\\n estão corretos.")

    if not dados.get("legenda_instagram"):
        obs.append("legenda_instagram ausente — recomendado para distribuição social.")

    dados["observacoes_editoriais"] = obs
    return dados


def completar_com_defaults(dados: dict, schema: dict) -> dict:
    """
    Completa campos ausentes com defaults do schema.
    Garante que todos os campos obrigatórios existam.
    """
    resultado = dict(schema)
    for k, v in dados.items():
        if k in resultado:
            if isinstance(v, dict) and isinstance(resultado[k], dict):
                resultado[k] = completar_com_defaults(v, resultado[k])
            else:
                resultado[k] = v
    return resultado


def normalizar_tags(tags_raw: Any) -> list[str]:
    """
    Normaliza o campo tags para sempre ser lista de strings.
    Aceita string separada por vírgula ou lista.
    """
    if isinstance(tags_raw, list):
        return [str(t).strip() for t in tags_raw if str(t).strip()]
    if isinstance(tags_raw, str):
        return [t.strip() for t in tags_raw.split(",") if t.strip()]
    return []
