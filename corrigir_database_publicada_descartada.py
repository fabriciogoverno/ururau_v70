from pathlib import Path
import re

arquivo = Path(r"ururau\core\database.py")
texto = arquivo.read_text(encoding="utf-8")
backup = arquivo.with_suffix(".py.bak_publicada_descartada")
backup.write_text(texto, encoding="utf-8")

def substituir_funcao(texto, nome, nova_funcao):
    padrao = re.compile(
        rf"(?ms)^    def {re.escape(nome)}\(.*?^    def ",
    )
    m = padrao.search(texto)
    if not m:
        raise SystemExit(f"ERRO: função {nome} não encontrada ou é a última função do arquivo.")
    bloco = m.group(0)
    # mantém o "    def " da próxima função
    novo_bloco = nova_funcao.rstrip() + "\n\n    def "
    return texto[:m.start()] + novo_bloco + texto[m.end():]

nova_pauta_foi_descartada = r'''    def pauta_foi_descartada(self, link: str, uid: str = "") -> bool:
        """
        Verifica se a pauta foi explicitamente descartada/bloqueada.

        HOTFIX:
        - Não usa mais link_esta_bloqueado() de forma genérica antes de checar status.
        - Se a pauta atual está ativa no banco, não deve ser tratada como descartada
          apenas porque o link aparece na tabela de bloqueio.
        - Links com motivo de publicação ficam para pauta_ja_publicada().
        """
        status_descartados = ("rejeitada", "bloqueada", "excluida")
        status_ativos = ("captada", "triada", "aprovada", "em_redacao", "revisada", "pronta")

        with _lock:
            conn = self._conectar()
            try:
                # 1. Se existe a pauta atual por UID, o status dela manda.
                if uid:
                    row = conn.execute(
                        "SELECT status FROM pautas WHERE uid=? LIMIT 1",
                        (uid,)
                    ).fetchone()
                    if row:
                        status = row["status"]
                        if status in status_descartados:
                            return True
                        if status in status_ativos or status == "publicada":
                            return False

                # 2. Se não achou por UID, consulta por link.
                if link:
                    row = conn.execute(
                        "SELECT status FROM pautas WHERE link_origem=? ORDER BY id DESC LIMIT 1",
                        (link,)
                    ).fetchone()
                    if row:
                        status = row["status"]
                        if status in status_descartados:
                            return True
                        if status in status_ativos or status == "publicada":
                            return False

                    # 3. Só considera descartada se o motivo do bloqueio NÃO for publicação.
                    row = conn.execute(
                        "SELECT motivo FROM links_bloqueados WHERE link=? LIMIT 1",
                        (link.strip(),)
                    ).fetchone()
                    if row:
                        motivo = (row["motivo"] or "").lower()
                        if motivo.startswith("publicad"):
                            return False
                        return True

                return False
            finally:
                conn.close()
'''

nova_pauta_ja_publicada = r'''    def pauta_ja_publicada(self, link: str, uid: str = "") -> bool:
        """
        Verifica se a pauta já foi publicada no Ururau.

        HOTFIX:
        - Não usa mais link_esta_bloqueado(), porque essa função mistura
          descartadas, excluídas e publicadas.
        - Só retorna True para publicação real:
          1. status='publicada' na tabela pautas;
          2. motivo de bloqueio começando com 'publicad';
          3. registro em publicacoes com status='publicada'.
        """
        with _lock:
            conn = self._conectar()
            try:
                # 1. Status publicado por UID.
                if uid:
                    row = conn.execute(
                        "SELECT status FROM pautas WHERE uid=? LIMIT 1",
                        (uid,)
                    ).fetchone()
                    if row:
                        return row["status"] == "publicada"

                # 2. Status publicado por link.
                if link:
                    row = conn.execute(
                        "SELECT 1 FROM pautas WHERE link_origem=? AND status='publicada' LIMIT 1",
                        (link,)
                    ).fetchone()
                    if row:
                        return True

                    # 3. Link bloqueado por motivo de publicação, não por descarte.
                    row = conn.execute(
                        "SELECT motivo FROM links_bloqueados WHERE link=? LIMIT 1",
                        (link.strip(),)
                    ).fetchone()
                    if row:
                        motivo = (row["motivo"] or "").lower()
                        if motivo.startswith("publicad"):
                            return True

                    # 4. Registro formal em publicacoes.
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

texto = substituir_funcao(texto, "pauta_foi_descartada", nova_pauta_foi_descartada)
texto = substituir_funcao(texto, "pauta_ja_publicada", nova_pauta_ja_publicada)

arquivo.write_text(texto, encoding="utf-8")

print("OK: database.py corrigido.")
print(f"Backup criado em: {backup}")
