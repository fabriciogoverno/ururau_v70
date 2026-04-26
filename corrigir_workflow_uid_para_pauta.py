from pathlib import Path

arquivo = Path(r"ururau\publisher\workflow.py")
texto = arquivo.read_text(encoding="utf-8")
backup = arquivo.with_suffix(".py.bak_uid_para_pauta")
backup.write_text(texto, encoding="utf-8")

if "def _uid_para_pauta(" in texto:
    print("OK: _uid_para_pauta ja existe em workflow.py. Nada a fazer.")
else:
    marcador = '''if TYPE_CHECKING:
    from openai import OpenAI
    from ururau.core.database import Database
'''

    funcao = '''
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
'''

    if marcador not in texto:
        raise SystemExit("ERRO: marcador TYPE_CHECKING nao encontrado em workflow.py")

    texto = texto.replace(marcador, marcador + funcao, 1)
    arquivo.write_text(texto, encoding="utf-8")

    print("OK: _uid_para_pauta recolocada em workflow.py")
    print(f"Backup criado em: {backup}")
