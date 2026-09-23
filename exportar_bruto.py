# -*- coding: utf-8 -*-
"""Exporta TODAS as conversas do cofre de volta ao formato bruto (jsonl + txt legível)."""
import json, sys, datetime as dt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cofre import Vault

BASE = Path(__file__).resolve().parent
SAIDA = Path(r"C:/temp/bizz-deliveries")

v = Vault(BASE / "vault", "clin_demo")
tokens = v.tokens()

def fmt_ts(ts):
    if not isinstance(ts, (int, float)):
        return ""
    return dt.datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M")

conversas = []
for t in tokens:
    try:
        c = v.get(t, motivo="export_bruto", ator="bizz.ia.export")
    except Exception as e:
        print("ERRO", t, e)
        continue
    conversas.append({
        "contato_nome": c.get("contato_nome", ""),
        "operador": c.get("operador"),
        "mensagens": c.get("mensagens", []),
        "capturado_em": c.get("capturado_em"),
    })

# ordena por contato_nome para leitura
conversas.sort(key=lambda c: c["contato_nome"].lower())

# 1) JSONL bruto (formato original do extrator)
jsonl = SAIDA / "conversas_bruto.jsonl"
with jsonl.open("w", encoding="utf-8") as f:
    for c in conversas:
        f.write(json.dumps(c, ensure_ascii=False) + "\n")

# 2) TXT legível
txt = SAIDA / "conversas_bruto.txt"
with txt.open("w", encoding="utf-8") as f:
    f.write("=" * 70 + "\n")
    f.write("CONVERSAS COMPLETAS — WHATSAPP (clin_demo)\n")
    f.write(f"Total: {len(conversas)} conversas · exportado do cofre em {dt.datetime.now().strftime('%d/%m/%Y %H:%M')}\n")
    f.write("=" * 70 + "\n\n")
    for i, c in enumerate(conversas, 1):
        f.write(f"\n{'='*70}\n")
        f.write(f"[{i}] {c['contato_nome']}\n")
        f.write(f"    operador: {c.get('operador')} | capturado: {c.get('capturado_em')}\n")
        f.write("-" * 70 + "\n")
        for m in c.get("mensagens", []):
            de = "PACIENTE" if m.get("de") == "paciente" else "CLÍNICA"
            ts = fmt_ts(m.get("ts"))
            midia = " [MÍDIA]" if m.get("tem_midia") else ""
            f.write(f"[{de}] {ts} :: {m.get('texto','')}{midia}\n")
        f.write("\n")

print("conversas:", len(conversas))
print("jsonl:", jsonl, jsonl.stat().st_size, "bytes")
print("txt :", txt, txt.stat().st_size, "bytes")
