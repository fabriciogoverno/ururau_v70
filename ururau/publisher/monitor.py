"""
publisher/monitor.py — Robô de monitoramento 24h do Ururau v43.

FLUXO 1: MONITORAMENTO 24H
  - Publica DIRETAMENTE no CMS (rascunho=False)
  - Score mínimo mais alto (SCORE_MIN_AUTOPUBLICACAO)
  - Confiança mínima obrigatória (CONFIANCA_MIN_AUTOPUB)
  - Máx 4 publicações/hora (MAX_PUB_HORA_MONITOR)
  - Máx 4 pautas da mesma fonte por ciclo
  - Log de decisão transparente (motivo de aprovação/rejeição)

Uso:
    from ururau.publisher.monitor import MonitorRobo
    robo = MonitorRobo(db, client, modelo)
    robo.iniciar()   # bloqueia em loop — use em thread separada
    robo.parar()     # sinaliza parada limpa
"""
from __future__ import annotations

import os
import time
import threading
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from ururau.config.settings import (
    INTERVALO_ENTRE_CICLOS_SEGUNDOS,
    MAX_PUBLICACOES_MONITORAMENTO_POR_HORA,
    MAX_CANDIDATAS_AVALIADAS,
    LIMIAR_RELEVANCIA_PUBLICAR,
    LIMIAR_RELEVANCIA_URGENTE,
    LIMIAR_RISCO_MAXIMO,
    StatusPauta,
    SCORE_MONITOR_DIRETO_IMEDIATO,
    SCORE_MONITOR_DIRETO_CONFIANCA,
    SCORE_MONITOR_PAINEL_PRIORIDADE,
)

if TYPE_CHECKING:
    from openai import OpenAI
    from ururau.core.database import Database


# ── Logger ─────────────────────────────────────────────────────────────────────

def _setup_logger() -> logging.Logger:
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    logger = logging.getLogger("ururau.monitor")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                             datefmt="%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(log_dir / "monitor.log", encoding="utf-8")
    fh.setFormatter(fmt)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


# ── Classe principal ───────────────────────────────────────────────────────────

class MonitorRobo:
    """
    Robô de monitoramento editorial 24h.

    CRITÉRIOS RIGOROSOS (modo monitor):
      - rascunho=False  →  publica diretamente no CMS
      - score editorial mínimo: SCORE_MIN_AUTOPUBLICACAO (padrão 65, mais alto que o painel)
      - confiança mínima obrigatória: CONFIANCA_MIN_AUTOPUB (padrão 70)
      - exige pelo menos 1 critério de relevância real: regionalidade, impacto político,
        impacto policial, prioridade esportes/saúde/rural — NÃO publica só por score_base
      - máx 4 publicações/hora, mas NÃO corre para preenchê-las
      - se ciclo não encontrar nada relevante: aguarda INTERVALO_SEM_PAUTA (padrão 15 min)
        antes de tentar novamente, em vez do intervalo normal
      - máx 4 da mesma fonte por ciclo
      - log de decisão por pauta (motivo de aprovação/rejeição)
    """

    # Intervalo reduzido quando não há nada relevante (15 min)
    INTERVALO_SEM_PAUTA = int(os.getenv("INTERVALO_SEM_PAUTA_SEGUNDOS", "900"))
    # Score mínimo extra para monitor (mais alto que o painel)
    SCORE_MIN_MONITOR   = int(os.getenv("SCORE_MIN_MONITOR", "65"))
    # Exige sub-score de relevância acima de zero para publicar
    RELEVANCIA_MIN_MONITOR = int(os.getenv("RELEVANCIA_MIN_MONITOR", "5"))

    def __init__(
        self,
        db: "Database",
        client: "OpenAI",
        modelo: str,
        intervalo_segundos: int = INTERVALO_ENTRE_CICLOS_SEGUNDOS,
        max_por_hora: int = MAX_PUBLICACOES_MONITORAMENTO_POR_HORA,
        publicar_no_cms: bool = True,
    ):
        self.db               = db
        self.client           = client
        self.modelo           = modelo
        self.intervalo        = intervalo_segundos
        self.max_por_hora     = max_por_hora
        self.publicar_no_cms  = publicar_no_cms
        self._parar           = threading.Event()
        self._log             = _setup_logger()
        self._publicados_hora: list[datetime] = []   # timestamps das publicações na janela 1h

    # ── Controle ───────────────────────────────────────────────────────────────

    def iniciar(self):
        """Entra em loop de monitoramento (bloqueante). Use em thread separada."""
        self._log.info("=" * 60)
        self._log.info("=== MONITORAMENTO 24H iniciado — publicação DIRETA ===")
        self._log.info(
            f"Intervalo normal: {self.intervalo}s | "
            f"Intervalo sem pauta: {self.INTERVALO_SEM_PAUTA}s | "
            f"Max/hora: {self.max_por_hora} | "
            f"Score mínimo monitor: {self.SCORE_MIN_MONITOR}"
        )
        self._log.info("=" * 60)
        ciclo = 0
        while not self._parar.is_set():
            ciclo += 1
            self._log.info(f"--- Ciclo {ciclo} [{datetime.now().strftime('%H:%M:%S')}] ---")
            publicadas_ciclo = 0
            try:
                publicadas_ciclo = self._executar_ciclo(ciclo)
            except Exception as e:
                self._log.error(f"Erro no ciclo {ciclo}: {e}", exc_info=True)

            if self._parar.is_set():
                break

            # Intervalo adaptativo: se publicou algo, aguarda o intervalo completo
            # Se não publicou nada relevante, aguarda apenas 15 min antes de tentar novamente
            if publicadas_ciclo > 0:
                espera = self.intervalo
                self._log.info(
                    f"Publicadas: {publicadas_ciclo}. "
                    f"Aguardando {espera}s ({espera//60} min) para próximo ciclo..."
                )
            else:
                espera = self.INTERVALO_SEM_PAUTA
                self._log.info(
                    f"Nenhuma pauta relevante encontrada neste ciclo. "
                    f"Aguardando {espera}s ({espera//60} min) antes de nova busca..."
                )
            self._parar.wait(timeout=espera)

        self._log.info("=== Monitoramento encerrado ===")

    def parar(self):
        """Sinaliza parada limpa. O ciclo corrente é concluído antes de sair."""
        self._log.info("Sinal de parada recebido.")
        self._parar.set()

    # ── Ciclo ──────────────────────────────────────────────────────────────────

    def _executar_ciclo(self, ciclo: int) -> int:
        """
        Ciclo completo de coleta → seleção → processamento.

        CRITÉRIOS MONITOR (mais rígidos que o painel):
          - score mínimo = SCORE_MIN_MONITOR (padrão 65, configurável)
          - confiança mínima = CONFIANCA_MIN_AUTOPUB (padrão 70)
          - exige pelo menos um sub-score de relevância > RELEVANCIA_MIN_MONITOR:
            regionalidade, impacto político, policial, esportes, saúde ou rural
          - NÃO publica apenas por score_base + frescor (não é pauta de relevância real)
          - máx 4 da mesma fonte no ciclo
          - retorna número de pautas publicadas no ciclo
        """
        from ururau.coleta.rss import (coletar_rss, coletar_google_news,
                                       deduplicar, filtrar_contra_banco,
                                       obter_termos_google_news)
        from ururau.coleta.scoring import (
            calcular_score_completo,
            classificar_canal,
            filtrar_e_ordenar,
            PESOS,
        )
        from ururau.publisher.workflow import WorkflowPublicacao, _uid_para_pauta

        # ── 1. Coleta ──────────────────────────────────────────────────────────
        self._log.info("Coletando RSS + Google News...")
        fontes = _carregar_fontes_rss()
        raw: list[dict] = []
        if fontes:
            raw += coletar_rss(fontes)

        # Termos do Google News: usa consultas_google_news.json se disponível
        _termos_fallback = [
            "Rio de Janeiro", "RJ policia", "RJ politica", "RJ economia",
            "governo RJ", "Rio noticias", "estado RJ", "saude RJ",
            "rural norte fluminense", "Porto do Açu", "Campos dos Goytacazes",
            "Norte Fluminense", "ALERJ", "TCE-RJ",
        ]
        termos_gnews = obter_termos_google_news(_termos_fallback)
        self._log.info(f"Termos Google News: {len(termos_gnews)}")
        raw += coletar_google_news(termos_gnews, max_por_termo=8)
        self._log.info(f"Brutas coletadas: {len(raw)}")

        # ── 2. Deduplicação e filtro contra banco ──────────────────────────────
        raw = deduplicar(raw)
        candidatas, resumo = filtrar_contra_banco(raw, self.db)
        self._log.info(
            f"Filtro banco: {resumo['total']} → {resumo['aprovadas']} novas | "
            f"{resumo['publicadas']} já pub | {resumo['descartadas']} descartadas | "
            f"{resumo['similares']} similares"
        )

        # ── 2b. Filtro anti-duplicata: verifica o que está no ar no Portal Ururau
        # Passa db= para que links encontrados no site sejam bloqueados permanentemente
        if candidatas:
            try:
                from ururau.coleta.ururau_check import filtrar_contra_site_ururau
                candidatas, rem_site = filtrar_contra_site_ururau(candidatas, db=self.db)
                if rem_site:
                    self._log.info(
                        f"Filtro Portal Ururau: {rem_site} pautas removidas "
                        f"(assunto já publicado no site — bloqueados permanentemente)"
                    )
            except Exception as e_site:
                self._log.warning(f"Filtro Portal Ururau falhou (continuando): {e_site}")

        if not candidatas:
            self._log.info("Nenhuma candidata nova neste ciclo.")
            return 0

        # ── 3. Scoring completo ────────────────────────────────────────────────
        # Monta contexto de fontes para penalidade de repetição
        contexto_fontes: dict[str, int] = {}
        for p in candidatas:
            nome = p.get("fonte_nome") or p.get("nome_fonte") or "desconhecida"
            contexto_fontes[nome] = contexto_fontes.get(nome, 0) + 1

        for pauta in candidatas:
            try:
                sd = calcular_score_completo(pauta, contexto_fontes)
                pauta["_score_detalhado"]  = sd
                pauta["score_editorial"]   = sd.score_editorial
                pauta["score_autopub"]     = sd.score_confianca_autopub
                pauta["modo_destino"]      = sd.modo_destino
                pauta["justificativa"]     = "; ".join(sd.motivos_rejeicao[:2]) if sd.motivos_rejeicao else ""
                # Guarda sub-scores para gate de relevância
                pauta["_sub_regional"]   = sd.score_regionalidade
                pauta["_sub_politico"]   = sd.score_impacto_politico
                pauta["_sub_policial"]   = sd.score_impacto_policial
                pauta["_sub_esportes"]   = sd.score_prioridade_esportes
                pauta["_sub_saude"]      = sd.score_prioridade_saude
                pauta["_sub_rural"]      = sd.score_prioridade_rural
                pauta["_sub_audiencia"]  = sd.score_potencial_audiencia
                # Canal: sempre usa o do scoring (não sobrescreve com canal_forcado vazio)
                pauta["canal_forcado"]       = sd.canal_sugerido
                pauta["_confianca_canal"]    = sd.canal_confianca
            except Exception as ex:
                self._log.debug(f"Scoring falhou para pauta: {ex}")
                pauta["score_editorial"] = 0
                pauta["score_autopub"]   = 0
                pauta["modo_destino"]    = "rascunho"

        # ── 4. Filtragem e ordenação modo=monitor (score mínimo mais alto) ──────
        score_min_monitor = self.SCORE_MIN_MONITOR
        selecionadas = filtrar_e_ordenar(
            candidatas,
            score_minimo=score_min_monitor,
            max_por_canal=PESOS["max_por_canal"],
            modo="monitor",
            contexto_fontes=contexto_fontes,
        )
        self._log.info(
            f"Após filtro monitor (score≥{score_min_monitor}): "
            f"{len(selecionadas)} candidatas | total candidatas: {len(candidatas)}"
        )

        if not selecionadas:
            self._log.info(
                "Nenhuma pauta atingiu o critério mínimo do monitor. "
                "Aguardando próxima janela de busca."
            )
            return 0

        # ── 5. Processamento (respeitando limite/hora) ─────────────────────────
        wf = WorkflowPublicacao(self.db, self.client, self.modelo)
        processadas = 0

        for pauta in selecionadas:
            if self._parar.is_set():
                self._log.info("Parada solicitada durante processamento.")
                break

            vagas = self._vagas_na_hora()
            if vagas <= 0:
                self._log.info(
                    f"Limite {self.max_por_hora}/hora atingido. "
                    f"Aguardando próximo ciclo."
                )
                break

            titulo = (pauta.get("titulo_origem") or "")[:70]
            uid    = pauta.get("_uid") or _uid_para_pauta(
                pauta.get("link_origem", ""), pauta.get("titulo_origem", ""))
            pauta["_uid"] = uid

            score_ed    = pauta.get("score_editorial", 0)
            score_ap    = pauta.get("score_autopub", 0)
            canal       = pauta.get("canal_forcado", "?")
            confianca   = pauta.get("_confianca_canal", "?")
            justificativa = pauta.get("justificativa", "")

            # Sub-scores de relevância real
            sub_regional  = pauta.get("_sub_regional", 0)
            sub_politico  = pauta.get("_sub_politico", 0)
            sub_policial  = pauta.get("_sub_policial", 0)
            sub_esportes  = pauta.get("_sub_esportes", 0)
            sub_saude     = pauta.get("_sub_saude", 0)
            sub_rural     = pauta.get("_sub_rural", 0)
            sub_audiencia = pauta.get("_sub_audiencia", 0)

            # Intel editorial — sub-scores adicionais
            score_intel   = pauta.get("_score_intel_adicional", 0)
            intel_log     = pauta.get("_intel_log", "")
            intel_urgencia = bool(pauta.get("_intel_urgencia", False))
            intel_triang   = bool(pauta.get("_intel_triangulacao", False))
            intel_proto_ok = bool(pauta.get("_intel_protocolo_ok", True))

            # Relevância máxima entre todos os sub-scores específicos
            relevancia_max = max(
                sub_regional, sub_politico, sub_policial,
                sub_esportes, sub_saude, sub_rural, sub_audiencia,
                score_intel,  # intel conta como relevância também
            )

            self._log.info(
                f"\n  ▶ [{canal}] {titulo}\n"
                f"    Score: {score_ed} | Confiança: {score_ap} | "
                f"Canal conf: {confianca} | Relevância máx: {relevancia_max}\n"
                f"    Sub: regional={sub_regional} pol={sub_politico} "
                f"policial={sub_policial} esp={sub_esportes} "
                f"saude={sub_saude} rural={sub_rural} aud={sub_audiencia}\n"
                f"    Intel: +{score_intel} | urgencia={intel_urgencia} "
                f"triang={intel_triang} proto_ok={intel_proto_ok}"
                + (f"\n    Intel detalhe: {intel_log}" if intel_log else "")
            )

            # ── Gate 0: Protocolo de verdade — bloqueia autopub se falhou ─────
            if not intel_proto_ok:
                self._log.info(
                    f"    ✗ BLOQUEADA — Protocolo de verdade falhou: revisar cargo/fato.\n"
                    f"      → Rascunho no painel para revisão humana obrigatória."
                )
                continue

            # ── Gate 1: relevância real — não publica só por score_base + frescor ──
            if relevancia_max < self.RELEVANCIA_MIN_MONITOR:
                self._log.info(
                    f"    ✗ REJEITADA — relevância real {relevancia_max} < "
                    f"{self.RELEVANCIA_MIN_MONITOR} mínimo.\n"
                    f"      Esta pauta não tem impacto regional, político, policial, "
                    f"esportivo, de saúde ou rural suficiente para publicação direta.\n"
                    f"      → Vai para rascunho no painel se o editor quiser."
                )
                continue

            # ── Gate 2: confiança na classificação do canal ────────────────────
            confianca_min = PESOS["confianca_min_autopub"]
            if score_ap < confianca_min:
                self._log.info(
                    f"    ✗ REJEITADA — confiança autopub {score_ap} < {confianca_min}.\n"
                    f"      Motivo: {justificativa or 'score insuficiente'}\n"
                    f"      → Rascunho no painel."
                )
                continue

            # ── Gate 3: canal com confiança mínima ────────────────────────────
            if confianca == "baixa":
                self._log.info(
                    f"    ✗ REJEITADA — canal classificado com baixa confiança: {canal}.\n"
                    f"      Monitor exige confiança média ou alta na editoria.\n"
                    f"      → Rascunho no painel para revisão humana."
                )
                continue

            # ── Tier de publicação expandido (v43) ────────────────────────────
            # 90+: publicação direta e imediata (tier 1)
            # 80-89: direta se confiança canal=alta (tier 2)
            # 65-79: vai para painel como prioridade (tier 3)
            # <65: fila normal de painel (já filtrado pelo score_min_monitor acima)
            tier_pub = "direto"
            if score_ed >= SCORE_MONITOR_DIRETO_IMEDIATO:
                tier_pub = "direto_imediato"
            elif score_ed >= SCORE_MONITOR_DIRETO_CONFIANCA:
                tier_pub = "direto" if confianca == "alta" else "painel_prioridade"
            elif score_ed >= SCORE_MONITOR_PAINEL_PRIORIDADE:
                tier_pub = "painel_prioridade"
            else:
                tier_pub = "fila_normal"

            pauta["_tier_publicacao"] = tier_pub
            pauta["_intel_urgencia"]  = intel_urgencia
            pauta["_intel_triang"]    = intel_triang

            self._log.info(
                f"    ✓ APROVADA — score={score_ed} confiança={score_ap} "
                f"relevância={relevancia_max} canal={canal} ({confianca}) "
                f"tier={tier_pub}"
                + (" ⚡URGENTE" if intel_urgencia else "")
                + (" ★TRIANGULAÇÃO" if intel_triang else "")
            )

            try:
                resultado = self._processar_pauta(wf, uid, pauta)
                if resultado:
                    self._registrar_publicacao()
                    processadas += 1
                    self._log.info(
                        f"    [CMS OK] Publicado ao vivo: {titulo}\n"
                        f"             Canal: {canal} | Score: {score_ed} | "
                        f"Relevância: {relevancia_max}"
                    )
                else:
                    self._log.info(f"    [--] Pipeline falhou: {titulo}")
            except Exception as e:
                self._log.warning(
                    f"    [ERR] Erro ao processar '{titulo}': {e}",
                    exc_info=False,
                )

        self._log.info(
            f"Ciclo {ciclo} concluído. "
            f"Publicadas ao vivo: {processadas} | "
            f"Última hora: {self.publicacoes_na_hora}/{self.max_por_hora}"
        )
        return processadas

    # ── Processamento individual ───────────────────────────────────────────────

    def _processar_pauta(self, wf, uid: str, pauta: dict) -> bool:
        """
        Pipeline completo para uma pauta — publicação DIRETA (rascunho=False).

        Diferença principal em relação ao painel:
          wf.etapa_publicacao(..., rascunho=False)  → publica no ar imediatamente
        """
        # Gate anti-duplicação
        if not wf.etapa_gate_antiduplicacao(uid, pauta, modo="redigir"):
            self._log.debug(f"  Gate antiduplicação bloqueou: {uid}")
            return False

        # Triagem de risco/qualidade
        if not wf.etapa_triagem(uid, pauta):
            self._log.debug(f"  Triagem bloqueou: {uid}")
            return False

        # Salva na fila antes de redigir
        pauta["status"] = StatusPauta.CAPTADA
        try:
            self.db.salvar_pauta(pauta)
        except Exception:
            pass

        # v69: Coleta FAIL-CLOSED em modo monitor.
        if not wf.etapa_coleta_texto(uid, pauta, modo="monitor"):
            print(f"[MONITOR] [{uid[:8]}] Coleta falhou - publicacao direta bloqueada (FAIL-CLOSED).")
            try:
                wf.db.log_auditoria(uid, "monitor_fail_closed",
                                    "Extracao falhou - bloqueado em modo monitor",
                                    sucesso=False)
            except Exception:
                pass
            return False

        # Imagem
        imagem = wf.etapa_imagem(uid, pauta)

        # Redação pela IA
        materia = wf.etapa_redacao(uid, pauta)
        if not materia:
            self._log.debug(f"  Redação falhou: {uid}")
            return False

        # Pacote editorial (título, subtítulo, tags…)
        materia = wf.etapa_pacote_editorial(uid, materia)

        # Verificação de risco editorial
        if not wf.etapa_verificacao_risco(uid, pauta, materia):
            self._log.debug(f"  Risco bloqueante detectado: {uid}")
            return False

        # Persistência local
        if not wf.etapa_persistir_materia(uid, pauta, materia):
            self._log.debug(f"  Persistência falhou: {uid}")
            return False

        self._log.info(
            f"  Matéria: {materia.titulo[:60]}\n"
            f"  Canal: {materia.canal} | Risco: {materia.score_risco}/100"
        )

        # ── Publicação direta no CMS ────────────────────────────────────────────
        # rascunho=False → desmarca "Salvar como rascunho" → publica imediatamente
        if self.publicar_no_cms:
            sucesso_cms = wf.etapa_publicacao(uid, pauta, materia, imagem,
                                              rascunho=False)
            if sucesso_cms:
                self._log.info("  CMS: publicado ao vivo [OK]")
            else:
                self._log.warning(
                    "  CMS: falha na publicação direta — matéria salva localmente "
                    "(verificar manualmente)."
                )
                return False   # não registrar como publicação bem-sucedida se CMS falhou

        return True

    # ── Rate limiting ──────────────────────────────────────────────────────────

    def _vagas_na_hora(self) -> int:
        """Retorna quantas publicações ainda cabem na janela de 1 hora."""
        agora  = datetime.now()
        janela = agora - timedelta(hours=1)
        self._publicados_hora = [t for t in self._publicados_hora if t > janela]
        return self.max_por_hora - len(self._publicados_hora)

    def _registrar_publicacao(self):
        """Registra timestamp da publicação para controle de rate limit."""
        self._publicados_hora.append(datetime.now())

    # ── Estado público ─────────────────────────────────────────────────────────

    @property
    def publicacoes_na_hora(self) -> int:
        """Número de publicações feitas na última hora."""
        agora  = datetime.now()
        janela = agora - timedelta(hours=1)
        return sum(1 for t in self._publicados_hora if t > janela)

    @property
    def ativo(self) -> bool:
        return not self._parar.is_set()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _carregar_fontes_rss() -> list[dict]:
    import json
    p = Path("fontes_rss.json")
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return [
        {"url": "https://g1.globo.com/rss/g1/rio-de-janeiro/",
         "nome": "G1 RJ", "canal_forcado": "Estado RJ"},
        {"url": "https://www.cnnbrasil.com.br/rss/",
         "nome": "CNN Brasil", "canal_forcado": ""},
        {"url": "https://feeds.folha.uol.com.br/poder/rss091.xml",
         "nome": "Folha Poder", "canal_forcado": "Política"},
        {"url": "https://www.uol.com.br/esporte/rss.xml",
         "nome": "UOL Esportes", "canal_forcado": "Esportes"},
    ]


def coletar_google_news(termos: list[str], max_por_termo: int = 8) -> list[dict]:
    """Wrapper local para evitar importação circular."""
    from ururau.coleta.rss import coletar_google_news as _cgn
    return _cgn(termos, max_por_termo)
