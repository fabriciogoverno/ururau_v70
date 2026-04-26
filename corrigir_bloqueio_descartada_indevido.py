from pathlib import Path
import re
import sqlite3
import shutil
from datetime import datetime

ROOT = Path.cwd()
db_file = ROOT / "ururau.db"
database_py = ROOT / "ururau" / "core" / "database.py"
rss_py = ROOT / "ururau" / "coleta" / "rss.py"

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

# Backups
if db_file.exists():
    shutil.copy2(db_file, ROOT / f"ururau.db.bak_bloqueio_{stamp}")
    print(f"OK: backup do banco criado: ururau.db.bak_bloqueio_{stamp}")

for arq in [database_py, rss_py]:
    shutil.copy2(arq, arq.with_suffix(arq.suffix + f".bak_bloqueio_{stamp}"))
    print(f"OK: backup criado: {arq.with_suffix(arq.suffix + f'.bak_bloqueio_{stamp}')}")

texto = database_py.read_text(encoding="utf-8")

def replace_method(src: str, name: str, new_body: str) -> str:
    pattern = re.compile(rf"(?ms)^    def {re.escape(name)}\(.*?)(?=^    def |\Z)")
    m = pattern.search(src)
    if not m:
        raise SystemExit(f"ERRO: método {name} não encontrado em database.py")
    return src[:m.start()] + new_body.rstrip() + "\n\n" + src[m.end():]

nova_pauta_foi_descartada = r'''    def pauta_foi_descartada(self, link: str, uid: str = "") -> bool:
        """
        HOTFIX: verifica descarte real sem confundir pauta ativa com link bloqueado.

        Regra correta:
        - Se a pauta atual existe e está ativa, NÃO é descartada.
        - Se a pauta atual está rejeitada/bloqueada/excluida, é descartada.
        - Só consulta links_bloqueados depois de não encontrar pauta ativa.
        """
        status_descartados = ("rejeitada", "bloqueada", "excluida")
        status_ativos = ("captada", "triada", "aprovada", "em_redacao", "revisada", "pronta")

        with _lock:
            conn = self._conectar()
            try:
                # 1. UID da pauta atual manda.
                if uid:
                    row = conn.execute(
                        "SELECT status FROM pautas WHERE uid=? LIMIT 1",
                        (uid,)
                    ).fetchone()
                    if row:
                        status = (row["status"] or "").lower()
                        if status in status_descartados:
                            return True
                        if status in status_ativos or status == "publicada":
                            return False

                # 2. Link da pauta atual manda.
                if link:
                    row = conn.execute(
                        "SELECT status FROM pautas WHERE link_origem=? ORDER BY atualizada_em DESC LIMIT 1",
                        (link,)
                    ).fetchone()
                    if row:
                        status = (row["status"] or "").lower()
                        if status in status_descartados:
                            return True
                        if status in status_ativos or status == "publicada":
                            return False

                    # 3. Só agora consulta links_bloqueados.
                    row = conn.execute(
                        "SELECT motivo FROM links_bloqueados WHERE link=? LIMIT 1",
                        (link.strip(),)
                    ).fetchone()
                    if row:
                        motivo = (row["motivo"] or "").lower()
                        # link publicado não é "descartado"; isso é função de pauta_ja_publicada()
                        if motivo.startswith("publicad"):
                            return False
                        return True

                return False
            finally:
                conn.close()
'''

nova_pauta_ja_publicada = r'''    def pauta_ja_publicada(self, link: str, uid: str = "") -> bool:
        """
        HOTFIX: verifica publicação real sem usar link_esta_bloqueado() genericamente.

        Regra correta:
        - link bloqueado por descarte/exclusão NÃO significa publicado.
        - Só retorna True para status publicada ou motivo publicada.
        """
        with _lock:
            conn = self._conectar()
            try:
                if uid:
                    row = conn.execute(
                        "SELECT status FROM pautas WHERE uid=? LIMIT 1",
                        (uid,)
                    ).fetchone()
                    if row:
                        return (row["status"] or "").lower() == "publicada"

                if link:
                    row = conn.execute(
                        "SELECT status FROM pautas WHERE link_origem=? ORDER BY atualizada_em DESC LIMIT 1",
                        (link,)
                    ).fetchone()
                    if row and (row["status"] or "").lower() == "publicada":
                        return True

                    row = conn.execute(
                        "SELECT motivo FROM links_bloqueados WHERE link=? LIMIT 1",
                        (link.strip(),)
                    ).fetchone()
                    if row:
                        motivo = (row["motivo"] or "").lower()
                        if motivo.startswith("publicad"):
                            return True

                    row = conn.execute(
                        "SELECT 1 FROM publicacoes WHERE dados_json LIKE ? AND status='publicada' LIMIT 1",
                        (f'%"{link}"%',)
                    ).fetchone()
                    if row:
                        return True

                return False
            finally:
                conn.close()
'''

texto = replace_method(texto, "pauta_foi_descartada", nova_pauta_foi_descartada)
texto = replace_method(texto, "pauta_ja_publicada", nova_pauta_ja_publicada)
database_py.write_text(texto, encoding="utf-8")
print("OK: database.py corrigido: publicada e descartada agora são coisas separadas.")

# Corrige ordem no filtro RSS: pauta ativa não pode ser barrada só por link_bloqueado.
rss = rss_py.read_text(encoding="utf-8")

old = '''        try:
            if link and db.link_esta_bloqueado(link):
                resumo["descartadas"] += 1
                print(f"[FILTRO] Link bloqueado (desc/pub): {titulo[:60]}")
                continue
        except AttributeError:
            pass  # db mais antigo sem o método - segue com os checks normais
'''

new = '''        try:
            status_pre = db.classificar_pauta(link, uid)
            if status_pre in ("captada", "triada", "aprovada", "em_redacao", "revisada", "pronta"):
                resumo["em_fila"] += 1
                print(f"[FILTRO] Já na fila ({status_pre}): {titulo[:60]}")
                continue

            if link and db.link_esta_bloqueado(link):
                resumo["descartadas"] += 1
                print(f"[FILTRO] Link bloqueado (desc/pub): {titulo[:60]}")
                continue
        except AttributeError:
            pass  # db mais antigo sem o método - segue com os checks normais
'''

if old in rss:
    rss = rss.replace(old, new, 1)
    rss_py.write_text(rss, encoding="utf-8")
    print("OK: rss.py corrigido: verifica pauta ativa antes de link bloqueado.")
else:
    print("AVISO: bloco exato do rss.py não encontrado. Nenhuma alteração feita no rss.py.")

# Repara o banco: remove links_bloqueados que pertencem a pautas ativas.
if db_file.exists():
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    try:
        ativos = ("captada", "triada", "aprovada", "em_redacao", "revisada", "pronta")
        qmarks = ",".join("?" for _ in ativos)

        antes = conn.execute("SELECT COUNT(*) FROM links_bloqueados").fetchone()[0]

        conflito = conn.execute(f"""
            SELECT COUNT(*)
            FROM links_bloqueados lb
            JOIN pautas p ON p.link_origem = lb.link
            WHERE p.status IN ({qmarks})
        """, ativos).fetchone()[0]

        conn.execute(f"""
            DELETE FROM links_bloqueados
            WHERE link IN (
                SELECT link_origem
                FROM pautas
                WHERE status IN ({qmarks})
                  AND link_origem IS NOT NULL
                  AND link_origem != ''
            )
        """, ativos)

        conn.commit()

        depois = conn.execute("SELECT COUNT(*) FROM links_bloqueados").fetchone()[0]
        print(f"OK: banco reparado. Links bloqueados antes: {antes}. Conflitos com pautas ativas removidos: {conflito}. Depois: {depois}.")
    finally:
        conn.close()
else:
    print("AVISO: ururau.db não encontrado. Pulei reparo do banco.")

print("FINALIZADO. Feche e reabra o painel para recarregar o cache.")
