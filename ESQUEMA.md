# bizz.ia — Esquema de Dados do Pipeline

## Modelo de confiança
- Clínica = CONTROLADORA. bizz.ia = OPERADORA.
- Chave-mestra no KMS (bizz.ia), com auditoria. Envelope: master key -> data key por clínica.
- Texto cru SÓ existe em: (1) memória durante processamento, (2) dentro do cofre cifrado.
- Fora do cofre, em disco: apenas tokens (hash), métricas agregadas e o audit log.

## Diretórios
```
vault/
  <clinica_id>/
    keys/
      <key_id>.enc          # data key cifrada pela master key (envelope)
    blobs/
      <token>.enc           # AES-256-GCM: payload da conversa
    index.json              # token -> metadados NAO sensiveis (operador, ts, contagens)
    audit.log               # append-only, hash-chained: toda leitura/escrita
metrics/
  <clinica_id>/
    conversas.jsonl         # 1 linha por conversa: metricas derivadas, so token
    operadores.json         # agregado por operador (nome real, NAO e dado de paciente)
    score_bizz_gold.json
train/
  <clinica_id>/
    pares.jsonl             # pares de treino extraidos; SEM texto cru, SEM reidentificador
forense/
  telemetria.json           # BLOCO 1: Raw Forensic Telemetry (score, hemorragia, team, invasao medica)
  dossie.md                 # BLOCO 2: Dossie Executivo de Intervencao (5 secoes)
dashboard_bizzia.html       # painel visual (logo + paleta + subdivisao destino/quem/terceira-via)
```

## Token do contato
token = base32( SHA-256( clinica_salt || contact_id ) )[:26]

- `clinica_salt` é um segredo por clínica, guardado no cofre.
- Sem o salt, o token não é reversível nem correlacionável entre clínicas.
- O mapping token -> contact_id fica DENTRO do cofre (campo `mapping`), nunca no index.

## Registro no cofre (blob)
```json
{
  "token": "XXXX...",
  "clinica_id": "clin_abc",
  "contact_id": "5511...",        // so existe cifrado
  "contato_nome": "Maria S.",     // so existe cifrado
  "operador": "recepcao_1",
  "mensagens": [
    {"ts": 1750000000, "de": "paciente|clinica", "texto": "...", "tem_midia": false}
  ],
  "capturado_em": "2026-09-16T20:00:00Z"
}
```

## Metrica derivada (fora do cofre) — metrics/conversas.jsonl
```json
{
  "token": "XXXX...",
  "operador": "recepcao_1",
  "n_msg_paciente": 7,
  "n_msg_clinica": 5,
  "primeira_resposta_seg": 142,
  "latencia_media_seg": 380,
  "gap_max_seg": 7200,
  "conversao": "fechou|perdeu|indefinido",
  "objecoes": ["preco", "horario"],
  "procedimento": "botox",
  "tempo_total_dias": 3,
  "n_followups": 1
}
```

## Par de treino (train/pares.jsonl) — SEM texto cru
```json
{
  "tarefa": "estilo_resposta|classe_objecao|qualidade_ancoragem",
  "entrada": "<texto do paciente MASCARADO: PII->[PII], procedimento generalizado>",
  "saida": "<resposta ideal segundo playbook, ou rótulo>",
  "rotulo": "...",
  "origem_token": "XXXX...",
  "operador_fora": true
}
```
Regra: o par de treino nunca contém nome, telefone, valor exato, data exata, nem
qualquer campo que reidentifique. O `origem_token` serve para auditoria, e é resolvido
só via cofre (com log), nunca no dataset.

## Audit log (hash chain)
linha[n] = {ts, ator, acao, alvo, detalle}
hash[n] = SHA-256(hash[n-1] || json(linha[n]))
Qualquer alteração quebra a cadeia -> detectável.
