"""
ia/pipeline.py — CAMADAS 7, 8 e 9: Pipeline central de geração e auditoria.

Orquestra o fluxo completo:
  1. Monta system prompt + contexto estrutural + memória dinâmica
  2. Chama a OpenAI para GERAÇÃO (temperatura baixa, JSON fixo)
  3. Valida o JSON programaticamente
  4. Chama a OpenAI para AUDITORIA (chamada separada, papel exclusivo)
  5. Valida o JSON de auditoria
  6. Bloqueia publicação se auditoria reprovar
  7. Persiste aprendizado na memória editorial
  8. Registra logs completos

O modelo é executor. Nunca agente livre.
Nenhuma ação relevante ocorre sem: política editorial + contexto + memória + feedback + auditoria.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from zoneinfo import ZoneInfo

from ururau.ia.politica_editorial import (
    montar_system_prompt,
    montar_contexto_para_acao,
)
from ururau.ia.schemas import (
    extrair_json,
    validar_geracao,
    validar_auditoria,
    validar_precisao_numerica,
    validar_precisao_titulo,
    validar_multiplos_percentuais,
    validar_consistencia_titulo_corpo,
    validar_fechamento_interpretativo,
    validar_repeticao_paragrafos,
    validar_citacao_excessiva,
    validar_verbos_crutch,
    validar_pacote_editorial_completo,
    enriquecer_com_observacoes,
    gerar_status_validacao,
    completar_com_defaults,
    normalizar_tags,
    SCHEMA_GERACAO,
    SCHEMA_AUDITORIA,
)
from ururau.editorial.extracao import validar_dados_essenciais, anotar_tipos_numericos
from ururau.ia.politica_editorial import (
    EXPRESSOES_PROIBIDAS,
    DIMENSAO_IMAGEM_PADRAO,
    CANAIS_VALIDOS,
    FRASES_UNSUPPORTED,
    TEXTO_MINIMO_CHARS_FONTE_CURTA,
)
from ururau.ia.memoria import obter_memoria

# ── Agente Editorial Ururau — system prompt definitivo ────────────────────────
# Importado aqui para ser enviado como `instructions` em TODA chamada de geração.
# Substitui o system_ger fragmentado por um único prompt editorial coerente.
try:
    from ururau.agents.agente_editorial_ururau import SYSTEM_PROMPT_EDITORIAL_URURAU as _SYSTEM_AGENTE
    _USA_AGENTE_EDITORIAL = True
except ImportError:
    _SYSTEM_AGENTE = ""
    _USA_AGENTE_EDITORIAL = False

if TYPE_CHECKING:
    from openai import OpenAI

TZ_BR = ZoneInfo("America/Sao_Paulo")

# ── Configurações de temperatura ──────────────────────────────────────────────
TEMPERATURE_GERACAO  = 0.3   # baixa: executor fiel
TEMPERATURE_AUDITORIA = 0.1  # muito baixa: auditor rigoroso
MAX_TENTATIVAS_GERACAO  = 2
MAX_TENTATIVAS_AUDITORIA = 2


# ── Funções de limpeza automática pré-validação ───────────────────────────────

def _remover_travessao(texto: str) -> str:
    """
    Remove travessões (— U+2014 e – U+2013) de um texto,
    substituindo-os por vírgula + espaço para manter a legibilidade.
    """
    import re
    # Travessão entre espaços → vírgula
    texto = re.sub(r"\s*[—–]\s*", ", ", texto)
    # Travessão residual sem espaço → vírgula
    texto = re.sub(r"[—–]", ", ", texto)
    return texto


def _limpar_expressoes_proibidas(texto: str) -> str:
    """
    Substitui automaticamente expressões proibidas no texto por suas
    alternativas definidas em EXPRESSOES_PROIBIDAS.

    Expressões sem substituto (None) são sinalizadas mas mantidas —
    a IA será informada para reescrevê-las na próxima tentativa.
    """
    if not texto:
        return texto

    resultado = texto
    # Ordena por tamanho decrescente para evitar substituição parcial de frases longas
    expressoes_ordenadas = sorted(
        EXPRESSOES_PROIBIDAS.items(),
        key=lambda kv: len(kv[0]),
        reverse=True,
    )
    import re as _re
    for expr, substituto in expressoes_ordenadas:
        if substituto is not None:
            # Substituição case-insensitive preservando a posição
            padrao = _re.compile(_re.escape(expr), _re.IGNORECASE)
            resultado = padrao.sub(substituto, resultado)
        # Se substituto é None, mantém mas será flagrado na validação
    return resultado


def _corrigir_paragrafos(texto: str) -> str:
    """
    Garante que o corpo_materia tenha parágrafos separados por \\n\\n.

    A IA às vezes entrega o texto como um bloco único sem quebras, ou usa
    apenas \\n simples. Esta função normaliza para sempre \\n\\n entre parágrafos.

    Estratégia:
    1. Se o texto já tem \\n\\n → mantém (apenas normaliza espaços extras)
    2. Se tem \\n simples → converte para \\n\\n
    3. Se é um bloco único → detecta pontos finais seguidos de maiúscula e insere \\n\\n
    """
    import re as _re

    if not texto or not texto.strip():
        return texto

    # Remove espaços múltiplos entre parágrafos (ex: \n\n\n → \n\n)
    texto = _re.sub(r"\n{3,}", "\n\n", texto)

    # Se já tem parágrafos com \n\n, está ok
    if "\n\n" in texto:
        # Normaliza: \n simples DENTRO de parágrafo existente — deixa como está
        return texto.strip()

    # Se tem \n simples (sem \n\n), converte todos para \n\n
    if "\n" in texto:
        texto = texto.replace("\n", "\n\n")
        return texto.strip()

    # Bloco único sem quebra alguma: detecta fim de frase + início de nova frase
    # Padrão: ponto/exclamação/? + espaço + letra maiúscula (início de novo parágrafo)
    sentencas = _re.split(r"(?<=[.!?])\s+(?=[A-ZÁÀÃÂÉÊÍÓÔÕÚÜÇ])", texto)

    if len(sentencas) <= 1:
        return texto.strip()

    # Agrupa sentenças em parágrafos de 2-3 frases cada.
    # NÃO força número mínimo de parágrafos — deixa o conteúdo determinar o tamanho.
    # Textos curtos geram poucos parágrafos (2-3), textos longos geram mais.
    import math as _math
    n = len(sentencas)
    # 2 frases por parágrafo como padrão (máximo 3). Se texto muito curto, 1 por parágrafo.
    frases_por_grupo = 2 if n >= 4 else 1

    paragrafos: list[str] = []
    grupo: list[str] = []
    for i, s in enumerate(sentencas):
        grupo.append(s)
        if len(grupo) >= frases_por_grupo or i == len(sentencas) - 1:
            paragrafos.append(" ".join(grupo))
            grupo = []

    return "\n\n".join(paragrafos).strip()


def _limpar_json_geracao(raw: dict) -> dict:
    """
    Aplica limpezas automáticas ao JSON bruto da IA antes da validação:
    1. Remove travessões de todos os campos textuais
    2. Substitui expressões proibidas onde há substituto disponível
    3. Normaliza alias: texto_final → corpo_materia
    4. Normaliza alias: subtitulo → subtitulo_curto
    5. Normaliza alias: legenda → legenda_curta
    6. Garante parágrafos separados por \\n\\n no corpo_materia
    """
    _CAMPOS_TEXTO = [
        "titulo_seo", "subtitulo_curto", "retranca", "titulo_capa",
        "corpo_materia", "legenda_curta", "legenda_instagram",
        "meta_description", "resumo_curto", "chamada_social",
    ]

    # Normaliza aliases de campos renomeados
    if "texto_final" in raw and not raw.get("corpo_materia"):
        raw["corpo_materia"] = raw.pop("texto_final")
    elif "texto_final" in raw and raw.get("corpo_materia"):
        raw.pop("texto_final", None)

    if "subtitulo" in raw and not raw.get("subtitulo_curto"):
        raw["subtitulo_curto"] = raw.pop("subtitulo")
    elif "subtitulo" in raw and raw.get("subtitulo_curto"):
        raw.pop("subtitulo", None)

    if "legenda" in raw and not raw.get("legenda_curta"):
        raw["legenda_curta"] = raw.pop("legenda")
    elif "legenda" in raw and raw.get("legenda_curta"):
        raw.pop("legenda", None)

    for campo in _CAMPOS_TEXTO:
        if isinstance(raw.get(campo), str):
            raw[campo] = _remover_travessao(raw[campo])
            if campo in ("corpo_materia", "titulo_seo"):
                raw[campo] = _limpar_expressoes_proibidas(raw[campo])

    # Garante parágrafos separados no corpo da matéria
    if isinstance(raw.get("corpo_materia"), str):
        raw["corpo_materia"] = _corrigir_paragrafos(raw["corpo_materia"])

    return raw


# ── Resultado do pipeline ─────────────────────────────────────────────────────

@dataclass
class ResultadoPipeline:
    """Resultado completo do pipeline de geração + auditoria."""
    sucesso: bool = False

    # JSON final aprovado (geração ou versão corrigida pela auditoria)
    dados_finais: dict = field(default_factory=dict)

    # JSONs intermediários
    json_geracao: dict = field(default_factory=dict)
    json_auditoria: dict = field(default_factory=dict)

    # Decisão de publicação
    aprovado_auditoria: bool = False
    bloqueado: bool = True
    status_publicacao: str = "bloquear"    # publicar_direto | salvar_rascunho | bloquear

    # Erros e violações
    erros_validacao_geracao: list[str] = field(default_factory=list)
    erros_validacao_auditoria: list[str] = field(default_factory=list)
    violacoes_factuais: list[str] = field(default_factory=list)
    violacoes_editoriais: list[str] = field(default_factory=list)
    todos_erros: list[str] = field(default_factory=list)

    # Log
    log: list[str] = field(default_factory=list)
    timestamp: str = ""
    modelo_usado: str = ""
    tentativas_geracao: int = 0
    tentativas_auditoria: int = 0

    def resumo(self) -> str:
        status = "APROVADO" if self.aprovado_auditoria else "REPROVADO"
        pub = self.status_publicacao.upper()
        n_erros = len(self.todos_erros)
        return (f"[PIPELINE] {status} | {pub} | "
                f"{n_erros} erros | {self.tentativas_geracao} ger. | "
                f"{self.tentativas_auditoria} aud.")


# ── Prompts de geração e auditoria ────────────────────────────────────────────

def _montar_prompt_geracao(
    pauta: dict,
    mapa_evidencias: dict,
    canal: str,
    contexto_redacao: str,
    bloco_memoria: str,
    instrucao_canal: str,
    template: dict,
    modo_operacional: str = "painel",
    modelo: str = "gpt-4.1-mini",
) -> tuple[str, str]:
    """
    Monta system prompt e user prompt para a etapa de geração.
    Retorna (system_prompt, user_prompt).
    """
    contextos = montar_contexto_para_acao("geracao", modo_operacional)
    system_prompt = montar_system_prompt(contextos)

    # Adiciona memória editorial ao system prompt
    if bloco_memoria:
        system_prompt += f"\n\n{bloco_memoria}"

    titulo_origem = pauta.get("titulo_origem", "")
    resumo_origem = pauta.get("resumo_origem", "")
    texto_fonte   = pauta.get("texto_fonte", "")
    dossie        = pauta.get("dossie", "")
    fonte_nome    = pauta.get("fonte_nome", "")
    link_origem   = pauta.get("link_origem", "")

    # Calcula tamanho da fonte para adaptar as instruções de tamanho do artigo
    _tamanho_fonte = len((texto_fonte or "") + " " + (dossie or "") + " " + (resumo_origem or ""))
    _fonte_curta = _tamanho_fonte < 800
    _fonte_muito_curta = _tamanho_fonte < 300

    # ── Monta lista de dados essenciais que OBRIGATORIAMENTE devem aparecer ──────
    _dados_num = mapa_evidencias.get("dados_numericos") or []
    _estudos   = mapa_evidencias.get("estudos_citados") or []
    _artigos   = mapa_evidencias.get("artigos_lei_citados") or []
    _impactos  = mapa_evidencias.get("impactos_citados") or []
    _argumentos = mapa_evidencias.get("argumentos_centrais") or []
    _pedidos   = mapa_evidencias.get("pedidos_ou_encaminhamentos") or []
    _base_jur  = mapa_evidencias.get("base_juridica") or ""
    _declaracoes = mapa_evidencias.get("declaracoes_identificadas") or []

    _bloco_obrigatorio = ""
    if any([_dados_num, _estudos, _artigos, _impactos, _argumentos, _pedidos, _base_jur]):
        linhas = ["== DADOS ESSENCIAIS — TODOS OBRIGATÓRIOS NO CORPO DA MATÉRIA ==",
                  "A matéria será REPROVADA se qualquer item abaixo estiver ausente.",
                  ""]
        if _dados_num:
            linhas.append("NÚMEROS E DADOS QUANTITATIVOS (citar todos):")
            linhas += [f"  • {d}" for d in _dados_num[:10]]
        if _estudos:
            linhas.append("\nESTUDOS E PESQUISAS (citar com atribuição):")
            linhas += [f"  • {e}" for e in _estudos[:6]]
        if _artigos:
            linhas.append("\nARTIGOS DE LEI / CONSTITUIÇÃO (preservar exatamente):")
            linhas += [f"  • {a}" for a in _artigos[:6]]
        if _impactos:
            linhas.append("\nIMPACTOS CITADOS (explicar no texto):")
            linhas += [f"  • {i}" for i in _impactos[:8]]
        if _argumentos:
            linhas.append("\nARGUMENTOS CENTRAIS (preservar substância):")
            linhas += [f"  • {a}" for a in _argumentos[:6]]
        if _pedidos:
            linhas.append("\nPEDIDOS / ENCAMINHAMENTOS (incluir no texto):")
            linhas += [f"  • {p}" for p in _pedidos[:4]]
        if _base_jur:
            linhas.append(f"\nBASE JURÍDICA (citar): {_base_jur}")
        _bloco_obrigatorio = "\n".join(linhas)

    _bloco_declaracoes = ""
    if _declaracoes:
        _bloco_declaracoes = (
            "== DECLARAÇÕES COM ATRIBUIÇÃO CORRETA ==\n" +
            "\n".join(f"  • {d}" for d in _declaracoes[:4])
        )

    # Instrução de tamanho adaptada à fonte
    if _fonte_muito_curta:
        _instrucao_tamanho = (
            "TAMANHO DO ARTIGO: fonte muito curta. "
            "Gere um artigo CURTO: 2-4 parágrafos, preservando todos os fatos disponíveis. "
            "NÃO expanda com informações ausentes da fonte."
        )
        _min_pars_instrucao = "2-4"
    elif _fonte_curta:
        _instrucao_tamanho = (
            "TAMANHO DO ARTIGO: fonte curta. "
            "Gere um artigo PROPORCIONAL: 3-5 parágrafos, preservando todos os fatos. "
            "NÃO expanda com informações ausentes da fonte."
        )
        _min_pars_instrucao = "3-5"
    else:
        _instrucao_tamanho = (
            "TAMANHO DO ARTIGO: fonte completa. "
            "Gere artigo completo: 5-8 parágrafos com todos os dados essenciais."
        )
        _min_pars_instrucao = "5-8"

    user_prompt = f"""
== PORTAL URURAU — GERAÇÃO EDITORIAL (modelo: {modelo if isinstance(modelo, str) else 'gpt-4.1-mini'}) ==
Esta matéria será publicada no Portal Ururau (Campos dos Goytacazes, RJ).
Modelo: GPT-4.1-mini | Objetivo: SEO jornalístico para Google Search e Google Discover.
Tamanho da fonte: {_tamanho_fonte} chars | Fonte curta: {_fonte_curta}

== CANAL: {canal.upper()} ==
{instrucao_canal}

== TEXTO-FONTE COMPLETO (leia com atenção antes de escrever) ==
{(texto_fonte + chr(10) + dossie)[:7000]}

== FATOS EXTRAÍDOS E CONFIRMADOS (base factual obrigatória) ==
{contexto_redacao}

{_bloco_obrigatorio}

{_bloco_declaracoes}

== REGRAS ABSOLUTAS DO CORPO DA MATÉRIA ==

1. LEAD OBRIGATÓRIO (1º parágrafo):
   Responda: quem, o quê, onde, quando, por quê / consequência.
   Não abra com "A matéria trata de..." ou qualquer frase genérica.
   Comece pelo fato, pela entidade ou pelo personagem principal.

2. PARÁGRAFOS:
   - {_instrucao_tamanho}
   - Número de parágrafos: {_min_pars_instrucao}.
   - Cada parágrafo: 2-4 frases. Não mais.
   - SEPARAÇÃO OBRIGATÓRIA: use \\n\\n entre cada parágrafo no JSON.
     Exemplo: "Parágrafo 1.\\n\\nParágrafo 2.\\n\\nParágrafo 3."
   - NUNCA entregue o corpo como bloco único sem quebras.

3. SUBSTÂNCIA OBRIGATÓRIA:
   - Todos os dados numéricos listados acima DEVEM aparecer no texto.
   - Todos os estudos citados DEVEM aparecer com atribuição.
   - Todos os artigos de lei/constituição DEVEM ser citados.
   - Todos os impactos DEVEM ser explicados no texto.
   - Todos os argumentos centrais DEVEM ser preservados.
   - Todos os pedidos/encaminhamentos DEVEM aparecer.
   - Matéria SEM esses dados = REPROVADA automaticamente.

4. REGRA DE FIDELIDADE — SEM EXPANSÃO ARTIFICIAL:
   NUNCA adicione informação não presente na fonte, especialmente:
   - "o próximo passo será..." (se a fonte não disser isso)
   - "as investigações seguem..." (se a fonte não confirmar)
   - "as autoridades continuarão..." (se não declarado na fonte)
   - "a medida visa garantir..." (se não declarado na fonte)
   - "novas informações serão divulgadas..." (se não declarado)
   - "o caso deve ter novos desdobramentos..." (se não declarado)
   - "a população aguarda respostas..." (se não declarado)
   - contexto histórico genérico não presente na fonte
   Um artigo curto e preciso PASSA. Um artigo longo com dados inventados FALHA.

5. REGRA DE DATA — NUNCA INVENTAR:
   Se a fonte diz "nesta quinta-feira (23)" → escreva "nesta quinta-feira (23)".
   Se a fonte diz "no dia 15" → escreva "no dia 15". NÃO invente mês ou ano.
   Só escreva data completa (dia+mês+ano) se a fonte apresentar os três.
   Preserve SEMPRE a referência temporal exatamente como aparece na fonte.

6. SEO JORNALÍSTICO:
   - titulo_seo: palavra-chave ou fato principal NO INÍCIO (não "Como...", não "Por que...").
   - Entre 40 e 89 caracteres. Factual. Sem clickbait. Sem interrogação/exclamação.
   - O título deve conter personagem, instituição ou tema que as pessoas buscariam no Google.
   - Exemplo bom: "Fecomércio-RJ critica pressa no fim da escala 6x1 e defende negociação"
   - Exemplo ruim: "Fecomércio-RJ critica debate acelerado e pede cautela" (genérico)

7. ORIGINALIDADE ABSOLUTA:
   - Não copie frases da fonte. Reescreva com apuração própria.
   - Não siga a ordem exata dos parágrafos da fonte.
   - Preserve DADOS (números, nomes, datas, artigos), mas mude a FORMA.

8. PROIBIÇÕES:
   - NUNCA use travessão (— ou –). Use vírgula, dois-pontos ou ponto.
   - NUNCA use: "reacende", "levanta debate", "acende alerta", "em meio a",
     "cenário complexo", "bastidores", "vale lembrar", "é importante destacar",
     "especialistas apontam", "analistas avaliam", "gera preocupação",
     "um novo capítulo", "não passou despercebido", "consolida tendência".
   - NUNCA invente fato ausente na fonte.
   - NUNCA inclua nome do portal de origem nas tags.

9. TAGS:
   - Entre 5 e 12 tags.
   - Incluir: personagem principal, instituição, cidade/estado, tema econômico/jurídico/político,
     termos que alguém buscaria no Google.
   - NÃO incluir nome do portal de origem.

== SCHEMA DE SAÍDA OBRIGATÓRIO ==
Retorne APENAS o JSON abaixo, completamente preenchido. Sem texto antes ou depois. Sem markdown.

{json.dumps(SCHEMA_GERACAO, ensure_ascii=False, indent=2)}

== CHECKLIST FINAL ANTES DE ENTREGAR ==
□ titulo_seo: 40-89 chars, fato/personagem/instituição no início
□ subtitulo_curto: ≤200 chars, complementa o título sem repetir
□ titulo_capa: 20-60 chars, forte para home do site
□ legenda_curta: ≤100 chars, factual
□ corpo_materia: {_min_pars_instrucao} parágrafos com \\n\\n, TODOS os dados essenciais presentes
□ tags: 5-12 strings, SEM portal de origem
□ canal: um de {CANAIS_VALIDOS}
□ imagem.dimensao_final: sempre "{DIMENSAO_IMAGEM_PADRAO}"
□ ZERO travessão em qualquer campo
□ ZERO expressões proibidas
□ ZERO fatos inventados
□ ZERO datas inventadas (preserve datas relativas como na fonte)
□ ZERO expansão artificial com "próximo passo", "investigações seguem", etc.
""".strip()

    return system_prompt, user_prompt


def _montar_prompt_auditoria(
    json_geracao: dict,
    fonte_bruta: str,
    mapa_evidencias: dict,
    bloco_memoria: str,
    canal: str,
    modo_operacional: str = "painel",
) -> tuple[str, str]:
    """
    Monta system prompt e user prompt para a etapa de auditoria.
    Retorna (system_prompt, user_prompt).
    """
    contextos = montar_contexto_para_acao("auditoria", modo_operacional)
    system_prompt = montar_system_prompt(contextos)

    if bloco_memoria:
        system_prompt += f"\n\n{bloco_memoria}"

    user_prompt = f"""
== MATERIAL ORIGINAL DA FONTE ==
{fonte_bruta[:4000]}

== MAPA DE EVIDÊNCIAS EXTRAÍDAS ==
Fato principal: {mapa_evidencias.get('fato_principal', '')}
Quem: {', '.join(mapa_evidencias.get('quem', [])[:6])}
Onde: {mapa_evidencias.get('onde', '')}
Quando: {mapa_evidencias.get('quando', '')}
Status real do fato: {mapa_evidencias.get('status_atual', '')}
Fonte primária: {mapa_evidencias.get('fonte_primaria', '')}
Inferências a evitar: {', '.join(mapa_evidencias.get('inferencias_a_evitar', [])[:4])}
Elementos sem fonte: {', '.join(mapa_evidencias.get('elementos_sem_fonte', [])[:4])}
Grau de confiança: {mapa_evidencias.get('grau_confianca', '')}
Risco editorial: {mapa_evidencias.get('risco_editorial', '')}

== JSON GERADO PARA AUDITORIA ==
{json.dumps(json_geracao, ensure_ascii=False, indent=2)[:6000]}

== CANAL ==
{canal}

== SUA TAREFA ==
Audite o JSON gerado com máximo rigor. Verifique:
1. Factualidade: algum fato foi inventado ou extrapolado além da fonte?
2. Data: a data está correta e sem conversão indevida?
3. Status do fato: foi inflado? (ex: debate virou lei, investigação virou condenação?)
4. Atribuição: afirmações importantes têm atribuição correta?
5. Título SEO: dentro de 40-89 chars? Palavra-chave no início?
6. Título capa: dentro de 20-60 chars?
7. Retranca: específica e não genérica?
8. Nome da fonte: correto e dentro do limite?
9. Crédito da foto: correto, dentro do limite, sem "Internet"?
10. Tags: array com 5-8 elementos?
11. Canal: dentro da taxonomia válida?
12. Expressões de IA: alguma expressão proibida no texto?
13. Travessão: há travessão (— ou –) no texto?
14. Imagem: dimensão é "{DIMENSAO_IMAGEM_PADRAO}"? Licença verificada?
15. Fluxo: status_publicacao_sugerido coerente com o modo ({canal}/{modo_operacional})?
16. Memória: algum erro já registrado se repetiu?

Se tudo estiver correto: aprovado=true, bloquear_publicacao=false.
Se houver qualquer problema: aprovado=false, bloquear_publicacao=true, detalhar erros.

Em versao_corrigida, entregue a versão corrigida dos campos problemáticos.

Retorne APENAS o JSON de auditoria abaixo, sem texto fora do JSON:
{json.dumps(SCHEMA_AUDITORIA, ensure_ascii=False, indent=2)}
""".strip()

    return system_prompt, user_prompt


# ── Pipeline principal ────────────────────────────────────────────────────────

def executar_pipeline(
    pauta: dict,
    mapa_evidencias: dict,
    contexto_redacao: str,
    canal: str,
    client: "OpenAI",
    modelo: str,
    instrucao_canal: str = "",
    template: dict | None = None,
    modo_operacional: str = "painel",
    caminho_db: str = "ururau.db",
) -> ResultadoPipeline:
    """
    Pipeline completo de geração + auditoria editorial.

    Parâmetros:
      - pauta: dict com título, resumo, texto_fonte, dossie, fonte_nome, link_origem
      - mapa_evidencias: dict retornado por extrair_mapa_evidencias()
      - contexto_redacao: string retornada por mapa_para_contexto_redacao()
      - canal: canal editorial de destino
      - client: instância OpenAI
      - modelo: nome do modelo OpenAI
      - instrucao_canal: instrução editorial específica do canal
      - template: template estrutural do canal
      - modo_operacional: "painel" ou "monitor"
      - caminho_db: caminho do banco SQLite

    Retorna ResultadoPipeline com decisão de publicação e dados finais.
    """
    ts = datetime.now(TZ_BR).isoformat(timespec="seconds")
    log: list[str] = [
        f"[{ts}] PIPELINE INICIADO | canal={canal} | modo={modo_operacional} | modelo={modelo}",
        f"[PIPELINE] Fluxo real: workflow → redacao.gerar_materia() → pipeline.executar_pipeline()",
        f"[PIPELINE] System prompt: {'Agente Editorial Ururau' if _USA_AGENTE_EDITORIAL else 'politica_editorial.py'}",
        f"[PIPELINE] Modelo configurado: {modelo} | gpt-4.1-mini obrigatório ✓" if "gpt-4.1" in str(modelo) else f"[PIPELINE] ⚠ Modelo: {modelo} (recomendado: gpt-4.1-mini)",
    ]
    resultado = ResultadoPipeline(timestamp=ts, modelo_usado=modelo)

    # ── PRÉ-VALIDAÇÃO OBRIGATÓRIA: config da OpenAI ──────────────────────────
    # Verifica chave e modelo ANTES de qualquer chamada à API.
    # Se inválida: aborta imediatamente, salva como erro_configuracao.
    # NUNCA gera artigo parcial com fallback quando a API não está configurada.
    from ururau.config.settings import validate_openai_config, classify_openai_exception, CategoriaErro
    _cfg_result = validate_openai_config()
    if not _cfg_result:
        _err_cfg = _cfg_result.erro_dict
        log.append(f"[WORKFLOW] generation_aborted reason={_cfg_result.codigo}")
        log.append("[WORKFLOW] REGRA: API inválida → NUNCA gerar artigo parcial/fallback")
        resultado.log = log
        resultado.todos_erros = [_err_cfg.get("mensagem", "Configuração OpenAI inválida")]
        resultado.bloqueado = True
        resultado.status_publicacao = "bloquear"
        resultado.dados_finais = {
            "status_validacao": "erro_configuracao",
            "status_publicacao_sugerido": "salvar_rascunho",
            "auditoria_bloqueada": True,
            "revisao_humana_necessaria": True,
            "erros_validacao": [_err_cfg],
            "corpo_materia": "",
            "titulo_seo": "",
            "titulo_capa": "",
            "subtitulo_curto": "",
            "retranca": canal,
            "tags": [canal],
            "legenda_curta": "",
            "meta_description": "",
            "nome_da_fonte": "",
            "creditos_da_foto": "",
            "observacoes_editoriais": [
                f"⚠ Geração abortada: {_err_cfg.get('mensagem','')}",
                f"Sugestão: {_err_cfg.get('sugestao','')}",
            ],
            "_is_config_error": True,
        }
        resultado.erros_validacao_geracao = [_err_cfg.get("mensagem", "")]
        print(f"[WORKFLOW] generation_aborted reason={_cfg_result.codigo}")
        print(f"[REVIEW] saved_config_error_draft")
        return resultado

    # ── Log: metadados separados da fonte ─────────────────────────────────────
    _legendas_fonte       = pauta.get("_legendas_fonte", [])
    _creditos_fonte       = pauta.get("_creditos_fonte", [])
    _metadados_descartados = pauta.get("_metadados_descartados", [])
    if _metadados_descartados:
        log.append(
            f"[PIPELINE] Metadados da fonte separados: "
            f"{len(_metadados_descartados)} itens descartados | "
            f"legendas={len(_legendas_fonte)} | créditos={len(_creditos_fonte)}"
        )
        log.append("[PIPELINE] REGRA: legendas e créditos NÃO viraram fatos no prompt de geração ✓")

    if template is None:
        template = {}

    # ── Carrega memória editorial dinâmica ────────────────────────────────────
    mem = obter_memoria(caminho_db)
    editoria_hint = canal
    bloco_memoria = mem.montar_bloco_contexto(editoria=editoria_hint)
    log.append(f"[MEMORIA] Bloco montado: {len(bloco_memoria)} chars")

    # ── Fonte bruta para auditoria ────────────────────────────────────────────
    fonte_bruta = (
        (pauta.get("texto_fonte") or "") + "\n" +
        (pauta.get("dossie") or "") + "\n" +
        (pauta.get("resumo_origem") or "")
    )[:5000]

    # ════════════════════════════════════════════════════════════════
    # ETAPA 1: GERAÇÃO
    # ════════════════════════════════════════════════════════════════
    log.append("[GERACAO] Iniciando etapa de geração...")
    json_geracao: dict = {}
    erros_geracao: list[str] = []

    system_ger, user_ger = _montar_prompt_geracao(
        pauta=pauta,
        mapa_evidencias=mapa_evidencias,
        canal=canal,
        contexto_redacao=contexto_redacao,
        bloco_memoria=bloco_memoria,
        instrucao_canal=instrucao_canal,
        template=template,
        modo_operacional=modo_operacional,
        modelo=modelo,
    )

    # ── Seleciona o system prompt de geração ──────────────────────────────────
    # Se o Agente Editorial está disponível, usa seu system prompt definitivo
    # como instructions. O user_ger (contexto factual + dados obrigatórios) é mantido.
    if _USA_AGENTE_EDITORIAL and _SYSTEM_AGENTE:
        _system_geracao = _SYSTEM_AGENTE
        log.append(
            f"[GERACAO] SYSTEM: Agente Editorial Ururau ({len(_SYSTEM_AGENTE)} chars) ✓"
        )
    else:
        _system_geracao = system_ger
        log.append(
            f"[GERACAO] SYSTEM: politica_editorial.py ({len(system_ger)} chars)"
        )

    for tentativa in range(1, MAX_TENTATIVAS_GERACAO + 1):
        resultado.tentativas_geracao = tentativa
        log.append(f"[GERACAO] Tentativa {tentativa}/{MAX_TENTATIVAS_GERACAO}")
        try:
            resposta = client.responses.create(
                model=modelo,
                instructions=_system_geracao,
                input=user_ger,
                temperature=TEMPERATURE_GERACAO,
            )
            texto_resposta = resposta.output_text
            log.append(f"[GERACAO] Resposta recebida: {len(texto_resposta)} chars")

            raw = extrair_json(texto_resposta)

            # Aplica limpeza automática (travessões, expressões proibidas, aliases)
            raw = _limpar_json_geracao(raw)

            raw = completar_com_defaults(raw, SCHEMA_GERACAO)

            # Normaliza tags para sempre ser lista
            raw["tags"] = normalizar_tags(raw.get("tags", []))

            # Garante dimensão da imagem
            if isinstance(raw.get("imagem"), dict):
                raw["imagem"]["dimensao_final"] = DIMENSAO_IMAGEM_PADRAO

            # Validação estrutural (campos, tamanhos, travessão, expressões)
            # Passa tamanho_fonte para validação proporcional
            _tamanho_fonte_val = len(
                (pauta.get("texto_fonte") or "") +
                (pauta.get("dossie") or "") +
                (pauta.get("resumo_origem") or "")
            )
            errs = validar_geracao(raw, tamanho_fonte=_tamanho_fonte_val)
            erros_geracao = [f"{e.campo}: {e.motivo}" for e in errs]
            if erros_geracao:
                log.append(f"[GERACAO] {len(errs)} erro(s) estruturais: {erros_geracao[:3]}")

            # Validação de substância: dados essenciais da fonte preservados
            corpo = raw.get("corpo_materia") or raw.get("texto_final") or ""
            ausentes_essenciais = validar_dados_essenciais(corpo, mapa_evidencias)
            if ausentes_essenciais:
                log.append(
                    f"[GERACAO] {len(ausentes_essenciais)} dado(s) essencial(is) ausente(s): "
                    + str(ausentes_essenciais[:3])
                )
                erros_geracao += [f"dado_essencial: {a}" for a in ausentes_essenciais]

            # Validação de precisão numérica: verifica se categorias semânticas preservadas
            _texto_fonte_val = pauta.get("texto_fonte") or ""
            _dados_num_mapa  = mapa_evidencias.get("dados_numericos") or []
            _numeros_tipados = anotar_tipos_numericos(_texto_fonte_val, _dados_num_mapa)
            _erros_precisao  = validar_precisao_numerica(raw, _numeros_tipados)
            if _erros_precisao:
                log.append(
                    f"[GERACAO] {len(_erros_precisao)} erro(s) de precisão numérica: "
                    + str([e.motivo[:60] for e in _erros_precisao[:2]])
                )
                erros_geracao += [f"precisao_numerica: {e.motivo}" for e in _erros_precisao]

            # ── GATE DE QUALIDADE FINAL (novas regras editoriais) ─────────────
            # Verifica todas as regras de qualidade antes de qualquer publicação
            _erros_fechamento    = validar_fechamento_interpretativo(raw)
            _erros_repeticao     = validar_repeticao_paragrafos(raw)
            _erros_citacao       = validar_citacao_excessiva(raw)
            _erros_verbos        = validar_verbos_crutch(raw)
            _erros_pacote        = validar_pacote_editorial_completo(raw)
            _erros_prec_titulo   = validar_precisao_titulo(raw, _numeros_tipados)
            _erros_multi_percent = validar_multiplos_percentuais(raw, _numeros_tipados)

            _gate_extra = (
                [f"fechamento_interpretativo: {e.motivo}" for e in _erros_fechamento]
                + [f"repeticao_paragrafos: {e.motivo}" for e in _erros_repeticao]
                + [f"citacao_excessiva: {e.motivo}" for e in _erros_citacao]
                + [f"verbo_crutch: {e.motivo}" for e in _erros_verbos]
                + [f"pacote_incompleto: {e.campo}: {e.motivo}" for e in _erros_pacote]
                + [f"precisao_titulo: {e.motivo}" for e in _erros_prec_titulo]
                + [f"multiplos_percentuais: {e.motivo}" for e in _erros_multi_percent]
            )
            if _gate_extra:
                log.append(
                    f"[GATE_QUALIDADE] {len(_gate_extra)} falha(s): "
                    + " | ".join(_gate_extra[:3])
                )
                erros_geracao += _gate_extra
            else:
                log.append("[GATE_QUALIDADE] ✓ Todas as verificações de qualidade editorial passaram")

            # ── Enriquecimento com observações editoriais e erros_validacao ───
            # Adiciona os campos 'erros_validacao' e 'observacoes_editoriais' ao JSON final.
            # Estes campos são parte do pacote editorial completo exigido (regra 9).
            _todos_erros_gate = [e for erros_list in [
                errs, _erros_fechamento, _erros_repeticao, _erros_citacao,
                _erros_verbos, _erros_pacote, _erros_prec_titulo, _erros_multi_percent,
                _erros_precisao,
            ] for e in erros_list]
            enriquecer_com_observacoes(raw, _todos_erros_gate)

            # Log detalhado de diagnóstico
            _titulo_seo_len   = len(raw.get('titulo_seo',''))
            _titulo_capa_len  = len(raw.get('titulo_capa',''))
            _n_tags           = len(raw.get('tags',[]) if isinstance(raw.get('tags'), list) else [])
            _n_pars           = len([p for p in corpo.split("\n\n") if p.strip()])
            _corpo_lower      = corpo.lower()

            # SEO: termos do título na fonte
            _titulo_seo       = raw.get('titulo_seo', '')
            _fonte_completa   = (pauta.get("texto_fonte","") or "") + " " + (pauta.get("resumo_origem","") or "")
            _palavras_titulo  = [w for w in _titulo_seo.lower().split() if len(w) >= 5]
            _palavras_na_fonte = [w for w in _palavras_titulo if w in _fonte_completa.lower()]
            _seo_cobertura    = len(_palavras_na_fonte) / max(1, len(_palavras_titulo))

            # Caption check: nenhuma legenda de fonte virou fato no artigo
            _legenda_misuse = []
            for leg in _legendas_fonte:
                leg_clean = leg.replace("legenda:", "").replace("caption:", "").strip().lower()
                if len(leg_clean) > 10 and leg_clean in _corpo_lower:
                    _legenda_misuse.append(leg_clean[:40])

            log.append(
                f"[GERACAO] Diagnóstico: "
                f"titulo_seo={_titulo_seo_len}chars | titulo_capa={_titulo_capa_len}chars | "
                f"retranca='{raw.get('retranca','')}' | tags={_n_tags} | "
                f"corpo={len(corpo)}chars | pars={_n_pars} | "
                f"erros_estruturais={len(errs)} | dados_ausentes={len(ausentes_essenciais)} | "
                f"seo_cobertura_titulo={_seo_cobertura:.0%}"
            )
            if _legenda_misuse:
                log.append(
                    f"[GERACAO] ⚠ CAPTION MISUSE: {len(_legenda_misuse)} legenda(s) da fonte "
                    f"apareceu literalmente no corpo: {_legenda_misuse[:2]}"
                )
                erros_geracao.append(
                    f"caption_misuse: legenda de imagem usada como fato no corpo: "
                    f"{_legenda_misuse[0][:50]}"
                )
            else:
                log.append("[GERACAO] Caption check: nenhuma legenda de imagem copiada literalmente no corpo ✓")

            if erros_geracao and tentativa < MAX_TENTATIVAS_GERACAO:
                # Segunda tentativa: lista todos os erros para correção
                _erros_fmt = "\n".join(f"- {e}" for e in erros_geracao[:10])
                _ausentes_fmt = (
                    "\n".join(f"- {a}" for a in ausentes_essenciais[:8])
                    if ausentes_essenciais else "Nenhum"
                )
                user_ger += f"""

== CORREÇÕES OBRIGATÓRIAS — TENTATIVA 2 ==
A matéria gerada foi REPROVADA. Corrija TODOS os problemas abaixo.

ERROS ENCONTRADOS:
{_erros_fmt}

DADOS ESSENCIAIS DA FONTE QUE ESTÃO AUSENTES NA MATÉRIA:
{_ausentes_fmt}

INSTRUÇÕES PARA A CORREÇÃO:
1. Mantenha TODOS os dados essenciais listados acima na matéria corrigida.
2. Corrija todos os erros estruturais listados.
3. Não invente informações novas.
4. Não use travessão, expressões proibidas ou texto genérico.
5. Preserve o tom jornalístico profissional.
6. Retorne o JSON completo corrigido.
"""
                time.sleep(0.5)
                continue

            # Gera status_validacao programaticamente (NUNCA pela IA)
            raw["status_validacao"] = gerar_status_validacao(raw, errs or [])
            if ausentes_essenciais:
                raw["status_validacao"]["dados_essenciais_ausentes"] = ausentes_essenciais
                raw["status_validacao"]["aprovado"] = False
                raw["status_validacao"]["pode_publicar"] = False

            log.append(
                f"[GERACAO] status_validacao: aprovado={raw['status_validacao']['aprovado']}, "
                f"erros_totais={len(erros_geracao)}"
            )

            json_geracao = raw
            log.append(
                f"[GERACAO] Geração concluída | "
                f"modelo={modelo} | "
                f"erros_residuais={len(erros_geracao)} | "
                f"aprovado={raw['status_validacao']['aprovado']}"
            )
            break

        except Exception as e:
            log.append(f"[GERACAO] Erro na tentativa {tentativa}: {e}")
            # Classifica se é erro de configuração/API
            _cfg_exc = classify_openai_exception(e)
            if not _cfg_exc.ok and _cfg_exc.codigo:
                # ERRO DE API (401, 429, timeout) — aborta IMEDIATAMENTE
                # NUNCA tenta segunda tentativa, NUNCA usa fallback
                _err_api = _cfg_exc.erro_dict
                log.append(f"[GERACAO] ABORTADO por CONFIG_ERROR: {_cfg_exc.codigo}")
                log.append("[WORKFLOW] generation_aborted reason=" + _cfg_exc.codigo)
                log.append("[WORKFLOW] REGRA: API error → NUNCA usar fallback de fragmento de fonte")
                resultado.dados_finais = {
                    "status_validacao": "erro_configuracao",
                    "status_publicacao_sugerido": "salvar_rascunho",
                    "auditoria_bloqueada": True,
                    "revisao_humana_necessaria": True,
                    "erros_validacao": [_err_api],
                    "corpo_materia": "",
                    "titulo_seo": "",
                    "titulo_capa": "",
                    "subtitulo_curto": "",
                    "retranca": canal,
                    "tags": [canal],
                    "legenda_curta": "",
                    "meta_description": "",
                    "nome_da_fonte": "",
                    "creditos_da_foto": "",
                    "observacoes_editoriais": [
                        f"⚠ Geração abortada: {_err_api.get('mensagem','')}",
                        f"Sugestão: {_err_api.get('sugestao','')}",
                    ],
                    "_is_config_error": True,
                }
                resultado.todos_erros = [_err_api.get("mensagem", str(e))]
                resultado.erros_validacao_geracao = [_err_api.get("mensagem", str(e))]
                resultado.bloqueado = True
                resultado.status_publicacao = "bloquear"
                resultado.log = log
                print(f"[WORKFLOW] generation_aborted reason={_cfg_exc.codigo}")
                print(f"[REVIEW] saved_config_error_draft")
                return resultado
            erros_geracao = [str(e)]
            if tentativa < MAX_TENTATIVAS_GERACAO:
                time.sleep(1)

    resultado.json_geracao = json_geracao
    resultado.erros_validacao_geracao = erros_geracao

    if not json_geracao:
        log.append("[GERACAO] FALHA TOTAL — pipeline bloqueado")
        resultado.log = log
        resultado.todos_erros = erros_geracao
        resultado.bloqueado = True
        resultado.status_publicacao = "bloquear"
        return resultado

    # ════════════════════════════════════════════════════════════════
    # ETAPA 1b: REVISÃO AUTOMÁTICA (reviseArticleIfNeeded)
    # Chamada apenas uma vez, quando dados essenciais estão ausentes
    # após as 2 tentativas normais de geração.
    # ════════════════════════════════════════════════════════════════
    _ausentes_pos_geracao = json_geracao.get("status_validacao", {}).get(
        "dados_essenciais_ausentes", []
    )
    _erros_residuais = [e for e in erros_geracao if not e.startswith("dado_essencial:")]

    if _ausentes_pos_geracao and not _erros_residuais:
        log.append(
            f"[REVISAO] Iniciando revisão automática — "
            f"{len(_ausentes_pos_geracao)} dado(s) essencial(is) ausente(s)"
        )
        try:
            _corpo_atual = json_geracao.get("corpo_materia") or json_geracao.get("texto_final") or ""
            _prompt_revisao = f"""
Você é um editor jornalístico revisando uma matéria que foi aprovada na forma mas está INCOMPLETA no conteúdo.
A matéria está bem escrita, mas deixou de incluir dados essenciais da fonte original.

== MATÉRIA ATUAL (corpo) ==
{_corpo_atual}

== FONTE ORIGINAL ==
{fonte_bruta[:5000]}

== DADOS ESSENCIAIS AUSENTES (TODOS devem ser incluídos na revisão) ==
{chr(10).join(f"  • {a}" for a in _ausentes_pos_geracao)}

== INSTRUÇÃO ==
Reescreva APENAS o campo corpo_materia para incluir TODOS os dados listados acima.
- Mantenha o tom jornalístico profissional.
- Não use travessão, expressões de IA ou linguagem genérica.
- Não invente informação nova além do que está na fonte.
- Preserve os dados já corretos da matéria.
- Se necessário para incluir dados ausentes, adicione parágrafos — mas apenas com dados presentes na fonte.
- Separe parágrafos com \\n\\n.

Retorne APENAS JSON com um único campo:
{{"corpo_materia": "texto revisado aqui..."}}
""".strip()

            _resp_revisao = client.responses.create(
                model=modelo,
                instructions=_SYSTEM_AGENTE if _USA_AGENTE_EDITORIAL and _SYSTEM_AGENTE else system_ger,
                input=_prompt_revisao,
                temperature=0.2,
            )
            _raw_revisao = _resp_revisao.output_text.strip()
            if "```" in _raw_revisao:
                import re as _re2
                _raw_revisao = _re2.sub(r"```(?:json)?", "", _raw_revisao).strip().replace("```", "")
            _j_revisao = json.loads(_raw_revisao[_raw_revisao.find("{"):_raw_revisao.rfind("}")+1])
            _corpo_revisado = _j_revisao.get("corpo_materia", "")

            if _corpo_revisado and len(_corpo_revisado) > len(_corpo_atual):
                # Aplica limpeza no corpo revisado
                _corpo_revisado = _corrigir_paragrafos(_remover_travessao(_corpo_revisado))
                json_geracao["corpo_materia"] = _corpo_revisado
                json_geracao["conteudo"]      = _corpo_revisado
                json_geracao["texto_final"]   = _corpo_revisado

                # Re-valida dados essenciais após revisão
                _ausentes_apos_revisao = validar_dados_essenciais(_corpo_revisado, mapa_evidencias)
                if _ausentes_apos_revisao:
                    log.append(
                        f"[REVISAO] Ainda ausentes após revisão: {_ausentes_apos_revisao[:3]} "
                        "→ salvar como rascunho"
                    )
                    json_geracao["status_validacao"]["dados_essenciais_ausentes"] = _ausentes_apos_revisao
                    json_geracao["status_validacao"]["revisao_automatica"] = "reprovada"
                else:
                    log.append("[REVISAO] Todos os dados essenciais incluídos após revisão ✓")
                    json_geracao["status_validacao"]["dados_essenciais_ausentes"] = []
                    json_geracao["status_validacao"]["revisao_automatica"] = "aprovada"
                    json_geracao["status_validacao"]["aprovado"] = True
                    json_geracao["status_validacao"]["pode_publicar"] = True
            else:
                log.append("[REVISAO] Revisão não melhorou o conteúdo — mantendo original")

        except Exception as _e_rev:
            log.append(f"[REVISAO] Erro na revisão automática: {_e_rev}")

    # ════════════════════════════════════════════════════════════════
    # ETAPA 2: AUDITORIA (chamada separada, papel exclusivo de auditor)
    # ════════════════════════════════════════════════════════════════
    log.append("[AUDITORIA] Iniciando etapa de auditoria...")
    json_auditoria: dict = {}
    erros_auditoria: list[str] = []

    system_aud, user_aud = _montar_prompt_auditoria(
        json_geracao=json_geracao,
        fonte_bruta=fonte_bruta,
        mapa_evidencias=mapa_evidencias,
        bloco_memoria=bloco_memoria,
        canal=canal,
        modo_operacional=modo_operacional,
    )

    for tentativa in range(1, MAX_TENTATIVAS_AUDITORIA + 1):
        resultado.tentativas_auditoria = tentativa
        log.append(f"[AUDITORIA] Tentativa {tentativa}/{MAX_TENTATIVAS_AUDITORIA}")
        try:
            resposta = client.responses.create(
                model=modelo,
                instructions=system_aud,
                input=user_aud,
                temperature=TEMPERATURE_AUDITORIA,
            )
            texto_resposta = resposta.output_text
            raw_aud = extrair_json(texto_resposta)
            raw_aud = completar_com_defaults(raw_aud, SCHEMA_AUDITORIA)

            # Normaliza tags na versão corrigida
            vc = raw_aud.get("versao_corrigida", {})
            if isinstance(vc, dict) and "tags" in vc:
                vc["tags"] = normalizar_tags(vc.get("tags", []))

            errs_aud = validar_auditoria(raw_aud)
            if errs_aud:
                erros_auditoria = [f"{e.campo}: {e.motivo}" for e in errs_aud]
                log.append(f"[AUDITORIA] {len(errs_aud)} erro(s) estruturais na resposta")
                if tentativa < MAX_TENTATIVAS_AUDITORIA:
                    time.sleep(0.5)
                    continue
            else:
                erros_auditoria = []

            json_auditoria = raw_aud
            break

        except Exception as e:
            log.append(f"[AUDITORIA] Erro na tentativa {tentativa}: {e}")
            erros_auditoria = [str(e)]
            if tentativa < MAX_TENTATIVAS_AUDITORIA:
                time.sleep(1)

    resultado.json_auditoria = json_auditoria
    resultado.erros_validacao_auditoria = erros_auditoria

    # ════════════════════════════════════════════════════════════════
    # ETAPA 3: DECISÃO
    # ════════════════════════════════════════════════════════════════
    aprovado = json_auditoria.get("aprovado", False)
    bloquear = json_auditoria.get("bloquear_publicacao", True)
    corrigir = json_auditoria.get("corrigir_e_regerar", False)
    viol_fat = json_auditoria.get("violacoes_factuais", [])
    viol_edi = json_auditoria.get("violacoes_editoriais", [])
    viol_flu = json_auditoria.get("violacoes_de_fluxo", [])
    viol_mem = json_auditoria.get("violacoes_de_memoria", [])
    erros_enc = json_auditoria.get("erros_encontrados", [])

    # Qualquer violação factual bloqueia sempre
    if viol_fat:
        bloquear = True
        aprovado = False
        log.append(f"[DECISAO] BLOQUEADO por violações factuais: {viol_fat[:2]}")

    # Erros de validação na geração também penalizam
    if erros_geracao:
        log.append(f"[DECISAO] Erros de geração ainda presentes: {erros_geracao[:2]}")

    resultado.aprovado_auditoria = aprovado
    resultado.bloqueado = bloquear
    resultado.violacoes_factuais = viol_fat
    resultado.violacoes_editoriais = viol_edi
    resultado.todos_erros = (
        erros_enc + viol_fat + viol_edi + viol_flu + viol_mem + erros_geracao
    )

    # Dados finais: usa versão corrigida da auditoria se disponível e aprovada
    versao_corrigida = json_auditoria.get("versao_corrigida", {})
    if not bloquear and aprovado:
        # Mescla versão corrigida sobre geração original
        dados_finais = dict(json_geracao)
        for campo, valor in versao_corrigida.items():
            if valor and campo in dados_finais:
                dados_finais[campo] = valor
        resultado.dados_finais = dados_finais
        resultado.status_publicacao = json_geracao.get(
            "status_publicacao_sugerido", "salvar_rascunho"
        )
        resultado.sucesso = True
        log.append(f"[DECISAO] APROVADO | status={resultado.status_publicacao}")
    else:
        # Bloqueado — entrega geração com marcação de bloqueio
        resultado.dados_finais = json_geracao
        resultado.status_publicacao = "bloquear"
        resultado.sucesso = False
        motivos = erros_enc[:3] + viol_fat[:2]
        log.append(f"[DECISAO] BLOQUEADO | motivos: {motivos}")

    # ── Log: relatório final completo ────────────────────────────────────────
    _dados_f = resultado.dados_finais
    _corpo_f = _dados_f.get("corpo_materia", "") or _dados_f.get("texto_final", "")
    _pars_f  = [p for p in _corpo_f.split("\n\n") if p.strip()]
    _erros_f = resultado.todos_erros
    _tags_f  = _dados_f.get("tags", [])
    _n_tags_f = len(_tags_f) if isinstance(_tags_f, list) else len(str(_tags_f).split(","))
    log.append(
        f"[RELATORIO_FINAL] status={'APROVADO' if resultado.aprovado_auditoria else 'REPROVADO'} | "
        f"publicacao={resultado.status_publicacao} | "
        f"titulo_seo={len(_dados_f.get('titulo_seo',''))}chars | "
        f"titulo_capa={len(_dados_f.get('titulo_capa',''))}chars | "
        f"retranca='{_dados_f.get('retranca','')}' | tags={_n_tags_f} | "
        f"corpo={len(_corpo_f)}chars | pars={len(_pars_f)} | "
        f"erros_totais={len(_erros_f)} | modelo={modelo}"
    )
    if not resultado.aprovado_auditoria:
        log.append("[RELATORIO_FINAL] BLOQUEIO: artigo salvo como rascunho para revisão humana")
        if _erros_f:
            log.append(f"[RELATORIO_FINAL] Motivos: {'; '.join(str(e) for e in _erros_f[:3])}")
    else:
        log.append("[RELATORIO_FINAL] APROVADO: artigo pronto para publicação ✓")

    # ════════════════════════════════════════════════════════════════
    # ETAPA 4: APRENDIZADO — persiste na memória editorial
    # ════════════════════════════════════════════════════════════════
    try:
        titulo_pauta = pauta.get("titulo_origem", "")[:80]
        mem.aprender_de_auditoria(json_auditoria, contexto_pauta=titulo_pauta)
        log.append("[MEMORIA] Aprendizado persistido da auditoria")
    except Exception as e:
        log.append(f"[MEMORIA] Erro ao persistir aprendizado: {e}")

    resultado.log = log
    log.append(resultado.resumo())
    return resultado


# ── Registro de aprovação/correção manual ─────────────────────────────────────

def registrar_aprovacao_manual(
    dados_materia: dict,
    editoria: str = "",
    caminho_db: str = "ururau.db",
):
    """
    Chamado quando o editor aprova uma matéria.
    Registra exemplos aprovados na memória para few-shot futuro.
    """
    mem = obter_memoria(caminho_db)
    titulo = dados_materia.get("titulo_seo") or dados_materia.get("titulo", "")
    if titulo:
        mem.aprender_de_aprovacao("titulo", titulo, editoria=editoria, score=8)
    subtitulo = (
        dados_materia.get("subtitulo_curto")
        or dados_materia.get("subtitulo", "")  # compatibilidade com versões antigas
    )
    if subtitulo:
        mem.aprender_de_aprovacao("subtitulo_curto", subtitulo, editoria=editoria, score=7)
    retranca = dados_materia.get("retranca", "")
    if retranca:
        mem.aprender_de_aprovacao("retranca", retranca, editoria=editoria, score=7)
    texto = (
        dados_materia.get("corpo_materia")
        or dados_materia.get("texto_final")
        or dados_materia.get("conteudo", "")
    )
    if texto:
        # Só salva os primeiros 500 chars (abertura) como exemplo
        mem.aprender_de_aprovacao("abertura", texto[:500], editoria=editoria, score=7)


def registrar_correcao_manual(
    campo: str,
    valor_errado: str,
    valor_correto: str,
    contexto: str = "",
    caminho_db: str = "ururau.db",
):
    """
    Chamado quando o editor corrige um campo gerado pela IA.
    Transforma a correção em memória operacional para próximas execuções.
    """
    mem = obter_memoria(caminho_db)
    mem.aprender_de_correcao_manual(
        campo=campo,
        valor_errado=valor_errado,
        valor_correto=valor_correto,
        contexto=contexto,
    )
    print(f"[PIPELINE] Correção manual registrada: campo='{campo}'")
