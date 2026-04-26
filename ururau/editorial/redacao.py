"""
editorial/redacao.py — Pipeline de geração de texto do Ururau (v62).

Fluxo obrigatório:
  1. Validação de OPENAI_API_KEY antes de qualquer chamada à IA
  2. Limpeza de fonte e separação de metadados (legendas, créditos, links)
  3. Validação de suficiência da fonte (sufficiency gate)
  4. Extração de evidências (mapa factual — ancora toda a geração)
  5. Geração via IA (Agente Editorial Ururau + contexto + memória + feedback)
  6. Auditoria automática em chamada separada
  7. Validação de cobertura de fatos essenciais
  8. Bloqueio se auditoria reprovar / cobertura baixa
  9. Aprendizado persistido na memória editorial
 10. Retorna dataclass Materia compatível com painel e monitor

Compatibilidade de campos (v45 → painel/CMS):
  corpo_materia   → conteudo / texto_final
  subtitulo_curto → subtitulo
  legenda_curta   → legenda

NOVO em v62:
  - Substituído _truncar_titulo_seguro por safe_title centralizado
  - Sem mais slicing bruto (titulo_seo[:89] / titulo_capa[:60])
  - safe_title remove conectores fracos finais (de, da, do, em...)
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ururau.config.house_style import instrucao_canal, template_para_canal
from ururau.core.models import MapaEvidencias, Materia
from ururau.editorial.extracao import (
    extrair_mapa_evidencias,
    mapa_para_contexto_redacao,
    separar_fonte_de_metadados,
)
from ururau.editorial.risco import analisar_risco
from ururau.editorial.safe_title import (
    safe_title,
    safe_truncate,
    validar_limites_titulos,
    LIMITE_TITULO_SEO,
    LIMITE_TITULO_CAPA,
)
from ururau.ia.pipeline import executar_pipeline
from ururau.ia.logger import obter_logger


# Alias mantido por compatibilidade com chamadas legadas em outros módulos.
# Internamente delega para safe_title (módulo editorial.safe_title).
def _truncar_titulo_seguro(texto: str, limite: int) -> str:
    """Wrapper legado — usar safe_title diretamente em código novo."""
    return safe_title(texto, limite)

if TYPE_CHECKING:
    from openai import OpenAI


def _extrair_texto_corpo(dados: dict, fallback: str = "") -> str:
    """
    Extrai o corpo da matéria dos dados, tentando todos os aliases possíveis.
    Ordem de prioridade: corpo_materia > texto_final > conteudo > fallback.
    """
    return (
        dados.get("corpo_materia")
        or dados.get("texto_final")
        or dados.get("conteudo")
        or fallback
    )


def _extrair_subtitulo(dados: dict, fallback: str = "") -> str:
    """
    Extrai o subtítulo tentando todos os aliases.
    Ordem: subtitulo_curto > subtitulo > fallback.
    """
    return (
        dados.get("subtitulo_curto")
        or dados.get("subtitulo")
        or fallback
    )


def _extrair_legenda(dados: dict, fallback: str = "Reprodução") -> str:
    """
    Extrai a legenda tentando todos os aliases.
    Ordem: legenda_curta > legenda > fallback.
    """
    return (
        dados.get("legenda_curta")
        or dados.get("legenda")
        or fallback
    )


def gerar_materia(
    pauta: "dict | object",
    client: "OpenAI",
    modelo: str,
    canal: str,
    modo_operacional: str = "painel",
    caminho_db: str = "ururau.db",
) -> Materia:
    """
    Pipeline principal de redação — v49.

    1. Extrai mapa de evidências (ancora toda geração em fatos confirmados).
    2. Executa pipeline IA: geração + auditoria + aprendizado.
    3. Bloqueia se auditoria reprovar.
    4. Aplica score de risco editorial.
    5. Retorna Materia populada com metadados completos de auditoria.
    """

    # ── Compatibilidade dict / dataclass ──────────────────────────────────────
    def _get(key: str, default=""):
        if isinstance(pauta, dict):
            return pauta.get(key, default)
        return getattr(pauta, key, default)

    titulo_origem = _get("titulo_origem")
    resumo_origem = _get("resumo_origem")
    texto_fonte   = _get("texto_fonte")
    link_origem   = _get("link_origem")
    fonte_nome    = _get("fonte_nome")
    dossie        = _get("dossie", "")
    score_edit    = int(_get("score_editorial", 0))
    uid           = _get("uid") or _get("_uid", "")

    pauta_dict: dict = {
        "uid":           uid,
        "titulo_origem": titulo_origem,
        "resumo_origem": resumo_origem,
        "texto_fonte":   texto_fonte,
        "link_origem":   link_origem,
        "fonte_nome":    fonte_nome,
        "dossie":        dossie,
        "canal_forcado": canal,
        # Metadados separados (disponíveis para o pipeline mas não devem virar fatos)
        "_legendas_fonte":        [],   # preenchido após separação (ver abaixo)
        "_creditos_fonte":        [],
        "_metadados_descartados": [],
    }

    # ── Etapa 0: Separação de metadados da fonte ─────────────────────────────
    # Separa legenda de imagem, créditos, links relacionados, timestamps e publicidade
    # do corpo real da matéria ANTES de qualquer extração ou geração.
    # REGRA: legendas e créditos NÃO devem virar fatos no artigo gerado.
    _texto_para_separar = (texto_fonte or "") + "\n" + (dossie or "")
    _separacao = separar_fonte_de_metadados(_texto_para_separar)
    _metadados_descartados = _separacao.get("metadados_descartados", [])
    _legendas_fonte = _separacao.get("legendas_identificadas", [])
    _creditos_fonte = _separacao.get("creditos_foto", [])
    _texto_limpo = _separacao.get("corpo_limpo", _texto_para_separar)

    print(f"[REDACAO] Separação de metadados: "
          f"{len(_metadados_descartados)} itens removidos "
          f"(legendas={len(_legendas_fonte)}, créditos={len(_creditos_fonte)})")
    if _metadados_descartados:
        for item in _metadados_descartados[:5]:
            print(f"[REDACAO]   Removido: {item}")

    # Usa o texto limpo (sem metadados) para extração e geração
    # dossie limpo = parte do texto_limpo que é "extra" além do texto_fonte
    _texto_fonte_limpo = _texto_limpo[:len(texto_fonte or "")] if texto_fonte else _texto_limpo
    _dossie_limpo = _texto_limpo[len(_texto_fonte_limpo):].strip()

    # Propaga metadados para o pauta_dict
    pauta_dict["_legendas_fonte"]        = _legendas_fonte
    pauta_dict["_creditos_fonte"]        = _creditos_fonte
    pauta_dict["_metadados_descartados"] = _metadados_descartados
    # Usa texto limpo no pipeline (evita que metadados virem fatos)
    pauta_dict["texto_fonte"] = _texto_fonte_limpo or texto_fonte or ""
    pauta_dict["dossie"]      = _dossie_limpo or dossie

    # ── Etapa 1: Mapa de evidências ───────────────────────────────────────────
    print(f"[REDACAO] Extraindo mapa de evidências: {titulo_origem[:60]}")
    mapa_dict = extrair_mapa_evidencias(
        titulo=titulo_origem,
        resumo=resumo_origem,
        texto_fonte=_texto_fonte_limpo or texto_fonte or "",
        dossie=_dossie_limpo or dossie,
        client=client,
        modelo=modelo,
    )
    contexto_redacao = mapa_para_contexto_redacao(mapa_dict)

    # Carrega estilo personalizado do .env
    import os as _os
    _ep = (_os.getenv("URURAU_ESTILO_POSITIVO") or "").strip()
    _en = (_os.getenv("URURAU_ESTILO_NEGATIVO") or "").strip()
    _ex = (_os.getenv("URURAU_ESTILO_EXEMPLOS") or "").strip()
    if _ep or _en or _ex:
        partes = ["== ESTILO EDITORIAL PERSONALIZADO =="]
        if _ep:
            partes.append(f"DIRETRIZES:\n{_ep}")
        if _en:
            partes.append(f"EXCLUSÕES:\n{_en}")
        if _ex:
            partes.append(f"EXEMPLOS DE REFERÊNCIA:\n{_ex}")
        contexto_redacao = "\n\n".join(partes) + "\n\n" + contexto_redacao

    instrucao_do_canal = instrucao_canal(canal)
    template = template_para_canal(canal)

    # ── v70: ENGINE CANONICO eh o caminho real de producao ──────────────────
    import os as _os70
    if _os70.getenv("URURAU_DISABLE_V70_ENGINE", "0").strip() not in ("1", "true", "yes"):
        try:
            from ururau.editorial.engine import generate_ururau_article
            _m70 = generate_ururau_article(pauta_dict, client, modelo, canal, modo=modo_operacional)
            print(f"[REDACAO v70] engine canonico OK | status={_m70.status_validacao}")
            return _m70
        except Exception as _e70:
            print(f"[REDACAO v70] engine canonico FALHOU: {_e70}")
            from ururau.core.models import Materia as _M70
            _merr = _M70()
            _merr.status_validacao = "erro_configuracao"
            _merr.status_publicacao_sugerido = "salvar_rascunho"
            _merr.revisao_humana_necessaria = True
            _merr.auditoria_bloqueada = True
            _merr.erros_validacao = [{
                "categoria": "CONFIG_ERROR", "codigo": "engine_v70_failed",
                "mensagem": f"Engine v70 falhou: {_e70}",
                "bloqueia_publicacao": True, "corrigivel_automaticamente": False,
            }]
            return _merr

    # ── v69c: Pre-IA — required_facts + entity_relationships ANTES da geracao
    # Os fatos obrigatorios e relacoes entram como contexto no prompt para que
    # o GPT-4.1-mini gere artigo cobrindo todos os fatos essenciais.
    _required_facts_pre = []
    _relacoes_pre = []
    try:
        from ururau.editorial.coverage_por_tipo import extract_required_facts_from_source
        from ururau.editorial.relationships import extract_entity_relationships
        _src_pre = (_texto_limpo or texto_fonte or "")
        _tipo_pre = canal or ""
        _required_facts_pre = extract_required_facts_from_source(_src_pre, _tipo_pre)
        _relacoes_pre = extract_entity_relationships(_src_pre, _tipo_pre, client, modelo)
        # Anexa ao pauta_dict para o pipeline/agente usar no prompt
        pauta_dict["required_facts_pre"] = _required_facts_pre
        pauta_dict["entity_relationships_pre"] = _relacoes_pre
        # Anexa tambem ao contexto_redacao
        if _required_facts_pre:
            _bloco_req = "\n\n== FATOS OBRIGATORIOS DA FONTE (incluir todos no corpo) ==\n"
            _bloco_req += "\n".join(f"- [{f.get('type','')}] {f.get('text','')[:120]}"
                                    for f in _required_facts_pre[:15])
            contexto_redacao += _bloco_req
        if _relacoes_pre:
            _bloco_rel = "\n\n== RELACOES FACTUAIS (preservar subject->relationship->object) ==\n"
            _bloco_rel += "\n".join(
                f"- {r.get('subject','')} {r.get('relationship','')} {r.get('object','')}"
                for r in _relacoes_pre[:8]
            )
            contexto_redacao += _bloco_rel
        print(f"[REDACAO v69c] pre-IA: {len(_required_facts_pre)} fatos + "
               f"{len(_relacoes_pre)} relacoes adicionadas ao prompt")
    except Exception as _e:
        print(f"[REDACAO v69c] aviso: pre-IA falhou: {_e}")

    # ── Etapa 2: Geração IA — v69c usa AGENTE CANONICO por default ───────────
    # URURAU_USE_CANONICAL_AGENT=1 (default) usa agente_editorial_ururau.gerar_via_agente
    # Para fallback ao pipeline antigo, defina URURAU_USE_CANONICAL_AGENT=0.
    import os as _os69c
    _USE_CANON = _os69c.getenv("URURAU_USE_CANONICAL_AGENT", "1").strip() not in ("0", "false", "no")
    print(f"[REDACAO] Geracao IA (canal={canal}, modo={modo_operacional}, modelo={modelo}, "
          f"motor={'CANONICAL' if _USE_CANON else 'pipeline_legacy'})")

    resultado = None
    if _USE_CANON and client is not None:
        try:
            from ururau.agents.agente_editorial_ururau import gerar_via_agente
            # Repassa contexto_redacao via dossie para o agente
            pauta_dict_canon = dict(pauta_dict)
            pauta_dict_canon["dossie"] = (pauta_dict.get("dossie", "") + "\n\n" + contexto_redacao).strip()
            dados_canon = gerar_via_agente(
                pauta_dict_canon, client, modelo, canal, modo_operacional
            )
            # Adapta para a interface ResultadoPipeline esperada abaixo
            from types import SimpleNamespace
            resultado = SimpleNamespace(
                sucesso=True,
                dados_finais=dados_canon or {},
                aprovado_auditoria=bool(dados_canon and not dados_canon.get("_auditoria_bloqueada", False)),
                bloqueado=bool(dados_canon and dados_canon.get("_auditoria_bloqueada", False)),
                status_publicacao=dados_canon.get("status_publicacao_sugerido", "salvar_rascunho") if dados_canon else "bloquear",
                violacoes_factuais=dados_canon.get("_violacoes_factuais", []) if dados_canon else [],
                todos_erros=dados_canon.get("auditoria_erros", []) if dados_canon else [],
                erros_validacao_geracao=[],
                erros_validacao_auditoria=[],
                violacoes_editoriais=[],
                log=[],
                timestamp="",
                modelo_usado=modelo,
                tentativas_geracao=1,
                tentativas_auditoria=0,
                _modo_operacional=modo_operacional,
            )
            print(f"[REDACAO v69c] motor canonical OK")
        except Exception as _e:
            print(f"[REDACAO v69c] motor canonical FALHOU: {_e} - fallback ao pipeline legacy")
            resultado = None

    if resultado is None:
        resultado = executar_pipeline(
            pauta=pauta_dict,
            mapa_evidencias=mapa_dict,
            contexto_redacao=contexto_redacao,
            canal=canal,
            client=client,
            modelo=modelo,
            instrucao_canal=instrucao_do_canal,
            template=template,
            modo_operacional=modo_operacional,
            caminho_db=caminho_db,
        )

    # ── Etapa 3: Log completo ─────────────────────────────────────────────────
    logger = obter_logger(caminho_db)
    resultado._modo_operacional = modo_operacional  # type: ignore
    logger.registrar_de_resultado(resultado, pauta_dict, acao="geracao_materia")

    # ── Etapa 4: Extrai dados finais ──────────────────────────────────────────
    dados = resultado.dados_finais

    # Se pipeline falhou completamente — NÃO usar fragmento de fonte como corpo
    # Falha pode ser CONFIG_ERROR (API key inválida) ou EXTRACTION_ERROR (fonte vazia)
    if not dados:
        # Tenta aproveitar dados_finais que pipeline.py já preencheu com erro estruturado
        _df = resultado.dados_finais or {}
        _is_config_err = _df.get("_is_config_error", False)
        _status_val = _df.get("status_validacao", "")

        if _is_config_err or _status_val == "erro_configuracao":
            # CONFIG_ERROR: pipeline detectou falha de API — preserva o resultado já estruturado
            dados = _df
        else:
            # Outro tipo de falha de pipeline: cria rascunho técnico SEM corpo gerado por IA
            # corpo_materia fica VAZIO — nunca usar resumo_origem ou fonte como corpo
            dados = {
                "titulo_seo":         safe_title(titulo_origem, LIMITE_TITULO_SEO),
                "titulo_capa":        safe_title(titulo_origem, LIMITE_TITULO_CAPA),
                "subtitulo_curto":    safe_truncate(resumo_origem, 200),
                "legenda_curta":      safe_truncate(resumo_origem, 100) or "Reprodução",
                "retranca":           canal,
                "tags":               [canal],
                "nome_da_fonte":      "Redação",
                "creditos_da_foto":   "Reprodução",
                "corpo_materia":      "",          # NUNCA fragmento de fonte
                "editoria":           canal,
                "canal":              canal,
                "status_publicacao_sugerido": "bloquear",
                "justificativa_status": "Falha no pipeline de geração",
                "status_validacao":   "erro_extracao",
                "slug": re.sub(r"[^a-z0-9]+", "-", titulo_origem.lower())[:80].strip("-"),
                "meta_description":   resumo_origem[:155],
                "resumo_curto":       resumo_origem[:280],
                "chamada_social":     titulo_origem[:240],
                "estrutura_decisao":  "",
                "erros_validacao": [{
                    "categoria": "EXTRACTION_ERROR",
                    "codigo":    "pipeline_failure",
                    "mensagem":  "Pipeline falhou sem produzir dados — artigo não gerado.",
                    "campo":     "corpo_materia",
                    "bloqueante": True,
                }],
            }

    # ── Normalização de campos: resolve todos os aliases ─────────────────────
    # Título SEO — truncagem segura via safe_title (sem slicing bruto)
    titulo_seo = safe_title(
        str(dados.get("titulo_seo") or dados.get("titulo") or titulo_origem),
        LIMITE_TITULO_SEO,
    )

    # Título capa — truncagem segura via safe_title (sem slicing bruto)
    titulo_capa = safe_title(
        str(dados.get("titulo_capa") or titulo_origem),
        LIMITE_TITULO_CAPA,
    )

    # Subtítulo — aceita subtitulo_curto (v45) ou subtitulo (legado)
    subtitulo = str(_extrair_subtitulo(dados, ""))[:200].rstrip()

    # Legenda — aceita legenda_curta (v45) ou legenda (legado)
    legenda_raw = _extrair_legenda(dados, "Reprodução")
    legenda = str(legenda_raw)[:100].rstrip()
    if not legenda.strip():
        legenda = (subtitulo or titulo_capa or "Reprodução")[:100]

    # Retranca
    retranca = str(dados.get("retranca") or canal)[:30].rstrip()

    # Meta description
    meta_description = str(dados.get("meta_description") or "")[:160]

    # Resumo curto
    resumo_curto = str(dados.get("resumo_curto") or "")[:280]

    # Chamada social
    chamada_social = str(dados.get("chamada_social") or "")[:240]

    # Slug
    slug = dados.get("slug") or re.sub(r"[^a-z0-9]+", "-", titulo_seo.lower())[:80].strip("-")

    # v68 fix: corpo_materia NUNCA usa resumo/titulo como fallback.
    texto_conteudo = _extrair_texto_corpo(dados, "")
    if not texto_conteudo or not texto_conteudo.strip():
        texto_conteudo = ""
        _err = {
            "categoria":  "EDITORIAL_BLOCKER",
            "codigo":     "corpo_materia_ausente",
            "severidade": "alta",
            "campo":      "corpo_materia",
            "mensagem":   "Corpo da materia vazio apos geracao - sem fallback (v68).",
            "trecho":     "",
            "sugestao":   "Reprocessar com fonte completa ou aprovar manualmente.",
            "bloqueia_publicacao":     True,
            "corrigivel_automaticamente": False,
        }
        erros_existentes = dados.get("erros_validacao") or []
        if not any(isinstance(e, dict) and e.get("codigo") == "corpo_materia_ausente"
                    for e in erros_existentes):
            erros_existentes.append(_err)
        dados["erros_validacao"] = erros_existentes
        dados["status_validacao"] = "erro_extracao"
        dados["status_publicacao_sugerido"] = "salvar_rascunho"
        dados["revisao_humana_necessaria"] = True

    # Normaliza parágrafos no corpo (garante \n\n entre parágrafos)
    # Importa a função de limpeza do pipeline para reusar a lógica
    try:
        from ururau.ia.pipeline import _corrigir_paragrafos
        texto_conteudo = _corrigir_paragrafos(texto_conteudo)
    except Exception:
        pass

    # Grava aliases canônicos no dict para compatibilidade total downstream
    dados["titulo_seo"]      = titulo_seo
    dados["titulo"]          = titulo_seo        # alias legado para painel
    dados["titulo_capa"]     = titulo_capa
    dados["subtitulo_curto"] = subtitulo
    dados["subtitulo"]       = subtitulo         # alias legado para copydesk / painel
    dados["legenda_curta"]   = legenda
    dados["legenda"]         = legenda           # alias legado para copydesk / painel
    dados["retranca"]        = retranca
    dados["meta_description"] = meta_description
    dados["resumo_curto"]    = resumo_curto
    dados["chamada_social"]  = chamada_social
    dados["slug"]            = slug
    dados["corpo_materia"]   = texto_conteudo
    dados["conteudo"]        = texto_conteudo    # alias legado para copydesk / painel
    dados["texto_final"]     = texto_conteudo    # alias legado para compatibilidade

    # ── Tags: sempre string separada por vírgulas ─────────────────────────────
    tags_raw = dados.get("tags", [canal])
    if isinstance(tags_raw, list):
        tags_str = ", ".join(str(t).strip() for t in tags_raw if str(t).strip())
    else:
        tags_str = str(tags_raw)
    dados["tags"] = tags_str

    # ── Etapa 4.5: Validação de limites de títulos (FIXABLE_FIELD) ───────────
    # Se algum título escapou do safe_title (raro), aplica correção e registra
    # em erros_validacao como FIXABLE_FIELD. Reaplica safe_title para garantir.
    _erros_titulo = validar_limites_titulos(dados)
    if _erros_titulo:
        # Re-corrige automaticamente
        dados["titulo_seo"]  = safe_title(dados["titulo_seo"], LIMITE_TITULO_SEO)
        dados["titulo_capa"] = safe_title(dados["titulo_capa"], LIMITE_TITULO_CAPA)
        dados["titulo"]      = dados["titulo_seo"]
        # Mescla erros (não duplicados)
        _existentes = dados.get("erros_validacao", []) or []
        dados["erros_validacao"] = list(_existentes) + _erros_titulo
        print(f"[REDACAO] ⚠ {len(_erros_titulo)} título(s) corrigido(s) por safe_title")

    # ── Etapa 4.7 (v67): Coverage Score + Quality Score reais ───────────────
    # Coverage: compara mapa de evidencias com corpo gerado.
    # Quality: penaliza erros, limites, expressoes proibidas, etc.
    try:
        from ururau.editorial.quality_gates import (
            calculate_fact_coverage,
            calculate_quality_score,
        )
        _cov = calculate_fact_coverage(dados, mapa_dict)
        _qual = calculate_quality_score(
            dados,
            essential_facts=mapa_dict,
            erros_validacao=dados.get("erros_validacao") or [],
            coverage=_cov,
        )
        dados["coverage_score"]   = _cov["coverage_score"]
        dados["facts_required"]   = _cov["facts_required"]
        dados["facts_used"]       = _cov["facts_used"]
        dados["facts_missing"]    = _cov["facts_missing"]
        dados["score_qualidade"]  = _qual["score_qualidade"]
        dados["score_qualidade_detalhes"] = _qual["detalhes"]
        print(f"[REDACAO] coverage_score={_cov['coverage_score']:.2f} | "
              f"facts_used={len(_cov['facts_used'])}/{len(_cov['facts_required'])} | "
              f"score_qualidade={_qual['score_qualidade']}/100")
        # Se cobertura baixa, adiciona EDITORIAL_BLOCKER
        if _cov["coverage_score"] < 0.85:
            erros_existentes = dados.get("erros_validacao") or []
            erros_existentes.append({
                "categoria": "EDITORIAL_BLOCKER",
                "codigo":    "low_source_coverage",
                "severidade":"alta",
                "campo":     "corpo_materia",
                "mensagem":  (f"Coverage baixa: {_cov['coverage_score']:.2f}. "
                              f"{len(_cov['facts_missing'])} fato(s) ausente(s)."),
                "trecho":    "",
                "sugestao":  "Reescreva o corpo incluindo os fatos essenciais ausentes.",
                "bloqueia_publicacao":     True,
                "corrigivel_automaticamente": False,
            })
            dados["erros_validacao"] = erros_existentes
    except Exception as _e:
        print(f"[REDACAO] Aviso: nao foi possivel calcular coverage/quality: {_e}")
        dados["coverage_score"]  = 0.0
        dados["score_qualidade"] = 0

    # ── Etapa 5: Score de risco ───────────────────────────────────────────────
    resultado_risco = analisar_risco(dados["conteudo"], canal=canal)
    score_risco = resultado_risco.score
    print(f"[REDACAO] Score de risco: {score_risco}/100 ({resultado_risco.nivel})")

    # ── Etapa 6: Informações de auditoria nos dados ───────────────────────────
    dados["_auditoria_aprovada"]  = resultado.aprovado_auditoria
    dados["_auditoria_bloqueada"] = resultado.bloqueado
    dados["_auditoria_erros"]     = resultado.todos_erros[:5]
    dados["_status_pipeline"]     = resultado.status_publicacao
    dados["_violacoes_factuais"]  = resultado.violacoes_factuais

    bloq_txt = "BLOQUEADA" if resultado.bloqueado else "APROVADA"
    print(f"[REDACAO] Auditoria: {bloq_txt} | Título: '{titulo_seo[:60]}'")
    print(f"[REDACAO] Corpo: {len(dados['conteudo'])} chars | "
          f"Parágrafos: {len([p for p in dados['conteudo'].split(chr(10)*2) if p.strip()])}")

    # ── Determina status da matéria com base na auditoria ────────────────────
    # Se a auditoria bloqueou → salva como rascunho para revisão humana.
    # Nunca expõe artigo bloqueado para publicação direta.
    _status_materia = "rascunho"
    if resultado.aprovado_auditoria and not resultado.bloqueado:
        _pub = resultado.status_publicacao
        if _pub == "publicar_direto":
            _status_materia = "pronta"
        elif _pub == "salvar_rascunho":
            _status_materia = "rascunho"
        else:
            _status_materia = "rascunho"

    if resultado.bloqueado:
        print(f"[REDACAO] ⛔ MATÉRIA BLOQUEADA — será salva como rascunho para revisão humana")
        print(f"[REDACAO] Motivos: {resultado.todos_erros[:3]}")

    # ── Etapa 7: Monta dataclass Materia ─────────────────────────────────────
    mapa_obj = MapaEvidencias(
        fato_principal    = mapa_dict.get("fato_principal", ""),
        fatos_secundarios = mapa_dict.get("fatos_secundarios", []),
        quem              = mapa_dict.get("quem", []),
        onde              = mapa_dict.get("onde", ""),
        quando            = mapa_dict.get("quando", ""),
        por_que_importa   = mapa_dict.get("por_que_importa", ""),
        consequencia      = mapa_dict.get("consequencia", ""),
        contexto_anterior = mapa_dict.get("contexto_anterior", ""),
        numero_principal  = mapa_dict.get("numero_principal", ""),
        orgao_central     = mapa_dict.get("orgao_central", ""),
        status_atual      = mapa_dict.get("status_atual", ""),
        proximos_passos   = mapa_dict.get("proximos_passos", ""),
        fonte_primaria    = mapa_dict.get("fonte_primaria", ""),
        fontes_secundarias = mapa_dict.get("fontes_secundarias", []),
        grau_confianca    = mapa_dict.get("grau_confianca", "medio"),
        risco_editorial   = mapa_dict.get("risco_editorial", "baixo"),
    )

    materia = Materia(
        retranca          = dados["retranca"],
        titulo            = dados["titulo"],
        titulo_capa       = dados["titulo_capa"],
        titulos_alternativos     = [],
        titulos_capa_alternativos = [],
        frase_chave       = dados.get("frase_chave", ""),
        slug              = dados["slug"],
        meta_description  = dados["meta_description"],
        subtitulo         = dados["subtitulo"],
        legenda           = dados["legenda"],
        tags              = dados["tags"],
        intertitulos      = [],
        estrutura_decisao = dados.get("estrutura_decisao", ""),
        conteudo          = dados["conteudo"],
        resumo_curto      = dados["resumo_curto"],
        chamada_social    = dados["chamada_social"],
        fonte_nome        = fonte_nome,
        link_origem       = link_origem,
        canal             = canal,
        score_editorial   = score_edit,
        score_risco       = score_risco,
        status            = _status_materia,
        mapa_evidencias   = mapa_obj,
        termos_ia_detectados = [],
        nome_da_fonte     = dados.get("nome_da_fonte", "Redação"),
        creditos_da_foto  = dados.get("creditos_da_foto", ""),
        auditoria_aprovada  = resultado.aprovado_auditoria,
        auditoria_bloqueada = resultado.bloqueado,
        auditoria_erros   = resultado.todos_erros[:5],
        status_pipeline   = resultado.status_publicacao,
        violacoes_factuais = resultado.violacoes_factuais,
        metadados_apurados = dados.get("metadados_apurados", {}),
    )

    # ── v69b: PROPAGAÇÃO COMPLETA dos campos para Materia ───────────────────
    # Bug do v69: este bloco estava truncado e gerar_materia() podia retornar None.
    # Agora todos os campos sao propagados, coverage tipado calculado, relacoes
    # validadas e finalmente retornamos a Materia com tudo populado.
    try:
        materia.coverage_score          = float(dados.get("coverage_score", 0.0) or 0.0)
        materia.score_qualidade         = int(dados.get("score_qualidade", 0) or 0)
        materia.score_risco_validacao   = int(dados.get("score_risco_validacao", 0) or 0)
        materia.facts_required          = list(dados.get("facts_required", []) or [])
        materia.facts_used              = list(dados.get("facts_used", []) or [])
        materia.facts_missing           = list(dados.get("facts_missing", []) or [])
        materia.entity_relationships    = list(dados.get("entity_relationships", []) or [])
        materia.relationship_errors     = list(dados.get("relationship_errors", []) or [])
        materia.source_sufficiency_score = int(_get("source_sufficiency_score", 0) or 0)
        materia.extraction_method       = str(_get("extraction_method", ""))
        materia.extraction_status       = str(_get("extraction_status", ""))
        materia.raw_source_text         = str(_get("raw_source_text", ""))[:8000]
        materia.cleaned_source_text     = str(_get("cleaned_source_text", _texto_limpo or ""))[:8000]
        materia.rss_context_text        = str(_get("rss_context_text", ""))[:4000]
        materia.article_type            = str(dados.get("article_type", "") or canal or "")
        materia.editorial_angle         = str(dados.get("editorial_angle", ""))
        materia.paragraph_plan          = list(dados.get("paragraph_plan", []) or [])
        materia.generated_article_json  = {k: v for k, v in dados.items()
                                            if not k.startswith("_") and k != "metadados_apurados"
                                            and not callable(v)}
        # Status / revisao
        if dados.get("status_validacao"):
            materia.status_validacao = str(dados["status_validacao"])
            materia.status_publicacao_sugerido = str(dados["status_publicacao_sugerido"])
        if dados.get("revisao_humana_necessaria") is not None:
            materia.revisao_humana_necessaria = bool(dados["revisao_humana_necessaria"])
        if dados.get("erros_validacao"):
            materia.erros_validacao = list(dados["erros_validacao"])
    except Exception as _e:
        print(f"[REDACAO v69c] aviso: propagacao parcial falhou: {_e}")

    # ── v69c: Coverage tipado (validacao pos-IA) ─────────────────────────────
    try:
        from ururau.editorial.coverage_por_tipo import (
            extract_required_facts_from_source, calculate_fact_coverage_typed,
        )
        _src_cov = materia.cleaned_source_text or _texto_limpo or ""
        _tipo = materia.article_type or canal or ""
        if _src_cov:
            req_facts = extract_required_facts_from_source(_src_cov, _tipo)
            cov = calculate_fact_coverage_typed(dados, req_facts, _src_cov)
            materia.coverage_score = cov["coverage_score"]
            materia.facts_required = cov["facts_required"]
            materia.facts_used     = cov["facts_used"]
            materia.facts_missing  = cov["facts_missing"]
            print(f"[REDACAO v69c] coverage_tipado={cov['coverage_score']:.2f}")
            if cov["coverage_score"] < 0.85 and len(req_facts) > 0:
                erros = list(materia.erros_validacao or [])
                if not any(isinstance(e, dict) and e.get("codigo") == "low_source_coverage"
                           for e in erros):
                    erros.append({
                        "categoria": "EDITORIAL_BLOCKER",
                        "codigo": "low_source_coverage",
                        "severidade": "alta",
                        "campo": "corpo_materia",
                        "mensagem": f"Coverage tipado baixo: {cov['coverage_score']:.2f}",
                        "bloqueia_publicacao": True,
                        "corrigivel_automaticamente": False,
                    })
                    materia.erros_validacao = erros
                materia.auditoria_bloqueada = True
                materia.status_validacao = "reprovado"
    except Exception as _e:
        print(f"[REDACAO v69c] aviso: coverage falhou: {_e}")

    # ── v69c: Validacao de relacoes (pos-IA) ────────────────────────────────
    try:
        from ururau.editorial.relationships import (
            extract_entity_relationships, validate_entity_relationships,
        )
        _src_rel = materia.cleaned_source_text or _texto_limpo or ""
        if _src_rel:
            relacoes = extract_entity_relationships(_src_rel, materia.article_type, client, modelo)
            materia.entity_relationships = relacoes
            erros_rel = validate_entity_relationships(dados, relacoes)
            if erros_rel:
                materia.relationship_errors = erros_rel
                materia.erros_validacao = list(materia.erros_validacao or []) + erros_rel
                if any(e.get("categoria") == "EDITORIAL_BLOCKER" for e in erros_rel):
                    materia.auditoria_bloqueada = True
                    materia.status_validacao = "reprovado"
    except Exception as _e:
        print(f"[REDACAO v69c] aviso: relacoes falhou: {_e}")

    return materia
