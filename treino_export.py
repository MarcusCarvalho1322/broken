"""
treino_export.py — Extrai pares de treino do cofre SEM persistir texto cru.

Le os blobs (com log de auditoria em cada leitura), monta pares rotulados
(tarefa, entrada mascarada, saida/rotulo) e grava apenas os pares.
O texto original continua existindo so dentro do cofre cifrado.

Uso:
  python treino_export.py --clinica clin_demo --vault ./vault --out ./train
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cofre import Vault
from anonimizador import mascarar_texto, OBJECOES, PROCEDIMENTOS

TAREFA_ESTILO = "estilo_resposta"
TAREFA_OBJECAO = "classe_objecao"
TAREFA_ANCORAGEM = "qualidade_ancoragem"


def _turnos(mensagens: list[dict]) -> list[tuple[str, str]]:
    """Agrupa a ultima fala do paciente com a resposta seguinte da clinica."""
    pares = []
    ultimo_pac = None
    for m in mensagens:
        if m.get("de") == "paciente" and m.get("texto", "").strip():
            ultimo_pac = m["texto"].strip()
        elif m.get("de") == "clinica" and ultimo_pac and m.get("texto", "").strip():
            pares.append((ultimo_pac, m["texto"].strip()))
            ultimo_pac = None
    return pares


def _rotulo_objecao(texto_paciente: str) -> str:
    t = texto_paciente.lower()
    for k, kws in OBJECOES.items():
        if any(w in t for w in kws):
            return k
    return "nenhuma"


def _qualidade_ancoragem(resposta: str, tinha_preco: bool) -> str:
    """Heuristica simples de ancoragem de autoridade."""
    r = resposta.lower()
    ancoragem = any(w in r for w in ["doutor", "dra", "dr.", "especialista", "avaliação", "avaliacao", "protocolo"])
    so_preco = tinha_preco and not ancoragem
    if so_preco:
        return "ruim_preco_seco"
    if ancoragem and tinha_preco:
        return "boa_ancorou_e_preco"
    if ancoragem:
        return "boa_ancorou"
    return "neutra"


def exportar(clinica: str, vault_dir: Path, out_dir: Path, limite: int | None = None) -> dict:
    v = Vault(vault_dir, clinica)
    out = out_dir / clinica
    out.mkdir(parents=True, exist_ok=True)
    destino = out / "pares.jsonl"

    tokens = v.tokens()
    if limite:
        tokens = tokens[:limite]

    n_pares = 0
    n_conv = 0
    # encoding="utf-8" obrigatorio: no Windows o padrao cp1252 quebra com acentos
    with destino.open("w", encoding="utf-8") as f:
        for token in tokens:
            # leitura auditada: cada acesso de treino fica registrado
            conv = v.get(token, motivo="export_treino", ator="bizz.ia.pipeline")
            n_conv += 1
            for entrada, saida in _turnos(conv.get("mensagens", [])):
                tinha_preco = bool(re.search(r"r\$|valor|preço|preco", entrada.lower()))
                rotulos = {
                    TAREFA_ESTILO: _rotulo_objecao(entrada) != "nenhuma" and "responder_objecao" or "resposta_padrao",
                    TAREFA_OBJECAO: _rotulo_objecao(entrada),
                    TAREFA_ANCORAGEM: _qualidade_ancoragem(saida, tinha_preco),
                }
                for tarefa, rotulo in rotulos.items():
                    par = {
                        "tarefa": tarefa,
                        "entrada": mascarar_texto(entrada),   # PII reduzida antes de sair
                        "saida": mascarar_texto(saida) if tarefa == TAREFA_ESTILO else None,
                        "rotulo": rotulo,
                        "origem_token": token,                 # apenas para auditoria via cofre
                        "operador_fora": True,
                    }
                    f.write(json.dumps(par, ensure_ascii=False) + "\n")
                    n_pares += 1

    v.audit.append("bizz.ia", "export_treino", clinica, f"{n_conv} conversas -> {n_pares} pares")
    return {"conversas_lidas": n_conv, "pares": n_pares, "arquivo": str(destino)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clinica", required=True)
    ap.add_argument("--vault", default="./vault")
    ap.add_argument("--out", default="./train")
    ap.add_argument("--limite", type=int, default=None)
    a = ap.parse_args()
    print(json.dumps(exportar(a.clinica, Path(a.vault), Path(a.out), a.limite), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
