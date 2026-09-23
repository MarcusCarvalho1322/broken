# -*- coding: utf-8 -*-
"""motor_forense.py — BIZZ.IA CORE ENGINE v3.1 (modelo paramétrico).

Correções de integridade do Master Prompt v3.1 vs v1:
  1. Hemorragia Invisível™ é FÓRMULA paramétrica (R = k × T), NUNCA número absoluto
     arbitrado. k é fato do corpus; T é variável da clínica.
  2. Score Bizz-Gold™ de 6 EIXOS (24/16/22/18/12/8), não 4.
  3. Camada 1 de densidade: fantasma / ruído / válida.
  4. Ponto cego de áudio declarado (cobertura analítica).
  5. Dupla saída: dossiê DIRECAO (nominal) vs EQUIPE (anônima).
  6. Schema v3.1 (audit_metadata / financial_leakage com k / operator_performance /
     governance_and_mrr / leads_for_immediate_rescue).
"""
from __future__ import annotations

import argparse
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

from gerar_dashboard import destino, carregar_metricas


# ================================================================ CONFIG

PESOS = {
    "qualificacao": 0.24,       # E1
    "valor_ancoragem": 0.16,    # E2
    "contorno_objecao": 0.22,   # E3
    "conducao_fechamento": 0.18,  # E4
    "velocidade": 0.12,         # E5
    "followup": 0.08,           # E6
}
LIMIAR_RESPOSTA_SEG = 10 * 60

# Tabela de sensibilidade: faixas de REFERÊNCIA para o cliente achar o próprio ticket.
# NÃO é arbitragem de LTV — nunca usamos isto como base do cálculo (ver Módulo 11-A).
T_SENSIBILIDADE = [1500, 2500, 5000, 10000, 25000, 50000]

# Assinaturas individuais (recepção La Vienne)
RE_SIG_CARLA = re.compile(r"aqui\s*[ée]\s*a?\s*carla", re.I)
RE_SIG_MARIA = re.compile(r"aqui\s*[ée]\s*a?\s*maria", re.I)

# Auto-identificação do médico (tácita, clara e inequívoca)
RE_SELF_MEDICO = re.compile(
    r"(aqui\s*[ée]\s*(a|o)\s*(dra?|dr)\.?\s*(larissa|raphael|rafael))"
    r"|((dra?|dr)\.?\s*(larissa|raphael|rafael)\s+(aqui|falando))"
    r"|(sou\s*(a|o)\s*(dra?|dr)\.?\s*(larissa|raphael|rafael))",
    re.I,
)


def _txt(m: dict) -> str:
    return (m.get("texto") or "").strip()


def _medico_autodeclarado(t: str) -> str | None:
    for mm in re.finditer(RE_SELF_MEDICO, t):
        frag = mm.group(0)
        if re.search(r"larissa", frag, re.I):
            return "Larissa"
        if re.search(r"raphael|rafael", frag, re.I):
            return "Raphael"
    return None


def quem_atendeu_detalhado(msgs: list[dict]) -> str:
    counts = {"Carla": 0, "Maria": 0, "Dra. Larissa": 0, "Dr. Raphael": 0}
    for m in msgs:
        if m.get("de") != "clinica":
            continue
        t = _txt(m)
        if RE_SIG_CARLA.search(t):
            counts["Carla"] += 1
        elif RE_SIG_MARIA.search(t):
            counts["Maria"] += 1
        else:
            med = _medico_autodeclarado(t)
            if med == "Larissa":
                counts["Dra. Larissa"] += 1
            elif med == "Raphael":
                counts["Dr. Raphael"] += 1
    melhor = max(counts, key=counts.get)
    return melhor if counts[melhor] > 0 else "Recepcao"


# ================================================================ FASE 1 — TRIAGEM

SINAIS_CLINICA = [
    r"\bdr[aa]?\.?\s+\w", r"\bdra?\s+(larissa|raphael)", r"aqui[ ée] (a|da|o)",
    r"recep[cç][aã]o", r"cl[ií]nica", r"valor (do|da|de)", r"o valor fica",
    r"or[cç]amento", r"agendamos?", r"vou te passar", r"convite da",
    r"seguimos[ àa] disposi", r"qualquer d[uú]vida",
]
SINAIS_PACIENTE = [
    r"quanto (fica|custa|sai)", r"quero (saber|agendar|fazer)", r"gostaria de",
    r"estou interessad", r"tem (vaga|hor[áa]rio)", r"meu nome [ée]",
    r"voc[êe]s? (atendem|fazem|tem)", r"poderia me (passar|informar)",
]
SINAIS_ADMIN = [
    r"nota fiscal", r"receita", r"dieta", r"retorno", r"remarca", r"desmarca",
    r"exame", r"resultado", r"laudo", r"confirma[cç][aã]o de (consulta|hor[áa]rio)",
    r"preciso (remarcar|desmarcar|cancelar)", r"meu retorno", r"p[óo]s[- ]?operat[óo]rio",
]
SINAIS_COMERCIAL = [
    r"valor", r"pre[cç]o", r"quanto (fica|custa)", r"or[cç]amento",
    r"botox", r"toxina", r"preenchimento", r"harmoniza", r"lipo", r"faceta",
    r"lentes", r"implante", r"clareamento", r"peeling", r"limpeza de pele",
    r"procedimento", r"avalia[cç][aã]o", r"consulta", r"quero (fazer|agendar)",
    r"tenho interesse", r"gostaria de (fazer|saber)", r"cirurgia", r"rinoplastia",
    r"abdominoplastia", r"preenchimento labial",
]


def corrigir_autoria(msgs: list[dict]) -> list[dict]:
    saida = []
    for m in msgs:
        t = _txt(m)
        origem = m.get("de", "desconhecido")
        efetiva = origem
        motivo = None

        med = _medico_autodeclarado(t)
        tem_clinica = any(re.search(p, t, re.I) for p in SINAIS_CLINICA)
        tem_paciente = any(re.search(p, t, re.I) for p in SINAIS_PACIENTE)

        if med:
            efetiva = "clinica"
            if origem != "clinica":
                motivo = f"Autodeclaração médica no texto: '{med}'"
        elif origem == "paciente" and tem_clinica and not tem_paciente:
            efetiva = "clinica"
            motivo = f"Conteúdo semântico da clínica: '{t[:60]}...'"
        elif origem == "clinica" and tem_paciente and not tem_clinica:
            efetiva = "paciente"
            motivo = f"Conteúdo semântico do paciente: '{t[:60]}...'"

        m2 = dict(m)
        m2["autoria_origem"] = origem
        m2["autoria_efetiva"] = efetiva
        m2["motivo_correcao"] = motivo
        m2["de"] = efetiva
        saida.append(m2)
    return saida


def classificar_densidade(msgs: list[dict]) -> str:
    """Camada 1 (Módulo 02): fantasma / ruído / válida."""
    npac = sum(1 for m in msgs if m.get("de") == "paciente")
    ncli = sum(1 for m in msgs if m.get("de") == "clinica")
    if npac == 0 and ncli <= 2:
        return "fantasma"
    if npac <= 1 and ncli <= 2:
        return "ruido"
    return "valida"


def classificar_intencao(msgs: list[dict]) -> str:
    """Camada 2 (Módulo 02): comercial vs administrativo."""
    txt = " ".join(_txt(m) for m in msgs).lower()
    adm = sum(1 for p in SINAIS_ADMIN if re.search(p, txt))
    com = sum(1 for p in SINAIS_COMERCIAL if re.search(p, txt))
    if com == 0 and adm > 0:
        return "administrativo"
    return "comercial"


# ================================================================ FASE 2 — CHRONOS

FRICCAO_PADROES = {
    "Desmarcação por viagem da doutora": r"vai viajar|viajou|precisamos desmarcar|desmarcar",
    "Remarcação": r"remarcar",
    "Sistema fora do ar": r"sistema (caiu|fora|fora do ar)|problema no sistema",
    "Agenda sem horário/vaga": r"agenda (cheia|fechada)|sem (hor[áa]rio|vaga)|n[ãa]o temos (hor[áa]rio|vaga)",
}


def detectar_friccao(msgs: list[dict]) -> list[str]:
    achados = []
    for m in msgs:
        if m.get("de") != "clinica":
            continue
        t = _txt(m)
        for label, p in FRICCAO_PADROES.items():
            if re.search(p, t, re.I):
                achados.append(label)
    return achados


def invasao_medica(msgs: list[dict]) -> int:
    n = 0
    for m in msgs:
        if m.get("de") == "clinica" and _medico_autodeclarado(_txt(m)):
            n += 1
    return n


# ================================================================ FASE 3 — FORENSIC PSYCH

SPIN_PADROES = [
    r"h[áa] quanto tempo", r"qual (o|seu) objetivo", r"o que (te |lhe )?incomoda",
    r"j[áa] fez", r"j[áa] fez algum", r"como est[áa]", r"o que (voc[êe]|a senhora) busca",
    r"me conta", r"h[áa] quanto tempo sente", r"qual (sua|a sua) (queixa|dor)",
]
ANCORAGEM_PADROES = [
    r"doutor", r"dra\.?", r"protocolo", r"avalia[cç][aã]o", r"inclui",
    r"planejamento", r"naturalidade", r"tecnologia", r"diferencial", r"autoridade",
    r"anatomia", r"funcionalidade", r"seguran[cç]a",
]
OBJECAO_PADROES = [r"caro", r"valor", r"pre[cç]o", r"tempo", r"demora", r"hor[áa]rio",
                   r"c[ôo]njuge", r"marido", r"esposa", r"medo", r"dor", r"receio",
                   r"vou pensar", r"depois", r"mais pra frente"]
TRATAMENTO_OBJECAO = [
    r"entendo", r"compreendo", r"parcel", r"posso (ajustar|ver)", r"o valor inclui",
    r"inclui", r"vale (a pena|muito)", r"doutor", r"dra", r"avalia[cç][aã]o",
    r"prioridade", r"posso te explicar", r"n[ãa]o [ée] s[óo]",
]
CTA_PADROES = [
    r"posso (te )?encaixar", r"qual (o melhor )?hor[áa]rio", r"amanh[ãa]", r"segunda",
    r"ter[cç]a", r"quero confirmar", r"vou agendar", r"posso agendar", r"escolhe",
    r"prefere (manh[ãa]|tarde)", r"tem prefer[êe]ncia",
]


def _idx_primeiro_preco(msgs: list[dict]) -> int | None:
    for i, m in enumerate(msgs):
        if m.get("de") == "clinica" and re.search(r"r\$|\bvalor\b|tabela|pre[cç]o", _txt(m), re.I):
            return i
    return None


def detectar_spin(msgs: list[dict]) -> bool:
    ipreco = _idx_primeiro_preco(msgs)
    for i, m in enumerate(msgs):
        if m.get("de") != "clinica":
            continue
        if ipreco is not None and i >= ipreco:
            break
        if any(re.search(p, _txt(m), re.I) for p in SPIN_PADROES):
            return True
    return False


def detectar_ancoragem(msgs: list[dict]) -> bool:
    ipreco = _idx_primeiro_preco(msgs)
    for i, m in enumerate(msgs):
        if m.get("de") != "clinica":
            continue
        if ipreco is not None and i >= ipreco:
            break
        if any(re.search(p, _txt(m), re.I) for p in ANCORAGEM_PADROES):
            return True
    return False


def tratar_objeceao(msgs: list[dict]) -> bool:
    flag_objecao = False
    for m in msgs:
        t = _txt(m)
        if m.get("de") == "paciente" and any(re.search(p, t, re.I) for p in OBJECAO_PADROES):
            flag_objecao = True
        elif m.get("de") == "clinica" and flag_objecao:
            if any(re.search(p, t, re.I) for p in TRATAMENTO_OBJECAO):
                return True
    return False


def detectar_cta(msgs: list[dict]) -> bool:
    for m in reversed(msgs):
        if m.get("de") != "clinica":
            continue
        return any(re.search(p, _txt(m), re.I) for p in CTA_PADROES)
    return False


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip().lower()


def detectar_spam_global(conversas: list[dict]) -> tuple[set[str], Counter, set[str]]:
    origem: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for c in conversas:
        token = c.get("token", "")
        for m in c.get("mensagens", []):
            if m.get("de") != "clinica":
                continue
            t = _norm(_txt(m))
            if len(t) < 40:
                continue
            if RE_SIG_CARLA.search(t):
                fonte = "Carla"
            elif RE_SIG_MARIA.search(t):
                fonte = "Maria"
            else:
                fonte = "Recepcao"
            origem[t][fonte].add(token)
    spammers = set()
    fontes_spam = set()
    contagem = Counter()
    for t, fontes in origem.items():
        todos = set()
        for toks in fontes.values():
            todos |= toks
        if len(todos) >= 5:  # v3.1: 5+ leads
            for tok in todos:
                spammers.add(tok)
            contagem[t] = len(todos)
            for f in fontes:
                fontes_spam.add(f)
    return spammers, contagem, fontes_spam


# ================================================================ FASE 4 — ECONOMETRIA

def score_bizz_gold(eixos: dict) -> float:
    s = sum(PESOS[k] * eixos.get(k, 0.0) for k in PESOS)
    return round(s * 100, 1)


def _sensitivity_table(k: float, n_nc: int) -> list[dict]:
    return [
        {"ticket_referencia": T, "exposto": n_nc * T, "recuperavel": round(k * T)}
        for T in T_SENSIBILIDADE
    ]


# ================================================================ OUTPUT

def _anom(nome: str, token: str) -> str:
    return f"LEAD_{token[:8].upper()}"


def rodar(clinica: str, vault_dir: Path, metrics_dir: Path, out_dir: Path) -> dict:
    v = Vault(vault_dir, clinica)
    rows = carregar_metricas(metrics_dir / clinica / "conversas.jsonl")

    conversas = []
    for c in rows:
        t = c.get("token")
        if not t:
            continue
        try:
            b = v.get(t, motivo="motor_forense", ator="bizz.ia.engine")
        except Exception:
            continue
        msgs = corrigir_autoria(b.get("mensagens", []))
        nome = b.get("contato_nome", "")
        conversas.append({
            "token": t, "nome": nome, "mensagens": msgs,
            "quem": quem_atendeu_detalhado(msgs),
            "destino": destino(nome, " ".join(_txt(m) for m in msgs)),
            "densidade": classificar_densidade(msgs),
            "intencao": classificar_intencao(msgs),
            "conversao": c.get("conversao"),
            "procedimento": c.get("procedimento", "indefinido"),
            "objecoes": c.get("objecoes") or [],
            "primeira_resposta_seg": c.get("primeira_resposta_seg"),
            "spin": detectar_spin(msgs),
            "ancoragem": detectar_ancoragem(msgs),
            "tratou_objecao": tratar_objeceao(msgs),
            "cta": detectar_cta(msgs),
            "friccao": detectar_friccao(msgs),
            "invasao_medica": invasao_medica(msgs),
            "n_audio_clinica": sum(1 for m in msgs if m.get("de") == "clinica"
                                   and (m.get("tem_midia") or re.search(r"áudio|audio|voz", _txt(m), re.I))),
            "n_audio_paciente": sum(1 for m in msgs if m.get("de") == "paciente"
                                    and (m.get("tem_midia") or re.search(r"áudio|audio|voz", _txt(m), re.I))),
        })

    spammers, spam_contagem, fontes_spam = detectar_spam_global(conversas)

    validas_comerciais = [c for c in conversas
                          if c["densidade"] == "valida" and c["intencao"] == "comercial"]
    fantasmas = [c for c in conversas if c["densidade"] == "fantasma" and c["intencao"] == "comercial"]
    administrativos = [c for c in conversas if c["intencao"] == "administrativo"]
    ruidos = [c for c in conversas if c["densidade"] == "ruido"]

    n = len(validas_comerciais) or 1
    com_objecao = [c for c in validas_comerciais if c["objecoes"] or any(
        re.search(p, " ".join(_txt(m) for m in c["mensagens"]), re.I) for p in OBJECAO_PADROES)]
    eixos = {
        "qualificacao": sum(1 for c in validas_comerciais if c["spin"]) / n,
        "valor_ancoragem": sum(1 for c in validas_comerciais if c["ancoragem"]) / n,
        "contorno_objecao": (sum(1 for c in com_objecao if c["tratou_objecao"]) / len(com_objecao))
                            if com_objecao else 0.0,
        "conducao_fechamento": sum(1 for c in validas_comerciais if c["cta"]) / n,
        "velocidade": sum(1 for c in validas_comerciais if c["primeira_resposta_seg"] is not None
                          and c["primeira_resposta_seg"] <= LIMIAR_RESPOSTA_SEG) / n,
        "followup": 1.0 - (sum(1 for c in validas_comerciais if c["token"] in spammers) / n),
    }
    score = score_bizz_gold(eixos)

    n_c = len(validas_comerciais)
    n_f = sum(1 for c in validas_comerciais if c["conversao"] == "fechou")
    n_nc = n_c - n_f
    n_g = len(fantasmas)
    t = (n_f / n_c) if n_c else 0.0
    recebidos = [c for c in conversas if c["token"] in spammers]
    responderam = [c for c in recebidos if any(m.get("de") == "paciente" for m in c["mensagens"])]
    r = (len(responderam) / len(recebidos)) if recebidos else 0.0
    k = (n_nc * t) + (n_g * t * r)
    sensibilidade = _sensitivity_table(k, n_nc)

    medicos_invasao, n_msg_medico = [], 0
    for c in conversas:
        for m in c["mensagens"]:
            if m.get("de") != "clinica":
                continue
            med = _medico_autodeclarado(_txt(m))
            if med:
                n_msg_medico += 1
                canonico = "Dra. Larissa" if med == "Larissa" else "Dr. Raphael"
                if canonico not in medicos_invasao:
                    medicos_invasao.append(canonico)

    friccoes = Counter()
    for c in conversas:
        for f in c["friccao"]:
            friccoes[f] += 1

    n_audio = sum(c["n_audio_clinica"] + c["n_audio_paciente"] for c in conversas)
    n_total_msgs = sum(len(c["mensagens"]) for c in conversas)
    cobertura = round(100 * (1 - (n_audio / n_total_msgs)), 1) if n_total_msgs else 100.0

    ops = defaultdict(lambda: {"n": 0, "fechou": 0, "spam": 0})
    for c in validas_comerciais:
        o = c["quem"]
        ops[o]["n"] += 1
        if c["conversao"] == "fechou":
            ops[o]["fechou"] += 1
        if o in fontes_spam:
            ops[o]["spam"] += 1
    team = []
    for nome, x in ops.items():
        nn = x["n"]
        taxa = round(100 * x["fechou"] / nn, 1) if nn else 0.0
        if x["spam"] > 0 and taxa < 20:
            flaw = "Follow-up robótico + ausência de qualificação"
        elif x["spam"] > 0:
            flaw = "Follow-up robótico (mensagens em massa)"
        elif taxa >= 40:
            flaw = "Nenhuma falha fatal detectada"
        elif taxa >= 20:
            flaw = "Despejo de tabela sem ancoragem de valor"
        else:
            flaw = "Alta latência + ausência de contorno de objeção"
        team.append({
            "name": nome, "commercial_conversion_rate": taxa,
            "primary_fatal_flaw": flaw, "spam_detected": x["spam"] > 0,
            "cross_selling_attempts": 0,
        })

    ordem_proc = {"cirurgia": 5, "clareamento": 4, "implante": 3, "preenchimento": 2,
                  "botox": 1, "limpeza_pele": 0, "avaliacao": 0, "indefinido": 0}
    resgate = [c for c in validas_comerciais if c["conversao"] != "fechou"]
    resgate.sort(key=lambda c: -ordem_proc.get(c["procedimento"], 0))
    leads_resgate = []
    for c in resgate[:5]:
        leads_resgate.append({
            "lead_hash": _anom(c["nome"], c["token"]),
            "procedure_interest": c["procedimento"],
            "drop_reason": ("objeção não tratada" if c["objecoes"] else "em aberto sem desfecho"),
            "suggested_recovery_script": (
                "[NOME], aqui é a recepção da clínica. Vi que você tinha interesse e acabou "
                "sem retorno — quero resolver com prioridade. A doutora vai te chamar "
                "pessoalmente pra uma avaliação técnica do seu caso, sem compromisso. "
                "Posso encaixar você amanhã?"
            ),
        })

    telemetria = {
        "audit_metadata": {
            "total_chats_parsed": len(conversas),
            "commercial_tickets_isolated": n_c,
            "administrative_tickets_ignored": len(administrativos),
            "ghost_and_noise": len(fantasmas) + len(ruidos),
            "score_bizz_gold_overall": score,
            "cobertura_analitica_pct": cobertura,
        },
        "financial_leakage": {
            "commercial_leads_lost": n_nc,
            "constants": {"N_c": n_c, "N_f": n_f, "N_nc": n_nc, "N_g": n_g,
                          "t": round(t, 4), "r": round(r, 4)},
            "formula_exposed": "E = N_nc × T",
            "formula_recoverable": "R = k × T",
            "multiplier_k": round(k, 4),
            "sensitivity_table": sensibilidade,
            "ltv_confidence": "Baixo (Nível 4 — sem tabela/faturamento da clínica; T permanece variável)",
        },
        "operator_performance": team,
        "governance_and_mrr": {
            "doctors_in_support_role": medicos_invasao,
            "doctor_messages": n_msg_medico,
            "clinic_induced_friction_events": dict(friccoes.most_common()),
            "patients_at_churn_risk": 0,
        },
        "leads_for_immediate_rescue": leads_resgate,
        "_spam_messages": dict(spam_contagem.most_common(10)),
        "_score_eixos": {k: round(v * 100, 1) for k, v in eixos.items()},
    }

    dossie_direcao, dossie_equipe = _gerar_dossies(validas_comerciais, fantasmas, administrativos,
                                                   ruidos, score, eixos, telemetria, team,
                                                   medicos_invasao, n_msg_medico, friccoes,
                                                   cobertura, k, n_nc)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "telemetria.json").write_text(json.dumps(telemetria, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "dossie_direcao.md").write_text(dossie_direcao, encoding="utf-8")
    (out_dir / "dossie_equipe.md").write_text(dossie_equipe, encoding="utf-8")
    return telemetria


def _gerar_dossies(validas, fantasmas, adm, ruidos, score, eixos, tel, team,
                   medicos, n_msg_medico, friccoes, cobertura, k, n_nc):
    eixos_ord = sorted(eixos.items(), key=lambda x: x[1])
    eixos_txt = "\n".join(f"- {nome}: **{round(v*100,1)}/100**" for nome, v in eixos_ord)

    t = tel["financial_leakage"]["constants"]["t"]
    hemo = (f"**{n_nc} leads comerciais não convertidos × ticket médio (T).** "
            f"Com a taxa de conversão de {round(t*100,1)}% que a própria operação já pratica, "
            f"o recuperável é **k × T = {round(k,4)} × T**. Se o ticket médio for R$ 2.500, "
            f"o recuperável é ~R$ {round(k*2500):,} — mas o ticket é seu: confira a tabela de "
            f"sensibilidade na telemetria.")

    fric_txt = ", ".join(f"{k} ({v})" for k, v in friccoes.most_common()) or "nenhuma detectada"

    dossie_direcao = f"""# Dossiê Executivo — Protocolo Blind-Audit™

> **Documento confidencial — não distribuir à equipe de atendimento.**

## I. Abismo Financeiro (Receita em Aberto sem Próximo Passo — Hemorragia Invisível™)

{hemo}

## II. Raio-X Operacional e Fricção de Base

{chr(10).join(f"- **{x['name']}**: conversão {x['commercial_conversion_rate']}%{' · 🚨 SPAM' if x['spam_detected'] else ''}. *{x['primary_fatal_flaw']}*." for x in team)}

## III. Invasão Médica e Fricção da Clínica

- Invasão médica: {", ".join(medicos) if medicos else "não detectada"} ({n_msg_medico} mensagens de médico assumindo atendimento).
- Fricção da gestão: **{fric_txt}** — responsabilidade da gestão, não da recepção.

## IV. Matriz de Resgate High-Ticket™

{chr(10).join(f"- **{l['lead_hash']}** ({l['procedure_interest']}) — {l['drop_reason']}: _{l['suggested_recovery_script']}_" for l in tel['leads_for_immediate_rescue'])}

## V. Score Bizz-Gold™: {score}/100 (Índice de Aderência a Protocolo)

{eixos_txt}

## VI. Playbook de Correção (SPIN Scripts)

- **Síndrome do Balcão** (cotar sem qualificar): "Antes de valores, me conta: há quanto tempo isso te incomoda e o que você já tentou?"
- **Objeção de terceiro decisor**: "Entendo que a decisão é conjunta — que tal eu já agendar uma avaliação e você vem com ele?"

## Cobertura analítica

Este laudo enxerga **{cobertura}%** das interações (áudio/mídia não transcrito é ponto cego declarado). Amostra: {len(validas)} comerciais válidas · {len(adm)} administrativas · {len(fantasmas)} fantasmas · {len(ruidos)} ruído.
"""

    dossie_equipe = f"""# Treinamento de Recepção — Oportunidades de Receita (versão equipe)

> Material de treinamento. Sem nomes, sem vigilância — isto é uma ferramenta de ganho, não de cobrança.

## O que encontramos (agregado, sem apontar pessoas)

- {n_nc} conversas comerciais ficaram sem desfecho — receita que a operação pode destravar.
- A operação converte {round(t*100,1)}% das conversas comerciais válidas. Cada ponto de conversão recuperado vale o ticket médio (T) de cada lead.
- Prioridades de treinamento (eixos mais fracos): **{", ".join(nome for nome, _ in eixos_ord[:2])}**.

## As 3 ferramentas da semana

1. **Qualificar antes de cotar** — entender a dor e o histórico antes de falar valor.
2. **Ancorar valor** — explicar o que está incluído e a autoridade médica antes do preço.
3. **Pedir o fechamento** — oferecer horário concreto com duas opções reais.

## Cobertura

Este material enxerga **{cobertura}%** das interações (áudio/mídia é ponto cego reconhecido).
"""

    return dossie_direcao, dossie_equipe


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clinica", required=True)
    ap.add_argument("--vault", default="./vault")
    ap.add_argument("--metrics", default="./metrics")
    ap.add_argument("--out", default="./forense")
    a = ap.parse_args()
    t = rodar(a.clinica, Path(a.vault), Path(a.metrics), Path(a.out))
    print(json.dumps({
        "telemetria": str(Path(a.out) / "telemetria.json"),
        "dossie_direcao": str(Path(a.out) / "dossie_direcao.md"),
        "dossie_equipe": str(Path(a.out) / "dossie_equipe.md"),
        "score_bizz_gold": t["audit_metadata"]["score_bizz_gold_overall"],
        "multiplier_k": t["financial_leakage"]["multiplier_k"],
        "cobertura_analitica": t["audit_metadata"]["cobertura_analitica_pct"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
