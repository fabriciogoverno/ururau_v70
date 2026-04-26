from pathlib import Path
import re

arquivo = Path(r"ururau\ui\painel.py")
texto = arquivo.read_text(encoding="utf-8")
original = texto

backup = arquivo.with_suffix(".py.bak_lambda_e")
backup.write_text(original, encoding="utf-8")

# Garante traceback disponível para registrar o erro real da redação
if "import traceback" not in texto:
    texto = texto.replace("import threading\n", "import threading\nimport traceback\n", 1)

# Correção principal: _redigir_thread
old_redigir = '''        except Exception as e:
            self.after(0, lambda: self._set_status(f"Erro na redacao: {e}"))
            self.after(0, lambda: messagebox.showerror("Erro na redacao", str(e)))
'''

new_redigir = '''        except Exception as e:
            erro_msg = str(e)
            erro_tb = traceback.format_exc()
            print(f"[ERRO REDACAO] {erro_msg}\\n{erro_tb}")
            self.after(0, lambda erro_msg=erro_msg: self._set_status(f"Erro na redacao: {erro_msg}"))
            self.after(0, lambda erro_msg=erro_msg: messagebox.showerror("Erro na redacao", erro_msg))
'''

if old_redigir in texto:
    texto = texto.replace(old_redigir, new_redigir, 1)
    print("OK: bloco _redigir_thread corrigido.")
else:
    print("AVISO: bloco exato de _redigir_thread nao encontrado. Vou aplicar correcao generica.")

# Correção da aba Fonte, que usa lambda multilinha com {e}
old_fonte = '''            except Exception as e:
                self.after(0, lambda: (
                    self._lbl_leitura_status.config(text=f"Erro: {e}", fg=COR_VERMELHO),
                    self._escrever(self._leitura_txt, f"Erro ao carregar fonte: {e}")
                ))
'''

new_fonte = '''            except Exception as e:
                erro_msg = str(e)
                self.after(0, lambda erro_msg=erro_msg: (
                    self._lbl_leitura_status.config(text=f"Erro: {erro_msg}", fg=COR_VERMELHO),
                    self._escrever(self._leitura_txt, f"Erro ao carregar fonte: {erro_msg}")
                ))
'''

if old_fonte in texto:
    texto = texto.replace(old_fonte, new_fonte, 1)
    print("OK: bloco _carregar_aba_leitura corrigido.")

# Correção genérica: qualquer self.after(... lambda: ...) na mesma linha usando e
linhas = texto.splitlines(True)
corrigidas = 0
novas = []

for linha in linhas:
    if "self.after(" in linha and "lambda:" in linha and ("str(e)" in linha or "{e}" in linha):
        linha = linha.replace("lambda:", "lambda e=e:", 1)
        corrigidas += 1
    novas.append(linha)

texto = "".join(novas)

arquivo.write_text(texto, encoding="utf-8")

print(f"OK: {corrigidas} lambda(s) simples corrigida(s).")
print(f"Backup criado em: {backup}")
print("Arquivo atualizado:", arquivo)
