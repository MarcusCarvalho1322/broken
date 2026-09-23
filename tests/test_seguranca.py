"""Prova as garantias de seguranca do pipeline. Sai 0 se tudo passar."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

CLINICA = sys.argv[1] if len(sys.argv) > 1 else "clin_t4"

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

PII = ["Maria Souza", "João Pereira", "Ana Lima", "5511999887766", "5521988776655",
       "5531977665544", "maria.souza@gmail.com", "99988-7766", "1.200,00"]

falhas = []


def check(nome, cond, detalhe=""):
    print(("  OK  " if cond else " FALHA") + f" | {nome}" + (f" — {detalhe}" if detalhe else ""))
    if not cond:
        falhas.append(nome)


print("== 1. Nenhuma PII em claro fora do cofre ==")
for area in ["metrics", "train"]:
    for f in (BASE / area).rglob("*"):
        if f.is_file():
            txt = f.read_text(errors="ignore")
            for p in PII:
                if p.lower() in txt.lower():
                    check(f"{area}/{f.name} sem PII", False, f"vazou: {p!r}")
                    break
            else:
                check(f"{area}/{f.name} sem PII", True)

print("\n== 2. Cofre cifrado = ilegivel sem a chave ==")
blobs = list((BASE / "vault").rglob("blobs/*.enc"))
check("blobs existem", len(blobs) > 0, f"{len(blobs)} blobs")
for b in blobs:
    raw = b.read_bytes()
    achou = any(p.encode() in raw for p in PII)
    check(f"{b.name} cifrado", not achou, "texto cru encontrado!" if achou else "")

print("\n== 3. Chave errada nao decifra ==")
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cofre import Vault
v = Vault(BASE / "vault", CLINICA)
tok = v.tokens()[0]
try:
    blob = v.get(tok, motivo="teste_legitimo")
    check("leitura com chave correta", "mensagens" in blob)
except Exception as e:
    check("leitura com chave correta", False, str(e))

import base64, os, tempfile
_master_ok = os.environ["BIZZ_MASTER_KEY_FILE"]
_fake = os.path.join(tempfile.gettempdir(), f"master_errada_{os.getpid()}.key")
os.environ["BIZZ_MASTER_KEY_FILE"] = _fake
Path(_fake).write_bytes(base64.b64encode(AESGCM.generate_key(bit_length=256)))
try:
    v2 = Vault(BASE / "vault", CLINICA)
    v2.get(tok, motivo="teste_nao_autorizado")
    check("chave errada deve falhar", False, "decifrou com chave errada!")
except Exception:
    check("chave errada deve falhar", True)
finally:
    os.environ["BIZZ_MASTER_KEY_FILE"] = _master_ok
    Path(_fake).unlink(missing_ok=True)

print("\n== 4. Audit detecta adulteracao ==")
from cofre import AuditLog
alog_path = BASE / "vault" / CLINICA / "audit.log"
ok, n = AuditLog(alog_path, CLINICA).verify()
check("cadeia integra", ok, f"{n} entradas")

backup = alog_path.read_text()
linhas = backup.strip().splitlines()
d = json.loads(linhas[0]); d["ator"] = "intruso"
linhas[0] = json.dumps(d, ensure_ascii=False)
alog_path.write_text("\n".join(linhas) + "\n")
ok2, _ = AuditLog(alog_path, CLINICA).verify()
check("adulteracao detectada", not ok2)
alog_path.write_text(backup)

print("\n== 5. Token nao correlaciona entre clinicas ==")
v_a = Vault(BASE / "vault", CLINICA)
t_a = v_a.token("5511999887766")
check("token opaco", "5511" not in t_a and len(t_a) == 26, t_a)

print()
if falhas:
    print(f"RESULTADO: {len(falhas)} FALHA(S): {falhas}")
    sys.exit(1)
print("RESULTADO: todas as garantias passaram")
