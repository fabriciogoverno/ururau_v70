"""
core/models.py — Modelos de dados do Ururau.
Dataclasses tipadas para Pauta, Materia, ImagemDados, AuditLog.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

TZ_BR = ZoneInfo("America/Sao_Paulo")


def agora_br() -> str:
    return datetime.now(TZ_BR).strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class ImagemDados:
    caminho_imagem:    str
    caminho_original:  str = ""
    credito_foto:      str = "Reprodução"
    url_imagem:        str = ""
    estrategia_imagem: str = ""
    dimensoes_origem:  str = ""
    largura_origem:    int = 0
    altura_origem:     int = 0
    melhor_qualidade:  bool = False
    score_imagem:      float = 0.0
    uid:               str = ""

    def to_dict(self) -> dict:
        return {
            "caminho_imagem":    self.caminho_imagem,
            "caminho_original":  self.caminho_original,
            "credito_foto":      self.credito_foto,
            "url_imagem":        self.url_imagem,
            "estrategia_imagem": self.estrategia_imagem,
            "dimensoes_origem":  self.dimensoes_origem,
            "largura_origem":    self.largura_origem,
            "altura_origem":     self.altura_origem,
            "melhor_qualidade":  self.melhor_qualidade,
            "score_imagem":      self.score_imagem,
            "uid":               self.uid,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ImagemDados":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class MapaEvidencias:
    """Estrutura de fatos extraída antes da redação."""
    fato_principal:     str = ""
    fatos_secundarios:  list[str] = field(default_factory=list)
    quem:               list[str] = field(default_factory=list)
    onde:               str = ""
    quando:             str = ""
    por_que_importa:    str = ""
    consequencia:       str = ""
    contexto_anterior:  str = ""
    numero_principal:   str = ""
    orgao_central:      str = ""
    status_atual:       str = ""
    proximos_passos:    str = ""
    fonte_primaria:     str = ""
    fontes_secundarias: list[str] = field(default_factory=list)
    grau_confianca:     str = "medio"   # alto | medio | baixo
    risco_editorial:    str = "baixo"   # alto | medio | baixo

    def to_dict(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)


@dataclass
class Materia:
    """Pacote editorial completo de uma matéria."""
    retranca:           str = ""
    titulo:             str = ""
    titulo_capa:        str = ""
    titulos_alternativos: list[str] = field(default_factory=list)
    titulos_capa_alternativos: list[str] = field(default_factory=list)
    frase_chave:        str = ""
    slug:               str = ""
    meta_description:   str = ""
    subtitulo:          str = ""
    legenda:            str = ""
    tags:               str = ""
    intertitulos:       list[str] = field(default_factory=list)
    estrutura_decisao:  str = ""
    conteudo:           str = ""
    resumo_curto:       str = ""
    chamada_social:     str = ""
    fonte_nome:         str = ""
    link_origem:        str = ""
    canal:              str = ""
    score_editorial:    int = 0
    score_risco:        int = 0
    status:             str = "rascunho"
    mapa_evidencias:    Optional[MapaEvidencias] = None
    termos_ia_detectados: list[str] = field(default_factory=list)

    # ── Campos de auditoria v44 ───────────────────────────────────────────────
    nome_da_fonte:       str = "Redação"
    creditos_da_foto:    str = ""
    auditoria_aprovada:  bool = False
    auditoria_bloqueada: bool = True
    auditoria_erros:     list[str] = field(default_factory=list)
    status_pipeline:     str = "bloquear"   # publicar_direto | salvar_rascunho | bloquear
    violacoes_factuais:  list[str] = field(default_factory=list)
    metadados_apurados:  dict = field(default_factory=dict)

    # ── Campos de revisão humana (v59+) ──────────────────────────────────────
    # status_validacao: "aprovado" | "pendente" | "reprovado"
    status_validacao:          str = "pendente"
    # status_publicacao_sugerido: "publicar" | "salvar_rascunho" | "bloquear"
    status_publicacao_sugerido: str = "bloquear"
    # Flag explícita de necessidade de revisão humana
    revisao_humana_necessaria: bool = True
    # Erros de validação padronizados (lista de dicts)
    erros_validacao:           list[dict] = field(default_factory=list)
    # Histórico de correções automáticas e manuais
    historico_correcoes:       list[dict] = field(default_factory=list)
    # Campos de aprovação manual
    approved_by:               str = ""
    approved_at:               str = ""
    manual_approval_reason:    str = ""
    # Snapshot das fontes (para comparação na aba Revisão)
    original_source_text:      str = ""
    cleaned_source_text:       str = ""

    # ── v69: Campos de qualidade/coverage/relacoes (propagacao) ────────────
    coverage_score:            float = 0.0
    score_qualidade:           int   = 0
    score_risco_validacao:     int   = 0
    facts_required:            list  = field(default_factory=list)
    facts_used:                list  = field(default_factory=list)
    facts_missing:             list  = field(default_factory=list)
    entity_relationships:      list  = field(default_factory=list)
    relationship_errors:       list  = field(default_factory=list)
    source_sufficiency_score:  int   = 0
    extraction_method:         str   = ""
    extraction_status:         str   = ""
    raw_source_text:           str   = ""
    rss_context_text:          str   = ""
    generated_article_json:    dict  = field(default_factory=dict)
    article_type:              str   = ""
    editorial_angle:           str   = ""
    paragraph_plan:            list  = field(default_factory=list)

    def to_dict(self) -> dict:
        import dataclasses
        d = dataclasses.asdict(self)
        if self.mapa_evidencias:
            d["mapa_evidencias"] = self.mapa_evidencias.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Materia":
        campos = cls.__dataclass_fields__
        filtrado = {k: v for k, v in d.items() if k in campos and k != "mapa_evidencias"}
        m = cls(**filtrado)
        if "mapa_evidencias" in d and isinstance(d["mapa_evidencias"], dict):
            try:
                m.mapa_evidencias = MapaEvidencias(**{
                    k: v for k, v in d["mapa_evidencias"].items()
                    if k in MapaEvidencias.__dataclass_fields__
                })
            except Exception:
                pass
        return m


@dataclass
class Pauta:
    """Pauta captada pelo sistema, com ciclo de vida completo."""
    titulo_origem:      str
    link_origem:        str
    fonte_nome:         str
    resumo_origem:      str = ""
    texto_fonte:        str = ""
    canal_forcado:      str = ""
    score_editorial:    int = 0
    confianca_editoria: int = 0
    scores_editoria:    dict = field(default_factory=dict)
    status:             str = "captada"
    urgente:            bool = False
    imagem_status:      str = "pendente"
    imagem_dados:       Optional[ImagemDados] = None
    imagem_dimensoes_origem: str = ""
    imagem_estrategia:  str = ""
    imagem_caminho:     str = ""
    imagem_url:         str = ""
    imagem_credito:     str = ""
    imagem_info:        str = ""
    materia:            Optional[Materia] = None
    captada_em:         str = field(default_factory=agora_br)
    atualizada_em:      str = field(default_factory=agora_br)
    tentativas_publicacao: int = 0
    erros:              list[str] = field(default_factory=list)
    auditoria:          list[str] = field(default_factory=list)

    # Compatibilidade com o código legado que acessa pauta["campo"]
    def __getitem__(self, key: str):
        return getattr(self, key)

    def __setitem__(self, key: str, value):
        setattr(self, key, value)

    def get(self, key, default=None):
        return getattr(self, key, default)
