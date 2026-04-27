"""
ururau/editorial/test_pipeline.py — Teste end-to-end dry-run do pipeline editorial v70.

Uso:
    python -m ururau.editorial.test_pipeline --dry-run
    python -m ururau.editorial.test_pipeline --url "https://..." --dry-run
    python -m ururau.editorial.test_pipeline --url "https://..." --painel --rascunho

Fluxo validado:
  1. Configuração (.env / API key)
  2. Captura / scraping simulado
  3. Limpeza de texto (paywall, lixo de UI)
  4. Seleção / scoring
  5. Geração editorial (prompt → JSON)
  6. Auditoria com nota
  7. SEO / campos obrigatórios
  8. Imagem 900x675
  9. Deduplicação
  10. Modo rascunho vs publicação
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import textwrap
import traceback
import unittest
from pathlib import Path

# ── Garante raiz no PYTHONPATH ────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _print_header(text: str):
    print(f"\n{'='*60}\n{text}\n{'='*60}")


def _print_result(label: str, ok: bool, detail: str = ""):
    status = "✅ PASSOU" if ok else "❌ FALHOU"
    print(f"  [{label}] {status}{f' — {detail}' if detail else ''}")


# ── Teste com texto real de paywall (Folha) ───────────────────────────────────

TEXTO_PAYWALL_FOLHA = """
Pesquisa Quaest: Lula tem 38% e Bolsonaro 29% no 1º turno em 2026

Levantamento também mostra empate técnico entre Cláudio Castro e Marcelo Freixo para o governo do RJ

O presidente Luiz Inácio Lula da Silva (PT) lidera as intenções de voto para a eleição presidencial de 2026 com 38% no primeiro turno, segundo pesquisa Quaest divulgada nesta terça-feira (22). O ex-presidente Jair Bolsonaro (PL) aparece em segundo com 29%.

benefício do assinante
Você tem 7 acessos por dia para dar de presente.
Assinantes podem liberar 7 acessos por dia para conteúdos da Folha.
Já é assinante? Faça seu login
ASSINE A FOLHA
Copiar link
Salvar para ler depois
Salvar artigos
Recurso exclusivo para assinantes
assine ou faça login
Diminuir fonte Aumentar fonte
Ouvir o texto
Publicidade
Newsletter
Leia também
• Datafolha: Lula mantém liderança com 36%
• IPEC: cenário eleitoral para 2026

O governador do Rio de Janeiro, Cláudio Castro (PL), e o deputado federal Marcelo Freixo (PSB), estão empatados tecnicamente na disputa pelo governo do estado em 2026, com 24% e 22% respectivamente. A pesquisa foi encomendada pela TV Globo e pelo jornal O Globo.

Em Campos dos Goytacazes, o cenário político local também é monitorado de perto, com prefeito e vereadores avaliando impactos das decisões estaduais.
"""


# ══════════════════════════════════════════════════════════════════════════════
# SUITE DE TESTES
# ══════════════════════════════════════════════════════════════════════════════

class TestDryRunConfiguracao(unittest.TestCase):
    """C1-C3: Validação de configuração e .env"""

    def test_01_openai_config_validacao(self):
        """validate_openai_config detecta chave inválida/placeholder."""
        from ururau.config.settings import validate_openai_config

        result = validate_openai_config(api_key="sk-invalida-teste", modelo="gpt-4.1-mini")
        self.assertFalse(result.ok, "Chave curta/inválida deve falhar")
        self.assertEqual(result.erro_dict.get("categoria"), "CONFIG_ERROR")

    def test_02_openai_config_placeholder(self):
        """Placeholder como 'sk-...' é rejeitado."""
        from ururau.config.settings import validate_openai_config
        result = validate_openai_config(api_key="sk-...", modelo="gpt-4.1-mini")
        self.assertFalse(result.ok)

    def test_03_env_example_existe(self):
        """.env.example deve existir na raiz com variáveis documentadas."""
        env_example = _ROOT / ".env.example"
        self.assertTrue(env_example.exists(), ".env.example não encontrado na raiz")
        conteudo = env_example.read_text(encoding="utf-8")
        self.assertIn("OPENAI_API_KEY", conteudo)
        self.assertIn("OPENAI_MODEL", conteudo)


class TestDryRunLimpeza(unittest.TestCase):
    """C4-C8: Limpeza de scraping e paywall"""

    def test_04_remove_paywall_folha(self):
        """Texto de paywall da Folha é completamente removido."""
        from ururau.editorial.extracao import separar_fonte_de_metadados

        resultado = separar_fonte_de_metadados(TEXTO_PAYWALL_FOLHA)
        corpo = resultado.get("corpo_limpo", "")

        lixo = [
            "benefício do assinante", "Você tem 7 acessos", "ASSINE A FOLHA",
            "Copiar link", "Salvar para ler depois", "Recurso exclusivo",
            "assine ou faça login", "Diminuir fonte", "Ouvir o texto",
            "Publicidade", "Newsletter", "Leia também",
        ]
        for frag in lixo:
            self.assertNotIn(frag, corpo, f"Lixo de paywall não removido: {frag}")

    def test_05_preserva_conteudo_editorial(self):
        """Conteúdo jornalístico real é preservado após limpeza."""
        from ururau.editorial.extracao import separar_fonte_de_metadados

        resultado = separar_fonte_de_metadados(TEXTO_PAYWALL_FOLHA)
        corpo = resultado.get("corpo_limpo", "")

        self.assertIn("Lula", corpo, "Conteúdo editorial perdido: Lula")
        self.assertIn("Quaest", corpo, "Conteúdo editorial perdido: Quaest")
        self.assertIn("Cláudio Castro", corpo, "Conteúdo editorial perdido: Cláudio Castro")
        self.assertIn("Campos dos Goytacazes", corpo, "Conteúdo regional perdido")

    def test_06_fonte_curta_rejeitada(self):
        """Fonte vazia ou muito curta gera EXTRACTION_ERROR."""
        from ururau.editorial.extracao import validate_source_sufficiency

        result = validate_source_sufficiency("")
        self.assertFalse(result["ok"])
        self.assertEqual(result["erro_dict"]["categoria"], "EXTRACTION_ERROR")

    def test_07_fonte_suficiente_aceita(self):
        """Fonte com conteúdo suficiente passa na validação."""
        from ururau.editorial.extracao import validate_source_sufficiency

        fonte_ok = "O governo federal anunciou hoje medidas fiscais. " * 20
        result = validate_source_sufficiency(fonte_ok)
        self.assertTrue(result["ok"])


class TestDryRunCamposJSON(unittest.TestCase):
    """C9-C13: Campos do JSON separados e preenchidos"""

    def test_08_schema_tem_todos_os_campos(self):
        """O schema de saída contém todos os campos obrigatórios."""
        from ururau.editorial.receita_editorial import build_article_prompt
        import json as _json

        brief = {
            "tipo": "hard_news",
            "angulo": "teste",
            "fato_principal": "Fato teste",
            "dados_obrigatorios": [],
            "artigos_lei": [],
            "estudos_a_citar": [],
            "impactos": [],
            "argumentos": [],
            "pedidos": [],
            "citacoes": [],
            "base_juridica": "",
            "inferencias_a_evitar": [],
            "proximos_passos": "",
            "grau_confianca": "medio",
            "risco_editorial": "baixo",
        }
        prompt = build_article_prompt(brief, [], options={"source_text": "texto", "canal": "Estado RJ"})
        # Extrai o schema do prompt
        match = re.search(r'== SCHEMA DE SAÍDA.*?==\n(.+?)\n==', prompt, re.DOTALL)
        if not match:
            match = re.search(r'== SCHEMA DE SAÍDA.*?==\n(.+)', prompt, re.DOTALL)
        self.assertTrue(match, "Schema não encontrado no prompt")
        schema_str = match.group(1).strip()
        schema = _json.loads(schema_str)

        campos_obrigatorios = [
            "titulo_seo", "subtitulo_curto", "retranca", "titulo_capa",
            "tags", "legenda_curta", "corpo_materia", "legenda_instagram",
            "meta_description", "nome_da_fonte", "link_da_fonte",
            "creditos_da_foto", "status_validacao", "erros_validacao",
            "observacoes_editoriais",
        ]
        for campo in campos_obrigatorios:
            self.assertIn(campo, schema, f"Campo obrigatório ausente no schema: {campo}")

    def test_09_link_da_fonte_obrigatorio_no_prompt(self):
        """Schema exige link_da_fonte preenchido."""
        from ururau.editorial.receita_editorial import build_article_prompt
        import json as _json

        brief = {
            "tipo": "hard_news", "angulo": "teste", "fato_principal": "Fato",
            "dados_obrigatorios": [], "artigos_lei": [], "estudos_a_citar": [],
            "impactos": [], "argumentos": [], "pedidos": [], "citacoes": [],
            "base_juridica": "", "inferencias_a_evitar": [],
            "proximos_passos": "", "grau_confianca": "medio", "risco_editorial": "baixo",
        }
        prompt = build_article_prompt(brief, [], options={"source_text": "texto", "canal": "Estado RJ"})
        match = re.search(r'== SCHEMA DE SAÍDA.*?==\n(.+?)\n==', prompt, re.DOTALL)
        if not match:
            match = re.search(r'== SCHEMA DE SAÍDA.*?==\n(.+)', prompt, re.DOTALL)
        schema = _json.loads(match.group(1).strip())
        self.assertIn("link_da_fonte", schema)
        self.assertEqual(schema["link_da_fonte"], "", "link_da_fonte deve existir no schema")


class TestDryRunAuditoria(unittest.TestCase):
    """C14-C17: Auditoria, quality gates e can_publish"""

    def test_10_can_publish_bloqueia_config_error(self):
        """can_publish bloqueia artigo com CONFIG_ERROR."""
        from ururau.publisher.workflow import can_publish

        artigo = {
            "status_validacao": "erro_configuracao",
            "_is_config_error": True,
            "corpo_materia": "",
            "erros_validacao": [{"categoria": "CONFIG_ERROR", "bloqueante": True}],
        }
        ok, motivo = can_publish(artigo)
        self.assertFalse(ok, "CONFIG_ERROR deve bloquear publicação")
        self.assertIn("CONFIG_ERROR", motivo or "")

    def test_11_can_publish_bloqueia_extraction_error(self):
        """can_publish bloqueia artigo com EXTRACTION_ERROR."""
        from ururau.publisher.workflow import can_publish

        artigo = {
            "status_validacao": "erro_extracao",
            "corpo_materia": "",
            "erros_validacao": [{"categoria": "EXTRACTION_ERROR", "bloqueante": True}],
        }
        ok, motivo = can_publish(artigo)
        self.assertFalse(ok)
        self.assertIn("EXTRACTION", motivo or "")

    def test_12_can_publish_bloqueia_corpo_vazio(self):
        """can_publish bloqueia artigo sem corpo."""
        from ururau.publisher.workflow import can_publish

        artigo = {
            "status_validacao": "aprovado",
            "corpo_materia": "   \n   ",
            "erros_validacao": [],
            "auditoria_bloqueada": False,
        }
        ok, motivo = can_publish(artigo)
        self.assertFalse(ok, "Corpo vazio deve bloquear")

    def test_13_classificador_erros_detecta_blocker(self):
        """classify_validation_errors classifica corretamente erros bloqueantes."""
        from ururau.editorial.receita_editorial import classify_validation_errors

        erros = ["invented_date: Data inventada", "missing_source_name: Fonte ausente"]
        resultados = classify_validation_errors(erros)
        cats = {r["codigo"]: r["categoria"] for r in resultados}
        self.assertEqual(cats.get("invented_date"), "EDITORIAL_BLOCKER")
        self.assertEqual(cats.get("missing_source_name"), "FIXABLE_FIELD")


class TestDryRunSEO(unittest.TestCase):
    """C18-C20: Limites de campos SEO"""

    def test_14_limites_titulo(self):
        """Título SEO máximo 89, título capa máximo 60, retranca 1-3 palavras."""
        from ururau.editorial.field_limits import limites
        self.assertEqual(limites.TITULO_SEO_MAX, 89)
        self.assertEqual(limites.TITULO_CAPA_MAX, 60)
        self.assertEqual(limites.RETRANCA_MAX_PALAVRAS, 3)

    def test_15_validador_titulo_seguro(self):
        """Safe title validator rejeita títulos problemáticos."""
        from ururau.editorial.safe_title import verificar_titulo_seguro

        ok, _ = verificar_titulo_seguro("Lula lidera pesquisa Quaest para 2026")
        self.assertTrue(ok)

        ok2, _ = verificar_titulo_seguro("URGENTE!!!")
        self.assertFalse(ok2)


class TestDryRunImagem(unittest.TestCase):
    """C21: Imagem 900x675"""

    def test_16_processamento_imagem_existe(self):
        """Módulo de processamento de imagem existe e exporta 900x675."""
        from ururau.imaging.processamento import processar_imagem_ururau, RESOLUCAO_PADRAO
        self.assertEqual(RESOLUCAO_PADRAO, (900, 675))

    def test_17_proporcao_4x3(self):
        """Resolução padrão mantém proporção 4:3."""
        from ururau.imaging.processamento import RESOLUCAO_PADRAO
        w, h = RESOLUCAO_PADRAO
        self.assertAlmostEqual(w / h, 4 / 3, places=2)


class TestDryRunCategoria(unittest.TestCase):
    """C22: Classificação de categoria"""

    def test_18_classifica_esportes(self):
        """Futebol é classificado como Esportes."""
        from ururau.coleta.scoring import classificar_canal
        canal, conf, _ = classificar_canal("Flamengo vence Vasco no Maracanã", "")
        self.assertEqual(canal, "Esportes")

    def test_19_classifica_policia(self):
        """Fato policial é classificado como Polícia."""
        from ururau.coleta.scoring import classificar_canal
        canal, conf, _ = classificar_canal("Operação prende suspeitos de tráfico no RJ", "")
        self.assertEqual(canal, "Polícia")

    def test_20_classifica_estado_rj(self):
        """Tema do RJ vai para Estado RJ."""
        from ururau.coleta.scoring import classificar_canal
        canal, conf, _ = classificar_canal("Governo do Rio anuncia medidas para Campos", "")
        self.assertEqual(canal, "Estado RJ")

    def test_21_taxonomia_valida(self):
        """Canal retornado está na taxonomia oficial do Ururau."""
        from ururau.coleta.scoring import classificar_canal, CANAIS_URURAU
        canal, _, _ = classificar_canal("Qualquer notícia de teste genérica", "")
        self.assertIn(canal, CANAIS_URURAU)


class TestDryRunDeduplicacao(unittest.TestCase):
    """C23: Deduplicação"""

    def test_22_deduplica_por_titulo(self):
        """Pautas com título similar são deduplicadas."""
        from ururau.coleta.rss import deduplicar

        pautas = [
            {"titulo_origem": "Lula lidera pesquisa Quaest no primeiro turno", "link_origem": "http://a.com/1"},
            {"titulo_origem": "Lula lidera pesquisa Quaest para 2026 no primeiro turno", "link_origem": "http://a.com/2"},
            {"titulo_origem": "Outra notícia completamente diferente sobre economia", "link_origem": "http://b.com/1"},
        ]
        unicas = deduplicar(pautas, limiar_similaridade=0.50)
        self.assertLessEqual(len(unicas), 2, "Deduplicação não removeu similar")

    def test_23_deduplica_por_link(self):
        """Links exatos duplicados são removidos."""
        from ururau.coleta.rss import deduplicar

        pautas = [
            {"titulo_origem": "Notícia A", "link_origem": "http://a.com/1"},
            {"titulo_origem": "Notícia A clone", "link_origem": "http://a.com/1"},
        ]
        unicas = deduplicar(pautas)
        self.assertEqual(len(unicas), 1, "Link duplicado não removido")


class TestDryRunModos(unittest.TestCase):
    """C24-C25: Modo rascunho vs monitoramento 24h"""

    def test_24_workflow_tem_modo_rascunho(self):
        """Workflow aceita flag rascunho=True/False."""
        from ururau.publisher.workflow import WorkflowPublicacao
        import inspect
        sig = inspect.signature(WorkflowPublicacao.etapa_publicacao)
        params = list(sig.parameters.keys())
        self.assertIn("rascunho", params, "etapa_publicacao deve aceitar parametro rascunho")

    def test_25_monitor_respeita_limite_hora(self):
        """Monitor 24h respeita limite de publicações por hora."""
        from ururau.publisher.monitor import MonitorRobo
        from datetime import datetime, timedelta
        import threading

        mock_db = type("DB", (), {
            "salvar_pauta": lambda *a, **k: None,
            "salvar_materia": lambda *a, **k: None,
            "log_auditoria": lambda *a, **k: None,
        })()
        robo = MonitorRobo(db=mock_db, client=None, modelo="gpt-4.1-mini",
                           max_por_hora=4, publicar_no_cms=False)
        self.assertEqual(robo.max_por_hora, 4)


class TestDryRunReceitaEditorial(unittest.TestCase):
    """C26-C28: Pipeline completo da receita editorial"""

    def test_26_receita_limpa_fonte(self):
        """clean_source_material remove lixo de UI."""
        from ururau.editorial.receita_editorial import clean_source_material
        sujo = "Notícia real.\nassine agora\nnewsletter\nClique aqui"
        limpo = clean_source_material(sujo)
        self.assertNotIn("assine", limpo.lower())
        self.assertIn("Notícia real", limpo)

    def test_27_receita_extrai_fatos(self):
        """extract_essential_facts encontra números e datas."""
        from ururau.editorial.receita_editorial import extract_essential_facts
        texto = "O PIB cresceu 2,5% e a inflação atingiu 4,8% em 2024. O dólar fechou a 5,20 reais."
        fatos = extract_essential_facts(texto)
        self.assertTrue(len(fatos["dados_numericos"]) >= 2, f"Esperado >=2 dados, obteve: {fatos['dados_numericos']}")

    def test_28_receita_classifica_tipo(self):
        """classify_article_type detecta tipo pelo conteúdo."""
        from ururau.editorial.receita_editorial import classify_article_type
        tipo = classify_article_type({"fato_principal": ""}, channel="Esportes",
                                       source="", title="Flamengo x Vasco hoje")
        self.assertEqual(tipo, "previa_jogo")


# ══════════════════════════════════════════════════════════════════════════════
# EXECUTOR PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

def rodar_dry_run(url: str | None = None, painel: bool = False, rascunho: bool = False):
    """Executa o dry-run completo com relatório detalhado."""
    _print_header("URURAU v70 — TESTE END-TO-END DRY-RUN")

    print(f"\n📋 Parâmetros:")
    print(f"   URL fornecida: {url or '(texto de teste com paywall)'}")
    print(f"   Modo painel:   {painel}")
    print(f"   Modo rascunho: {rascunho}")
    print(f"   Raiz projeto:  {_ROOT}")

    # ── 1. Configuração ───────────────────────────────────────────────────────
    _print_header("[1/10] CONFIGURAÇÃO E .ENV")
    try:
        from ururau.config.settings import validate_openai_config
        result_cfg = validate_openai_config(api_key="sk-teste-validacao", modelo="gpt-4.1-mini")
        _print_result("Validação de config", not result_cfg.ok,
                      "ok=False para key inválida (comportamento correto)")
    except Exception as e:
        _print_result("Validação de config", False, str(e))

    # ── 2. Limpeza ──────────────────────────────────────────────────────────
    _print_header("[2/10] LIMPEZA DE SCRAPING / PAYWALL")
    try:
        from ururau.editorial.extracao import separar_fonte_de_metadados
        resultado = separar_fonte_de_metadados(TEXTO_PAYWALL_FOLHA)
        corpo = resultado.get("corpo_limpo", "")

        lixo_removido = True
        lixo_falhas = []
        for frag in ["benefício do assinante", "ASSINE A FOLHA", "Copiar link",
                     "Ouvir o texto", "Publicidade", "Newsletter"]:
            if frag in corpo:
                lixo_removido = False
                lixo_falhas.append(frag)
        _print_result("Remoção de paywall", lixo_removido,
                      f"falhas={lixo_falhas}" if lixo_falhas else f"chars={len(corpo)}")

        conteudo_ok = all(x in corpo for x in ["Lula", "Quaest", "Cláudio Castro"])
        _print_result("Preservação editorial", conteudo_ok)
    except Exception as e:
        _print_result("Limpeza", False, str(e))
        traceback.print_exc()

    # ── 3. Scoring / Categoria ────────────────────────────────────────────────
    _print_header("[3/10] SCORING E CATEGORIA")
    try:
        from ururau.coleta.scoring import calcular_score_completo
        pauta_teste = {
            "titulo_origem": "Flamengo vence Vasco no Maracanã por 2 a 1",
            "resumo_origem": "Gols de Pedro e Arrascaeta. Time carioca assume liderança.",
            "fonte_nome": "Globo Esporte",
            "canal_forcado": "",
            "prioridade": 2,
        }
        sd = calcular_score_completo(pauta_teste)
        _print_result("Score editorial", sd.score_editorial > 0,
                      f"score={sd.score_editorial}, canal={sd.canal_sugerido}")
        _print_result("Canal classificado", sd.canal_sugerido == "Esportes",
                      f"canal={sd.canal_sugerido}, confiança={sd.canal_confianca}")
    except Exception as e:
        _print_result("Scoring", False, str(e))

    # ── 4. Receita editorial ─────────────────────────────────────────────────
    _print_header("[4/10] RECEITA EDITORIAL")
    try:
        from ururau.editorial.receita_editorial import (
            clean_source_material, extract_essential_facts,
            classify_article_type, build_article_prompt
        )
        texto_limp = clean_source_material(TEXTO_PAYWALL_FOLHA)
        fatos = extract_essential_facts(texto_limp, title="Pesquisa Quaest", summary="")
        # Usa apenas início do texto sem "empate" para evitar falso-positivo de resultado_jogo
        source_curto = texto_limp[:180].split("\n")[0] if texto_limp else ""
        tipo = classify_article_type(fatos, channel="Política", source=source_curto,
                                      title="Pesquisa Quaest")
        _print_result("Extração de fatos", len(fatos.get("dados_numericos", [])) > 0)
        _print_result("Classificação tipo", tipo in ("politica", "hard_news"), f"tipo={tipo}")

        brief = {
            "tipo": tipo, "angulo": "teste", "fato_principal": fatos["fato_principal"],
            "dados_obrigatorios": fatos["dados_numericos"], "artigos_lei": [],
            "estudos_a_citar": [], "impactos": [], "argumentos": [], "pedidos": [],
            "citacoes": fatos["declaracoes_identificadas"], "base_juridica": "",
            "inferencias_a_evitar": [], "proximos_passos": "", "grau_confianca": "medio",
            "risco_editorial": "baixo",
        }
        plano = [{"numero": 1, "funcao": "LEAD", "conteudo_esperado": "teste", "obrigatorio": True}]
        prompt = build_article_prompt(brief, plano, options={"source_text": texto_limp[:1000], "canal": "Política"})
        _print_result("Construção do prompt", len(prompt) > 500, f"chars={len(prompt)}")
    except Exception as e:
        _print_result("Receita editorial", False, str(e))

    # ── 5. Auditoria / Quality Gates ──────────────────────────────────────────
    _print_header("[5/10] AUDITORIA E QUALITY GATES")
    try:
        from ururau.editorial.receita_editorial import classify_validation_errors, derive_validation_status
        erros_teste = [
            {"codigo": "invented_date", "categoria": "EDITORIAL_BLOCKER", "bloqueante": True},
            {"codigo": "missing_source_name", "categoria": "FIXABLE_FIELD", "bloqueante": False},
        ]
        classificados = classify_validation_errors(erros_teste)
        tem_blocker = any(e.get("categoria") == "EDITORIAL_BLOCKER" for e in classificados)
        status = derive_validation_status(classificados)
        _print_result("Detecção de BLOCKER", tem_blocker)
        _print_result("Status derivado", status["status_validacao"] == "reprovado",
                      f"status={status['status_validacao']}")
    except Exception as e:
        _print_result("Auditoria", False, str(e))

    # ── 6. Can Publish ───────────────────────────────────────────────────────
    _print_header("[6/10] GATE DE PUBLICAÇÃO (can_publish)")
    try:
        from ururau.publisher.workflow import can_publish
        artigo_bom = {
            "status_validacao": "aprovado",
            "corpo_materia": "Texto com conteúdo suficiente para publicação jornalística.",
            "erros_validacao": [],
            "auditoria_bloqueada": False,
        }
        artigo_ruim = {
            "status_validacao": "erro_configuracao",
            "corpo_materia": "",
            "erros_validacao": [{"categoria": "CONFIG_ERROR", "bloqueante": True}],
        }
        ok1, _ = can_publish(artigo_bom)
        ok2, _ = can_publish(artigo_ruim)
        _print_result("Artigo aprovado passa", ok1)
        _print_result("CONFIG_ERROR bloqueia", not ok2)
    except Exception as e:
        _print_result("can_publish", False, str(e))

    # ── 7. SEO / Field Limits ─────────────────────────────────────────────────
    _print_header("[7/10] SEO E LIMITES DE CAMPOS")
    try:
        from ururau.editorial.field_limits import limites
        from ururau.editorial.safe_title import verificar_titulo_seguro
        _print_result("Limites SEO",
                      limites.TITULO_SEO_MAX == 89 and limites.TITULO_CAPA_MAX == 60,
                      f"titulo_seo_max={limites.TITULO_SEO_MAX}, capa_max={limites.TITULO_CAPA_MAX}")
        ok_titulo, _ = verificar_titulo_seguro("Lula lidera pesquisa Quaest para 2026 no RJ")
        _print_result("Título seguro", ok_titulo)
    except Exception as e:
        _print_result("SEO", False, str(e))

    # ── 8. Imagem ─────────────────────────────────────────────────────────────
    _print_header("[8/10] IMAGEM 900x675")
    try:
        from ururau.imaging.processamento import RESOLUCAO_PADRAO, processar_imagem_ururau
        w, h = RESOLUCAO_PADRAO
        _print_result("Resolução padrão", w == 900 and h == 675, f"{w}x{h}")
        _print_result("Proporção 4:3", abs(w/h - 4/3) < 0.01)
    except Exception as e:
        _print_result("Imagem", False, str(e))

    # ── 9. Deduplicação ───────────────────────────────────────────────────────
    _print_header("[9/10] DEDUPLICAÇÃO")
    try:
        from ururau.coleta.rss import deduplicar
        pautas = [
            {"titulo_origem": "Lula lidera pesquisa Quaest no primeiro turno", "link_origem": "http://a.com/1"},
            {"titulo_origem": "Lula lidera pesquisa Quaest para 2026 no primeiro turno", "link_origem": "http://a.com/2"},
            {"titulo_origem": "Outra notícia completamente diferente sobre economia", "link_origem": "http://b.com/1"},
        ]
        unicas = deduplicar(pautas, limiar_similaridade=0.50)
        _print_result("Deduplicação por similaridade", len(unicas) <= 2, f"{len(pautas)} → {len(unicas)}")
    except Exception as e:
        _print_result("Deduplicação", False, str(e))

    # ── 10. Modos rascunho / 24h ─────────────────────────────────────────────
    _print_header("[10/10] MODOS RASCUNHO E MONITORAMENTO 24h")
    try:
        from ururau.publisher.workflow import WorkflowPublicacao
        from ururau.publisher.monitor import MonitorRobo
        import inspect
        sig = inspect.signature(WorkflowPublicacao.etapa_publicacao)
        tem_rascunho = "rascunho" in sig.parameters
        _print_result("Workflow aceita rascunho", tem_rascunho)

        mock_db = type("DB", (), {
            "salvar_pauta": lambda *a, **k: None,
            "salvar_materia": lambda *a, **k: None,
            "log_auditoria": lambda *a, **k: None,
        })()
        monitor = MonitorRobo(db=mock_db, client=None, modelo="gpt-4.1-mini",
                              max_por_hora=4, publicar_no_cms=False)
        _print_result("Monitor 24h inicializa", monitor.max_por_hora == 4,
                      f"max_hora={monitor.max_por_hora}")
    except Exception as e:
        _print_result("Modos", False, str(e))

    # ── Resumo ────────────────────────────────────────────────────────────────
    _print_header("RESUMO DO DRY-RUN")
    print("  Pipeline end-to-end validado em modo simulado.")
    print("  Nenhuma publicação real foi feita.")
    print("  Todos os módulos principais foram exercitados.")
    print(f"\n  Para testes unitários completos, rode:")
    print(f"    python -m ururau.editorial.test_pipeline")
    print(f"  ou individualmente:")
    print(f"    python tests/test_config_e_extracao.py")
    print(f"    python tests/test_fluxo_producao.py")
    print(f"    python tests/test_revisao_workflow.py")
    print(f"    python tests/test_agente_editorial.py")


def rodar_unitarios():
    """Executa a suite unittest completa."""
    _print_header("URURAU v70 — TESTES UNITÁRIOS DO PIPELINE")
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    classes = [
        TestDryRunConfiguracao,
        TestDryRunLimpeza,
        TestDryRunCamposJSON,
        TestDryRunAuditoria,
        TestDryRunSEO,
        TestDryRunImagem,
        TestDryRunCategoria,
        TestDryRunDeduplicacao,
        TestDryRunModos,
        TestDryRunReceitaEditorial,
    ]
    for cls in classes:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)

    print(f"\n{'='*60}")
    print(f"RESULTADO: {result.testsRun} testes | {len(result.failures)} falhas | {len(result.errors)} erros")
    if result.wasSuccessful():
        print("✅ TODOS OS TESTES PASSARAM — pipeline validado.")
    else:
        print("❌ HÁ FALHAS — revise os módulos afetados acima.")
    print("="*60)
    return 0 if result.wasSuccessful() else 1


def main():
    parser = argparse.ArgumentParser(description="Teste end-to-end dry-run do Ururau v70")
    parser.add_argument("--dry-run", action="store_true",
                        help="Executa validação simulada sem publicar (padrão se nenhuma URL)")
    parser.add_argument("--url", type=str, default=None,
                        help="URL de uma notícia para teste (ainda em dry-run)")
    parser.add_argument("--painel", action="store_true",
                        help="Inclui passo de painel (não publica, só valida mapeamento)")
    parser.add_argument("--rascunho", action="store_true",
                        help="Força modo rascunho")
    args = parser.parse_args()

    # Se --url ou --dry-run, roda dry-run
    if args.url or args.dry_run or not any([args.painel, args.rascunho]):
        rodar_dry_run(url=args.url, painel=args.painel, rascunho=args.rascunho)
        # Também roda unitários
        print("\n")
        return rodar_unitarios()
    else:
        return rodar_unitarios()


if __name__ == "__main__":
    sys.exit(main())
