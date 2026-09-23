# bizz.ia — Pipeline de Auditoria de Conversão WhatsApp (Blind-Audit™)

Pipeline completo da bizz.ia: extração forense de conversas do WhatsApp Web (via Edge
logado), cofre pseudonimizado (LGPD), motor forense de análise (Core Engine v3.1 — paramétrico),
dashboard e dossiê executivo — sem PII em claro fora do cofre.

**Princípio do projeto: a extração exemplar é a RAIZ.** Dados brutos depurados e
confirmados vêm primeiro; a análise é camada secundária. Fidedignidade é fundamental.

## Arquitetura (6 estágios)

```
Edge logado (WhatsApp Web)
   │  CDP (leitura passiva, comportamento humano)
   ▼
[1] extrator_cdp.js ──► conversas.jsonl (texto cru, temporário, local)
   │
   ▼
[2] anonimizador.py ──► cofre cifrado (vault/) + métricas (metrics/)
   │
   ▼
[3] treino_export.py ──► pares de treino mascarados (train/)
   │
   ▼
[4] motor_forense.py ──► forense/telemetria.json + dossie_direcao.md + dossie_equipe.md  (Core Engine v3.1)
   │
   ▼
[5] gerar_dashboard.py ──► dashboard_bizzia.html (logo + paleta + subdivisão)
```

`rodar.ps1` roda as 6 etapas de uma vez (anonimizar → treino → verify → forense →
dashboard → resumo).

## Garantia central de fidedignidade

- O extrator **força a página a se reportar visível** (`visibilityState=visible`) — sem
  isso o WhatsApp pausa o carregamento da lista quando a aba fica oculta.
- Rola a **sidebar** e o **chat** de forma **incremental**, acumulando tudo: a lista
  lateral (conversas) e o histórico completo de cada conversa (mensagens). Antes havia
  truncamento: só a janela visível (~30 msgs) era capturada, perdendo o meio.
- **Correção de autoria por texto** (não confia na tag): o clássico "chamou a médica de
  paciente" é revertido. Médico só conta quando **se identifica de forma tácita, clara e
  inequívoca** ("Aqui é a Dra."); menção genérica fica como recepção.
- **Dedup por nome normalizado** (ignora acento/espaço) — evita re-extração.
- O texto cru existe apenas (1) em memória e (2) cifrado no cofre. Fora dele, só tokens,
  métricas e texto mascarado.

## Saídas

| Caminho | Conteúdo |
|---|---|
| `vault/<clinica>/` | cofre cifrado AES-256-GCM + `audit.log` (hash chain) |
| `metrics/<clinica>/conversas.jsonl` | métricas (latência, conversão, objeções, procedimento) |
| `train/<clinica>/pares.jsonl` | pares de treino com PII mascarada |
| `forense/telemetria.json` | Raw Forensic Telemetry v3.2 (score 6 eixos, autoria semântica em 3 campos, hemorragia paramétrica k×T, team) |
| `forense/dossie_direcao.md` | Dossiê Executivo (nominal) — **NÃO distribuir à equipe** |
| `forense/dossie_equipe.md` | Material de treino da equipe (anônimo, sem nomes) |
| `dashboard_bizzia.html` | painel visual (logo + paleta BIZZ.IA) |

## Motor Forense (Core Engine v3.2 Canônico) — `motor_forense.py`

5 fases: (1) Triagem (autoria em 3 campos + **camada 1 densidade**: fantasma/ruído/válida + camada 2: comercial vs administrativo); (2) Chronos (latência, fricção da clínica, invasão médica); (3) Forensic Psych (SPIN, ancoragem, objeções, CTA, detector de spam); (4) Econométrico (Score 6 eixos + Receita em Aberto paramétrica $R = k \times T$); (5) Geração Dual de Entregáveis.

- **Autoria em 3 Campos**: `autoria_origem` (tag da exportação), `autoria_efetiva` (inferência semântica), `motivo_correcao` (verbatim).
- **Score Bizz-Gold™ = 6 eixos** — qualificação 24% + valor/ancoragem 16% + contorno de
  objeção 22% + condução ao fechamento 18% + velocidade 12% + follow-up 8% (penaliza spam).
- **Receita em Aberto sem Próximo Passo (Hemorragia Invisível™) = FÓRMULA paramétrica**, nunca número absoluto: `R = k × T`, onde
  `k` é fato do corpus (constantes N_c, N_f, N_nc, N_g, t, r) e `T` é o ticket da clínica
  (variável — ver tabela de sensibilidade). Proibido arbitrar LTV (Módulo 11-A).
- **Dupla saída** — `dossie_direcao.md` (nominal, confidencial) e `dossie_equipe.md`
  (anônima, para treino). Nunca entregar a nominal à equipe.
- **Ponto cego declarado** — % de cobertura analítica (áudio/mídia não transcrito).
- **Spam** = mensagens idênticas da clínica para ≥5 leads (broadcast). Atribuído à fonte
  real (Carla/Maria se assinaram; senão "recepção genérica", nunca o médico).
- **Invasão Médica™** = médico se identificando e assumindo atendimento (ineficiência da
  recepção).

## Instalação

```bash
pip install cryptography
npm install ws            # só se testar-seletores.js reclamar
node --version            # 18+
```

Gere a `master.key` (uma por clínica; nunca exponha, nunca copie entre clínicas):

```powershell
python -c "from cryptography.hazmat.primitives.ciphers.aead import AESGCM; import base64,pathlib; pathlib.Path('master.key').write_bytes(base64.b64encode(AESGCM.generate_key(bit_length=256)))"
$env:BIZZ_MASTER_KEY_FILE="$PWD\master.key"
```

## Uso (resumo)

```powershell
node extrator_cdp.js --port 9222 --out conversas.jsonl --max 150 --operador recepcao_1 --soPacientes true --horaFim 22:00
# limpar duplicatas (normalizado) — ver PROMPT_HERMES.md
.\rodar.ps1        # anonimizar + treino + verify + forense + dashboard
Remove-Item conversas.jsonl   # só após processamento OK
```

## Personalizar por clínica

1. **ID da clínica** — troque `clin_demo` em todos os comandos.
2. **Médicos** — `MEDICO_DERMATO` / `MEDICO_NUTRO` em `gerar_dashboard.py` + `RE_MEDICOS`
   em `extrator_cdp.js` (quem EXCLUIR da extração).
3. **Atendentes** — `RE_SIG_CARLA` / `RE_SIG_MARIA` em `motor_forense.py` (assinaturas).
4. **Pesos do score (6 eixos) / tabela de sensibilidade** — `PESOS` e `T_SENSIBILIDADE`
   no topo de `motor_forense.py`.
5. **`master.key`** — gere UMA nova por clínica.

## Segurança — garantias verificadas por teste

`python tests/test_seguranca.py` prova: nenhuma PII em claro fora do cofre; blobs
ilegíveis; chave errada não decifra; audit log detecta adulteração; token não
correlaciona entre clínicas.

## Travas de segurança do extrator (nunca desative)

Expediente 8h-22h seg-sex · limite diário 150 · detecção de bloqueio a cada conversa ·
mouse real (trajeto curvo) · leitura passiva (nunca envia/altera/apaga). Se o WhatsApp
avisar limitação, para sozinho (exit 2) — não insistir no mesmo dia.

## Documentação relacionada

- `PROMPT_HERMES.md` — prompt operacional completo (colar em sessão futura).
- `ESQUEMA.md` — esquema de dados (cofre, métricas, treino).
- `Master_Prompt_Blind-Audit_v3.1.pdf` / `Estratégia e Prompt para o Projeto Broken.pdf` — specs do produto.
- Skill Hermes `whatsapp-business-audit` — conhecimento operacional (pitfalls CDP, motor forense, atribuição de médico/atendente).
