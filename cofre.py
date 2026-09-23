"""
cofre.py — Cofre pseudonimizado da bizz.ia.

Envelope encryption:
  master key (KMS / arquivo offline) -> cifra a data key de cada clinica
  data key                            -> cifra cada blob do cofre (AES-256-GCM)

Fora do cofre nunca ha texto cru. Toda operacao vira linha no audit.log (hash chain).

CLI:
  python cofre.py init  --clinica clin_abc --vault ./vault
  python cofre.py put   --clinica clin_abc --blob arquivo.json
  python cofre.py get   --clinica clin_abc --token XXXX --motivo "auditoria"
  python cofre.py audit --clinica clin_abc
  python cofre.py verify --clinica clin_abc
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# ---------------------------------------------------------------- master key


def _master_key_path() -> Path:
    return Path(os.environ.get("BIZZ_MASTER_KEY_FILE", "/etc/bizz/master.key"))


def load_master_key() -> bytes:
    """Carrega a master key. Em producao isso vem do KMS; aqui, de arquivo 0600.

    NUNCA gera chave efemera silenciosamente: chave efemera significa que os
    dados de uma execucao nao podem ser lidos na proxima. Se a chave nao existir,
    o programa para e manda gerar uma.
    """
    p = _master_key_path()
    if p.exists():
        raw = base64.b64decode(p.read_bytes())
        if len(raw) != 32:
            raise ValueError("master key invalida (esperado 32 bytes)")
        return raw
    sys.stderr.write(
        "\n[cofre] ERRO: master key nao encontrada em " + str(p) + "\n"
        "        Sem ela, cada execucao usaria uma chave diferente e os dados\n"
        "        gravados ficariam irrecuperaveis. Gere uma chave fixa com:\n\n"
        "          python -c \"from cryptography.hazmat.primitives.ciphers.aead import AESGCM; import base64,pathlib; pathlib.Path('master.key').write_bytes(base64.b64encode(AESGCM.generate_key(bit_length=256)))\"\n\n"
        "        Depois defina, no PowerShell (arquivo no diretorio atual):\n\n"
        "          $env:BIZZ_MASTER_KEY_FILE=\"$PWD\\master.key\"\n\n"
        "        A chave tem de ser guardada com seguranca: quem a tem, abre o cofre.\n"
    )
    raise SystemExit(3)


# ---------------------------------------------------------------- util


def b64e(b: bytes) -> str:
    return base64.b64encode(b).decode()


def b64d(s: str) -> bytes:
    return base64.b64decode(s)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------- audit log


class AuditLog:
    """Append-only, hash-chained. Alterar o passado quebra a cadeia."""

    def __init__(self, path: Path, clinica_id: str):
        self.path = path
        self.clinica_id = clinica_id

    def _last_hash(self) -> str:
        if not self.path.exists():
            return "0" * 64
        last = "0" * 64
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                last = json.loads(line)["hash"]
        return last

    def append(self, ator: str, acao: str, alvo: str, detalhe: str = "") -> None:
        prev = self._last_hash()
        entry = {
            "ts": now_iso(),
            "clinica": self.clinica_id,
            "ator": ator,
            "acao": acao,
            "alvo": alvo,
            "detalhe": detalhe,
        }
        payload = json.dumps(entry, sort_keys=True, ensure_ascii=False)
        h = hashlib.sha256((prev + payload).encode()).hexdigest()
        entry["prev"] = prev
        entry["hash"] = h
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def verify(self) -> tuple[bool, int]:
        if not self.path.exists():
            return True, 0
        prev = "0" * 64
        n = 0
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            stored = e.pop("hash")
            e_prev = e.pop("prev")
            payload = json.dumps(e, sort_keys=True, ensure_ascii=False)
            calc = hashlib.sha256((prev + payload).encode()).hexdigest()
            if e_prev != prev or calc != stored:
                return False, n
            prev = stored
            n += 1
        return True, n


# ---------------------------------------------------------------- cofre


@dataclass
class Vault:
    root: Path
    clinica_id: str
    master: bytes = None  # type: ignore

    def __post_init__(self):
        self.root = Path(self.root)
        self.dir = self.root / self.clinica_id
        self.keys = self.dir / "keys"
        self.blobs = self.dir / "blobs"
        self.index = self.dir / "index.json"
        self.salt_file = self.dir / "salt.enc"
        self.audit = AuditLog(self.dir / "audit.log", self.clinica_id)
        if self.master is None:
            self.master = load_master_key()

    # -- envelope --------------------------------------------------

    def _new_data_key(self) -> tuple[str, bytes]:
        dk = AESGCM.generate_key(bit_length=256)
        key_id = secrets.token_hex(8)
        nonce = secrets.token_bytes(12)
        wrapped = AESGCM(self.master).encrypt(nonce, dk, self.clinica_id.encode())
        (self.keys / f"{key_id}.enc").write_bytes(nonce + wrapped)
        return key_id, dk

    def _unwrap(self, key_id: str) -> bytes:
        raw = (self.keys / f"{key_id}.enc").read_bytes()
        nonce, wrapped = raw[:12], raw[12:]
        return AESGCM(self.master).decrypt(nonce, wrapped, self.clinica_id.encode())

    # -- init ------------------------------------------------------

    def init(self, ator: str = "bizz.ia") -> dict:
        self.keys.mkdir(parents=True, exist_ok=True)
        self.blobs.mkdir(parents=True, exist_ok=True)
        if self.salt_file.exists():
            raise FileExistsError(f"cofre de {self.clinica_id} ja existe")
        key_id, dk = self._new_data_key()
        salt = secrets.token_bytes(32)
        nonce = secrets.token_bytes(12)
        enc_salt = AESGCM(dk).encrypt(nonce, salt, b"salt")
        self.salt_file.write_bytes(nonce + enc_salt)
        self.index.write_text(json.dumps({"clinica": self.clinica_id, "key_id": key_id,
                                          "criado": now_iso(), "tokens": []}, indent=2),
                              encoding="utf-8")
        self.audit.append(ator, "init", self.clinica_id, f"key_id={key_id}")
        return {"clinica_id": self.clinica_id, "key_id": key_id}

    def _data_key(self) -> tuple[str, bytes]:
        idx = json.loads(self.index.read_text(encoding="utf-8"))
        kid = idx["key_id"]
        return kid, self._unwrap(kid)

    def _salt(self) -> bytes:
        kid, dk = self._data_key()
        raw = self.salt_file.read_bytes()
        return AESGCM(dk).decrypt(raw[:12], raw[12:], b"salt")

    # -- token -----------------------------------------------------

    def token(self, contact_id: str) -> str:
        salt = self._salt()
        h = hashlib.sha256(salt + contact_id.encode()).digest()
        return base64.b32encode(h).decode().rstrip("=")[:26]

    # -- put/get ---------------------------------------------------

    def put(self, blob: dict, ator: str = "bizz.ia") -> str:
        kid, dk = self._data_key()
        contact_id = blob.get("contact_id", "")
        if not contact_id:
            raise ValueError("blob precisa de contact_id")
        token = blob.get("token") or self.token(contact_id)
        blob = {**blob, "token": token}
        nonce = secrets.token_bytes(12)
        pt = json.dumps(blob, ensure_ascii=False).encode()
        ct = AESGCM(dk).encrypt(nonce, pt, token.encode())
        (self.blobs / f"{token}.enc").write_bytes(nonce + ct)

        idx = json.loads(self.index.read_text(encoding="utf-8"))
        if token not in idx["tokens"]:
            idx["tokens"].append(token)
        idx.setdefault("meta", {})[token] = {
            "operador": blob.get("operador"),
            "capturado_em": blob.get("capturado_em"),
            "n_mensagens": len(blob.get("mensagens", [])),
        }
        self.index.write_text(json.dumps(idx, indent=2, ensure_ascii=False), encoding="utf-8")
        self.audit.append(ator, "put", token, f"n_msg={len(blob.get('mensagens', []))}")
        return token

    def get(self, token: str, motivo: str, ator: str = "bizz.ia") -> dict:
        kid, dk = self._data_key()
        raw = (self.blobs / f"{token}.enc").read_bytes()
        pt = AESGCM(dk).decrypt(raw[:12], raw[12:], token.encode())
        self.audit.append(ator, "get", token, f"motivo={motivo}")
        return json.loads(pt)

    def tokens(self) -> list[str]:
        return json.loads(self.index.read_text(encoding="utf-8"))["tokens"]


# ---------------------------------------------------------------- cli


def main() -> int:
    ap = argparse.ArgumentParser(description="Cofre pseudonimizado bizz.ia")
    ap.add_argument("cmd", choices=["init", "put", "get", "list", "audit", "verify"])
    ap.add_argument("--clinica", required=True)
    ap.add_argument("--vault", default="./vault")
    ap.add_argument("--blob")
    ap.add_argument("--token")
    ap.add_argument("--motivo", default="nao-declarado")
    ap.add_argument("--ator", default="bizz.ia")
    a = ap.parse_args()

    v = Vault(Path(a.vault), a.clinica)

    if a.cmd == "init":
        print(json.dumps(v.init(a.ator), ensure_ascii=False))
    elif a.cmd == "put":
        blob = json.loads(Path(a.blob).read_text(encoding="utf-8"))
        print(v.put(blob, a.ator))
    elif a.cmd == "get":
        print(json.dumps(v.get(a.token, a.motivo, a.ator), ensure_ascii=False))
    elif a.cmd == "list":
        print(json.dumps(v.tokens(), ensure_ascii=False))
    elif a.cmd == "audit":
        p = v.dir / "audit.log"
        print(p.read_text(encoding="utf-8") if p.exists() else "(vazio)")
    elif a.cmd == "verify":
        ok, n = v.audit.verify()
        print(json.dumps({"integridade": ok, "entradas": n}))
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
