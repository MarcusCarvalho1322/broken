"""
anonimizador.py — Recebe conversas cruas do extrator, grava no cofre e emite
SOMENTE metricas derivadas para fora.

Regra de ouro: o texto cru entra, vira blob cifrado no cofre, e o resto do pipeline
nunca o ve. O que sai daqui em claro sao numeros, rotulos e o token.

Uso:
  python anonimizador.py --clinica clin_demo --entrada conversas.jsonl \
      --vault ./vault --metricas ./metrics
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cofre import Vault, now_iso

# ---------------------------------------------------------------- heuristica

PRECO_RE = re.compile(r"R\$\s?[\d\.\,]+|r\$\s?[\d\.\,]+", re.I)
HORARIO_RE = re.compile(r"\b([01]?\d|2[0-3])(:\d{2}|h\d{2})\b")
TELEFONE_RE = re.compile(r"\b(?:\+?55\s?)?\(?\d{2}\)?\s?9?\d{4}[\s-]?\d{4}\b")
EMAIL_RE = re.compile(r"[\w\.-]+@[\w\.-]+\.\w+")
NOME_PROPRIO_RE = re.compile(r"\b[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]{2,}\b")

OBJECOES = {
    "preco": ["caro", "valor", "preço", "custa", "quanto", "investimento", "parcelar"],
    "horario": ["horário", "horario", "agenda", "disponível", "disponivel", "vaga"],
    "medo": ["medo", "dor", "dói", "doi", "risco", "insegura", "receio"],
    "tempo": ["tempo", "demora", "rápido", "rapido", "recuperação", "recuperacao"],
    "indecisao": ["vou pensar", "depois", "mais pra frente", "ver com", "me informar"],
}

PROCEDIMENTOS = {
    "botox": ["botox", "botulínica", "botulinica", "toxina"],
    "preenchimento": ["preenchimento", "ácido hialurônico", "acido hialuronico", "harmonização"],
    "limpeza_pele": ["limpeza de pele", "peeling", "hidratação"],
    "implante": ["implante", "coroa", "prótese", "protese"],
    "clareamento": ["clareamento", "lentes de contato dental", "faceta"],
    "cirurgia": ["cirurgia", "lipo", "abdominoplastia", "rinoplastia"],
    "avaliacao": ["avaliação", "avaliacao", "consulta", "orçamento"],
}

# Palavras frequentes do portugues que NAO sao nomes proprios. Evita que
# capitalizadas no inicio de periodo virem [NOME] por engano.
PALAVRAS_FREQUENTES = set("""
quer quero queria pode poderia posso podemos gostaria tenho temos tem
vou vamos vai preciso precisa consigo consegue faz fazemos fazer foi ser sou
estou estamos está estão ficou fica achei acho entendi entendo obrigado obrigada
sim nao não claro certo tudo bem bom boa olá ola oi aqui então entao mas por
qual quando como quanto onde quem que se para com sem sobre depois antes
agora hoje amanha amanhã ontem segunda terca terça quarta quinta sexta sabado
sábado domingo janeiro fevereiro março marco abril maio junho julho agosto
setembro outubro novembro dezembro ainda tambem também já ja só so mais menos
muito pouco sempre nunca talvez atende atendem atender agendar agendo marcou
marcar confirmo confirmado valor preco preço horario horário disponivel
disponível vaga consulta avaliacao avaliação procedimento tratamento resultado
""".split())

CONVERSAO_FECHOU = ["agendado", "agendei", "confirmado", "confirmo", "marcado", "vou comparecer", "pode agendar"]
CONVERSAO_PERDEU = ["não vou", "nao vou", "desisti", "deixa pra depois", "outra clínica", "outra clinica", "obrigado, mas"]

# Horario comercial de atendimento (default 08h-19h, seg-sex). Fora disso, a
# latencia nao deve penalizar o operador: o paciente escreveu quando a clinica dormia.
HORA_INICIO, HORA_FIM = 8, 19
TZ_OFFSET_H = -3  # America/Sao_Paulo (ajuste conforme a clinica)


def _lower_all(mensagens: list[dict]) -> str:
    return " ".join(m.get("texto", "") for m in mensagens).lower()


def _expediente_segundos(ts_inicio: int, ts_fim: int) -> int:
    """Segundos transcorridos ENTRE ts_inicio e ts_fim que cairam no expediente.

    Uma mensagem que chega 23h e e respondida 8h30 nao gera latencia de 9h:
    gera ~30min de expediente. Preserva o intervalo real de trabalho em segundos.
    """
    import time as _t

    if ts_fim <= ts_inicio:
        return 0
    total = 0
    cur = ts_inicio
    passo = 1800  # amostragem de 30min
    while cur < ts_fim:
        hora = _t.gmtime(cur + TZ_OFFSET_H * 3600)
        if hora.tm_wday < 5 and HORA_INICIO <= hora.tm_hour < HORA_FIM:
            total += min(passo, ts_fim - cur)
        cur += passo
    return total


def classificar_metrica(conversa: dict) -> dict:
    msgs = conversa.get("mensagens", [])
    txt = _lower_all(msgs)

    objecoes = [k for k, kws in OBJECOES.items() if any(w in txt for w in kws)]
    procedimentos = [k for k, kws in PROCEDIMENTOS.items() if any(w in txt for w in kws)]

    if any(w in txt for w in CONVERSAO_FECHOU):
        conversao = "fechou"
    elif any(w in txt for w in CONVERSAO_PERDEU):
        conversao = "perdeu"
    else:
        conversao = "indefinido"

    pac = [m for m in msgs if m.get("de") == "paciente"]
    cli = [m for m in msgs if m.get("de") == "clinica"]

    primeira_resp = None
    lat_amostra: list[int] = []
    gap_max = 0
    ultimo_pac = None
    for m in msgs:
        ts = m.get("ts")
        if not isinstance(ts, (int, float)):
            continue
        if m.get("de") == "paciente":
            ultimo_pac = ts
        elif m.get("de") == "clinica" and ultimo_pac is not None:
            # latencia em SEGUNDOS DE EXPEDIENTE, nao em relogio de parede
            d = _expediente_segundos(ultimo_pac, ts)
            if d >= 0:
                lat_amostra.append(d)
                if primeira_resp is None:
                    primeira_resp = d
                gap_max = max(gap_max, d)
            ultimo_pac = None

    tempo_total_dias = 0
    # algumas mensagens vem sem ts (sem data-pre-plain-text): ignora nulos
    timestamps = [m.get("ts") for m in msgs if isinstance(m.get("ts"), (int, float))]
    if len(timestamps) >= 2:
        span = max(timestamps) - min(timestamps)
        tempo_total_dias = round(span / 86400, 2)

    n_followups = 0
    prev_cli = None
    for m in msgs:
        ts = m.get("ts")
        if m.get("de") == "clinica" and isinstance(ts, (int, float)):
            if prev_cli is not None and ts - prev_cli > 3600 * 12:
                n_followups += 1
            prev_cli = ts

    return {
        "token": conversa.get("token"),
        "operador": conversa.get("operador", "nao_informado"),
        "n_msg_paciente": len(pac),
        "n_msg_clinica": len(cli),
        "primeira_resposta_seg": primeira_resp,
        "latencia_media_seg": round(sum(lat_amostra) / len(lat_amostra)) if lat_amostra else None,
        "gap_max_seg": gap_max or None,
        "conversao": conversao,
        "objecoes": objecoes,
        "procedimento": procedimentos[0] if procedimentos else "indefinido",
        "tempo_total_dias": tempo_total_dias,
        "n_followups": n_followups,
    }


def mascarar_texto(texto: str) -> str:
    """Remove/reduz PII de um trecho antes de virar dado de treino.

    Ordem importa: primeiro os padroes estruturados (tel/email/valor/hora),
    depois os nomes proprios, que sao o vetor mais facil de reidentificar.
    """
    t = TELEFONE_RE.sub("[TEL]", texto)
    t = EMAIL_RE.sub("[EMAIL]", t)
    t = PRECO_RE.sub("[VALOR]", t)
    t = HORARIO_RE.sub("[HORA]", t)
    t = mascarar_nomes(t)
    return t


def mascarar_nomes(texto: str) -> str:
    """Substitui nomes proprios por [NOME] sem destruir palavras comuns.

    Armadilhas tratadas:
      - 'Boa noite' NAO e nome -> exigimos que a palavra nao seja inicio de frase
        comum/exclamacao e nao esteja numa whitelist de saudacoes.
      - 'Dra. Ana' -> 'Dra. [NOME]' (preserva o titulo, que e sinal de tecnica).
      - nomes em qualquer posicao, precedidos de 'é', 'sou', 'aqui é', etc.
    """
    # 1) titulos medicos: preserva titulo, mascara o nome
    texto = re.sub(
        r"\b(Dra?\.?|Doutora?)\s+([A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+)",
        r"\1 [NOME]",
        texto,
    )

    # 2) nomes "nus": so mascara se a palavra NAO for saudacao/palavra comum.
    comuns = {
        "Boa", "Bom", "Oi", "Ola", "Olá", "Tudo", "Bem", "Gostaria", "Queria",
        "Preciso", "Pode", "Poderia", "Bom", "Aqui", "Obrigado", "Obrigada",
        "Meu", "Minha", "Qual", "Quando", "Como", "Quanto", "Vou", "Sim", "Nao",
        "Não", "Acho", "Achei", "Entendo", "Segunda", "Terca", "Terça", "Quarta",
        "Quinta", "Sexta", "Sabado", "Sábado", "Domingo", "Janeiro", "Fevereiro",
        "Marco", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro",
        "Outubro", "Novembro", "Dezembro", "Hoje", "Amanha", "Amanhã", "Ontem",
        "Valor", "Preco", "Preço", "Horario", "Horário", "Clínica", "Clinica",
    }

    # termos de dominio clinico: NUNCA sao PII, e sao sinais de treino valiosos
    dominio = {
        "Botox", "Preenchimento", "Peeling", "Limpeza", "Implante", "Clareamento",
        "Lentes", "Facetas", "Harmonizacao", "Harmonização", "Toxina", "Botox",
        "Rinoplastia", "Lipo", "Abdominoplastia", "Protese", "Prótese", "Coroa",
        "Avaliacao", "Avaliação", "Consulta", "Orçamento", "Orcamento", "Protocolo",
        "WhatsApp", "Pix", "Cartao", "Cartão", "Boleto", "Doutor", "Doutora",
        "SPIN", "Neurovendas",
    }
    comuns = comuns | dominio

    def _sub(m: re.Match) -> str:
        palavra = m.group(0)
        if palavra in comuns:
            return palavra
        # verbos/palavras frequentes iniciando periodo: nao sao nomes
        if palavra.lower() in PALAVRAS_FREQUENTES:
            return palavra
        # nome precedido de contexto que indica pessoa
        inicio = m.start()
        antes = texto[max(0, inicio - 24):inicio].lower()
        marcadores = ("nome é ", "nome e ", "sou ", "aqui é ", "aqui e ", "é o ", "é a ",
                      "com a ", "com o ", "falou ", "conversei com ")
        if any(antes.endswith(x) or x in antes[-14:] for x in marcadores):
            return "[NOME]"
        # palavra capitalizada no meio da frase tende a ser nome
        if inicio > 0 and texto[inicio - 1] not in ".!?\n":
            return "[NOME]"
        return palavra

    texto = NOME_PROPRIO_RE.sub(_sub, texto)
    # colapsa nomes repetidos e limpa pontuacao/espacos orfaos da substituicao
    texto = re.sub(r"(\[NOME\]\s*)+", "[NOME] ", texto)
    texto = re.sub(r"\[\s*\.\s*\]", "[NOME]", texto)
    texto = re.sub(r"\s+\.", ".", texto)
    texto = re.sub(r"\s+([,!?])", r"\1", texto)
    texto = re.sub(r"\[NOME\]\s*\.", "[NOME]", texto)
    texto = re.sub(r"\s{2,}", " ", texto)
    return texto.strip()


# ---------------------------------------------------------------- pipeline


def processar(clinica: str, entrada: Path, vault_dir: Path, metricas_dir: Path) -> dict:
    v = Vault(vault_dir, clinica)
    out = metricas_dir / clinica
    out.mkdir(parents=True, exist_ok=True)
    mfile = out / "conversas.jsonl"

    n = 0
    # encoding="utf-8" e obrigatorio: o Windows usa cp1252 por padrao e quebra
    # com acentos do portugues. errors="replace" evita travar com byte corrompido.
    with entrada.open(encoding="utf-8", errors="replace") as fin, \
         mfile.open("a", encoding="utf-8") as fout:
        for line in fin:
            if not line.strip():
                continue
            conv = json.loads(line)
            blob = {
                "clinica_id": clinica,
                "contact_id": conv.get("contact_id") or conv.get("contato_nome", ""),
                "contato_nome": conv.get("contato_nome", ""),
                "operador": conv.get("operador"),
                "mensagens": conv.get("mensagens", []),
                "capturado_em": conv.get("capturado_em") or now_iso(),
            }
            token = v.put(blob)
            conv = {**conv, "token": token}
            met = classificar_metrica(conv)
            fout.write(json.dumps(met, ensure_ascii=False) + "\n")
            n += 1

    v.audit.append("bizz.ia", "processar", clinica, f"{n} conversas importadas")
    return {"conversas": n, "metricas": str(mfile)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clinica", required=True)
    ap.add_argument("--entrada", required=True)
    ap.add_argument("--vault", default="./vault")
    ap.add_argument("--metricas", default="./metrics")
    a = ap.parse_args()
    r = processar(a.clinica, Path(a.entrada), Path(a.vault), Path(a.metricas))
    print(json.dumps(r, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
