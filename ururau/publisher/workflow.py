"""
publisher/workflow.py — Máquina de estado do workflow de publicação.
Orquestra todas as etapas: coleta → imagem → redação → copydesk → risco → publicação.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from ururau.config.settings import (
    LIMIAR_RISCO_MAXIMO,
    LOGIN,
    SENHA,
    StatusPauta,
    CategoriaErro,
)
from ururau.core.models import Pauta, Materia, ImagemDados
from ururau.editorial.redacao import gerar_materia
from ururau.editorial.pacote import completar_pacote_editorial
from ururau.editorial.risco import analisar_risco, resumo_risco
from ururau.imaging.processamento import pipeline_imagem
from ururau.coleta.scraping import extrair_dossie

if TYPE_CHECKING:
    from openai import OpenAI
    from ururau.core.database import Database

def _uid_para_pauta(link: str, titulo: str) -> str:
    """
    Gera UID estável para uma pauta a partir de link + título.

    Mantida em workflow.py por compatibilidade com painel.py, monitor.py
    e rotinas antigas que importam:
        from ururau.publisher.workflow import _uid_para_pauta
    """
    import hashlib
    base = f"{link or ''}{titulo or ''}"
    return hashlib.md5(base.encode("utf-8")).hexdigest()[:16]


# ── Gate de publicação — função central obrigatória ──────────────────────────

def can_publish(artigo: dict, modo: str = "panel") -> tuple[bool, str]:
    """
    Gate de publicação v69c — aceita modo='panel' ou modo='monitor'.

    PANEL:  coverage_score >= 0.85, score_qualidade >= 90
    MONITOR: coverage_score >= 0.90, score_qualidade >= 92, score_risco <= 10

    Comum: status_validacao='aprovado', auditoria_bloqueada=False, sem
    CONFIG_ERROR/EXTRACTION_ERROR/EDITORIAL_BLOCKER, sem relationship_errors,
    limites validos, corpo nao vazio.

    Aprovação manual libera mesmo com erros (mas exige corpo).
    """
    modo = (modo or "panel").lower()
    if not artigo:
        return False, "Artigo nulo ou vazio."

    # ── Caminho 0 (SEMPRE BLOQUEANTE): CONFIG_ERROR e EXTRACTION_ERROR ────────
    # Estes erros indicam que o artigo NUNCA FOI GERADO corretamente.
    # Nem aprovação manual pode autorizar a publicação de um artigo sem corpo.
    erros_val = artigo.get("erros_validacao", []) or []

    if artigo.get("_is_config_error"):
        return False, (
            "CONFIG_ERROR: O pipeline abortou por falha de configuração da API OpenAI. "
            "O artigo não foi gerado. Corrija a API key e reprocesse."
        )

    status_val_raw = artigo.get("status_validacao") or ""
    _sv_str = status_val_raw if isinstance(status_val_raw, str) else ""
    if _sv_str == "erro_configuracao":
        return False, (
            "CONFIG_ERROR: status_validacao='erro_configuracao'. "
            "O artigo não foi gerado — chave de API inválida ou ausente. "
            "Corrija a configuração e use 'Reprocessar' na aba de Revisão."
        )
    if _sv_str == "erro_extracao":
        return False, (
            "EXTRACTION_ERROR: status_validacao='erro_extracao'. "
            "A fonte estava vazia ou inválida — o artigo não foi gerado. "
            "Verifique a fonte e use 'Reprocessar' na aba de Revisão."
        )

    _config_erros = [
        e for e in erros_val
        if isinstance(e, dict) and e.get("categoria") == CategoriaErro.CONFIG_ERROR
    ]
    if _config_erros:
        primeiro = _config_erros[0]
        return False, (
            f"CONFIG_ERROR: {primeiro.get('mensagem', 'Falha de configuração da API')} "
            f"[{primeiro.get('codigo','')}]. O artigo não foi gerado."
        )

    _extr_erros = [
        e for e in erros_val
        if isinstance(e, dict) and e.get("categoria") == CategoriaErro.EXTRACTION_ERROR
    ]
    if _extr_erros:
        primeiro = _extr_erros[0]
        return False, (
            f"EXTRACTION_ERROR: {primeiro.get('mensagem', 'Fonte inválida ou vazia')} "
            f"[{primeiro.get('codigo','')}]. O artigo não foi gerado."
        )

    # Bloqueia se corpo_materia estiver vazio (artigo sem conteúdo gerado)
    corpo = (artigo.get("corpo_materia") or artigo.get("conteudo") or "").strip()
    if not corpo:
        return False, (
            "Artigo sem corpo (corpo_materia vazio). "
            "O pipeline não gerou conteúdo — verifique erros e reprocesse."
        )

    # ── Caminho 1: aprovação manual explícita ─────────────────────────────────
    approved_by     = artigo.get("approved_by", "") or ""
    approved_at     = artigo.get("approved_at", "") or ""
    approval_reason = artigo.get("manual_approval_reason", "") or ""
    if approved_by.strip() and approved_at.strip() and approval_reason.strip():
        return True, ""

    # ── Caminho 2: aprovação automática (auditoria passou) ───────────────────
    status_val = _sv_str.lower().strip() if _sv_str else (
        str(status_val_raw) if isinstance(status_val_raw, str) else ""
    )
    aud_bloqueada = artigo.get("auditoria_bloqueada", True)

    # Aceita "aprovado" ou mapa de auditoria com aprovado=True
    _aprovado_status = status_val == "aprovado"
    if not _aprovado_status:
        # Fallback: dict status_validacao do pipeline (pode ser dict ou str)
        sv = artigo.get("status_validacao")
        if isinstance(sv, dict):
            _aprovado_status = bool(sv.get("aprovado", False))

    if not _aprovado_status:
        return False, (
            f"status_validacao='{status_val}' (esperado: 'aprovado'). "
            "Corrija os erros de validação ou obtenha aprovação manual."
        )

    if aud_bloqueada:
        erros_aud = artigo.get("auditoria_erros", []) or []
        resumo = "; ".join(str(e) for e in erros_aud[:2])
        return False, (
            f"Auditoria bloqueou o artigo. "
            f"{('Erros: ' + resumo) if resumo else 'Verifique a aba Auditoria.'}"
        )

    # Verifica erros classificados como EDITORIAL_BLOCKER
    blockers = [
        e for e in erros_val
        if isinstance(e, dict) and e.get("categoria") == CategoriaErro.EDITORIAL_BLOCKER
    ]
    if blockers:
        return False, (
            f"{len(blockers)} erro(s) EDITORIAL_BLOCKER não resolvido(s). "
            f"Primeiro: {blockers[0].get('mensagem', '')[:80]}"
        )

    # ── v69c: gates por MODO (panel: 0.85/90, monitor: 0.90/92/risco<=10) ──
    cov_min = 0.90 if modo == "monitor" else 0.85
    sq_min  = 92 if modo == "monitor" else 90

    cov = artigo.get("coverage_score")
    if modo == "monitor":
        # Monitor: coverage AUSENTE/0 bloqueia
        if cov is None or cov == 0:
            return False, (
                f"coverage_score ausente/0 (modo monitor exige >= {cov_min}). "
                "Reescreva incluindo os fatos essenciais ausentes."
            )
    if cov is not None:
        try:
            cov_f = float(cov)
            if cov_f > 0 and cov_f < cov_min:
                return False, (
                    f"coverage_score={cov_f:.2f} abaixo de {cov_min} (modo={modo}). "
                    "Reescreva incluindo os fatos essenciais ausentes."
                )
        except Exception:
            return False, f"coverage_score invalido: {cov!r}"

    sq = artigo.get("score_qualidade")
    if sq is not None:
        try:
            sq_i = int(sq)
            if sq_i > 0 and sq_i < sq_min:
                return False, (
                    f"score_qualidade={sq_i} abaixo de {sq_min} (modo={modo}). "
                    "Use o Copydesk para corrigir os campos com problema."
                )
        except Exception:
            pass

    # Monitor: gate adicional de risco
    if modo == "monitor":
        risco = artigo.get("score_risco_validacao") or artigo.get("score_risco") or 0
        try:
            if int(risco) > 10:
                return False, f"score_risco={risco} > 10 (modo monitor exige <=10)."
        except Exception:
            pass

    rel_errs = artigo.get("relationship_errors") or []
    if rel_errs:
        primeiro = rel_errs[0] if isinstance(rel_errs[0], dict) else {}
        return False, (
            f"{len(rel_errs)} erro(s) de relacao factual. "
            f"Primeiro: {primeiro.get('mensagem', str(rel_errs[0]))[:80]}"
        )

    titulo_seo = artigo.get("titulo_seo") or artigo.get("titulo") or ""
    titulo_capa = artigo.get("titulo_capa") or ""
    if titulo_seo and len(titulo_seo) > 89:
        return False, f"titulo_seo tem {len(titulo_seo)} chars (limite 89)."
    if titulo_capa and len(titulo_capa) > 60:
        return False, f"titulo_capa tem {len(titulo_capa)} chars (limite 60)."

    return True, ""


def revisao_humana_necessaria(artigo: dict) -> bool:
    """
    Retorna True se o artigo precisa de revisão humana antes de publicar.

    Critérios:
    - auditoria_bloqueada = True
    - status_validacao != "aprovado"
    - status_publicacao_sugerido in ("salvar_rascunho", "bloquear")
    - revisao_humana_necessaria = True (campo explícito)
    """
    if artigo.get("revisao_humana_necessaria"):
        return True
    if artigo.get("auditoria_bloqueada", False):
        return True
    sv = artigo.get("status_validacao", "") or ""
    if isinstance(sv, dict):
        sv = "aprovado" if sv.get("aprovado") else "reprovado"
    if sv not in ("aprovado",):
        return True
    pub = (artigo.get("status_publicacao_sugerido") or "").lower()
    if pub in ("salvar_rascunho", "bloquear"):
        return True
    return False


class WorkflowPublicacao:
    """
    Máquina de estados para o ciclo de vida completo de uma pauta.

    Estados formais (StatusPauta):
        captada → triada → aprovada → em_redacao → revisada → pronta → publicada
        Em caso de falha: → rejeitada | bloqueada
    """

    def __init__(
        self,
        db: "Database",
        client: "OpenAI",
        modelo: str,
    ):
        self.db = db
        self.client = client
        self.modelo = modelo

    # ── Helpers de log ────────────────────────────────────────────────────────

    def _log(self, uid: str, acao: str, detalhe: str = "", sucesso: bool = True):
        """Registra evento no log de auditoria e imprime no console."""
        print(f"[WORKFLOW] [{uid[:8]}] {acao}: {detalhe}")
        try:
            self.db.log_auditoria(uid, acao, detalhe, sucesso=sucesso)
        except Exception as e:
            print(f"[WORKFLOW] Falha ao registrar auditoria: {e}")

    def _set_status(self, uid: str, pauta_dict: dict, status: str, motivo: str = ""):
        """Atualiza status da pauta no banco e no dict."""
        pauta_dict["status"] = status
        try:
            self.db.atualizar_status_pauta(uid, status)
        except Exception:
            pass
        if motivo:
            self._log(uid, f"status:{status}", motivo)
        else:
            self._log(uid, f"status:{status}")

    # ── Etapas individuais ────────────────────────────────────────────────────

    def etapa_gate_antiduplicacao(self, uid: str, pauta: dict,
                                     modo: str = "redigir") -> bool:
        """
        Gate de entrada anti-duplicação.

        modo='redigir' (padrão): bloqueia se já publicada, descartada ou título similar.
            Permite pautas em qualquer status de rascunho (pronta, revisada, etc.).

        modo='publicar': verifica APENAS se já foi publicada de fato no CMS.
            Permite publicar rascunhos em qualquer estágio.

        Verifica (em ordem, para modo='redigir'):
          1. Já publicada no Ururau  → rejeita definitivamente
          2. Descartada/bloqueada   → rejeita (não reprocessa)
          3. Título similar publicado nas últimas 72h → rejeita

        Para modo='publicar':
          1. Apenas verifica se já publicada no CMS
        """
        link   = pauta.get("link_origem", "")
        titulo = pauta.get("titulo_origem", "")

        # 1. Já publicada no CMS (bloqueia sempre, qualquer modo)
        if self.db.pauta_ja_publicada(link, uid):
            self._log(uid, "gate:duplicada", "Pauta ja publicada no Ururau", sucesso=False)
            return False

        # Para modo publicar: só verifica se já foi publicada de fato
        if modo == "publicar":
            return True

        # 2. Descartada ou bloqueada anteriormente (apenas no modo redigir)
        if self.db.pauta_foi_descartada(link, uid):
            status_anterior = self.db.classificar_pauta(link, uid)
            self._log(uid, "gate:descartada",
                      f"Status anterior: {status_anterior}", sucesso=False)
            return False

        # 3. Título similar publicado recentemente (apenas no modo redigir)
        similar = self.db.titulo_similar_ja_publicado(titulo)
        if similar:
            self._log(uid, "gate:similar",
                      f"Titulo similar: '{similar[:60]}'", sucesso=False)
            self._set_status(uid, pauta, StatusPauta.REJEITADA,
                             f"Similar a: {similar[:60]}")
            return False

        return True

    def etapa_triagem(self, uid: str, pauta: dict) -> bool:
        """Valida dados mínimos da pauta."""
        titulo = pauta.get("titulo_origem", "")
        link   = pauta.get("link_origem", "")

        if not titulo or not link:
            self._log(uid, "triagem", "Pauta sem título ou link", sucesso=False)
            self._set_status(uid, pauta, StatusPauta.REJEITADA, "Dados incompletos")
            return False

        self._set_status(uid, pauta, StatusPauta.TRIADA)
        return True

    def etapa_coleta_texto(self, uid: str, pauta: dict, modo: str = "panel") -> bool:
        """
        v68: Extrai texto completo via extrair_dossie_completo() e respeita
        extraction_status. Se 'failed', NAO continua com resumo_origem.

        modo='panel'   -> em failed, salva como rascunho (status='erro_extracao')
                          e retorna False para encerrar pipeline.
        modo='monitor' -> em failed, retorna False (publicacao direta nunca
                          parte de fonte falhada).
        """
        try:
            from ururau.coleta.scraping import extrair_dossie_completo
            res = extrair_dossie_completo(
                url=pauta.get("link_origem", ""),
                texto_existente=pauta.get("texto_fonte", ""),
            )
            dossie    = res.get("dossie", "") or ""
            status    = res.get("extraction_status", "failed")
            metodo    = res.get("extraction_method", "failed")
            score     = res.get("source_sufficiency_score", 0)
            raw_src   = res.get("raw_source_text", "")
            clean_src = res.get("cleaned_source_text", "")

            pauta["dossie"]                   = dossie
            pauta["raw_source_text"]          = raw_src
            pauta["cleaned_source_text"]      = clean_src
            pauta["extraction_method"]        = metodo
            pauta["source_sufficiency_score"] = score
            pauta["extraction_status"]        = status

            # Mantem texto_fonte tambem para retrocompatibilidade
            if not pauta.get("texto_fonte") and dossie:
                pauta["texto_fonte"] = dossie[:3000]

            self._log(uid, "coleta_texto",
                       f"{len(dossie)} chars | metodo={metodo} | status={status} | score={score}")

            if status == "failed":
                # v68: NAO mascara falha com resumo_origem.
                self._log(uid, "coleta_texto",
                           "FAIL-CLOSED: extracao falhou, abortando pipeline.",
                           sucesso=False)
                # Marca a pauta para revisao com extraction error
                pauta["status_validacao"]            = "erro_extracao"
                pauta["status_publicacao_sugerido"]  = "salvar_rascunho"
                pauta["revisao_humana_necessaria"]   = True
                self._set_status(uid, pauta, StatusPauta.REVISADA,
                                  "Extracao da fonte falhou")
                return False

            return True
        except Exception as e:
            self._log(uid, "coleta_texto", f"Erro: {e}", sucesso=False)
            # v68: NUNCA continuar com resumo_origem como fonte
            pauta["dossie"]                   = ""
            pauta["status_validacao"]         = "erro_extracao"
            pauta["status_publicacao_sugerido"] = "salvar_rascunho"
            pauta["revisao_humana_necessaria"] = True
            self._set_status(uid, pauta, StatusPauta.REVISADA,
                              f"Erro de extracao: {e}")
            return False

    def etapa_imagem(self, uid: str, pauta: dict) -> Optional[ImagemDados]:
        """Executa pipeline de imagem."""
        try:
            imagem = pipeline_imagem(
                url_pagina=pauta.get("link_origem", ""),
                titulo=pauta.get("titulo_origem", ""),
                pauta_uid=uid,
            )
            if imagem and imagem.caminho_imagem:
                pauta["imagem_status"]   = "aprovada"
                pauta["imagem_caminho"]  = imagem.caminho_imagem
                pauta["imagem_url"]      = imagem.url_imagem
                pauta["imagem_credito"]  = imagem.credito_foto
                pauta["imagem_estrategia"] = imagem.estrategia_imagem
                self.db.salvar_imagem(uid, imagem.to_dict())
                self._log(uid, "imagem", f"Estratégia: {imagem.estrategia_imagem}")
                return imagem
            else:
                pauta["imagem_status"] = "sem_imagem"
                self._log(uid, "imagem", "Nenhuma imagem encontrada", sucesso=False)
                return None
        except Exception as e:
            pauta["imagem_status"] = "erro"
            self._log(uid, "imagem", f"Erro: {e}", sucesso=False)
            return None

    def etapa_redacao(self, uid: str, pauta: dict) -> Optional[Materia]:
        """Gera a matéria completa."""
        canal = pauta.get("canal_forcado") or pauta.get("canal") or "Brasil e Mundo"

        self._set_status(uid, pauta, StatusPauta.EM_REDACAO)
        try:
            materia = gerar_materia(pauta, self.client, self.modelo, canal)
            self._log(uid, "redacao", f"Título: {materia.titulo[:60]}")
            return materia
        except Exception as e:
            self._log(uid, "redacao", f"Erro: {e}", sucesso=False)
            self._set_status(uid, pauta, StatusPauta.REJEITADA, f"Falha na redação: {e}")
            return None

    def etapa_pacote_editorial(self, uid: str, materia: Materia) -> Materia:
        """Complementa com títulos alternativos, chamada social e resumo."""
        try:
            materia = completar_pacote_editorial(materia, self.client, self.modelo)
            self._log(uid, "pacote_editorial", "Pacote completo")
        except Exception as e:
            self._log(uid, "pacote_editorial", f"Aviso: {e}", sucesso=False)
        return materia

    def etapa_verificacao_risco(self, uid: str, pauta: dict, materia: Materia) -> bool:
        """
        Verifica score de risco editorial.
        Retorna False (e bloqueia) se score >= LIMIAR_RISCO_MAXIMO.
        """
        resultado = analisar_risco(materia.conteudo, canal=materia.canal)
        materia.score_risco = resultado.score
        pauta["score_risco"] = resultado.score

        resumo = resumo_risco(resultado)
        self._log(uid, "risco", resumo, sucesso=not resultado.bloqueante)

        if resultado.bloqueante:
            self._set_status(
                uid, pauta, StatusPauta.BLOQUEADA,
                f"Score de risco: {resultado.score}/100 — {', '.join(resultado.alertas[:3])}"
            )
            return False

        self._set_status(uid, pauta, StatusPauta.REVISADA)
        return True

    def etapa_persistir_materia(self, uid: str, pauta: dict, materia: Materia) -> bool:
        """
        Persiste matéria no banco de dados.

        IMPORTANTE: NÃO define status=PRONTA se a auditoria bloqueou a matéria.
        Matérias bloqueadas ficam em StatusPauta.REVISADA (aguardando revisão humana).
        Apenas matérias aprovadas chegam a StatusPauta.PRONTA.
        """
        try:
            materia_dict = materia.to_dict()
            pauta["materia"] = materia_dict
            self.db.salvar_materia(uid, materia_dict)
            self.db.salvar_pauta({**pauta, "_uid": uid})

            # Nunca marca PRONTA se há CONFIG_ERROR ou EXTRACTION_ERROR
            _erros_mat = materia_dict.get("erros_validacao", []) or []
            _has_sys_error = (
                materia_dict.get("_is_config_error") or
                materia_dict.get("status_validacao") in ("erro_configuracao", "erro_extracao") or
                any(
                    isinstance(e, dict) and e.get("categoria") in (
                        CategoriaErro.CONFIG_ERROR, CategoriaErro.EXTRACTION_ERROR
                    )
                    for e in _erros_mat
                )
            )
            if _has_sys_error:
                self._set_status(uid, pauta, StatusPauta.REVISADA)
                self._log(uid, "persistencia",
                          "Matéria salva para REVISÃO HUMANA — CONFIG/EXTRACTION ERROR detectado",
                          sucesso=False)
            # Gate: só marca PRONTA se a auditoria aprovada E não bloqueada
            elif materia.auditoria_aprovada and not materia.auditoria_bloqueada:
                self._set_status(uid, pauta, StatusPauta.PRONTA)
                self._log(uid, "persistencia", "Matéria aprovada e salva como PRONTA")
            else:
                # Bloqueada ou pendente: salva como REVISADA (aguarda revisão humana)
                self._set_status(uid, pauta, StatusPauta.REVISADA)
                self._log(uid, "persistencia",
                          f"Matéria salva para REVISÃO HUMANA "
                          f"(auditoria_bloqueada={materia.auditoria_bloqueada}, "
                          f"status_pipeline={materia.status_pipeline})")
            return True
        except Exception as e:
            self._log(uid, "persistencia", f"Erro: {e}", sucesso=False)
            return False

    def etapa_publicacao(
        self,
        uid: str,
        pauta: dict,
        materia: Materia,
        imagem: Optional[ImagemDados],
        rascunho: bool = True,
    ) -> bool:
        """
        Executa publicação via Playwright.

        rascunho=True (padrão) → salva como rascunho no CMS (não publica ao vivo).
        rascunho=False → publica diretamente (use com cautela).

        Gate v62: chama can_publish() antes de qualquer ação no CMS.
        Em modo rascunho, ainda permite envio (CMS recebe e salva como draft),
        mas registra o motivo do bloqueio para auditoria.
        """
        # Gate v67: FAIL-CLOSED em modo monitor (rascunho=False).
        artigo_dict = {}
        try:
            artigo_dict = materia.to_dict() if hasattr(materia, "to_dict") else {}
        except Exception:
            artigo_dict = {}
        try:
            # v69c: modo apropriado - rascunho=False (publicacao real) eh "monitor"
            _modo_cp = "monitor" if not rascunho else "panel"
            pode, motivo = can_publish(artigo_dict, modo=_modo_cp)
        except Exception as _e:
            if not rascunho:
                self._log(uid, "gate_can_publish",
                          f"FAIL-CLOSED (monitor): can_publish lancou: {_e}",
                          sucesso=False)
                return False
            else:
                self._log(uid, "gate_can_publish",
                          f"Aviso (rascunho): can_publish falhou - prosseguindo. {_e}",
                          sucesso=True)
                pode, motivo = True, ""
        if not pode and not rascunho:
            self._log(uid, "gate_can_publish",
                      f"Bloqueado por can_publish: {motivo}", sucesso=False)
            return False
        if not pode and rascunho:
            self._log(uid, "gate_can_publish",
                      f"Salvando rascunho mesmo com restrições: {motivo}",
                      sucesso=True)
        # v67: gate adicional para monitor (publicacao direta)
        if not rascunho:
            try:
                from ururau.editorial.quality_gates import monitor_autopub_check
                pode_dir, motivos = monitor_autopub_check(artigo_dict)
                if not pode_dir:
                    self._log(uid, "monitor_autopub_gate",
                              f"BLOQUEADO: {'; '.join(motivos[:3])}",
                              sucesso=False)
                    return False
                self._log(uid, "monitor_autopub_gate", "OK", sucesso=True)
            except Exception as _e:
                self._log(uid, "monitor_autopub_gate",
                          f"FAIL-CLOSED: {_e}", sucesso=False)
                return False

        try:
            print(f"[PUBLICACAO] Chamando Playwright: canal={materia.canal} rascunho={rascunho}")
            try:
                sucesso = asyncio.run(
                    _publicar_async(materia, imagem, LOGIN, SENHA, rascunho=rascunho)
                )
            except RuntimeError as re:
                if "event loop" in str(re).lower():
                    # Já existe um event loop rodando (thread) — usa executor com novo loop
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(
                            asyncio.run,
                            _publicar_async(materia, imagem, LOGIN, SENHA, rascunho=rascunho)
                        )
                        sucesso = future.result(timeout=120)
                else:
                    raise
            if sucesso:
                self._set_status(uid, pauta, StatusPauta.PUBLICADA)
                self.db.registrar_publicacao(
                    uid, materia.canal, materia.titulo,
                    sucesso=True,
                    link_origem=pauta.get("link_origem", ""),
                )
                self._log(uid, "publicacao", f"Canal: {materia.canal}")
                return True
            else:
                self._log(uid, "publicacao", "Falha na publicação", sucesso=False)
                pauta["tentativas_publicacao"] = pauta.get("tentativas_publicacao", 0) + 1
                return False
        except Exception as e:
            self._log(uid, "publicacao", f"Erro: {e}", sucesso=False)
            return False

    # ── Pipeline principal ────────────────────────────────────────────────────

    def executar_publicacao(
        self,
        pauta: dict,
        publicar: bool = True,
    ) -> dict:
        """
        Executa o workflow completo para uma pauta.

        Parâmetros:
            pauta: dict com dados da pauta (deve ter título, link, canal_forcado)
            publicar: se True, tenta publicar no CMS após aprovação

        Retorna dict com resultado do workflow:
            - sucesso: bool
            - uid: str
            - status: str
            - materia: dict | None
            - imagem: dict | None
            - erro: str
        """
        uid = pauta.get("_uid") or _uid_para_pauta(
            pauta.get("link_origem", ""),
            pauta.get("titulo_origem", ""),
        )
        pauta["_uid"] = uid

        resultado = {
            "sucesso": False,
            "uid": uid,
            "status": pauta.get("status", StatusPauta.CAPTADA),
            "materia": None,
            "imagem": None,
            "erro": "",
        }

        self._log(uid, "inicio_workflow", pauta.get("titulo_origem", "")[:80])

        # ── Etapa 0: Gate anti-duplicação (modo redigir — não bloqueia rascunhos) ─
        if not self.etapa_gate_antiduplicacao(uid, pauta, modo="redigir"):
            resultado["status"] = pauta.get("status", StatusPauta.REJEITADA)
            resultado["erro"] = "Pauta bloqueada pelo gate anti-duplicacao"
            return resultado

        # ── Etapa 1: Triagem ───────────────────────────────────────────────────
        if not self.etapa_triagem(uid, pauta):
            resultado["status"] = pauta["status"]
            resultado["erro"] = "Falhou triagem"
            return resultado

        # ── Etapa 2: Coleta de texto ───────────────────────────────────────────
        # v68: respeita resultado da extracao - se failed, NAO segue para geracao.
        # modo do workflow: panel quando publicar=False (rascunho), monitor quando publicar=True.
        _modo_extracao = "monitor" if publicar else "panel"
        if not self.etapa_coleta_texto(uid, pauta, modo=_modo_extracao):
            resultado["status"] = pauta.get("status", StatusPauta.REVISADA)
            resultado["erro"] = "Falhou na extracao da fonte (sem fallback)"
            return resultado

        # ── Etapa 3: Imagem ────────────────────────────────────────────────────
        imagem = self.etapa_imagem(uid, pauta)
        if imagem:
            resultado["imagem"] = imagem.to_dict()

        # ── Etapa 4: Redação ───────────────────────────────────────────────────
        materia = self.etapa_redacao(uid, pauta)
        if not materia:
            resultado["status"] = pauta["status"]
            resultado["erro"] = "Falhou na redação"
            return resultado

        # ── Etapa 5: Pacote editorial ──────────────────────────────────────────
        materia = self.etapa_pacote_editorial(uid, materia)

        # ── Etapa 6: Verificação de risco ──────────────────────────────────────
        # ── Etapa 7: Persistência ──────────────────────────────────────────────
        if not self.etapa_persistir_materia(uid, pauta, materia):
            resultado["status"] = pauta["status"]
            resultado["erro"] = "Falha na persistência"
            return resultado

        resultado["materia"] = materia.to_dict()

        # Gate editorial obrigatorio
        # Gate editorial obrigatorio
        if materia.auditoria_bloqueada:
            self._log(uid, "gate_editorial",
                      f"BLOQUEADO: {materia.auditoria_erros[:2]}", sucesso=False)
          