"""
editorial/risco.py — Score de risco jurídico e editorial.
Detecta problemas de atribuição, tom acusatório, especulação e risco reputacional.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field


@dataclass
class ResultadoRisco:
    score: int = 0          # 0-100
    nivel: str = "baixo"    # baixo | medio | alto | critico
    alertas: list[str] = field(default_factory=list)
    bloqueante: bool = False

    def adicionar(self, msg: str, pontos: int):
        self.alertas.append(msg)
        self.score += pontos
        self.score = min(self.score, 100)
        self._atualizar_nivel()

    def _atualizar_nivel(self):
        if self.score >= 70:
            self.nivel = "critico"
            self.bloqueante = True
        elif self.score >= 50:
            self.nivel = "alto"
        elif self.score >= 25:
            self.nivel = "medio"
        else:
            self.nivel = "baixo"


# ── Padrões de risco ───────────────────────────────────────────────────────────

# Afirmações de culpa sem sentença
_CULPA_SEM_SENTENCA = [
    (r'\bé culpad[oa]\b', "Afirmação de culpa sem sentença judicial", 30),
    (r'\bconfessou\b(?! que (negou|disse|afirmou))', "Afirmação de confissão sem qualificação", 20),
    (r'\bcometeu o crime\b', "Afirmação de crime sem sentença", 30),
    (r'\bcomprovadamente corrupto\b', "Adjetivo acusatório sem base", 35),
    (r'\bnotoriamente\b', "Termo vago sem fonte", 15),
    (r'\bsabidamente\b', "Afirmação sem fonte", 15),
    (r'\bdefinitivamente acusado\b', "Tom acusatório excessivo", 20),
]

# Especulação disfarçada de fato
_ESPECULACAO = [
    (r'\bteria (?:cometido|praticado|recebido|dado)\b', "Afirmação especulativa sem fonte", 10),
    (r'\bprovavelmente\b(?! (?:segundo|de acordo|conforme))', "Especulação sem atribuição", 8),
    (r'\bcertamente\b', "Certeza sem base factual", 12),
    (r'\bé evidente que\b', "Conclusão não demonstrada", 10),
    (r'\bfica claro que\b', "Conclusão não demonstrada", 10),
    (r'\btudo indica que\b', "Especulação genérica", 8),
]

# Falta de atribuição em afirmações importantes
_SEM_ATRIBUICAO = [
    (r'(?:fontes|interlocutores|pessoas próximas) (?:afirmam|dizem|revelam)\b(?! (?:que|ao|à))',
     "Fonte não identificada adequadamente", 12),
    (r'\bsegundo apurado\b(?! (?:pelo|pela))', "Atribuição vaga sem identificação", 10),
    (r'\bconforme apurado\b(?! (?:pelo|pela))', "Atribuição vaga sem identificação", 10),
    (r'\bde acordo com fontes\b(?! (?:do|da|das|dos|policiais|oficiais|da Polícia|do MP|do tribunal))',
     "Fonte não qualificada", 8),
]

# Problemas em matérias de polícia
_POLICIA = [
    (r'\b(?:bandido|marginal|traficante)\b(?! (?:preso|identificado como|apontado pela))',
     "Classificação penal sem sentença", 20),
    (r'\bcriminoso\b(?! (?:preso|identificado|apontado))', "Classificação penal sem sentença", 20),
    (r'\bvagabundo\b', "Linguagem inadequada em matéria policial", 25),
]

# Tom opinativo em matéria factual
_OPINATIVO = [
    (r'\bfelizmente\b', "Tom opinativo em matéria factual", 10),
    (r'\binfelizmente\b', "Tom opinativo em matéria factual", 10),
    (r'\bé absurdo\b', "Tom opinativo", 15),
    (r'\bé vergonhoso\b', "Tom opinativo", 15),
    (r'\bé uma pena\b', "Tom opinativo", 10),
    (r'\bé lamentável\b', "Tom opinativo", 10),
]

# Problemas em matérias políticas
_POLITICO = [
    (r'\bcorrupto\b(?! (?:preso|condenado|investigado|indiciado|acusado))',
     "Classificação penal sem processo", 25),
    (r'\bladrão\b', "Classificação penal sem sentença", 25),
    (r'\bbandalheira\b', "Linguagem inadequada para matéria política", 20),
]

ALL_PATTERNS = [
    (_CULPA_SEM_SENTENCA,  1.0),
    (_ESPECULACAO,         1.0),
    (_SEM_ATRIBUICAO,      0.8),
    (_POLICIA,             1.0),
    (_OPINATIVO,           0.6),
    (_POLITICO,            1.0),
]


def analisar_risco(texto: str, canal: str = "") -> ResultadoRisco:
    """
    Analisa o texto e retorna score de risco editorial.
    Score 0-100. Acima de 70 bloqueia publicação automática.
    """
    resultado = ResultadoRisco()
    texto_lower = texto.lower()

    for patterns, multiplicador in ALL_PATTERNS:
        for padrao, descricao, pontos in patterns:
            if re.search(padrao, texto_lower):
                resultado.adicionar(descricao, int(pontos * multiplicador))

    # Bonus de risco por canal
    if canal in ("Polícia", "Política") and resultado.score > 0:
        resultado.score = min(int(resultado.score * 1.2), 100)
        resultado._atualizar_nivel()

    return resultado


def resumo_risco(resultado: ResultadoRisco) -> str:
    """Retorna string formatada do resultado de risco para exibição na GUI."""
    if resultado.score == 0:
        return "✓ Sem risco editorial detectado"
    alertas_txt = "\n".join(f"  • {a}" for a in resultado.alertas[:8])
    bloqueio = " — BLOQUEADO PARA PUBLICAÇÃO AUTOMÁTICA" if resultado.bloqueante else ""
    return (
        f"⚠ Risco {resultado.nivel.upper()} (score {resultado.score}/100){bloqueio}\n"
        f"{alertas_txt}"
    )
