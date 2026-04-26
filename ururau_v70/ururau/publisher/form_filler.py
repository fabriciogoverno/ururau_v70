"""
publisher/form_filler.py — Preenchimento de formulário CMS via Playwright.
v8 — Canal automático e link da fonte:
     - Seleciona canal correto no select name="canais" com base em materia.canal
     - Preenche linkfonte com materia.link_origem (URL da notícia original)
     - Preenche nomefonte com materia.fonte_nome ou materia.nomefonte

v7 — Correções finais:
     - rascunho=True como padrão (salva como rascunho, não publica direto)
     - Converte \n\n em tags <p> antes de enviar ao CKEditor
     - Preenche name="marcarfoto" com "Não" (sem marca d'água)
     - Aguarda CKEditor inicializar antes de tentar setData()
     - Verifica se conteúdo foi de fato inserido com getData()
     - Fallback: injeta diretamente no textarea hidden do CKEditor
     - Fallback final: digita no iframe do CKEditor
     - Aguarda resposta pós-submit lendo mensagens de erro da página

CAMPOS DO CMS (confirmados pelo diagnóstico):
  name="assunto"       → retranca/assunto da matéria
  name="titulo"        → título SEO
  name="titulocapa"    → título de capa
  name="subtitulo"     → subtítulo / chapéu
  name="legenda"       → legenda da imagem
  name="conteudo"      → textarea + CKEditor 4
  name="img"           → upload da imagem (file input)
  name="creditosfoto"  → crédito da foto
  name="nomefonte"     → nome da fonte / agência
  name="linkfonte"     → link da fonte original
  name="tags"          → tags (texto livre)
  name="assinatura"    → assinatura da matéria
  name="canais"        → select de canal — preenchido automaticamente com materia.canal
  name="rss"           → select "cadastrar no RSS" — selecionar "sim"
  name="marcarfoto"    → select "Marcar foto?" — selecionar "Não" (sem marca d'água)
  name="status"        → checkbox "Salvar como rascunho" — MARCAR por padrão (rascunho=True)
  name="enviarCadastro"→ botão <button type="submit">Cadastrar</button>

LOGIN:
  - Polling de até 30s pelo campo de usuário.
  - Fallback: any input[type=text]:first-of-type.
  - Detecta navegação por URL change.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from ururau.config.settings import (
    HEADLESS,
    SLOW_MO,
    SITE_LOGIN_URL,
    SITE_NOVA_URL,
    ASSINATURA_FIXA,
)

if TYPE_CHECKING:
    from playwright.async_api import Page
    from ururau.core.models import Materia, ImagemDados


# ── Conversão de texto para HTML ─────────────────────────────────────────────

def _texto_para_html(texto: str) -> str:
    """
    Converte texto com quebras de parágrafo (\n\n) em HTML com tags <p>.
    Garante que o CKEditor renderize parágrafos corretamente.

    Regras:
    - Parágrafos separados por \n\n → cada um vira <p>...</p>
    - Intertítulos em MAIÚSCULAS ou com ** → vira <h2>
    - Links deixados como texto
    - HTML existente passado sem modificação
    """
    import re as _re

    # Se já tem tags HTML, retorna sem alterar
    if "<p>" in texto or "<h2>" in texto or "<br" in texto:
        return texto

    paragrafos = _re.split(r"\n\n+", texto.strip())
    partes = []
    for p in paragrafos:
        p = p.strip()
        if not p:
            continue
        # Subtítulo: linha curta em maiúsculas ou com **
        if (p.startswith("**") and p.endswith("**") and len(p) < 120):
            h = p.strip("*").strip()
            partes.append(f"<h2>{h}</h2>")
        elif (p.isupper() and 4 < len(p) < 100):
            partes.append(f"<h2>{p.title()}</h2>")
        else:
            # Newlines simples dentro do parágrafo viram <br>
            p_html = p.replace("\n", "<br>\n")
            partes.append(f"<p>{p_html}</p>")

    return "\n".join(partes)


# ── Seletores de login ────────────────────────────────────────────────────────

_SEL_USER = [
    'input[name="log"]',
    'input[name="username"]',
    'input[name="user_login"]',
    'input#user_login',
    'input[type="email"]',
    'input[type="text"]:first-of-type',
]

_SEL_PASS = [
    'input[name="pwd"]',
    'input[name="password"]',
    'input[name="user_pass"]',
    'input#user_pass',
    'input[type="password"]',
]

_SEL_BTN = [
    'text="ACESSAR"',
    'text="Acessar"',
    'text="ENTRAR"',
    'text="Entrar"',
    'text="Login"',
    'text="Log In"',
    'input[value="ACESSAR"]',
    'input[value="Acessar"]',
    'input[type="submit"]',
    'button[type="submit"]',
    'form button',
    'button',
]

_PASTA_DEBUG = Path("prints")


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _screenshot_debug(page: "Page", nome: str):
    """Salva screenshot para diagnóstico de falhas."""
    try:
        _PASTA_DEBUG.mkdir(exist_ok=True)
        caminho = _PASTA_DEBUG / f"debug_{nome}_{int(time.time())}.png"
        await page.screenshot(path=str(caminho))
        print(f"[FORM] Screenshot salvo: {caminho}")
    except Exception:
        pass


async def _aguardar_campo_usuario(page: "Page", timeout_total: int = 30) -> bool:
    """
    Aguarda campo de usuário aparecer:
    1. wait_for_selector nativo (30s)
    2. Polling manual como fallback
    """
    sels_combinados = ', '.join(_SEL_USER[:5])
    try:
        await page.wait_for_selector(sels_combinados,
                                     timeout=timeout_total * 1000,
                                     state="visible")
        print("[FORM] Campo de usuário encontrado (wait_for_selector).")
        return True
    except Exception as e:
        print(f"[FORM] wait_for_selector falhou ({e}), iniciando polling...")

    loop     = asyncio.get_event_loop()
    deadline = loop.time() + timeout_total
    while loop.time() < deadline:
        for sel in _SEL_USER:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    print(f"[FORM] Campo encontrado via polling: {sel}")
                    return True
            except Exception:
                pass
        await asyncio.sleep(0.8)

    print("[FORM] Tempo esgotado aguardando campo de usuário.")
    return False


async def _fill_first(page: "Page", seletores: list[str], valor: str) -> str | None:
    """Preenche o primeiro seletor visível. Retorna seletor usado ou None."""
    for sel in seletores:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.fill(valor)
                return sel
        except Exception:
            continue
    return None


async def _preencher_campo(page: "Page", name: str, valor: str,
                            tag: str = "input") -> bool:
    """Preenche input/textarea pelo atributo name=. Retorna True se OK."""
    if not valor:
        return False
    seletor = f'{tag}[name="{name}"], input[name="{name}"]' if tag == "textarea" else \
              f'input[name="{name}"], textarea[name="{name}"]'
    try:
        el = await page.query_selector(seletor)
        if el:
            await el.fill(str(valor))
            return True
        print(f"[FORM] Campo '{name}' não encontrado.")
    except Exception as e:
        print(f"[FORM] Erro campo '{name}': {e}")
    return False


async def _select_campo(page: "Page", name: str, valor: str) -> bool:
    """Seleciona opção em <select name=...>. Retorna True se OK."""
    if not valor:
        return False
    try:
        el = await page.query_selector(f'select[name="{name}"]')
        if el:
            await el.select_option(valor)
            return True
        print(f"[FORM] Select '{name}' não encontrado.")
    except Exception as e:
        print(f"[FORM] Erro select '{name}': {e}")
    return False


# ── Login ─────────────────────────────────────────────────────────────────────

async def fazer_login(page: "Page", usuario: str, senha: str,
                      url_login: str = SITE_LOGIN_URL) -> bool:
    """Login robusto v5 — aguarda até 30s, detecta navegação por URL change."""
    try:
        print(f"[FORM] Acessando: {url_login}")
        await page.goto(url_login, wait_until="domcontentloaded", timeout=45000)
        try:
            await page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass
        print(f"[FORM] Página carregada. URL: {page.url}")

        if not await _aguardar_campo_usuario(page, timeout_total=30):
            await _screenshot_debug(page, "sem_campo_usuario")
            return False

        sel_u = await _fill_first(page, _SEL_USER, usuario)
        if not sel_u:
            await _screenshot_debug(page, "sem_usuario")
            return False
        print(f"[FORM] Usuário preenchido via: {sel_u}")

        sel_p = await _fill_first(page, _SEL_PASS, senha)
        if not sel_p:
            await _screenshot_debug(page, "sem_senha")
            return False
        print(f"[FORM] Senha preenchida via: {sel_p}")

        await page.wait_for_timeout(400)
        url_antes = page.url

        for sel in _SEL_BTN:
            try:
                el = await page.query_selector(sel)
                if not el:
                    continue
                try:
                    visivel = await el.is_visible()
                except Exception:
                    visivel = False
                if not visivel:
                    continue

                print(f"[FORM] Clicando: {sel}")
                await el.click(timeout=8000)

                for _ in range(16):
                    await asyncio.sleep(0.5)
                    if page.url != url_antes:
                        break

                if page.url != url_antes:
                    print(f"[FORM] Navegou para: {page.url}")
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=15000)
                    except Exception:
                        pass
                    url_nova = page.url
                    if "login" not in url_nova.lower():
                        print("[FORM] Login realizado com sucesso.")
                        return True
                    for sel_err in [".error", ".mensagem", "#login_error", ".alert"]:
                        try:
                            el_err = await page.query_selector(sel_err)
                            if el_err:
                                txt = await el_err.inner_text()
                                if txt.strip():
                                    print(f"[FORM] Erro CMS: {txt.strip()[:120]}")
                                    break
                        except Exception:
                            pass
                    await _screenshot_debug(page, "login_falhou")
                    return False

            except Exception as e:
                if "context was destroyed" in str(e) or "navigation" in str(e).lower():
                    await asyncio.sleep(1)
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=15000)
                    except Exception:
                        pass
                    url_nova = page.url
                    if "login" not in url_nova.lower() and url_nova != url_antes:
                        print(f"[FORM] Login OK (navegação detectada): {url_nova}")
                        return True
                continue

        # Fallback JS submit
        try:
            await page.evaluate(
                "() => { const f = document.querySelector('form'); if(f) f.submit(); }")
            await asyncio.sleep(4)
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=12000)
            except Exception:
                pass
            if page.url != url_antes and "login" not in page.url.lower():
                print(f"[FORM] Login OK via JS: {page.url}")
                return True
        except Exception:
            pass

        await _screenshot_debug(page, "login_final_falhou")
        print(f"[FORM] Login falhou. URL final: {page.url}")
        return False

    except Exception as e:
        print(f"[FORM] Erro crítico no login: {e}")
        try:
            await _screenshot_debug(page, "login_excecao")
        except Exception:
            pass
        return False


# ── Diagnóstico do formulário ─────────────────────────────────────────────────

async def _diagnosticar_formulario(page: "Page"):
    """Salva screenshot + dump HTML + lista de campos para diagnóstico."""
    await _screenshot_debug(page, "formulario")
    try:
        _PASTA_DEBUG.mkdir(exist_ok=True)
        html = await page.content()
        dump_path = _PASTA_DEBUG / f"formulario_html_{int(time.time())}.html"
        dump_path.write_text(html[:80000], encoding="utf-8", errors="replace")
        print(f"[FORM] HTML do formulário salvo em: {dump_path}")

        info = await page.evaluate("""() => {
            const info = {};
            info.inputs = Array.from(document.querySelectorAll('input,textarea,select'))
                .map(el => ({tag: el.tagName, id: el.id, name: el.name, type: el.type,
                             class: el.className.substring(0,60)}))
                .slice(0, 50);
            info.buttons = Array.from(document.querySelectorAll('button,input[type=submit]'))
                .map(el => ({tag: el.tagName, id: el.id, name: el.name,
                             value: el.value, text: el.innerText?.substring(0,40),
                             type: el.type}))
                .slice(0, 20);
            info.tinymce   = typeof tinyMCE !== 'undefined';
            info.ckeditor  = typeof CKEDITOR !== 'undefined';
            info.ckeditor5 = typeof ClassicEditor !== 'undefined';
            info.quill     = !!document.querySelector('.ql-editor');
            return info;
        }""")

        print("[FORM] === DIAGNÓSTICO DO FORMULÁRIO ===")
        print(f"[FORM] TinyMCE: {info.get('tinymce')} | CKEditor: {info.get('ckeditor')} | CKEditor5: {info.get('ckeditor5')} | Quill: {info.get('quill')}")
        print("[FORM] Inputs/Textareas:")
        for el in info.get("inputs", []):
            print(f"[FORM]   <{el['tag']}> id={el['id']!r} name={el['name']!r} type={el['type']!r} class={el['class']!r}")
        print("[FORM] Botões:")
        for el in info.get("buttons", []):
            print(f"[FORM]   <{el['tag']}> id={el['id']!r} name={el['name']!r} value={el['value']!r} text={el['text']!r} type={el['type']!r}")
        print("[FORM] === FIM DO DIAGNÓSTICO ===")
    except Exception as e:
        print(f"[FORM] Diagnóstico parcial: {e}")


# ── Preenchimento de conteúdo ─────────────────────────────────────────────────

async def _aguardar_ckeditor(page: "Page", timeout_s: int = 15) -> bool:
    """
    Aguarda o CKEditor 4 estar pronto para uso.
    O CKEditor carrega assincronamente — pode não estar pronto logo após networkidle.
    """
    loop     = asyncio.get_event_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        try:
            pronto = await page.evaluate("""() => {
                if (typeof CKEDITOR === 'undefined') return false;
                for (const name in CKEDITOR.instances) {
                    const ed = CKEDITOR.instances[name];
                    if (ed && ed.status === 'ready') return true;
                }
                return false;
            }""")
            if pronto:
                print("[FORM] CKEditor 4 pronto.")
                return True
        except Exception:
            pass
        await asyncio.sleep(0.5)
    print("[FORM] CKEditor 4 não ficou pronto no tempo esperado.")
    return False


async def _preencher_conteudo(page: "Page", conteudo: str) -> bool:
    """
    Preenche o campo de conteúdo do CMS Ururau (CKEditor 4 confirmado).

    Estratégia:
    1. Aguarda CKEditor ficar 'ready' (até 15s)
    2. setData() via API do CKEditor
    3. Verifica com getData() se o conteúdo foi inserido
    4. Fallback: injeta no textarea hidden e dispara evento change
    5. Fallback: digita diretamente no iframe body do CKEditor
    6. Fallback: qualquer textarea visível
    """
    # Aguarda CKEditor inicializar completamente
    ck_pronto = await _aguardar_ckeditor(page, timeout_s=15)

    if ck_pronto:
        # Estratégia 1: setData() via API + verificação
        try:
            resultado = await page.evaluate("""(c) => {
                for (const name in CKEDITOR.instances) {
                    const ed = CKEDITOR.instances[name];
                    if (ed && ed.status === 'ready') {
                        ed.setData(c);
                        // Dispara evento para o CMS saber que foi alterado
                        ed.fire('change');
                        ed.updateElement();
                        return {ok: true, name: name, len: ed.getData().length};
                    }
                }
                return {ok: false};
            }""", conteudo)

            if resultado.get("ok") and resultado.get("len", 0) > 10:
                print(f"[FORM] CKEditor setData OK — instância: {resultado['name']}, "
                      f"{resultado['len']} chars inseridos.")
                return True
            elif resultado.get("ok"):
                print(f"[FORM] CKEditor setData chamado mas getData() retornou {resultado.get('len')} chars.")
        except Exception as e:
            print(f"[FORM] CKEditor setData erro: {e}")

        # Estratégia 2: força via updateElement + textarea hidden
        try:
            injetado = await page.evaluate("""(c) => {
                // Injeta no textarea hidden que o CKEditor mantém sincronizado
                const ta = document.querySelector('textarea[name="conteudo"]');
                if (ta) {
                    // Remove o CKEditor e usa o textarea diretamente
                    if (typeof CKEDITOR !== 'undefined') {
                        for (const name in CKEDITOR.instances) {
                            const ed = CKEDITOR.instances[name];
                            if (ed) {
                                ed.setData(c);
                                ed.updateElement();
                                ta.value = c;
                                ta.dispatchEvent(new Event('input', {bubbles: true}));
                                ta.dispatchEvent(new Event('change', {bubbles: true}));
                            }
                        }
                    }
                    return ta.value.length;
                }
                return 0;
            }""", conteudo)
            if injetado and injetado > 10:
                print(f"[FORM] Conteúdo via CKEditor + textarea sync: {injetado} chars.")
                return True
        except Exception as e:
            print(f"[FORM] Sync textarea: {e}")

    # Estratégia 3: iframe body do CKEditor (digitação direta)
    try:
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            try:
                # CKEditor cria um iframe com body contenteditable
                body = await frame.query_selector("body")
                if body:
                    is_editable = await frame.evaluate(
                        "() => document.body.getAttribute('contenteditable') === 'true' || "
                        "document.designMode === 'on'")
                    if is_editable:
                        # Seleciona tudo e digita
                        await body.click()
                        await frame.evaluate("() => document.execCommand('selectAll')")
                        await frame.evaluate("(c) => document.execCommand('insertHTML', false, c)",
                                             conteudo)
                        # Sincroniza textarea
                        await page.evaluate("""(c) => {
                            const ta = document.querySelector('textarea[name=\"conteudo\"]');
                            if (ta) { ta.value = c; }
                            if (typeof CKEDITOR !== 'undefined') {
                                for (const n in CKEDITOR.instances)
                                    CKEDITOR.instances[n].updateElement();
                            }
                        }""", conteudo)
                        print(f"[FORM] Conteúdo via iframe CKEditor (execCommand).")
                        return True
            except Exception:
                pass
    except Exception:
        pass

    # Estratégia 4: TinyMCE
    try:
        tmce_ok = await page.evaluate("""(c) => {
            if (typeof tinyMCE !== 'undefined') {
                const ed = tinyMCE.activeEditor ||
                           (tinyMCE.editors && Object.values(tinyMCE.editors)[0]);
                if (ed) { ed.setContent(c); return true; }
            }
            return false;
        }""", conteudo)
        if tmce_ok:
            print("[FORM] Conteúdo via TinyMCE.")
            return True
    except Exception:
        pass

    # Estratégia 5: textarea direto (quando não há editor rico)
    for sel in [
        'textarea[name="conteudo"]',
        'textarea#conteudo',
        'textarea[name="content"]',
        'textarea',
    ]:
        try:
            el = await page.query_selector(sel)
            if el:
                await el.fill(conteudo)
                print(f"[FORM] Conteúdo via textarea direto: {sel}")
                return True
        except Exception:
            pass

    print("[FORM] ERRO: nenhuma estratégia de conteúdo funcionou.")
    return False


# ── Publicação ────────────────────────────────────────────────────────────────

async def preencher_e_publicar(
    materia:  "Materia",
    imagem:   Optional["ImagemDados"],
    page:     "Page",
    rascunho: bool = True,
) -> bool:
    """
    Preenche o formulário do CMS Ururau e clica em Cadastrar.

    Campos mapeados (confirmados por diagnóstico real):
      assunto, titulo, titulocapa, subtitulo, legenda, conteudo,
      img (file), creditosfoto, nomefonte, linkfonte, tags, assinatura,
      rss (select → "sim"), marcarfoto (select → "Não"), status (checkbox rascunho),
      enviarCadastro (submit).

    rascunho=True (padrão) → marca checkbox "Salvar como rascunho" (NÃO publica).
    rascunho=False → deixa desmarcado (publica imediatamente).

    IMPORTANTE: Por segurança, o padrão é rascunho=True.
    Para publicar direto, chame com rascunho=False.
    """
    try:
        print(f"[FORM] Acessando formulário: {SITE_NOVA_URL}")
        await page.goto(SITE_NOVA_URL, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        await page.wait_for_timeout(1200)
        print(f"[FORM] Formulário: {page.url}")

        # Diagnóstico automático (screenshot + dump HTML)
        await _diagnosticar_formulario(page)

        # ── Campos textuais — seletores name= exatos do CMS ──────────────────

        # Assunto / Retranca
        assunto = (getattr(materia, "retranca", "") or "").strip()
        if not assunto:
            assunto = (getattr(materia, "canal", "") or "Geral")
        await _preencher_campo(page, "assunto", assunto)

        # Título SEO (obrigatório)
        titulo = (getattr(materia, "titulo", "") or "").strip()
        await _preencher_campo(page, "titulo", titulo)

        # Título de Capa
        titulo_capa = (getattr(materia, "titulo_capa", "") or "").strip()
        if not titulo_capa:
            titulo_capa = titulo  # fallback: usa título SEO
        await _preencher_campo(page, "titulocapa", titulo_capa)

        # Subtítulo / Legenda Curta (OBRIGATÓRIO no CMS Ururau)
        # Campo name="subtitulo" — sempre deve ter um valor
        subtitulo = (getattr(materia, "subtitulo", "") or "").strip()
        if not subtitulo:
            # Gera legenda curta a partir do resumo_curto ou início do conteúdo
            subtitulo = (getattr(materia, "resumo_curto", "") or "").strip()
        if not subtitulo:
            # Último fallback: primeiros 120 chars do conteúdo sem HTML
            import re as _re
            conteudo_raw = (getattr(materia, "conteudo", "") or "")
            subtitulo = _re.sub(r"<[^>]+>", " ", conteudo_raw)
            subtitulo = _re.sub(r"\s+", " ", subtitulo).strip()[:120]
        if not subtitulo:
            subtitulo = titulo[:120]  # extremo fallback
        await _preencher_campo(page, "subtitulo", subtitulo)
        print(f"[FORM] Subtítulo/legenda curta: {subtitulo[:60]!r}")

        # Tags
        tags = (getattr(materia, "tags", "") or "").strip()
        if tags:
            await _preencher_campo(page, "tags", tags)

        # Assinatura
        assinatura = (ASSINATURA_FIXA or getattr(materia, "assinatura", "") or "").strip()
        if assinatura:
            await _preencher_campo(page, "assinatura", assinatura)

        # ── Aguarda CKEditor antes de preencher conteúdo ─────────────────────
        # O CKEditor carrega assincronamente — esperar é fundamental
        print("[FORM] Aguardando CKEditor inicializar...")
        await page.wait_for_timeout(2000)  # pausa extra para garantir init

        # ── Conteúdo (CKEditor 4 ou fallback) ────────────────────────────────
        # Converte texto com \n\n em HTML com <p> antes de enviar ao CKEditor
        conteudo_raw = materia.conteudo or ""
        conteudo_html = _texto_para_html(conteudo_raw)
        print(f"[FORM] Conteúdo: {len(conteudo_raw)} chars → HTML: {len(conteudo_html)} chars")
        conteudo_ok = await _preencher_conteudo(page, conteudo_html)
        if not conteudo_ok:
            # v69: ABORTA imediatamente. Nunca submete CMS sem conteudo confirmado.
            print("[FORM] ABORTANDO (v69): conteudo nao foi preenchido no CKEditor/textarea.")
            await _screenshot_debug(page, "v69_conteudo_falhou_abort")
            return False

        # ── Legenda da foto (OBRIGATÓRIO — independente de ter imagem) ───────────
        # O CMS exige legenda mesmo sem imagem. Sempre preenche com fallback.
        import re as _re
        legenda = (getattr(materia, "legenda", "") or "").strip()
        if not legenda:
            # Tenta título de capa ou subtítulo
            legenda = titulo_capa.strip() or subtitulo[:100].strip()
        if not legenda:
            # Fallback: primeiros 100 chars do título
            legenda = titulo[:100].strip()
        await _preencher_campo(page, "legenda", legenda)
        print(f"[FORM] Legenda: {legenda[:60]!r}")

        # Crédito da foto — padrão "Reprodução" se não informado
        credito_img = ""
        if imagem:
            credito_img = (getattr(imagem, "credito_foto", "") or "").strip()
        if not credito_img:
            credito_img = "Reprodução"
        await _preencher_campo(page, "creditosfoto", credito_img)

        # ── Imagem (upload do arquivo) ────────────────────────────────────────
        if imagem and imagem.caminho_imagem:
            p = Path(imagem.caminho_imagem)
            if not p.exists():
                p = Path("imagens") / p.name
            if p.exists():
                try:
                    el_file = await page.query_selector('input[name="img"], input[type="file"]')
                    if el_file:
                        await el_file.set_input_files(str(p))
                        await page.wait_for_timeout(1500)
                        print(f"[FORM] Imagem: {p.name}")
                    else:
                        print("[FORM] Input de imagem não encontrado.")
                except Exception as e:
                    print(f"[FORM] Upload imagem: {e}")
            else:
                print(f"[FORM] Imagem não encontrada: {imagem.caminho_imagem}")

        # ── Fonte de origem ───────────────────────────────────────────────────
        # nomefonte: usa fonte_nome se disponível, senão nomefonte, senão "Portal Ururau"
        nomefonte = (
            getattr(materia, "fonte_nome", "") or
            getattr(materia, "nomefonte", "") or ""
        ).strip()
        # linkfonte: usa o link original da notícia (link_origem), não um campo interno
        linkfonte = (
            getattr(materia, "link_origem", "") or
            getattr(materia, "linkfonte", "") or ""
        ).strip()
        if nomefonte:
            await _preencher_campo(page, "nomefonte", nomefonte)
            print(f"[FORM] nomefonte: {nomefonte[:80]!r}")
        if linkfonte:
            await _preencher_campo(page, "linkfonte", linkfonte)
            print(f"[FORM] linkfonte: {linkfonte[:80]!r}")

        # ── Canal editorial — seleciona no select name="canais" ───────────────
        # Usa materia.canal para selecionar o canal correto no CMS
        canal_materia = (getattr(materia, "canal", "") or "Brasil e Mundo").strip()
        try:
            canal_selecionado = False
            sel_canais = await page.query_selector('select[name="canais"]')
            if sel_canais:
                # Tenta selecionar pelo texto exato do canal
                try:
                    await sel_canais.select_option(label=canal_materia)
                    canal_selecionado = True
                    print(f"[FORM] Canal selecionado (label exato): {canal_materia!r}")
                except Exception:
                    pass

                if not canal_selecionado:
                    # Tenta por valor (pode ser igual ao texto)
                    try:
                        await sel_canais.select_option(value=canal_materia)
                        canal_selecionado = True
                        print(f"[FORM] Canal selecionado (value): {canal_materia!r}")
                    except Exception:
                        pass

                if not canal_selecionado:
                    # Busca opção que contenha o canal (parcial, case-insensitive)
                    canal_js = await page.evaluate("""(canal) => {
                        const sel = document.querySelector('select[name="canais"]');
                        if (!sel) return null;
                        // Tenta match exato primeiro
                        for (const opt of sel.options) {
                            if (opt.text.trim() === canal || opt.value === canal) {
                                sel.value = opt.value;
                                sel.dispatchEvent(new Event('change'));
                                return opt.text.trim();
                            }
                        }
                        // Tenta match parcial (case-insensitive)
                        const lc = canal.toLowerCase();
                        for (const opt of sel.options) {
                            if (opt.text.toLowerCase().includes(lc) ||
                                lc.includes(opt.text.toLowerCase())) {
                                sel.value = opt.value;
                                sel.dispatchEvent(new Event('change'));
                                return opt.text.trim();
                            }
                        }
                        // Log das opções disponíveis para diagnóstico
                        const opts = Array.from(sel.options).map(o => o.text.trim());
                        return 'OPTS:' + opts.join('|');
                    }""", canal_materia)
                    if canal_js and not canal_js.startswith("OPTS:"):
                        canal_selecionado = True
                        print(f"[FORM] Canal selecionado (JS parcial): {canal_js!r}")
                    elif canal_js and canal_js.startswith("OPTS:"):
                        print(f"[FORM] Canal '{canal_materia}' não encontrado. Opções disponíveis: {canal_js[5:]}")
            else:
                print("[FORM] Select 'canais' não encontrado no formulário.")
        except Exception as e:
            print(f"[FORM] Seleção de canal: {e}")

        # ── RSS — seleciona "sim" ─────────────────────────────────────────────
        try:
            rss_ok = await _select_campo(page, "rss", "sim")
            if rss_ok:
                print("[FORM] RSS selecionado: sim")
            else:
                # Tenta por valor numérico ou texto
                await page.evaluate("""() => {
                    const sel = document.querySelector('select[name="rss"]');
                    if (!sel) return;
                    // Tenta encontrar opção "sim" por texto
                    for (const opt of sel.options) {
                        if (opt.text.toLowerCase().includes('sim') ||
                            opt.value.toLowerCase() === 'sim' ||
                            opt.value === '1') {
                            sel.value = opt.value;
                            sel.dispatchEvent(new Event('change'));
                            return;
                        }
                    }
                }""")
                print("[FORM] RSS: seleção alternativa aplicada.")
        except Exception as e:
            print(f"[FORM] RSS select: {e}")

        # ── Marcar foto — seleciona "Não" para desativar marca d'água ───────────
        # name="marcarfoto" → sempre selecionar "Não"
        try:
            mf_ok = False
            mf_el = await page.query_selector('select[name="marcarfoto"]')
            if mf_el:
                # Tenta os valores mais comuns: "nao", "Não", "0", "2"
                for val in ["nao", "Não", "não", "0", "2", "n"]:
                    try:
                        await mf_el.select_option(val)
                        mf_ok = True
                        print(f"[FORM] marcarfoto: selecionado '{val}'")
                        break
                    except Exception:
                        pass
                if not mf_ok:
                    # Fallback: seleciona a opção que contém "não" no texto
                    await page.evaluate("""() => {
                        const sel = document.querySelector('select[name="marcarfoto"]');
                        if (!sel) return;
                        for (const opt of sel.options) {
                            const t = opt.text.toLowerCase();
                            if (t.includes('n') && !t.includes('sim') && !t.includes('s')) {
                                sel.value = opt.value;
                                sel.dispatchEvent(new Event('change'));
                                return;
                            }
                        }
                        // Se não achou, seleciona a ÚLTIMA opção (geralmente "Não")
                        if (sel.options.length > 1) {
                            sel.selectedIndex = sel.options.length - 1;
                            sel.dispatchEvent(new Event('change'));
                        }
                    }""")
                    print("[FORM] marcarfoto: fallback JS aplicado.")
            else:
                print("[FORM] marcarfoto: campo não encontrado (pode não existir no CMS).")
        except Exception as e:
            print(f"[FORM] marcarfoto: {e}")

        # ── Rascunho — controla o checkbox name="status" ──────────────────────
        # MARCAR = salvar como rascunho (não publica)
        # DEIXAR DESMARCADO = publicar imediatamente
        try:
            cb_status = await page.query_selector('input[name="status"][type="checkbox"]')
            if cb_status:
                marcado = await cb_status.is_checked()
                if rascunho and not marcado:
                    await cb_status.check()
                    print("[FORM] Rascunho: marcado (não publica agora).")
                elif not rascunho and marcado:
                    await cb_status.uncheck()
                    print("[FORM] Rascunho: desmarcado (publicará).")
                else:
                    estado = "marcado (rascunho)" if marcado else "desmarcado (publica)"
                    print(f"[FORM] Checkbox status: {estado} — sem alteração.")
            else:
                print("[FORM] Checkbox status não encontrado.")
        except Exception as e:
            print(f"[FORM] Checkbox status: {e}")

        # ── v67 Pre-submit fail-safe ─────────────────────────────────────────
        # Aborta antes do Cadastrar se titulo ou corpo nao foram preenchidos.
        try:
            presub = await page.evaluate("""() => {
                const titulo = (document.querySelector('input[name="titulo"]') || {}).value || '';
                const ta = document.querySelector('textarea[name="conteudo"]');
                const conteudoTA = ta ? ta.value : '';
                let conteudoCK = '';
                if (typeof CKEDITOR !== 'undefined') {
                    for (const n in CKEDITOR.instances) {
                        try { conteudoCK = CKEDITOR.instances[n].getData(); break; } catch(_){}
                    }
                }
                return {
                    titulo_len:   titulo.trim().length,
                    conteudoTA:   conteudoTA.trim().length,
                    conteudoCK:   conteudoCK.trim().length,
                };
            }""")
            tit_len = presub.get("titulo_len", 0)
            ck_len  = presub.get("conteudoCK", 0)
            ta_len  = presub.get("conteudoTA", 0)
            corpo_len = max(ck_len, ta_len)
            print(f"[FORM] PRE-SUBMIT v67: titulo={tit_len} chars, corpo CK={ck_len} TA={ta_len}")
            if tit_len < 10:
                print("[FORM] ABORTANDO: titulo nao preenchido (< 10 chars).")
                await _screenshot_debug(page, "presubmit_titulo_vazio")
                return False
            if corpo_len < 100:
                print("[FORM] ABORTANDO: corpo nao preenchido (< 100 chars).")
                await _screenshot_debug(page, "presubmit_corpo_vazio")
                return False
        except Exception as _e:
            print(f"[FORM] Pre-submit check (v67) falhou: {_e}")

        # ── Botão Cadastrar ───────────────────────────────────────────────────
        await page.wait_for_timeout(600)
        url_antes = page.url

        cadastrou = False

        # Seletor exato do CMS (confirmado pelo diagnóstico)
        for sel in [
            'button[name="enviarCadastro"]',
            'button[type="submit"][name="enviarCadastro"]',
            'button[type="submit"]:has-text("Cadastrar")',
            'button:has-text("Cadastrar")',
            'text="Cadastrar"',
            'button[type="submit"]',
        ]:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.click()
                    print(f"[FORM] Botão cadastrar clicado: {sel}")
                    cadastrou = True
                    break
            except Exception:
                pass

        if not cadastrou:
            # Último recurso: JS click
            try:
                res = await page.evaluate("""() => {
                    const b = document.querySelector('button[name="enviarCadastro"]') ||
                              document.querySelector('button[type="submit"]') ||
                              document.querySelector('input[type="submit"]');
                    if (b) { b.click(); return b.innerText || b.value || 'ok'; }
                    return null;
                }""")
                if res:
                    print(f"[FORM] Cadastrar via JS: {res!r}")
                    cadastrou = True
            except Exception as e:
                print(f"[FORM] JS click cadastrar: {e}")

        if not cadastrou:
            await _screenshot_debug(page, "sem_botao_cadastrar")
            print("[FORM] ERRO: botão Cadastrar não encontrado.")
            return False

        # Aguarda processamento — tenta detectar mudança de URL OU mensagem de sucesso
        # v62: detecta "Notícia adicionada com sucesso" mesmo quando URL não muda
        # (Ururau CMS pode limpar form e exibir overlay sem redirecionar).
        print("[FORM] Aguardando resposta do servidor...")
        url_final = page.url
        sucesso_por_msg = False
        for _ in range(30):  # até 15s aguardando mudança
            await asyncio.sleep(0.5)
            url_final = page.url
            if url_final != url_antes:
                break
            # v62: detecta mensagem de sucesso do CMS Ururau ANTES de URL mudar
            try:
                _msg = await page.evaluate("""() => {
                    const txt = (document.body && document.body.innerText) || '';
                    const sucesso_patterns = [
                        /Ok!\\s*Not[ií]cia\\s+adicionada\\s+com\\s+sucesso/i,
                        /Not[ií]cia\\s+adicionada\\s+com\\s+sucesso/i,
                        /salv[ao]\\s+com\\s+sucesso/i,
                        /cadastrad[ao]\\s+com\\s+sucesso/i,
                    ];
                    for (const p of sucesso_patterns) {
                        if (p.test(txt)) return true;
                    }
                    return false;
                }""")
                if _msg:
                    sucesso_por_msg = True
                    break
            except Exception:
                pass

        print(f"[FORM] URL após cadastrar: {url_final}")

        if url_final != url_antes or sucesso_por_msg:
            # URL mudou OU mensagem de sucesso detectada — sucesso!
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
            if sucesso_por_msg:
                print("[FORM] ✓ Mensagem 'Notícia adicionada com sucesso' detectada!")
            print("[FORM] ✓ Cadastrado com sucesso!")
            return True

        # URL não mudou — lê mensagens de erro/sucesso da página
        try:
            diagnostico = await page.evaluate("""() => {
                // Mensagens de erro/sucesso mais comuns
                const sels_erro = [
                    '.alert', '.alert-danger', '.alert-error', '.error',
                    '.mensagem', '.msg', '.notice', '.aviso',
                    '[class*="erro"]', '[class*="error"]', '[class*="alert"]',
                    '#mensagem', '.feedback', 'p.error', 'div.error',
                ];
                const sels_ok = [
                    '.alert-success', '.success', '.ok', '.mensagem-ok',
                    '[class*="success"]', '[class*="sucesso"]',
                ];
                const msgs = [];
                for (const s of sels_erro) {
                    const el = document.querySelector(s);
                    if (el && el.innerText && el.innerText.trim()) {
                        msgs.push({tipo: 'ERRO', texto: el.innerText.trim().substring(0, 200)});
                    }
                }
                for (const s of sels_ok) {
                    const el = document.querySelector(s);
                    if (el && el.innerText && el.innerText.trim()) {
                        msgs.push({tipo: 'OK', texto: el.innerText.trim().substring(0, 200)});
                    }
                }
                // Verifica campos obrigatórios com validação HTML5
                const invalidos = Array.from(document.querySelectorAll(':invalid'))
                    .map(el => ({name: el.name, type: el.type, msg: el.validationMessage}))
                    .slice(0, 10);
                // Verifica conteúdo do CKEditor
                let conteudoCK = '';
                if (typeof CKEDITOR !== 'undefined') {
                    for (const n in CKEDITOR.instances) {
                        conteudoCK = CKEDITOR.instances[n].getData();
                        break;
                    }
                }
                // Conteúdo da textarea
                const ta = document.querySelector('textarea[name="conteudo"]');
                const conteudoTA = ta ? ta.value : '';
                return {
                    msgs,
                    invalidos,
                    conteudoCK_len: conteudoCK.length,
                    conteudoTA_len: conteudoTA.length,
                    titulo: (document.querySelector('input[name="titulo"]') || {}).value || '',
                };
            }""")

            print(f"[FORM] === DIAGNÓSTICO PÓS-SUBMIT ===")
            print(f"[FORM] Título no form: {diagnostico.get('titulo', '')[:60]!r}")
            print(f"[FORM] Conteúdo CKEditor: {diagnostico.get('conteudoCK_len', 0)} chars")
            print(f"[FORM] Conteúdo textarea: {diagnostico.get('conteudoTA_len', 0)} chars")
            for m in diagnostico.get("msgs", []):
                print(f"[FORM] [{m['tipo']}] {m['texto']}")
            for inv in diagnostico.get("invalidos", []):
                print(f"[FORM] [INVÁLIDO] name={inv['name']!r} | {inv['msg']}")
            print(f"[FORM] ===================================")

            # Sucesso se encontrou msg OK
            for m in diagnostico.get("msgs", []):
                if m["tipo"] == "OK":
                    print("[FORM] ✓ Mensagem de sucesso detectada.")
                    return True

            # Conteúdo vazio = motivo provável do erro
            if diagnostico.get("conteudoCK_len", 0) == 0 and \
               diagnostico.get("conteudoTA_len", 0) == 0:
                print("[FORM] ✗ PROBLEMA: CKEditor e textarea estão VAZIOS após preencher.")
                print("[FORM]   → Causa: CKEditor não aceitou o conteúdo via setData().")
                await _screenshot_debug(page, "conteudo_vazio_pos_submit")

        except Exception as e:
            print(f"[FORM] Diagnóstico pós-submit falhou: {e}")

        await _screenshot_debug(page, "pos_cadastrar_sem_mudanca")
        print("[FORM] ✗ Cadastro não confirmado — URL não mudou e sem msg de sucesso.")
        return False

    except Exception as e:
        print(f"[FORM] Erro ao publicar: {e}")
        await _screenshot_debug(page, "erro_publicacao")
        return False


async def executar_publicacao_playwright(
    materia:  "Materia",
    imagem:   Optional["ImagemDados"],
    usuario:  str,
    senha:    str,
    rascunho: bool = True,
) -> bool:
    """Executa login + preenchimento + cadastro em sessao Playwright isolada."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("[FORM] Playwright nao instalado.")
        return False

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS, slow_mo=SLOW_MO)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()
        try:
            if not await fazer_login(page, usuario, senha):
                return False
            return await preencher_e_publicar(materia, imagem, page, rascunho=rascunho)
        finally:
            await browser.close()
