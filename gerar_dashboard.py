"""Gera dashboard_bizzia.html a partir das metricas pseudonimizadas + cofre.

Uso (no Windows, dentro da pasta bizz, com a master key ja configurada):

  $env:BIZZ_MASTER_KEY_FILE="$PWD\\master.key"
  python gerar_dashboard.py --clinica clin_demo --metrics .\\metrics --vault .\\vault ^
      --logo .\\assets\\logo.png --template .\\dashboard_template.html --saida .\\dashboard_bizzia.html

O dashboard NAO le texto de conversa nem dado pessoal: apenas contagens, rotulos,
latencias, a distribuicao horaria (agregada do instante das mensagens no cofre) e a
subdivisao destino/quem-atendeu/desfecho (classificacao feita DENTRO do cofre, sem
nunca expor texto cru). Toda leitura fica auditada no cofre.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

try:
    from cofre import Vault
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from cofre import Vault


# ---------------------------------------------------------------- classificacao

RE_RAPHAEL = re.compile(r"\b(raphael|rafael|rafa|rapha)\b", re.I)
RE_LARISSA = re.compile(r"\b(larissa|lari|lala|lary)\b", re.I)
RE_SIG_LARISSA = re.compile(r"dra?\.?\s*larissa", re.I)
RE_SIG_RAPHAEL = re.compile(r"dr\.?\s*(raphael|rafael)", re.I)
KW_DERMATO = re.compile(r"(dermato|derma|botox|toxina|preenchimento|pele|harmoniza|facial|limpeza de pele|peeling)", re.I)
KW_NUTRO = re.compile(r"(nutro|nutrologia|dieta|nutri|emagrec|peso|suplemento|redução de peso|reeducação)", re.I)
RE_NOME_DERMATO = re.compile(r"(dermato|derma|botox|facial)", re.I)
RE_NOME_NUTRO = re.compile(r"(nutro|nutrologia)", re.I)

# médicos da clínica — ajuste por clínica se mudar
MEDICO_DERMATO = "Dra. Larissa"
MEDICO_NUTRO = "Dr. Raphael"


def destino(nome: str, txt_all: str) -> str:
    if RE_LARISSA.search(txt_all) and not RE_RAPHAEL.search(txt_all):
        return MEDICO_DERMATO
    if RE_RAPHAEL.search(txt_all) and not RE_LARISSA.search(txt_all):
        return MEDICO_NUTRO
    if RE_NOME_DERMATO.search(nome):
        return MEDICO_DERMATO
    if RE_NOME_NUTRO.search(nome):
        return MEDICO_NUTRO
    d = KW_DERMATO.search(txt_all)
    n = KW_NUTRO.search(txt_all)
    if d and not n:
        return MEDICO_DERMATO
    if n and not d:
        return MEDICO_NUTRO
    return "nao_identificado"


def quem_atendeu(msgs: list[dict]) -> str:
    larissa = raphael = 0
    for m in msgs:
        if m.get("de") != "clinica":
            continue
        t = m.get("texto", "")
        if RE_SIG_LARISSA.search(t):
            larissa += 1
        if RE_SIG_RAPHAEL.search(t):
            raphael += 1
    if larissa > raphael:
        return MEDICO_DERMATO
    if raphael > larissa:
        return MEDICO_NUTRO
    return "Recepcao"


def terceira_via(msgs: list[dict], objecoes: list[str]) -> str:
    if objecoes:
        return "Travado em objeção (preço/horário/tempo/medo)"
    ultimo = msgs[-1].get("de") if msgs else None
    if ultimo == "clinica":
        return "Aguarda paciente (clínica respondeu, paciente sumiu)"
    if ultimo == "paciente":
        return "Aguarda clínica (paciente ficou SEM resposta)"
    return "Sem sinal"


# ---------------------------------------------------------------- agregacao

def carregar_metricas(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if linha:
                rows.append(json.loads(linha))
    return rows


def _blob_por_token(vault: Vault, tokens: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for t in tokens:
        try:
            out[t] = vault.get(t, motivo="dashboard_subdivisao", ator="bizz.ia.pipeline")
        except Exception:
            continue
    return out


def agregar(rows: list[dict], vault: Vault | None) -> dict:
    n = len(rows) or 1
    fechou = sum(1 for c in rows if c.get("conversao") == "fechou")
    perdeu = sum(1 for c in rows if c.get("conversao") == "perdeu")
    indef = len(rows) - fechou - perdeu
    lats = [c["primeira_resposta_seg"] for c in rows
            if c.get("primeira_resposta_seg") is not None]

    out: dict = {"kpis": {}, "procedimentos": [], "objecoes": [],
                 "destino": [], "quem_atendeu": [], "dest_x_desf": [],
                 "quem_x_desf": [], "terceira_via": [], "horas": [], "dias": []}

    out["kpis"] = {
        "total": len(rows),
        "fechou": fechou,
        "perdeu": perdeu,
        "indefinido": indef,
        "taxa_fechamento": round(100 * fechou / n, 1),
        "taxa_perda": round(100 * perdeu / n, 1),
        "latencia_media_min": round(sum(lats) / len(lats) / 60, 1) if lats else 0,
        "latencia_pior_min": round(max(lats) / 60, 1) if lats else 0,
        "msg_paciente": sum(c.get("n_msg_paciente", 0) for c in rows),
        "msg_clinica": sum(c.get("n_msg_clinica", 0) for c in rows),
        "followups": sum(c.get("n_followups", 0) for c in rows),
    }

    # blobs (para classificar destino/quem e agregar horario) — leitura auditada
    blobs: dict[str, dict] = {}
    if vault is not None:
        blobs = _blob_por_token(vault, [c.get("token") for c in rows if c.get("token")])

    # ---- destino + quem_atendeu + terceira via ----
    dest = defaultdict(lambda: {"n": 0, "fechou": 0, "perdeu": 0, "terceira": 0})
    quem = defaultdict(lambda: {"n": 0, "fechou": 0, "perdeu": 0, "terceira": 0})
    tv = Counter()
    hh, dd = Counter(), Counter()

    for c in rows:
        conv_final = c.get("conversao")
        desf = conv_final if conv_final in ("fechou", "perdeu") else "terceira"
        blob = blobs.get(c.get("token")) or {}
        nome = blob.get("contato_nome", "")
        msgs = blob.get("mensagens", [])
        txt = " ".join(m.get("texto", "") for m in msgs)

        d = destino(nome, txt)
        q = quem_atendeu(msgs)

        dest[d]["n"] += 1
        dest[d][desf] += 1
        quem[q]["n"] += 1
        quem[q][desf] += 1

        if desf == "terceira":
            tv[terceira_via(msgs, c.get("objecoes") or [])] += 1

        # horario/dia a partir do instante da 1a mensagem
        tss = [m.get("ts") for m in msgs if isinstance(m.get("ts"), (int, float))]
        if tss:
            d0 = dt.datetime.fromtimestamp(min(tss))
            hh[d0.hour] += 1
            dd[d0.weekday()] += 1

    def _fmt(d: dict) -> list[dict]:
        lista = [{"nome": k, "n": v["n"], "fechou": v["fechou"], "perdeu": v["perdeu"],
                  "terceira": v["terceira"],
                  "taxa": round(100 * v["fechou"] / v["n"], 1) if v["n"] else 0}
                 for k, v in d.items()]
        lista.sort(key=lambda z: -z["n"])
        return lista

    out["destino"] = _fmt(dest)
    out["quem_atendeu"] = _fmt(quem)
    out["dest_x_desf"] = [{"nome": k, "fechou": v["fechou"], "perdeu": v["perdeu"], "terceira": v["terceira"]}
                          for k, v in dest.items()]
    out["quem_x_desf"] = [{"nome": k, "fechou": v["fechou"], "perdeu": v["perdeu"], "terceira": v["terceira"]}
                          for k, v in quem.items()]
    out["terceira_via"] = [{"situacao": k, "n": v} for k, v in tv.most_common()]

    procs = Counter(c.get("procedimento", "indefinido") for c in rows)
    out["procedimentos"] = [{"nome": k, "n": v, "pct": round(100 * v / n, 1)}
                            for k, v in procs.most_common()]

    objs = Counter()
    for c in rows:
        for o in c.get("objecoes", []):
            objs[o] += 1
    out["objecoes"] = [{"nome": k, "n": v, "pct": round(100 * v / n, 1)}
                       for k, v in objs.most_common()]

    out["horas"] = [{"h": h, "n": hh.get(h, 0)} for h in range(8, 22)]
    nomes_d = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    out["dias"] = [{"d": nomes_d[i], "n": dd.get(i, 0)} for i in range(7)]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clinica", required=True)
    ap.add_argument("--metrics", required=True, help="pasta metrics/")
    ap.add_argument("--vault", required=True, help="pasta vault/")
    ap.add_argument("--logo", required=True, help="png da logo bizz.ia")
    ap.add_argument("--template", required=True, help="dashboard_template.html")
    ap.add_argument("--saida", required=True)
    args = ap.parse_args()

    metrics = Path(args.metrics) / args.clinica / "conversas.jsonl"
    if not metrics.exists():
        sys.stderr.write(f"[dashboard] metricas nao encontradas: {metrics}\n")
        return 2
    rows = carregar_metricas(metrics)

    try:
        vault = Vault(Path(args.vault), args.clinica)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[dashboard] cofre indisponivel ({e}); horarios/subdivisao ficarao zerados\n")
        vault = None

    dados = agregar(rows, vault)
    
    # Enriquecer com telemetria forense se existir
    telemetria_file = Path(args.metrics).parent / "forense" / "telemetria.json"
    if not telemetria_file.exists():
        telemetria_file = Path("./forense/telemetria.json")
    if telemetria_file.exists():
        try:
            dados["telemetria"] = json.loads(telemetria_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    logo_b64 = base64.b64encode(Path(args.logo).read_bytes()).decode()
    tpl = Path(args.template).read_text(encoding="utf-8")
    html = (tpl.replace("__LOGO__", "data:image/png;base64," + logo_b64)
               .replace("/*__DADOS__*/{}", json.dumps(dados, ensure_ascii=False)))
    Path(args.saida).write_text(html, encoding="utf-8")
    print(json.dumps({"dashboard": args.saida, "conversas": len(rows),
                      "destinos": len(dados["destino"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
