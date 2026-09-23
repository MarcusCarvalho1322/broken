# -*- coding: utf-8 -*-
"""Explora o cofre: especialidade no nome, menções a Raphael/Larissa, assinaturas da clinica."""
import json, os, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cofre import Vault

v = Vault(Path("./vault"), "clin_demo")
tokens = v.tokens()

print(f"total tokens: {len(tokens)}\n")

# padrões
RE_ESP = re.compile(r"(dermato|derma|nutro|nutrologia|face\s*botox|botox|vip|orto|gineco|ped)", re.I)
RE_RAPHAEL = re.compile(r"\b(raphael|rafael|rafa|rapha)\b", re.I)
RE_LARISSA = re.compile(r"\b(larissa|lari|lala|lary)\b", re.I)

from collections import Counter
esp_count = Counter()
raphel_total = 0
larissa_total = 0
nenhum_doc = 0
assinaturas = Counter()

amostras = []
for t in tokens:
    try:
        conv = v.get(t, motivo="explorar_analise", ator="bizz.ia.analise")
    except Exception as e:
        print(f"ERRO get {t}: {e}")
        continue
    nome = conv.get("contato_nome", "")
    msgs = conv.get("mensagens", [])
    txt_all = " ".join(m.get("texto", "") for m in msgs)
    txt_clinica = " ".join(m.get("texto", "") for m in msgs if m.get("de") == "clinica")

    # especialidade no nome
    m_esp = RE_ESP.search(nome)
    esp = m_esp.group(0).lower() if m_esp else "(sem marcador)"
    esp_count[esp] += 1

    # menções a medico
    has_raphael = bool(RE_RAPHAEL.search(txt_all))
    has_larissa = bool(RE_LARISSA.search(txt_all))
    if has_raphael: raphel_total += 1
    if has_larissa: larissa_total += 1
    if not has_raphael and not has_larissa: nenhum_doc += 1

    # assinaturas na clinica: linhas curtas com nome proprio ou "Dra/Dr"
    for m in msgs:
        if m.get("de") != "clinica":
            continue
        txt = m.get("texto", "")
        # procura "Dra. X" / "Dr. X" / "Dra X"
        for mm in re.finditer(r"\b(Dra?\.?|Doutora?|Dra|Dr)\s+([A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+)", txt):
            assinaturas[mm.group(0)] += 1
        # assinatura isolada: linha de ate 2 palavras capitalizadas no fim
        for linha in txt.split("\n"):
            linha = linha.strip()
            if 2 <= len(linha) <= 30 and re.fullmatch(r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+(\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+){0,2}", linha):
                if linha.lower() not in ("atenciosamente", "obrigada", "obrigado", "equipe"):
                    assinaturas[linha] += 1

    if len(amostras) < 8:
        amostras.append((nome[:34], has_raphael, has_larissa, esp, len(msgs)))

print("== especialidade no nome ==")
for k, c in esp_count.most_common():
    print(f"  {k!r}: {c}")

print(f"\n== menções a medico ==")
print(f"  menciona Raphael: {raphel_total}")
print(f"  menciona Larissa: {larissa_total}")
print(f"  nenhum dos dois:  {nenhum_doc}")

print(f"\n== assinaturas/medicos na clinica (top 25) ==")
for k, c in assinaturas.most_common(25):
    print(f"  {k!r}: {c}")

print(f"\n== amostras ==")
for a in amostras:
    print(f"  {a}")
