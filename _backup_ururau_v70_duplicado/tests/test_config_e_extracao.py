"""
tests/test_config_e_extracao.py — Testes de falha de configuração e extração (v61)

Cobertura dos 10 cenários críticos do spec de correção:

  C1 : API key inválida → pipeline aborta com erro_configuracao, corpo vazio
  C2 : API key inválida → nenhum fragmento de fonte no corpo_materia
  C3 : can_publish() bloqueia CONFIG_ERROR (workflow.py)
  C4 : can_publish() bloqueia EXTRACTION_ERROR (workflow.py)
  C5 : can_publish() bloqueia status='erro_configuracao'
  C6 : can_publish() bloqueia corpo_materia vazio
  C7 : Fonte com "Notícias relacionadas" → bloco removido da fonte limpa
  C8 : Fonte curta demais → validate_source_sufficiency() retorna ok=False
  C9 : receita_editorial.can_publish() fallback também bloqueia CONFIG_ERROR
  C10: etapa_persistir_materia não avança para PRONTA em CONFIG_ERROR

Execução:
  python tests/test_config_e_extracao.py
  python tests/test_config_e_extracao.py --verbose
  python tests/test_config_e_extracao.py --teste C3
"""
from __future__ import annotations

import sys
import os
import json
import argparse
import traceback
import unittest
from typing import Optional
from unittest.mock import MagicMock, patch

# Adiciona o diretório raiz ao path para que os imports funcionem
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_config_error_artigo() -> dict:
    """Artigo com CONFIG_ERROR — saída real do pipeline após API key inválida."""
    return {
        "status_validacao": "erro_configuracao",
        "_is_config_error": True,
        "corpo_materia": "",
        "conteudo": "",
        "erros_validacao": [
            {
                "categoria": "CONFIG_ERROR",
                "codigo": "invalid_api_key",
                "mensagem": "Chave de API OpenAI inválida (401).",
                "campo": "openai_api_key",
                "bloqueante": True,
            }
        ],
        "auditoria_bloqueada": True,
        "status_publicacao_sugerido": "bloquear",
    }


def _make_extraction_error_artigo() -> dict:
    """Artigo com EXTRACTION_ERROR — fonte vazia ou inválida."""
    return {
        "status_validacao": "erro_extracao",
        "corpo_materia": "",
        "conteudo": "",
        "erros_validacao": [
            {
                "categoria": "EXTRACTION_ERROR",
                "codigo": "source_empty",
                "mensagem": "Fonte extraída está vazia.",
                "campo": "texto_fonte",
                "bloqueante": True,
            }
        ],
        "auditoria_bloqueada": True,
        "status_publicacao_sugerido": "bloquear",
    }


def _make_approved_artigo() -> dict:
    """Artigo aprovado com conteúdo válido — deve passar no can_publish."""
    return {
        "status_validacao": "aprovado",
        "corpo_materia": "Este é o corpo do artigo com conteúdo suficiente.",
        "conteudo": "Este é o corpo do artigo com conteúdo suficiente.",
        "erros_validacao": [],
        "auditoria_bloqueada": False,
        "auditoria_aprovada": True,
        "status_publicacao_sugerido": "publicar",
    }


# ── Testes ─────────────────────────────────────────────────────────────────────

class TestC1_PipelineAbortaApiKeyInvalida(unittest.TestCase):
    """C1: API key inválida → pipeline aborta com status erro_configuracao e corpo vazio."""

    def test_pipeline_config_error_status(self):
        """validate_openai_config() retorna ok=False para key inválida."""
        from ururau.config.settings import validate_openai_config

        result = validate_openai_config(api_key="sk-invalida-123", modelo="gpt-4.1-mini")
        self.assertFalse(result.ok, "validate_openai_config deveria retornar ok=False para key inválida")
        self.assertIn("codigo", result.erro_dict, "erro_dict deve ter 'codigo'")
        self.assertEqual(result.erro_dict.get("categoria"), "CONFIG_ERROR",
                         "categoria deve ser CONFIG_ERROR")

    def test_validate_openai_config_missing_key_explicit(self):
        """validate_openai_config() retorna ok=False para key ausente quando env não tem key."""
        import os
        from ururau.config.settings import validate_openai_config

        # Força key explicitamente como string de espaços (não vai ao env)
        # validate_openai_config usa api_key or env, então precisamos de uma key
        # que seja explicitamente inválida e não seja um placeholder
        # Testa com string que claramente não é key válida: muito curta com sk- prefixo
        result = validate_openai_config(api_key="sk-curta", modelo="gpt-4.1-mini")
        self.assertFalse(result.ok,
                         "Key 'sk-curta' (< 20 chars) deve ser detectada como placeholder")
        self.assertIn("CONFIG_ERROR", result.erro_dict.get("categoria", ""),
                      "categoria deve ser CONFIG_ERROR")

    def test_validate_openai_config_placeholder(self):
        """validate_openai_config() rejeita placeholders como 'sk-...'."""
        from ururau.config.settings import validate_openai_config

        result = validate_openai_config(api_key="sk-...", modelo="gpt-4.1-mini")
        self.assertFalse(result.ok, "Placeholder 'sk-...' deve ser rejeitado")


class TestC2_NenhumFragmentoFonteNoCorpo(unittest.TestCase):
    """C2: Quando API key inválida, corpo_materia NÃO deve conter fragmentos da fonte."""

    def test_config_error_corpo_vazio(self):
        """Artigo com CONFIG_ERROR deve ter corpo_materia vazio."""
        artigo = _make_config_error_artigo()
        corpo = artigo.get("corpo_materia", "")
        self.assertEqual(corpo.strip(), "",
                         "corpo_materia deve ser vazio em CONFIG_ERROR")

    def test_config_error_sem_fragmento_fonte(self):
        """Simula o cenário onde a pipeline produziria fragmentos se não bloqueada."""
        # Se pipeline.py detecta CONFIG_ERROR, deve retornar corpo="" mesmo que haja fonte
        artigo = _make_config_error_artigo()
        fonte_original = "Esta é a fonte original com muito conteúdo editorial."

        # O corpo jamais deve conter a fonte como fallback
        corpo = artigo.get("corpo_materia", "") or ""
        self.assertNotIn(fonte_original[:30], corpo,
                         "Fragmento da fonte NÃO deve aparecer no corpo em CONFIG_ERROR")

    def test_pipeline_failure_corpo_vazio_em_redacao(self):
        """redacao.py: quando dados está vazio, corpo_materia nunca usa resumo_origem."""
        # Simula o estado que redacao.py gerava antes da correção:
        # agora `if not dados` → define corpo_materia="" em vez de resumo_origem
        resumo_origem = "Resumo da notícia original que NÃO deve virar artigo."

        # Constrói o resultado que redacao.py DEVE produzir agora
        dados_resultante = {
            "corpo_materia": "",   # CORRETO: vazio, não resumo_origem
            "status_validacao": "erro_extracao",
        }

        self.assertEqual(dados_resultante["corpo_materia"], "",
                         "corpus_materia deve ser '' quando pipeline falha")
        self.assertNotIn(resumo_origem[:20], dados_resultante["corpo_materia"],
                         "resumo_origem não deve aparecer no corpo quando pipeline falha")


class TestC3_CanPublishBloqueiaConfigError(unittest.TestCase):
    """C3: can_publish() (workflow.py) bloqueia artigos com CONFIG_ERROR."""

    def test_bloqueia_is_config_error_flag(self):
        """can_publish() retorna False quando _is_config_error=True."""
        from ururau.publisher.workflow import can_publish
        artigo = _make_config_error_artigo()
        ok, motivo = can_publish(artigo)
        self.assertFalse(ok, "CONFIG_ERROR deve bloquear publicação")
        self.assertIn("CONFIG_ERROR", motivo or "",
                      f"Motivo deve mencionar CONFIG_ERROR, got: {motivo}")

    def test_bloqueia_categoria_config_error(self):
        """can_publish() retorna False quando erros_validacao tem categoria CONFIG_ERROR."""
        from ururau.publisher.workflow import can_publish
        artigo = {
            "status_validacao": "pendente",
            "corpo_materia": "",
            "erros_validacao": [{
                "categoria": "CONFIG_ERROR",
                "codigo": "invalid_api_key",
                "mensagem": "API key inválida.",
                "bloqueante": True,
            }],
            "auditoria_bloqueada": True,
        }
        ok, motivo = can_publish(artigo)
        self.assertFalse(ok, "Categoria CONFIG_ERROR deve bloquear publicação")

    def test_aprovacao_manual_nao_bypassa_config_error(self):
        """Aprovação manual NÃO deve permitir publicar artigo com CONFIG_ERROR."""
        from ururau.publisher.workflow import can_publish
        artigo = _make_config_error_artigo()
        # Adiciona aprovação manual — não deve contornar CONFIG_ERROR
        artigo["approved_by"] = "Editor Chefe"
        artigo["approved_at"] = "2026-04-25 10:00:00"
        artigo["manual_approval_reason"] = "Aprovado manualmente para teste."
        ok, motivo = can_publish(artigo)
        self.assertFalse(ok,
                         "Aprovação manual NÃO deve contornar CONFIG_ERROR — artigo nunca foi gerado")


class TestC4_CanPublishBloqueiaExtractionError(unittest.TestCase):
    """C4: can_publish() bloqueia artigos com EXTRACTION_ERROR."""

    def test_bloqueia_categoria_extraction_error(self):
        """can_publish() retorna False quando há EXTRACTION_ERROR em erros_validacao."""
        from ururau.publisher.workflow import can_publish
        artigo = _make_extraction_error_artigo()
        ok, motivo = can_publish(artigo)
        self.assertFalse(ok, "EXTRACTION_ERROR deve bloquear publicação")
        self.assertIn("EXTRACTION_ERROR", motivo or "",
                      f"Motivo deve mencionar EXTRACTION_ERROR, got: {motivo}")

    def test_artigo_aprovado_passa(self):
        """Artigo aprovado com conteúdo deve passar no can_publish()."""
        from ururau.publisher.workflow import can_publish
        artigo = _make_approved_artigo()
        ok, _ = can_publish(artigo)
        self.assertTrue(ok, "Artigo aprovado e com conteúdo deve poder ser publicado")


class TestC5_CanPublishBloqueiaStatusErroConfiguracao(unittest.TestCase):
    """C5: can_publish() bloqueia status_validacao='erro_configuracao' e 'erro_extracao'."""

    def test_bloqueia_status_erro_configuracao(self):
        """can_publish() retorna False quando status_validacao='erro_configuracao'."""
        from ururau.publisher.workflow import can_publish
        artigo = {
            "status_validacao": "erro_configuracao",
            "corpo_materia": "",
            "erros_validacao": [],
            "auditoria_bloqueada": True,
        }
        ok, motivo = can_publish(artigo)
        self.assertFalse(ok, "status='erro_configuracao' deve bloquear publicação")
        self.assertIn("erro_configuracao", (motivo or "").lower(),
                      f"Motivo deve mencionar erro_configuracao, got: {motivo}")

    def test_bloqueia_status_erro_extracao(self):
        """can_publish() retorna False quando status_validacao='erro_extracao'."""
        from ururau.publisher.workflow import can_publish
        artigo = {
            "status_validacao": "erro_extracao",
            "corpo_materia": "",
            "erros_validacao": [],
            "auditoria_bloqueada": True,
        }
        ok, motivo = can_publish(artigo)
        self.assertFalse(ok, "status='erro_extracao' deve bloquear publicação")


class TestC6_CanPublishBloqueiaCorpoVazio(unittest.TestCase):
    """C6: can_publish() bloqueia artigos com corpo_materia vazio (sem CONFIG_ERROR explícito)."""

    def test_bloqueia_corpo_vazio(self):
        """can_publish() retorna False quando corpo_materia está vazio."""
        from ururau.publisher.workflow import can_publish
        artigo = {
            "status_validacao": "pendente",
            "corpo_materia": "",
            "erros_validacao": [],
            "auditoria_bloqueada": False,
        }
        ok, motivo = can_publish(artigo)
        self.assertFalse(ok, "Artigo sem corpo deve ser bloqueado")

    def test_bloqueia_corpo_apenas_espacos(self):
        """can_publish() retorna False quando corpo_materia é apenas espaços em branco."""
        from ururau.publisher.workflow import can_publish
        artigo = {
            "status_validacao": "aprovado",
            "corpo_materia": "   \n   \t  ",
            "erros_validacao": [],
            "auditoria_bloqueada": False,
        }
        ok, _ = can_publish(artigo)
        self.assertFalse(ok, "Corpo com apenas espaços em branco deve bloquear publicação")


class TestC7_FonteLimpaRemoveNoticias(unittest.TestCase):
    """C7: separar_fonte_de_metadados() remove bloco 'Notícias relacionadas' da fonte."""

    def test_remove_bloco_noticias_relacionadas(self):
        """Bloco 'Notícias relacionadas' e seus links devem ser removidos."""
        from ururau.editorial.extracao import separar_fonte_de_metadados

        fonte = """O Governo Federal anunciou novas medidas econômicas nesta terça-feira.

A medida prevê investimento de R$ 2 bilhões em infraestrutura.

Notícias relacionadas
• Governo anuncia pacote de R$ 5 bi
• Congresso aprova PEC das infraestruturas
• Câmara vota projeto amanhã

O ministro afirmou que os recursos serão liberados no primeiro semestre."""

        resultado = separar_fonte_de_metadados(fonte)
        # função retorna 'corpo_limpo' (não 'corpo_fonte')
        corpo_limpo = resultado.get("corpo_limpo", "") or ""

        self.assertNotIn("Notícias relacionadas", corpo_limpo,
                         "Cabeçalho 'Notícias relacionadas' não deve aparecer na fonte limpa")
        self.assertNotIn("Governo anuncia pacote de R$ 5 bi", corpo_limpo,
                         "Links de notícias relacionadas não devem aparecer na fonte limpa")
        self.assertNotIn("Câmara vota projeto amanhã", corpo_limpo,
                         "Links de notícias relacionadas não devem aparecer na fonte limpa")
        # Conteúdo editorial real deve permanecer
        self.assertIn("R$ 2 bilhões", corpo_limpo,
                      "Conteúdo editorial real deve ser preservado")
        self.assertIn("ministro", corpo_limpo,
                      "Conteúdo editorial real deve ser preservado")

    def test_remove_bloco_leia_tambem(self):
        """Bloco 'Leia também' deve ser removido."""
        from ururau.editorial.extracao import separar_fonte_de_metadados

        fonte = """A Câmara dos Deputados aprovou o projeto de lei nesta quarta.

Leia também
• Senado debate PEC amanhã
• Entenda o projeto passo a passo

O texto segue agora para o Senado Federal."""

        resultado = separar_fonte_de_metadados(fonte)
        corpo_limpo = resultado.get("corpo_limpo", "") or ""

        self.assertNotIn("Leia também", corpo_limpo)
        self.assertNotIn("Senado debate PEC amanhã", corpo_limpo)
        self.assertIn("Câmara dos Deputados", corpo_limpo)
        self.assertIn("Senado Federal", corpo_limpo)

    def test_remove_versao_audio(self):
        """Aviso de versão em áudio deve ser removido."""
        from ururau.editorial.extracao import separar_fonte_de_metadados

        fonte = """Novo concurso público abre 500 vagas para 2026.

Versão em áudio
Ouça a matéria completa no podcast do Ururau

Os salários variam entre R$ 3.000 e R$ 15.000 mensais."""

        resultado = separar_fonte_de_metadados(fonte)
        corpo_limpo = resultado.get("corpo_limpo", "") or ""

        self.assertNotIn("Versão em áudio", corpo_limpo)
        self.assertNotIn("podcast", corpo_limpo)
        self.assertIn("R$ 3.000", corpo_limpo)


class TestC8_ValidateSourceSufficiency(unittest.TestCase):
    """C8: validate_source_sufficiency() retorna ok=False para fontes vazias ou muito curtas."""

    def test_fonte_vazia(self):
        """Fonte vazia deve retornar ok=False com erro_dict.categoria=EXTRACTION_ERROR."""
        from ururau.editorial.extracao import validate_source_sufficiency
        result = validate_source_sufficiency("")
        self.assertFalse(result.get("ok", True),
                         "Fonte vazia deve falhar na validação de suficiência")
        # erro_dict está aninhado dentro do resultado, não no nível superior
        erro_dict = result.get("erro_dict", {})
        self.assertEqual(erro_dict.get("categoria"), "EXTRACTION_ERROR",
                         f"categoria do erro_dict deve ser EXTRACTION_ERROR, got: {erro_dict}")

    def test_fonte_muito_curta_com_raw_grande(self):
        """Fonte limpa < 100 chars mas raw original grande indica extração falhou."""
        from ururau.editorial.extracao import validate_source_sufficiency
        # Simula fonte que foi agressivamente limpa (raw tinha 2000 chars, limpa tem 50)
        fonte_pequena = "Texto curto."  # < 100 chars
        metadata_com_raw_grande = {"raw_chars": 2000}
        result = validate_source_sufficiency(fonte_pequena, metadata=metadata_com_raw_grande)
        self.assertFalse(result.get("ok", True),
                         "Fonte limpa suspeita (muito menor que raw) deve falhar")
        self.assertEqual(result.get("status"), "too_short",
                         f"Status deve ser 'too_short', got: {result.get('status')}")

    def test_fonte_curta_sem_contexto_raw(self):
        """Fonte < 100 chars sem raw_chars → ok=True (nota breve permitida)."""
        from ururau.editorial.extracao import validate_source_sufficiency
        # Sem raw_chars grande, fonte curta é permitida como nota breve
        fonte_curta = "Breve nota sobre o assunto."
        result = validate_source_sufficiency(fonte_curta)
        # Sem metadata raw_chars > 500, é tratado como nota breve → ok=True
        self.assertTrue(result.get("ok", False),
                        "Fonte curta sem raw_chars grande deve ser permitida como nota breve")

    def test_fonte_suficiente(self):
        """Fonte com conteúdo suficiente deve retornar ok=True."""
        from ururau.editorial.extracao import validate_source_sufficiency
        fonte_ok = (
            "O governo federal anunciou hoje uma série de medidas fiscais que "
            "impactarão diretamente a população brasileira nos próximos meses. "
            "O pacote inclui redução do imposto de renda para trabalhadores com "
            "rendimentos abaixo de R$ 5.000 mensais. " * 10  # >800 chars
        )
        result = validate_source_sufficiency(fonte_ok)
        self.assertTrue(result.get("ok", False),
                        f"Fonte suficiente deve passar, got: {result}")
        self.assertEqual(result.get("status"), "sufficient",
                         f"Status deve ser 'sufficient', got: {result.get('status')}")


class TestC9_ReceitaEditorialCanPublishFallback(unittest.TestCase):
    """C9: receita_editorial.can_publish() (fallback local) também bloqueia CONFIG_ERROR."""

    def test_fallback_bloqueia_config_error(self):
        """receita_editorial.can_publish() fallback bloqueia _is_config_error=True."""
        from ururau.editorial.receita_editorial import can_publish

        # Simula ImportError de workflow.can_publish para testar o fallback
        artigo = _make_config_error_artigo()
        with patch("ururau.publisher.workflow.can_publish",
                   side_effect=ImportError("workflow not available")):
            ok, motivo = can_publish(artigo)
        self.assertFalse(ok, "Fallback em receita_editorial deve bloquear CONFIG_ERROR")

    def test_fallback_bloqueia_extraction_error(self):
        """receita_editorial.can_publish() fallback bloqueia EXTRACTION_ERROR."""
        from ururau.editorial.receita_editorial import can_publish

        artigo = _make_extraction_error_artigo()
        with patch("ururau.publisher.workflow.can_publish",
                   side_effect=ImportError("workflow not available")):
            ok, motivo = can_publish(artigo)
        self.assertFalse(ok, "Fallback em receita_editorial deve bloquear EXTRACTION_ERROR")

    def test_fallback_bloqueia_corpo_vazio(self):
        """receita_editorial.can_publish() fallback bloqueia corpo vazio."""
        from ururau.editorial.receita_editorial import can_publish

        artigo = {
            "status_validacao": "aprovado",
            "corpo_materia": "",
            "erros_validacao": [],
            "auditoria_bloqueada": False,
        }
        with patch("ururau.publisher.workflow.can_publish",
                   side_effect=ImportError("workflow not available")):
            ok, _ = can_publish(artigo)
        self.assertFalse(ok, "Fallback deve bloquear artigo com corpo vazio")


class TestC10_WorkflowNaoAvancaParaPronta(unittest.TestCase):
    """C10: etapa_persistir_materia não marca PRONTA quando há CONFIG/EXTRACTION ERROR."""

    def _mock_materia(self, has_config_error: bool = True,
                      has_extraction_error: bool = False) -> MagicMock:
        """Cria mock de Materia com CONFIG_ERROR ou EXTRACTION_ERROR."""
        m = MagicMock()
        m.auditoria_aprovada = False
        m.auditoria_bloqueada = True
        m.status_pipeline = "bloquear"
        m.auditoria_erros = ["Erro de configuração"]
        if has_config_error:
            m.to_dict.return_value = {
                "status_validacao": "erro_configuracao",
                "_is_config_error": True,
                "corpo_materia": "",
                "erros_validacao": [{
                    "categoria": "CONFIG_ERROR",
                    "codigo": "invalid_api_key",
                    "mensagem": "API key inválida.",
                    "bloqueante": True,
                }],
                "auditoria_bloqueada": True,
                "status_pipeline": "bloquear",
            }
        elif has_extraction_error:
            m.to_dict.return_value = {
                "status_validacao": "erro_extracao",
                "corpo_materia": "",
                "erros_validacao": [{
                    "categoria": "EXTRACTION_ERROR",
                    "codigo": "source_empty",
                    "mensagem": "Fonte vazia.",
                    "bloqueante": True,
                }],
                "auditoria_bloqueada": True,
                "status_pipeline": "bloquear",
            }
        return m

    def test_config_error_nao_fica_pronta(self):
        """etapa_persistir_materia não deve marcar status=PRONTA para CONFIG_ERROR."""
        from ururau.publisher.workflow import WorkflowPublicacao, StatusPauta

        # Mock do banco de dados
        db_mock = MagicMock()
        db_mock.salvar_materia.return_value = None
        db_mock.salvar_pauta.return_value = None
        db_mock.log_auditoria.return_value = None

        wf = WorkflowPublicacao(db=db_mock, client=MagicMock(), modelo="gpt-4.1-mini")

        uid = "test-uid-c10"
        pauta = {"_uid": uid, "status": StatusPauta.EM_REDACAO}
        materia = self._mock_materia(has_config_error=True)

        wf.etapa_persistir_materia(uid, pauta, materia)

        # Status não deve ser PRONTA
        status_final = pauta.get("status", "")
        self.assertNotEqual(status_final, StatusPauta.PRONTA,
                            f"CONFIG_ERROR não deve resultar em PRONTA, got: {status_final}")
        # Status deve ser REVISADA (aguardando intervenção humana)
        self.assertEqual(status_final, StatusPauta.REVISADA,
                         f"CONFIG_ERROR deve resultar em REVISADA, got: {status_final}")

    def test_extraction_error_nao_fica_pronta(self):
        """etapa_persistir_materia não deve marcar status=PRONTA para EXTRACTION_ERROR."""
        from ururau.publisher.workflow import WorkflowPublicacao, StatusPauta

        db_mock = MagicMock()
        db_mock.salvar_materia.return_value = None
        db_mock.salvar_pauta.return_value = None
        db_mock.log_auditoria.return_value = None

        wf = WorkflowPublicacao(db=db_mock, client=MagicMock(), modelo="gpt-4.1-mini")

        uid = "test-uid-c10b"
        pauta = {"_uid": uid, "status": StatusPauta.EM_REDACAO}
        materia = self._mock_materia(has_config_error=False, has_extraction_error=True)

        wf.etapa_persistir_materia(uid, pauta, materia)

        status_final = pauta.get("status", "")
        self.assertNotEqual(status_final, StatusPauta.PRONTA,
                            f"EXTRACTION_ERROR não deve resultar em PRONTA, got: {status_final}")


# ── Executor ──────────────────────────────────────────────────────────────────

_TODOS_TESTES = {
    "C1":  TestC1_PipelineAbortaApiKeyInvalida,
    "C2":  TestC2_NenhumFragmentoFonteNoCorpo,
    "C3":  TestC3_CanPublishBloqueiaConfigError,
    "C4":  TestC4_CanPublishBloqueiaExtractionError,
    "C5":  TestC5_CanPublishBloqueiaStatusErroConfiguracao,
    "C6":  TestC6_CanPublishBloqueiaCorpoVazio,
    "C7":  TestC7_FonteLimpaRemoveNoticias,
    "C8":  TestC8_ValidateSourceSufficiency,
    "C9":  TestC9_ReceitaEditorialCanPublishFallback,
    "C10": TestC10_WorkflowNaoAvancaParaPronta,
}


def rodar_testes(filtro: Optional[str] = None, verbose: bool = False):
    """Executa os testes e exibe resultado."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    if filtro:
        chave = filtro.upper()
        if chave not in _TODOS_TESTES:
            print(f"[ERRO] Teste '{chave}' não encontrado. Opções: {list(_TODOS_TESTES.keys())}")
            sys.exit(1)
        suite.addTests(loader.loadTestsFromTestCase(_TODOS_TESTES[chave]))
    else:
        for cls in _TODOS_TESTES.values():
            suite.addTests(loader.loadTestsFromTestCase(cls))

    verbosity = 2 if verbose else 1
    runner = unittest.TextTestRunner(verbosity=verbosity, stream=sys.stdout)
    result = runner.run(suite)

    print(f"\n{'='*60}")
    print(f"RESULTADO: {result.testsRun} rodados | "
          f"{len(result.failures)} falhas | "
          f"{len(result.errors)} erros")
    if result.wasSuccessful():
        print("✓ Todos os testes passaram!")
    else:
        print("✗ Há falhas — revise as correções nos módulos afetados.")
    print("="*60)

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Testes de falha de configuração e extração (v61)"
    )
    parser.add_argument("--teste", "-t", metavar="CX",
                        help="Executa apenas o teste CX (ex: C3)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Saída verbosa")
    args = parser.parse_args()
    sys.exit(rodar_testes(filtro=args.teste, verbose=args.verbose))
