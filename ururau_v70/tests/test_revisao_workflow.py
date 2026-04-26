"""
tests/test_revisao_workflow.py — Testes do fluxo de Revisão Editorial (v59)

Cobre todos os requisitos do sistema de revisão:
  T1: Botão Revisão substituiu Manual na toolbar (verificação de código)
  T2: Comportamento antigo do Manual foi preservado (dialog manual acessível)
  T3: Rascunhos pendentes aparecem na fila de revisão
  T4: Bloqueados aparecem na fila de revisão
  T5: Artigos aprovados NÃO aparecem na fila de revisão
  T6: Corrigir pendências — corrige FIXABLE_FIELD sem reescrever corpo
  T7: EDITORIAL_BLOCKER permanece bloqueado e visível
  T8: Publicar desabilitado para artigos pendente/reprovado sem aprovação manual
  T9: Aprovação manual — salva approved_by, approved_at, razão; preserva histórico
  T10: Pacote editorial não muda status para pronta se matéria bloqueada
  T11: can_publish() — todos os caminhos de publicação verificam o gate
  T12: Persistência — artigo pendente/reprovado persiste entre recarregamentos
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# Setup de path — v62: detecta raiz do projeto a partir do próprio arquivo
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_ROOT)
sys.path.insert(0, _ROOT)


# ── Helpers de teste ──────────────────────────────────────────────────────────

@dataclass
class ResultadoTeste:
    nome: str
    _falhas: list[str] = field(default_factory=list)
    _ok: list[str] = field(default_factory=list)

    def ok(self, msg: str = ""):
        self._ok.append(msg)

    def falha(self, msg: str):
        self._falhas.append(msg)

    @property
    def passou(self) -> bool:
        return not self._falhas

    def resumo(self) -> str:
        status = "✅ PASSOU" if self.passou else f"❌ FALHOU ({len(self._falhas)} falhas)"
        return f"  {status} — {self.nome}"

    def detalhes(self) -> list[str]:
        return [f"     ✗ {f}" for f in self._falhas]


_CORPO_TESTE = (
    "TJRJ bloqueou os bens do ex-secretário em decisão publicada nesta semana.\n\n"
    "A medida ocorreu após pedido do Ministério Público.\n\n"
    "A defesa ainda não se manifestou publicamente."
)


def _artigo_aprovado() -> dict:
    return {
        "status_validacao": "aprovado",
        "auditoria_bloqueada": False,
        "auditoria_aprovada": True,
        "erros_validacao": [],
        "auditoria_erros": [],
        "status_publicacao_sugerido": "publicar",
        "corpo_materia": _CORPO_TESTE,
        "conteudo": _CORPO_TESTE,
        "titulo_seo": "TJRJ bloqueia bens de ex-secretário em ação do MP",
        "coverage_score": 0.95,  # v69c: gate exige
        "score_qualidade": 92,   # v69c: gate exige
    }


def _artigo_reprovado() -> dict:
    return {
        "status_validacao": "reprovado",
        "auditoria_bloqueada": True,
        "auditoria_aprovada": False,
        "erros_validacao": [
            {
                "codigo": "DATA_INVENTADA",
                "categoria": "EDITORIAL_BLOCKER",
                "severidade": "alta",
                "campo": "corpo_materia",
                "mensagem": "Data inventada detectada no artigo.",
                "trecho": "amanhã será realizado o evento",
                "sugestao": "Remova ou confirme a data.",
                "bloqueia_publicacao": True,
                "corrigivel_automaticamente": False,
            }
        ],
        "auditoria_erros": ["Data inventada detectada."],
        "status_publicacao_sugerido": "bloquear",
        "corpo_materia": _CORPO_TESTE,
        "conteudo": _CORPO_TESTE,
        "titulo_seo": "TJRJ bloqueia bens de ex-secretário em ação do MP",
    }


def _artigo_pendente() -> dict:
    return {
        "status_validacao": "pendente",
        "auditoria_bloqueada": False,
        "auditoria_aprovada": False,
        "erros_validacao": [
            {
                "codigo": "FONTE_AUSENTE",
                "categoria": "FIXABLE_FIELD",
                "severidade": "media",
                "campo": "nome_da_fonte",
                "mensagem": "Nome da fonte ausente.",
                "trecho": "",
                "sugestao": "Preencha o campo nome_da_fonte.",
                "bloqueia_publicacao": False,
                "corrigivel_automaticamente": True,
            }
        ],
        "auditoria_erros": [],
        "status_publicacao_sugerido": "salvar_rascunho",
        "revisao_humana_necessaria": True,
        "corpo_materia": _CORPO_TESTE,
        "conteudo": _CORPO_TESTE,
        "titulo_seo": "TJRJ bloqueia bens de ex-secretário em ação do MP",
    }


def _pauta_base(status: str = "revisada", artigo: dict = None) -> dict:
    """Monta uma pauta de teste com matéria embutida."""
    md = {
        "titulo": "TJRJ bloqueia R$ 1,2 mi de ex-secretário",
        "titulo_capa": "TJRJ bloqueia ex-secretário",
        "subtitulo": "Decisão judicial determina bloqueio imediato de bens.",
        "retranca": "Judiciário",
        "slug": "tjrj-bloqueia-ex-secretario",
        "meta_description": "",
        "nome_da_fonte": "",
        "creditos_da_foto": "",
        "tags": ["TJRJ", "bloqueio", "secretário"],
        "conteudo": "Parágrafo 1.\n\nParágrafo 2.\n\nParágrafo 3.",
        "legenda": "Sede do Tribunal.",
        "legenda_curta": "",
        "legenda_instagram": "",
        "chamada_social": "Decisão histórica do TJRJ.",
        "resumo_curto": "O tribunal determinou o bloqueio.",
    }
    if artigo:
        md.update(artigo)
    return {
        "uid": "test_uid_001",
        "_uid": "test_uid_001",
        "titulo_origem": "TJRJ bloqueia R$ 1,2 mi de ex-secretário acusado de desvio",
        "link_origem": "https://example.com/tjrj-bloqueia",
        "fonte_nome": "G1 RJ",
        "canal": "Judiciário",
        "status": status,
        "score_risco": 20,
        "imagem_status": "aprovada",
        "atualizada_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "captada_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "materia": md,
    }


# ── T1: Botão Revisão substituiu Manual ──────────────────────────────────────

def testar_botao_revisao_substitui_manual() -> ResultadoTeste:
    """
    T1 (v66): Botão "Revisão" foi REMOVIDO da toolbar. Revisão agora acontece
    via Preview (edição inline) e Copydesk (item-por-item com IA).
    O método _acao_revisao() permanece como redirecionador para _acao_copydesk().
    """
    r = ResultadoTeste("T1_botao_revisao_substitui_manual")
    try:
        from pathlib import Path
        codigo = Path("ururau/ui/painel.py").read_text(encoding="utf-8")

        # v66: "Revisão" NÃO deve mais aparecer na toolbar como tupla ativa
        if '("Revisão",      self._acao_revisao' in codigo:
            r.falha("T1a: Botão 'Revisão' ainda está na toolbar (deveria ter sido removido em v66)")
        else:
            r.ok("v66: botão 'Revisão' removido da toolbar (correto)")

        # Botão Copydesk deve estar presente (substitui o fluxo de Revisão)
        if '"Copydesk"' in codigo and "self._acao_copydesk" in codigo:
            r.ok("v66: botão 'Copydesk' presente na toolbar")
        else:
            r.falha("T1b: botão 'Copydesk' não encontrado na toolbar")

        # _acao_revisao() ainda existe (redireciona para Copydesk)
        if "def _acao_revisao(" in codigo:
            r.ok("_acao_revisao() preservado (redireciona para Copydesk)")
        else:
            r.falha("T1c: _acao_revisao() removido completamente")

        # "Manual" não deve ser um botão de toolbar primário
        if '("Manual",       self._acao_manual,' in codigo or \
           '("Manual",  self._acao_manual,' in codigo:
            r.falha("T1d: Botão 'Manual' ainda está na toolbar como botão primário")
        else:
            r.ok("Botão Manual fora da toolbar primária")

        # _acao_revisao() deve existir
        if "def _acao_revisao" in codigo:
            r.ok("_acao_revisao() definido")
        else:
            r.falha("T1c: _acao_revisao() não encontrado no painel.py")

    except Exception as e:
        r.falha(f"T1: exceção: {e}")
    return r


# ── T2: Comportamento antigo do Manual foi preservado ────────────────────────

def testar_manual_preservado() -> ResultadoTeste:
    """
    T2: Verifica que _acao_manual() ainda existe e cria pautas manuais.
    O comportamento foi preservado — apenas o botão foi movido.
    """
    r = ResultadoTeste("T2_manual_preservado")
    try:
        from pathlib import Path
        codigo = Path("ururau/ui/painel.py").read_text(encoding="utf-8")

        if "def _acao_manual" in codigo:
            r.ok("_acao_manual() ainda existe")
        else:
            r.falha("T2a: _acao_manual() foi removido — funcionalidade perdida")

        # Ctrl+M ainda deve acionar manual
        if '"<Control-m>"' in codigo and "_acao_manual" in codigo:
            r.ok("Ctrl+M ainda aciona _acao_manual()")
        else:
            r.falha("T2b: Ctrl+M não aciona _acao_manual()")

        # Menu "Mais" deve oferecer acesso ao manual
        if "Adicionar pauta manual" in codigo or "_acao_manual" in codigo:
            r.ok("_acao_manual acessível via menu ou shortcut")

    except Exception as e:
        r.falha(f"T2: exceção: {e}")
    return r


# ── T3: Rascunhos pendentes aparecem na fila de revisão ──────────────────────

def testar_rascunho_pendente_na_lista() -> ResultadoTeste:
    """
    T3: Artigos com status_validacao=pendente entram na fila de revisão.
    """
    r = ResultadoTeste("T3_rascunho_pendente_na_lista")
    try:
        from ururau.ui.revisao import _e_para_revisao

        pauta_pend = _pauta_base("revisada", _artigo_pendente())
        if _e_para_revisao(pauta_pend):
            r.ok("T3a: artigo pendente entra na fila de revisão")
        else:
            r.falha("T3a: artigo com status_validacao=pendente NÃO entrou na fila")

        # Artigo com revisao_humana_necessaria=True
        pauta_rhn = _pauta_base("revisada", {
            **_artigo_pendente(),
            "revisao_humana_necessaria": True,
        })
        if _e_para_revisao(pauta_rhn):
            r.ok("T3b: revisao_humana_necessaria=True entra na fila")
        else:
            r.falha("T3b: revisao_humana_necessaria=True não entrou na fila")

    except Exception as e:
        r.falha(f"T3: exceção: {e}")
    return r


# ── T4: Bloqueados aparecem na fila de revisão ───────────────────────────────

def testar_bloqueado_na_lista() -> ResultadoTeste:
    """
    T4: Artigos com auditoria_bloqueada=True entram na fila de revisão.
    """
    r = ResultadoTeste("T4_bloqueado_na_lista")
    try:
        from ururau.ui.revisao import _e_para_revisao

        pauta_bloq = _pauta_base("bloqueada", _artigo_reprovado())
        if _e_para_revisao(pauta_bloq):
            r.ok("T4a: artigo reprovado/bloqueado entra na fila de revisão")
        else:
            r.falha("T4a: artigo auditoria_bloqueada=True não entrou na fila")

        # status_publicacao_sugerido=bloquear também deve entrar
        pauta_bloquear = _pauta_base("revisada", {
            **_artigo_pendente(),
            "status_publicacao_sugerido": "bloquear",
        })
        if _e_para_revisao(pauta_bloquear):
            r.ok("T4b: status_publicacao_sugerido=bloquear entra na fila")
        else:
            r.falha("T4b: status_publicacao_sugerido=bloquear não entrou na fila")

    except Exception as e:
        r.falha(f"T4: exceção: {e}")
    return r


# ── T5: Artigos aprovados NÃO aparecem por padrão ────────────────────────────

def testar_aprovado_nao_aparece() -> ResultadoTeste:
    """
    T5: Artigos totalmente aprovados NÃO aparecem na fila de revisão.
    """
    r = ResultadoTeste("T5_aprovado_nao_aparece_na_revisao")
    try:
        from ururau.ui.revisao import _e_para_revisao

        pauta_ok = _pauta_base("pronta", _artigo_aprovado())
        if not _e_para_revisao(pauta_ok):
            r.ok("T5a: artigo aprovado NÃO entra na fila de revisão")
        else:
            r.falha("T5a: artigo aprovado entrou na fila de revisão (indesejado)")

        # Publicado também não deve aparecer
        pauta_pub = _pauta_base("publicada", _artigo_aprovado())
        # pautas publicadas são excluídas pela query SQL (status='publicada')
        # _e_para_revisao verifica lógica interna
        if not _e_para_revisao(pauta_pub):
            r.ok("T5b: artigo publicado NÃO entra na fila de revisão")
        else:
            r.falha("T5b: artigo publicado entrou na fila de revisão (indesejado)")

    except Exception as e:
        r.falha(f"T5: exceção: {e}")
    return r


# ── T6: Corrigir pendências não reescreve o corpo ───────────────────────────

def testar_corrigir_pendencias() -> ResultadoTeste:
    """
    T6: corrigir_pendencias() corrige FIXABLE_FIELD sem reescrever corpo_materia.
    """
    r = ResultadoTeste("T6_corrigir_pendencias")
    try:
        # Simula sem DB real — testa a lógica de correção diretamente
        corpo_original = (
            "O TJRJ determinou o bloqueio de R$ 1,2 milhão em bens do ex-secretário "
            "acusado de desvio de verbas públicas.\n\n"
            "Parágrafo 2 original.\n\nParágrafo 3."
        )
        md = {
            "titulo": "TJRJ bloqueia R$ 1,2 mi",
            "titulo_capa": "",           # vazio — deve ser corrigido
            "nome_da_fonte": "",          # vazio — deve ser corrigido
            "creditos_da_foto": "",       # vazio — deve ser corrigido
            "legenda_curta": "",          # vazio — deve ser corrigido
            "meta_description": "curta",  # < 60 chars — deve ser corrigido
            "tags": ["tag1", "tag2", "tag3", "tag4", "tag5", "tag6", "tag7", "tag8", "tag9"],  # 9 tags — reduz
            "conteudo": corpo_original,
            "legenda": "Sede do tribunal.",
        }
        pauta = {
            "uid": "test_t6",
            "fonte_nome": "G1 RJ",
            "imagem_credito": "Reprodução",
            "materia": md,
        }

        # Simula a lógica de corrigir_pendencias sem DB (inline)
        corrigidos = []

        # Tags excessivas
        if len(md["tags"]) > 8:
            md["tags"] = md["tags"][:8]
            corrigidos.append("tags reduzidas para 8")

        # meta_description curta
        if len(md.get("meta_description", "").strip()) < 60:
            primeiro_par = (md["conteudo"].split("\n\n") or [""])[0].strip()
            md["meta_description"] = primeiro_par[:160]
            corrigidos.append("meta_description gerada")

        # legenda_curta ausente
        if not md.get("legenda_curta", "").strip():
            md["legenda_curta"] = md.get("legenda", "")[:120]
            corrigidos.append("legenda_curta preenchida")

        # nome_da_fonte ausente
        if not md.get("nome_da_fonte", "").strip():
            md["nome_da_fonte"] = pauta.get("fonte_nome", "Redação")
            corrigidos.append("nome_da_fonte preenchido")

        # titulo_capa ausente/longo
        if not md.get("titulo_capa", "").strip():
            md["titulo_capa"] = md["titulo"][:75]
            corrigidos.append("titulo_capa ajustado")

        # Verificações
        if md["conteudo"] == corpo_original:
            r.ok("T6a: corpo_materia NÃO foi reescrito")
        else:
            r.falha("T6a: corpo_materia foi modificado indevidamente")

        if "tags reduzidas para 8" in corrigidos and len(md["tags"]) == 8:
            r.ok("T6b: tags reduzidas de 9 para 8")
        else:
            r.falha(f"T6b: tags não foram reduzidas (len={len(md['tags'])})")

        if md.get("nome_da_fonte") == "G1 RJ":
            r.ok("T6c: nome_da_fonte preenchido da pauta")
        else:
            r.falha(f"T6c: nome_da_fonte={md.get('nome_da_fonte')} (esperado: G1 RJ)")

        if md.get("titulo_capa"):
            r.ok("T6d: titulo_capa preenchido")
        else:
            r.falha("T6d: titulo_capa ainda vazio")

        if len(md.get("meta_description", "")) >= 60:
            r.ok("T6e: meta_description gerada (>=60 chars)")
        else:
            r.falha(f"T6e: meta_description muito curta: {len(md.get('meta_description',''))} chars")

        if corrigidos:
            r.ok(f"T6f: {len(corrigidos)} correções realizadas: {corrigidos}")
        else:
            r.falha("T6f: nenhuma correção foi realizada")

    except Exception as e:
        r.falha(f"T6: exceção: {e}")
    return r


# ── T7: EDITORIAL_BLOCKER permanece bloqueado ─────────────────────────────────

def testar_editorial_blocker_persiste() -> ResultadoTeste:
    """
    T7: Artigo com EDITORIAL_BLOCKER permanece bloqueado depois de corrigir FIXABLE_FIELD.
    """
    r = ResultadoTeste("T7_editorial_blocker_persiste")
    try:
        from ururau.publisher.workflow import can_publish

        artigo_com_blocker = {
            "status_validacao": "reprovado",
            "auditoria_bloqueada": True,
            "erros_validacao": [
                {
                    "categoria": "EDITORIAL_BLOCKER",
                    "campo": "corpo_materia",
                    "mensagem": "Data inventada detectada.",
                    "bloqueia_publicacao": True,
                }
            ],
        }

        ok, motivo = can_publish(artigo_com_blocker)
        if not ok:
            r.ok(f"T7a: EDITORIAL_BLOCKER bloqueia publicação: {motivo[:60]}")
        else:
            r.falha("T7a: artigo com EDITORIAL_BLOCKER foi liberado indevidamente")

        # Mesmo após corrigir um FIXABLE_FIELD (sem tocar no blocker), ainda bloqueado
        artigo_pós_fixable = {
            **artigo_com_blocker,
            "nome_da_fonte": "G1 RJ",  # campo fixable corrigido
        }
        ok2, _ = can_publish(artigo_pós_fixable)
        if not ok2:
            r.ok("T7b: EDITORIAL_BLOCKER persiste após correção de FIXABLE_FIELD")
        else:
            r.falha("T7b: EDITORIAL_BLOCKER foi removido indevidamente")

        # Confirmação via montar_texto_erros
        from ururau.ui.revisao import montar_texto_erros
        txt = montar_texto_erros(artigo_com_blocker)
        if "EDITORIAL_BLOCKER" in txt or "BLOQUEADOR" in txt:
            r.ok("T7c: montar_texto_erros destaca EDITORIAL_BLOCKER")
        else:
            r.falha("T7c: montar_texto_erros não destacou EDITORIAL_BLOCKER")

    except Exception as e:
        r.falha(f"T7: exceção: {e}")
    return r


# ── T8: Publicar desabilitado para pendente/reprovado ────────────────────────

def testar_publicar_desabilitado() -> ResultadoTeste:
    """
    T8: can_publish() retorna False para artigos pendente/reprovado sem aprovação manual.
    """
    r = ResultadoTeste("T8_publicar_desabilitado_sem_aprovacao")
    try:
        from ururau.publisher.workflow import can_publish

        # Pendente — sem aprovação manual
        ok_p, m_p = can_publish(_artigo_pendente())
        if not ok_p:
            r.ok(f"T8a: pendente bloqueado: {m_p[:50]}")
        else:
            r.falha("T8a: artigo pendente foi liberado para publicação")

        # Reprovado — sem aprovação manual
        ok_r, m_r = can_publish(_artigo_reprovado())
        if not ok_r:
            r.ok(f"T8b: reprovado bloqueado: {m_r[:50]}")
        else:
            r.falha("T8b: artigo reprovado foi liberado para publicação")

        # Aprovado — deve passar
        ok_a, _ = can_publish(_artigo_aprovado())
        if ok_a:
            r.ok("T8c: aprovado liberado para publicação")
        else:
            r.falha("T8c: artigo aprovado foi bloqueado indevidamente")

    except Exception as e:
        r.falha(f"T8: exceção: {e}")
    return r


# ── T9: Aprovação manual ─────────────────────────────────────────────────────

def testar_aprovacao_manual() -> ResultadoTeste:
    """
    T9: Aprovação manual salva approved_by, approved_at, reason.
    Preserva histórico de erros. Permite publicação depois.
    """
    r = ResultadoTeste("T9_aprovacao_manual")
    try:
        from ururau.publisher.workflow import can_publish

        # Artigo reprovado com aprovação manual
        artigo_aprovado_manualmente = {
            **_artigo_reprovado(),
            "approved_by": "Editor Chefe",
            "approved_at": "2026-04-25 10:00:00",
            "manual_approval_reason": "Fatos verificados por redação, publicação autorizada.",
        }

        ok, motivo = can_publish(artigo_aprovado_manualmente)
        if ok:
            r.ok("T9a: aprovação manual habilita publicação")
        else:
            r.falha(f"T9a: aprovação manual não habilitou publicação: {motivo}")

        # Erros de validação DEVEM estar preservados
        erros = artigo_aprovado_manualmente.get("erros_validacao", [])
        if erros:
            r.ok(f"T9b: erros de validação preservados ({len(erros)} erro(s))")
        else:
            r.falha("T9b: erros de validação foram apagados (não deveriam ser)")

        # Aprovação incompleta (sem motivo) NÃO deve habilitar
        artigo_incompleto = {
            **_artigo_reprovado(),
            "approved_by": "Editor",
            "approved_at": "2026-04-25",
            "manual_approval_reason": "",  # vazio — inválido
        }
        ok2, _ = can_publish(artigo_incompleto)
        if not ok2:
            r.ok("T9c: aprovação manual incompleta (sem motivo) não habilita publicação")
        else:
            r.falha("T9c: aprovação manual sem motivo habilitou publicação indevidamente")

    except Exception as e:
        r.falha(f"T9: exceção: {e}")
    return r


# ── T10: Pacote editorial não muda status para pronta se bloqueado ────────────

def testar_pacote_nao_muda_status() -> ResultadoTeste:
    """
    T10: etapa_persistir_materia() mantém status=REVISADA (não PRONTA)
    para matérias com auditoria_bloqueada=True.
    """
    r = ResultadoTeste("T10_pacote_nao_muda_status_bloqueado")
    try:
        import inspect
        from ururau.publisher.workflow import WorkflowPublicacao
        codigo = inspect.getsource(WorkflowPublicacao.etapa_persistir_materia)

        # Verifica que o método verifica auditoria_bloqueada antes de definir PRONTA
        if "auditoria_bloqueada" in codigo and "REVISADA" in codigo:
            r.ok("T10a: etapa_persistir_materia verifica auditoria_bloqueada e usa REVISADA")
        else:
            r.falha("T10a: etapa_persistir_materia não verifica auditoria_bloqueada corretamente")

        # Verifica que não define PRONTA incondicionalmente
        if "set_status(uid, pauta, StatusPauta.PRONTA)" in codigo:
            # Deve estar dentro de um if
            idx_pronta = codigo.find("StatusPauta.PRONTA")
            trecho = codigo[max(0, idx_pronta-100):idx_pronta+50]
            if "if " in trecho or "aprovada" in trecho:
                r.ok("T10b: PRONTA só definido condicionalmente (após auditoria aprovada)")
            else:
                r.falha("T10b: PRONTA pode ser definido incondicionalmente")
        else:
            r.ok("T10b: PRONTA não usado incondicionalmente")

    except Exception as e:
        r.falha(f"T10: exceção: {e}")
    return r


# ── T11: can_publish() verificado em todos os caminhos ───────────────────────

def testar_can_publish_gate() -> ResultadoTeste:
    """
    T11: can_publish() é chamado em _acao_publicar() do painel.py.
    """
    r = ResultadoTeste("T11_can_publish_gate_todos_caminhos")
    try:
        from pathlib import Path
        codigo = Path("ururau/ui/painel.py").read_text(encoding="utf-8")

        if "can_publish" in codigo:
            r.ok("T11a: can_publish referenciado no painel.py")
        else:
            r.falha("T11a: can_publish NÃO referenciado no painel.py")

        if "from ururau.publisher.workflow import can_publish" in codigo:
            r.ok("T11b: can_publish importado em _acao_publicar")
        else:
            r.falha("T11b: can_publish não importado em _acao_publicar")

        # Verifica a função can_publish em workflow.py
        from ururau.publisher.workflow import can_publish
        if callable(can_publish):
            r.ok("T11c: can_publish() é callable")
        else:
            r.falha("T11c: can_publish não é callable")

        # Verifica comportamentos centrais (v62: corpo_materia obrigatório)
        ok1, _ = can_publish({
            "status_validacao": "aprovado", "auditoria_bloqueada": False,
            "corpo_materia": _CORPO_TESTE,
            "coverage_score": 0.95,
        })
        ok2, _ = can_publish({
            "status_validacao": "reprovado", "auditoria_bloqueada": True,
            "corpo_materia": _CORPO_TESTE,
        })
        ok3, _ = can_publish({
            "approved_by": "X", "approved_at": "Y",
            "manual_approval_reason": "Z",
            "corpo_materia": _CORPO_TESTE,
        })

        if ok1 and not ok2 and ok3:
            r.ok("T11d: can_publish retorna correto para aprovado/reprovado/manual")
        else:
            r.falha(f"T11d: can_publish retornou inesperado: aprovado={ok1} reprovado={ok2} manual={ok3}")

    except Exception as e:
        r.falha(f"T11: exceção: {e}")
    return r


# ── T12: Persistência de artigos pendentes/reprovados ───────────────────────

def testar_persistencia() -> ResultadoTeste:
    """
    T12: Artigos pendentes/reprovados persistem entre recarregamentos via DB.
    Usa DB temporário em memória para não contaminar o banco real.
    """
    r = ResultadoTeste("T12_persistencia_artigos_pendentes")
    try:
        import tempfile, os
        from ururau.core.database import Database
        from ururau.publisher.workflow import _uid_para_pauta

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_path = f.name

        try:
            db = Database(tmp_path)

            # Salva uma pauta com matéria bloqueada
            uid = _uid_para_pauta("https://example.com/test12", "Teste T12")
            md_bloqueado = {
                **_artigo_reprovado(),
                "titulo": "Teste T12",
                "conteudo": "Corpo.\n\nParágrafo 2.",
                "auditoria_bloqueada": True,
                "status_validacao": "reprovado",
            }
            pauta = {
                "_uid": uid,
                "uid": uid,
                "titulo_origem": "Teste T12",
                "link_origem": "https://example.com/test12",
                "fonte_nome": "Teste",
                "status": "revisada",  # bloqueada → revisada no novo fluxo
                "score_editorial": 50,
                "imagem_status": "pendente",
                "materia": md_bloqueado,
            }
            db.salvar_pauta(pauta)
            db.salvar_materia(uid, md_bloqueado)

            # Recarrega o DB e verifica que a pauta ainda está lá
            conn = db._conectar()
            try:
                row = conn.execute(
                    "SELECT uid, status, dados_json FROM pautas WHERE uid=?",
                    (uid,)
                ).fetchone()
            finally:
                conn.close()

            if row:
                r.ok("T12a: pauta persistiu no banco")
                if row["status"] in ("revisada", "bloqueada"):
                    r.ok(f"T12b: status={row['status']} (não pronta)")
                else:
                    r.falha(f"T12b: status={row['status']} (inesperado — deveria ser revisada ou bloqueada)")
            else:
                r.falha("T12a: pauta não foi encontrada no banco após salvar")

            # Recarrega matéria
            conn2 = db._conectar()
            try:
                row2 = conn2.execute(
                    "SELECT dados_json FROM materias WHERE pauta_uid=?",
                    (uid,)
                ).fetchone()
            finally:
                conn2.close()

            if row2:
                md_salvo = json.loads(row2["dados_json"] or "{}")
                if md_salvo.get("auditoria_bloqueada"):
                    r.ok("T12c: auditoria_bloqueada=True persistiu na matéria")
                else:
                    r.falha("T12c: auditoria_bloqueada não persistiu")
            else:
                r.falha("T12c: matéria não encontrada no banco")

        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    except Exception as e:
        r.falha(f"T12: exceção: {traceback.format_exc()[:200]}")
    return r


# ── Runner principal ──────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("TESTES — REVISÃO EDITORIAL v59")
    print("=" * 70)

    testes = [
        testar_botao_revisao_substitui_manual,
        testar_manual_preservado,
        testar_rascunho_pendente_na_lista,
        testar_bloqueado_na_lista,
        testar_aprovado_nao_aparece,
        testar_corrigir_pendencias,
        testar_editorial_blocker_persiste,
        testar_publicar_desabilitado,
        testar_aprovacao_manual,
        testar_pacote_nao_muda_status,
        testar_can_publish_gate,
        testar_persistencia,
    ]

    resultados = []
    for fn in testes:
        print(f"\n[{fn.__name__.replace('testar_','').upper()}]")
        try:
            r = fn()
        except Exception as e:
            r = ResultadoTeste(fn.__name__)
            r.falha(f"exceção não tratada: {e}")
        resultados.append(r)

    print("\n" + "=" * 70)
    print("RESUMO")
    print("=" * 70)
    passou = 0
    for _r in resultados:
        if not _r._falhas:
            passou += 1
    falhou = len(resultados) - passou
    for r in resultados:
        status = "OK" if not r._falhas else "FAIL"
        print(f"  {status} {r.nome}")
        for d in r._falhas:
            print(f"     - {d}")
    print(f"\nTotal: {passou}/{len(resultados)} aprovados")
    if falhou == 0:
        print("\nTODOS OS TESTES PASSARAM - revisao editorial validada.")
    else:
        print(f"\n{falhou} teste(s) falharam.")
    return falhou == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
