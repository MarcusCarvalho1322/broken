# -*- coding: utf-8 -*-
"""Empacota o pipeline bizz.ia reutilizável (sem segredos nem dados de clínica)."""
import zipfile
from pathlib import Path

BASE = Path(r"C:/Users/marcu/Documents/PROJETO BREAK/BIZZ.IA PIPELINE BROKEN/bizz")
SAIDA = Path(r"C:/Users/marcu/Documents/PROJETO BREAK/BIZZ.IA PIPELINE BROKEN/bizz-pipeline-template.zip")

# apenas arquivos reutilizáveis — SEM master.key, vault, metrics, train, extraidas, logs
ARQUIVOS = [
    "PROMPT_HERMES.md",
    "README.md",
    "ESQUEMA.md",
    "extrator_cdp.js",
    "testar-seletores.js",
    "diagnostico.js",
    "cofre.py",
    "anonimizador.py",
    "treino_export.py",
    "gerar_dashboard.py",
    "rodar.ps1",
    "dashboard_template.html",
    "assets/logo.png",
    "package.json",
    "package-lock.json",
    "tests/test_seguranca.py",
    "tests/gerar_sintetico.py",
]

faltantes = [f for f in ARQUIVOS if not (BASE / f).exists()]
if faltantes:
    print("FALTANDO:", faltantes)
    raise SystemExit(1)

with zipfile.ZipFile(SAIDA, "w", zipfile.ZIP_DEFLATED) as z:
    for f in ARQUIVOS:
        z.write(BASE / f, arcname=f"bizz-pipeline/{f}")

print("ZIP criado:", SAIDA)
print("tamanho:", SAIDA.stat().st_size, "bytes")
print("arquivos:", len(ARQUIVOS))
for f in ARQUIVOS:
    print("  -", f)
