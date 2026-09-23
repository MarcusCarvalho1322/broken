# PROMPT PARA O AGENTE HERMES — Auditoria bizz.ia (Protocolo Action Plan)

Você é um agente de execução técnica. Conduza a extração das conversas de WhatsApp
da clínica cliente, de ponta a ponta, de forma automática, segura e anonimizada,
no computador local onde o Edge está logado no WhatsApp Web.

**Você não precisa de administrador. Nunca envie mensagens. Nunca altere nada.
Apenas leia, extraia, processe e reporte.**

---

## PERSONALIZAR POR CLÍNICA (antes de começar)

Ao usar este pipeline numa clínica NOVA, troque **apenas** estes pontos:

1. **ID da clínica** — troque `clin_demo` pelo id da nova clínica em TODOS os comandos
   (`cofre.py init`, `anonimizador.py`, `treino_export.py`, `gerar_dashboard.py`).
2. **Médicos da clínica** — em `gerar_dashboard.py`, ajuste `MEDICO_DERMATO` e
   `MEDICO_NUTRO` para os nomes reais (ou adicione mais especialidades).
3. **Filtro de médicos no extrator** — em `extrator_cdp.js` (`RE_MEDICOS`), troque os
   nomes dos médicos a **excluir** da extração (nunca extrair conversa de médico).
4. **`master.key`** — gere UMA nova por clínica (comando na seção 1). Não copie a de outra
   clínica: cada cofre é independente.
5. **Atendentes da recepção** — em `motor_forense.py`, ajuste `RE_SIG_CARLA` / `RE_SIG_MARIA`
   para as assinaturas reais (padrão: "Aqui é a [nome], Hostess de Boas Vindas..."). É o que
   habilita a atribuição individual (quem atendeu) no Motor Forense e no dossiê.

---

## 0. CAMINHOS E VARIÁVEIS

Pasta de trabalho:
```
C:\Users\marcu\Documents\PROJETO BREAK\BIZZ.IA PIPELINE BROKEN\bizz
```

Todo comando é executado dentro dessa pasta, no PowerShell. O caminho tem espaços,
então sempre use aspas ao navegar:
```
cd "C:\Users\marcu\Documents\PROJETO BREAK\BIZZ.IA PIPELINE BROKEN\bizz"
```

Arquivos do pipeline (devem estar na pasta):
- `extrator_cdp.js` — extrai as conversas do WhatsApp Web
- `testar-seletores.js` — valida a leitura de 1 conversa
- `cofre.py` — cofre cifrado (AES-256-GCM)
- `anonimizador.py` — gera métricas + grava no cofre
- `treino_export.py` — gera pares de treino mascarados
- `gerar_dashboard.py` — monta o dashboard com logo + paleta + subdivisão (médico / quem atendeu / terceira via)
- `dashboard_template.html` + `assets/logo.png` — identidade visual do dashboard
- `rodar.ps1` — roda as 6 etapas (anonimizar, treino, verify, motor forense, dashboard, resumo)
- `master.key` — chave do cofre (NUNCA apagar, NUNCA expor)

---

## 1. VERIFICAÇÕES INICIAIS

Rode e confirme:

```powershell
cd "C:\Users\marcu\Documents\PROJETO BREAK\BIZZ.IA PIPELINE BROKEN\bizz"
node --version                 # >= 18
python --version               # >= 3.9
python -m pip show cryptography
dir
```

- Se faltar `cryptography`: `python -m pip install cryptography`
- Se faltar a lib `ws` (usada por testar-seletores.js): `npm install ws`
- Se faltar `master.key`, crie (UMA vez):
```powershell
python -c "from cryptography.hazmat.primitives.ciphers.aead import AESGCM; import base64,pathlib; pathlib.Path('master.key').write_bytes(base64.b64encode(AESGCM.generate_key(bit_length=256)))"
```
E defina a variável em TODA janela nova do PowerShell antes de usar o cofre:
```powershell
$env:BIZZ_MASTER_KEY_FILE="$PWD\master.key"
```

---

## 2. ABRIR O EDGE COM PORTA DE DEBUG

**Regra crítica:** nenhuma janela do Edge pode estar aberta, senão o parâmetro é
ignorado. O `--user-data-dir` explícito é obrigatório nas versões atuais do Edge.

```powershell
Stop-Process -Name msedge -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 4
Start-Process "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" -ArgumentList "--remote-debugging-port=9222","--remote-allow-origins=*","--user-data-dir=$env:LOCALAPPDATA\Microsoft\Edge\User Data","--profile-directory=Default"
Start-Sleep -Seconds 8
curl.exe http://127.0.0.1:9222/json/version
```

Deve retornar `"Browser": "Edg/..."`. Se não, tente o caminho sem `(x86)`:
`C:\Program Files\Microsoft\Edge\Application\msedge.exe`

Confirme que a aba do WhatsApp está acessível:
```powershell
curl.exe http://127.0.0.1:9222/json/list
```
Deve aparecer `"url": "https://web.whatsapp.com/"` com `"type": "page"`.

**Se pedir QR code:** o cliente precisa escanear uma vez (WhatsApp no celular →
Dispositivos conectados → Conectar dispositivo). Depois a sessão fica salva.

**Deixe a aba do WhatsApp ativa e visível** durante toda a extração. Não minimize a
janela nem troque de aba. Se a lista não renderizar, o extrator lê 0 conversas.

---

## 3. VALIDAR OS SELETORES

```powershell
node testar-seletores.js 0
```

Saída esperada: lista de conversas + mensagens da primeira, com `[clinica]` e
`[paciente]` alternando e datas. Se vier 0 mensagens, confirme que a conversa está
aberta na tela; se persistir, PARE e reporte (o WhatsApp mudou o HTML).

---

## 4. EXTRAÇÃO — CICLOS ATÉ COMPLETAR A META

**Meta: 150 conversas de pacientes.** O extrator já rola a lista sozinho, pula o que
já foi extraído (registro em `extraidas.json`) e trabalha em lotes aleatórios.

Comando:
```powershell
node extrator_cdp.js --port 9222 --out conversas.jsonl --max 150 --operador recepcao_1 --soPacientes true --horaFim 22:00
```

### Comportamento (sem padrão algum)
- Lote: 5 a 50 conversas, sorteado a cada ciclo
- Pausa ENTRE lotes: 4 a 14 min (longa)
- Pausa DENTRO do lote: 18 a 32s (curta)
- Delay por conversa: 4 a 9s
- Ritmo-alvo: 150 em ~2h
- Expede expediente: 8h até 22:00, seg-sex

### Filtros automáticos (o que NÃO é extraído)
- Médicos: Dr. Raphael e Dra. Larissa (qualquer variação do nome)
- Grupos: nomes com "grupo", "equipe", "scripts", "vendas", "orientações"
- Administração: Hotmart, secretaria, recepção, financeiro, internos
- Só entra: quem tem "Pct"/"Pcte"/"Paciente" no nome OU é número de telefone

### O WhatsApp só carrega conversas recentes na lista

O extrator já resolve isso sozinho: ele **força a página a se reportar visível**
(`visibilityState=visible`) — sem isso o WhatsApp pausa o carregamento da lista quando
a aba fica em segundo plano/minimizada — e rola a sidebar com `scrollTop` em passos
pequenos até o fim, pulando os já extraídos. Quando parar, leia o motivo no log:
"não há mais conversas antigas" = fim real da lista (a meta de 150 é só alvo; o total
de pacientes elegíveis costuma ser menor).

**Quando ele terminar antes da meta:**

1. Na janela do Edge de debug, **role a lista de conversas manualmente** até o fim
   (arraste a barra lateral de conversas para baixo, carregando os contatos antigos).
   Repita algumas vezes, com pausas — o WhatsApp carrega em blocos.
2. **Rode o mesmo comando de novo.** Ele pula os já extraídos e continua das novas.
3. Repita o ciclo (rolar → rodar) até o total acumulado chegar a 150.

**Como saber quantas já foram feitas:**
```powershell
python -c "import json; d=json.load(open('extraidas.json',encoding='utf-8')); print('extraidas:', len(d.get('extraidas',{})))"
```

**Sem pressa:** o limite diário é 150 e o audit de segurança é o mais importante.
Se o total passar do dia, continue no próximo dia útil — o progresso é salvo.

### Travas de segurança (NÃO desative)
| Trava | Valor |
|---|---|
| Expediente | 8h-22:00, seg-sex |
| Limite diário | 150 |
| Detecção de bloqueio | a cada conversa (para sozinho) |
| Mouse real | trajeto curvo, clique humanizado |
| Leitura passiva | nunca envia, nunca altera, nunca apaga |

**Se o WhatsApp exibir QUALQUER aviso de limitação, o extrator para sozinho
(exit code 2). Nesse caso, NÃO insista no mesmo dia. Reporte.**

---

## 5. LIMPAR O ARQUIVO DE CONVERSAS

O `conversas.jsonl` é **aditivo** e pode conter duplicatas de execuções anteriores.
Antes de processar, remova duplicatas mantendo a ocorrência mais recente de cada contato:

```powershell
python -c "import json,unicodedata; norm=lambda n: unicodedata.normalize('NFD',n).encode('ascii','ignore').decode().lower().strip(); ls=[json.loads(l) for l in open('conversas.jsonl',encoding='utf-8') if l.strip()]; u={}; [u.__setitem__(norm(c['contato_nome']), c) for c in ls]; open('conversas.jsonl','w',encoding='utf-8').write('\n'.join(json.dumps(v,ensure_ascii=False) for v in u.values())+'\n'); print('unicos:',len(u))"
```

---

## 6. PROCESSAR (anonimizar + métricas + treino + dashboard)

Na MESMA janela (a variável da chave precisa estar definida):

```powershell
$env:BIZZ_MASTER_KEY_FILE="$PWD\master.key"
# NÃO apague o cofre entre execuções: apagar + reinit PERDERIA os blobs já
# processados cujo texto cru foi apagado na etapa 7. O anonimizador faz append.
# Só rode init se o cofre ainda não existir (primeira execução).
if (-not (Test-Path "vault\clin_demo\salt.enc")) { python cofre.py init --clinica clin_demo --vault ./vault }
.\\rodar.ps1
```

O `rodar.ps1` faz:
1. `anonimizador.py` — grava no cofre cifrado + gera `metrics/clin_demo/conversas.jsonl`
2. `treino_export.py` — gera `train/clin_demo/pares.jsonl`
3. `cofre.py verify` — confere a integridade (deve dar `"integridade": true`)
4. `motor_forense.py` — gera `forense/telemetria.json` + `dossie_direcao.md` + `dossie_equipe.md`
5. `gerar_dashboard.py` — monta `dashboard_bizzia.html` com a logo e a paleta oficiais

Se `.\rodar.ps1` não existir, rode os 5 manualmente (atenção: sempre com espaço
depois das flags):
```powershell
python anonimizador.py --clinica clin_demo --entrada conversas.jsonl --vault ./vault --metricas ./metrics
python treino_export.py --clinica clin_demo --vault ./vault --out ./train
python cofre.py verify --clinica clin_demo --vault ./vault
python gerar_dashboard.py --clinica clin_demo --metrics ./metrics --vault ./vault --logo ./assets/logo.png --template ./dashboard_template.html --saida ./dashboard_bizzia.html
```

---

## 7. ONDE FICAM OS RESULTADOS

| Caminho | Conteúdo |
|---|---|
| `vault/clin_demo/` | **cofre cifrado** (o texto cru protegido) |
| `metrics/clin_demo/conversas.jsonl` | **métricas** por conversa (latência, conversão, objeções) |
| `train/clin_demo/pares.jsonl` | **pares de treino** com PII mascarada |
| `forense/telemetria.json` | **telemetria forense** (score 6 eixos, hemorragia paramétrica k×T) |
| `forense/dossie_direcao.md` | **dossiê executivo (nominal)** — confidencial, NÃO entregar à equipe |
| `forense/dossie_equipe.md` | **material de treino da equipe (anônimo, sem nomes)** |
| `dashboard_bizzia.html` | **painel visual** (logo + paleta bizz.ia) — abra no navegador |
| `extraidas.json` | progresso (quais contatos já foram feitos) |
| `.bizz-state.json` | controle do limite diário |
| `conversas.jsonl` | texto cru temporário — **apagar após processar** |

Após o `rodar.ps1`, apague o texto cru:
```powershell
Remove-Item conversas.jsonl
```

**Exceção:** só apague se o processamento deu certo (`{"conversas": N}` sem erro).
Se der erro, mantenha o arquivo para reprocessar.

---

## 8. VERIFICAR MÉTRICAS

```powershell
python -c "import json; ls=[json.loads(l) for l in open('metrics/clin_demo/conversas.jsonl',encoding='utf-8')]; print('conversas:',len(ls)); print('com conversao fechou:',sum(1 for c in ls if c['conversao']=='fechou')); print('com conversao perdeu:',sum(1 for c in ls if c['conversao']=='perdeu'))"
```

---

## 9. TROUBLESHOOTING

| Sintoma | Causa | Solução |
|---|---|---|
| `ECONNREFUSED 127.0.0.1:9222` | Edge sem debug | refaça a seção 2 (feche TODO o Edge antes) |
| `aba do WhatsApp não encontrada` | aba fechada/URL errada | abra `web.whatsapp.com` na janela de debug |
| `conversas visiveis: 0` | aba em segundo plano | traga a aba do WhatsApp para frente |
| `MENSAGENS EXTRAIDAS (0)` | seletor mudou | rode `node testar-seletores.js 0` e reporte |
| `Cannot find module 'ws'` | falta lib | `npm install ws` |
| `master key nao encontrada` | variável não definida | `$env:BIZZ_MASTER_KEY_FILE="$PWD\master.key"` |
| `unrecognized arguments: --vault./vault` | faltou espaço | escreva `--vault ./vault` (com espaço) |
| `UnicodeDecodeError` / `UnicodeEncodeError` | versão antiga do .py | atualize os .py do zip |
| QR code pedindo reconexão | sessão expirou | cliente escaneia uma vez |
| `fora do expediente` | fora de 8h-22:00 ou fds | rode em horário útil |
| Parou antes de 150 | lista não carregou mais | role a lista manualmente e rode de novo |

---

## 10. REGRAS DE SEGURANÇA — INVIOLÁVEIS

1. NUNCA envie mensagem. O extrator não tem função de envio.
2. NUNCA apague conversa ou mensagem.
3. NUNCA altere configurações da conta.
4. NUNCA desative as travas (expediente, limites, pausas, mouse real).
5. NUNCA rode fora do expediente ou acima do limite diário.
6. Se o WhatsApp exibir aviso de bloqueio, PARE e reporte.
7. O `master.key` nunca sai da máquina e nunca é exposto no chat.
8. O `conversas.jsonl` é texto cru: trate como dado sensível e apague após processar.
9. Nunca cole o CONTEÚDO das conversas no relatório — apenas números e status.

---

## 11. O QUE REPORTAR

Ao final de cada sessão, informe:
1. Quantas conversas foram extraídas nesta sessão e o **total acumulado**.
2. Se parou por limite diário, fim de expediente ou fim da lista.
3. Resultado do `cofre.py verify` (`integridade: true`).
4. Números: conversas com métricas, pares de treino, integridade do cofre.
5. Caminhos dos arquivos de saída.
6. Qualquer aviso ou erro exibido.

---

## RESUMO DOS COMANDOS

```powershell
cd "C:\Users\marcu\Documents\PROJETO BREAK\BIZZ.IA PIPELINE BROKEN\bizz"
$env:BIZZ_MASTER_KEY_FILE="$PWD\master.key"

# Abrir Edge com debug (feche TODO o Edge antes)
Stop-Process -Name msedge -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 4
Start-Process "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" -ArgumentList "--remote-debugging-port=9222","--remote-allow-origins=*","--user-data-dir=$env:LOCALAPPDATA\Microsoft\Edge\User Data","--profile-directory=Default"
Start-Sleep -Seconds 8
curl.exe http://127.0.0.1:9222/json/version

# Testar
node testar-seletores.js 0

# Extrair (repetir o ciclo: rolar a lista -> rodar -> ate completar 150)
node extrator_cdp.js --port 9222 --out conversas.jsonl --max 150 --operador recepcao_1 --soPacientes true --horaFim 22:00

# Limpar duplicatas
python -c "import json,unicodedata; norm=lambda n: unicodedata.normalize('NFD',n).encode('ascii','ignore').decode().lower().strip(); ls=[json.loads(l) for l in open('conversas.jsonl',encoding='utf-8') if l.strip()]; u={}; [u.__setitem__(norm(c['contato_nome']), c) for c in ls]; open('conversas.jsonl','w',encoding='utf-8').write('\n'.join(json.dumps(v,ensure_ascii=False) for v in u.values())+'\n'); print('unicos:',len(u))"

# Processar (NÃO apague o cofre entre execuções — append, não reinit)
if (-not (Test-Path "vault\clin_demo\salt.enc")) { python cofre.py init --clinica clin_demo --vault ./vault }
.\\rodar.ps1

# Limpar texto cru
Remove-Item conversas.jsonl
```
