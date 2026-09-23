/**
 * extrator_cdp.js — Extrator passivo de conversas do WhatsApp Web via CDP.
 *
 * Roda NO COMPUTADOR DO CLIENTE, ao lado do Edge JA LOGADO no WhatsApp Web.
 * Le apenas. Nao envia nada. Nao altera nada.
 *
 * Pre-requisito: abrir o Edge com debug remoto e a aba do WhatsApp Web logada:
 *   Windows:
 *     "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" ^
 *       --remote-debugging-port=9222 --user-data-dir="C:\edge-debug"
 *   (faca login no WhatsApp Web nessa janela uma vez; a sessao persiste)
 *
 * Uso:
 *   node extrator_cdp.js --port 9222 --out conversas.jsonl --max 100 --operador recepcao_1
 *
 * Seguranca operacional:
 *   - delays humanos com jitter (configuraveis)
 *   - pausa longa a cada --pausa-cada conversas
 *   - maxima de --max conversas por sessao (default 100)
 *   - leitura passiva: nunca clica em enviar, nunca altera mensagens
 */
"use strict";

const fs = require("fs");
const http = require("http");

const args = Object.fromEntries(
  process.argv.slice(2).map((a, i, arr) => {
    if (a.startsWith("--")) return [a.slice(2), arr[i + 1] && !arr[i + 1].startsWith("--") ? arr[i + 1] : true];
    return [];
  }).filter(Boolean)
);

const PORT = args.port || 9222;
const OUT = args.out || "conversas.jsonl";
const MAX = parseInt(args.max || "100", 10);
const OPERADOR = args.operador || "nao_informado";

// -- camada de comportamento humano (stealth) ------------------------------
// Delays base entre conversas, com jitter. Ritmo-alvo: 150 conversas em ~2h
// (~48s por conversa), para conversas curtas de clinica.
const MIN_DELAY = parseInt(args.minDelay || "4000", 10);
const MAX_DELAY = parseInt(args.maxDelay || "9000", 10);

// LOTES ALEATORIOS: o extrator extrai um lote (tamanho sorteado), faz uma pausa
// longa (tambem sorteada), e recomeca. Nenhum padrao de quantidade, tempo ou
// intervalo. Dentro do lote, pausas curtas; entre lotes, pausas longas.
const LOTE_MIN = parseInt(args.loteMin || "12", 10);   // conversas por lote
const LOTE_MAX = parseInt(args.loteMax || "38", 10);

// Pausa ENTRE lotes (longa): 4 a 9 min, as vezes 14 min.
const PAUSA_LOTE_MIN_MS = parseInt(args.pausaLoteMinMs || "240000", 10);   // 4 min
const PAUSA_LOTE_MAX_MS = parseInt(args.pausaLoteMaxMs || "540000", 10);   // 9 min
const PAUSA_LOTE_RARA_MS = parseInt(args.pausaLoteRaraMs || "840000", 10); // 14 min (1 em 6)

// Pausa DENTRO do lote (curta): 18 a 32s, as vezes 1min.
const PAUSA_INTRA_MIN_MS = parseInt(args.pausaIntraMinMs || "18000", 10);
const PAUSA_INTRA_MAX_MS = parseInt(args.pausaIntraMaxMs || "32000", 10);
const PAUSA_INTRA_RARA_MS = parseInt(args.pausaIntraRaraMs || "60000", 10); // 1 em 7

// Expediente humano: fora desta janela o extrator para de trabalhar.
// Aceita "8", "8:30", "20:30" etc.
function parseHora(v, padrao) {
  const s = String(v ?? padrao).trim();
  const m = s.match(/^(\d{1,2})(?:[:h](\d{1,2}))?$/);
  if (!m) return { h: parseInt(padrao, 10), min: 0 };
  return { h: parseInt(m[1], 10), min: m[2] ? parseInt(m[2], 10) : 0 };
}
const INICIO = parseHora(args.horaInicio, "8");
const FIM = parseHora(args.horaFim, "19");
const HORA_INICIO = INICIO.h, HORA_INICIO_MIN = INICIO.min;
const HORA_FIM = FIM.h, HORA_FIM_MIN = FIM.min;
const TZ_OFFSET_H = parseInt(args.tz || "-3", 10); // America/Sao_Paulo

// Teto diario e por sessao, com arquivo de estado para nao repetir no mesmo dia.
const LIMITE_DIA = parseInt(args.limiteDia || "150", 10);
const STATE_FILE = args.state || ".bizz-state.json";

// Permite rodar fora do padrao seg-sex 8-22h (ex.: clinica que abre no fim de
// semana). Use com consciencia: apenas quando o cliente confirma que a conta
// esta ativa hoje.
const IGNORAR_EXPEDIENTE = args.ignorarExpediente === true || args.ignorarExpediente === "true";

// Registro de progresso: contatos ja extraidos, para nunca repetir.
// Guarda o nome do contato (nao o telefone) + quando foi extraido.
const PROGRESS_FILE = args.progress || "extraidas.json";

// Filtro de escopo: por padrao extrai apenas conversas 1:1 com PACIENTES.
// Exclui:
//   - medicos (Dra. Raphael, Dra. Larissa e variacoes)
//   - grupos
//   - contatos da administracao / internos (secretaria, hotmart, etc.)
const SO_PACIENTES = args.soPacientes !== false && args.soPacientes !== "false";
const RE_PACIENTE = /(^|\s)(pct|pcte|paciente)(\s|$)/i;
const RE_TELEFONE = /^\+?\d[\d\s()-]{7,}$/;

// Medicos: Dr. Raphael (masculino) e Dra. Larissa (feminino).
// Pega qualquer variacao, com ou sem titulo: "Dr. Raphael", "Dra Larissa",
// "Raphael", "Larissa Pct", etc. Se o nome contem, e medico.
const EXCLUIR_MEDICOS = args.excluirMedicos !== false && args.excluirMedicos !== "false";
const RE_MEDICOS = /\b(raphael|rafael|larissa)\b/i;

// Grupos: nomes com sinais tipicos, ou deteccao pela propria pagina (membro/participante)
const RE_GRUPO = /(grupo|group|equipe|time|turma|orienta[cç][oõ]es|scripts|vendas|marketing|comunidade|aviso|interno)/i;

// Administracao / contatos internos e comerciais.
// Cuidado com falsos positivos: "P 104 Viviane ... Pct Nutrologia" e PACIENTE.
// Por isso "P 104" so exclui se NAO houver marcador de paciente no nome.
const RE_ADM = /(hotmart|secretaria|recep[cç][aã]o|administra|financeiro|suporte|plataforma|billing|notifica|equipe\s|rotary|dr\s*dan|esposa\s*dr)/i;

function parecePaciente(nome) {
  const n = (nome || "").trim();
  if (!n) return false;

  // paciente explicito tem prioridade: "Pct"/"Pcte"/"Paciente" no nome
  const temMarcadorPaciente = RE_PACIENTE.test(n) || RE_TELEFONE.test(n);

  // medicos: nunca (mas "Raphael Pct" e medico, nao paciente)
  if (EXCLUIR_MEDICOS && RE_MEDICOS.test(n)) return false;

  if (temMarcadorPaciente) return true;

  // grupos e adm: nunca
  if (RE_GRUPO.test(n)) return false;
  if (RE_ADM.test(n)) return false;

  if (!SO_PACIENTES) return true;
  return false;
}

// Normaliza nome para dedup: remove acentos, colapsa espacos, minusculas.
// O WhatsApp usa nomes ligeiramente diferentes entre a lista lateral e o
// cabecalho da conversa (acentos, espacos), o que fazia o extrator re-extrair
// contatos ja capturados.
function normNome(n) {
  return (n || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

// Micro-pausas ocasionais durante a leitura (humano se distrai, troca de aba).
const MICRO_PAUSA_CHANCE = parseFloat(args.microPausaChance || "0.06");
const MICRO_PAUSA_MS = parseInt(args.microPausaMs || "20000", 10);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const rand = (min, max) => min + Math.floor(Math.random() * (max - min + 1));
const humano = () => sleep(rand(MIN_DELAY, MAX_DELAY));
const nowIso = () => new Date().toISOString();

function horaLocal() {
  const d = new Date(Date.now() + TZ_OFFSET_H * 3600 * 1000);
  return {
    h: d.getUTCHours(),
    min: d.getUTCMinutes(),
    dow: d.getUTCDay(),
    dia: d.toISOString().slice(0, 10),
  };
}

function dentroDoExpediente() {
  const { h, min, dow } = horaLocal();
  if (IGNORAR_EXPEDIENTE) return true;
  if (dow === 0 || dow === 6) return false; // fim de semana
  const agora = h * 60 + min;
  const inicio = HORA_INICIO * 60 + HORA_INICIO_MIN;
  const fim = HORA_FIM * 60 + HORA_FIM_MIN;
  return agora >= inicio && agora < fim;
}

function fmtHora(h, min) {
  return min ? `${h}:${String(min).padStart(2, "0")}` : String(h);
}

function lerEstado() {
  try { return JSON.parse(require("fs").readFileSync(STATE_FILE, "utf8")); }
  catch { return { dia: null, feitasHoje: 0 }; }
}

function gravarEstado(s) {
  require("fs").writeFileSync(STATE_FILE, JSON.stringify(s, null, 2));
}

// -- registro de progresso (quais contatos ja foram extraidos) --------------
function lerProgresso() {
  try {
    const p = JSON.parse(require("fs").readFileSync(PROGRESS_FILE, "utf8"));
    return { extraidas: p.extraidas || {}, saltadas: p.saltadas || {} };
  } catch {
    return { extraidas: {}, saltadas: {} };
  }
}

function gravarProgresso(p) {
  require("fs").writeFileSync(PROGRESS_FILE, JSON.stringify(p, null, 2));
}

// Tamanho do proximo lote: sorteado, sem padrao. As vezes um lote bem curto.
function tamanhoLote() {
  const r = Math.random();
  if (r < 0.15) return rand(5, 10);           // lote curto ocasional
  if (r > 0.85) return rand(LOTE_MAX, LOTE_MAX + 12); // lote longo ocasional
  return rand(LOTE_MIN, LOTE_MAX);
}

// Pausa ENTRE lotes: longa e imprevisivel.
function pausaEntreLotes() {
  const r = Math.random();
  const ms = r < 0.17 ? PAUSA_LOTE_RARA_MS : rand(PAUSA_LOTE_MIN_MS, PAUSA_LOTE_MAX_MS);
  return ms;
}

// Pausa DENTRO do lote: curta.
function pausaIntraLote() {
  const r = Math.random();
  const ms = r < 0.14 ? PAUSA_INTRA_RARA_MS : rand(PAUSA_INTRA_MIN_MS, PAUSA_INTRA_MAX_MS);
  return ms;
}

function fmtMin(ms) {
  const m = Math.floor(ms / 60000), s = Math.round((ms % 60000) / 1000);
  return m > 0 ? `${m}min${s ? " " + s + "s" : ""}` : `${s}s`;
}


// ---------------------------------------------------------------- CDP minimo

function httpJson(path) {
  return new Promise((resolve, reject) => {
    http.get({ host: "127.0.0.1", port: PORT, path }, (res) => {
      let d = "";
      res.on("data", (c) => (d += c));
      res.on("end", () => {
        try { resolve(JSON.parse(d)); } catch (e) { reject(e); }
      });
    }).on("error", reject);
  });
}

class CDP {
  constructor(ws) { this.ws = ws; this.id = 0; this.pending = new Map(); }
  static async connect(wsUrl) {
    const WebSocket = globalThis.WebSocket || (await import("ws")).default;
    const ws = new WebSocket(wsUrl);
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
    const cdp = new CDP(ws);
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && cdp.pending.has(msg.id)) {
        const { res, rej } = cdp.pending.get(msg.id);
        cdp.pending.delete(msg.id);
        msg.error ? rej(new Error(JSON.stringify(msg.error))) : res(msg.result);
      }
    };
    return cdp;
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((res, rej) => {
      this.pending.set(id, { res, rej });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  async eval(expr) {
    const r = await this.send("Runtime.evaluate", {
      expression: expr, returnByValue: true, awaitPromise: true,
    });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.text);
    return r.result.value;
  }
}

// ---------------------------------------------------------------- scraping

// Estes seletores sao os do WhatsApp Web e mudam de tempo em tempo.
// Ajuste aqui se o WhatsApp atualizar o layout.
const S_PANEL_CONV = '[data-testid="conversation-panel-wrapper"], #main';
const S_BOLHA = 'div.message-in, div.message-out';
const S_TEXTO = 'span.selectable-text, .copyable-text';

// Forca a pagina a se reportar como VISIVEL, mesmo quando a aba/ janela do Edge
// esta em segundo plano ou oculta. Sem isso o WhatsApp pausa o carregamento da
// lista (virtualizada) e o scroll nao renderiza novos contatos — o extrator
// trava antes de alcancar as conversas antigas.
async function forcarVisibilidade(cdp) {
  await cdp.eval(`
    (() => {
      try {
        Object.defineProperty(document, 'visibilityState', { get: () => 'visible', configurable: true });
        Object.defineProperty(document, 'hidden', { get: () => false, configurable: true });
        Object.defineProperty(document, 'webkitVisibilityState', { get: () => 'visible', configurable: true });
      } catch (e) {}
      document.dispatchEvent(new Event('visibilitychange'));
      return document.visibilityState;
    })()
  `);
}

async function pegarListaConversas(cdp) {
  return cdp.eval(`
    (() => {
      // A sidebar usa [data-testid="cell-frame-container"] (ou, em versoes novas,
      // linhas com role=listitem dentro de #pane-side). Cobre os dois.
      let itens = document.querySelectorAll('[data-testid="cell-frame-container"]');
      if (!itens.length) itens = document.querySelectorAll('#pane-side div[role="listitem"]');
      if (!itens.length) {
        const lado = document.querySelector('#pane-side');
        if (lado) itens = lado.querySelectorAll('[role="row"], [role="listitem"], [role="button"]');
      }
      return Array.from(itens).map((el, i) => {
        const t = el.querySelector('[data-testid="cell-frame-title"], span[title]');
        const nome = (t?.getAttribute('title') || t?.innerText || '').trim();
        return { idx: i, nome };
      }).filter(c => c.nome);
    })()
  `);
}

// Detecta avisos de limitacao/bloqueio do WhatsApp e pede parada imediata.
async function detectarAvisoBloqueio(cdp) {
  return cdp.eval(`
    (() => {
      const t = (document.body.innerText || '').toLowerCase();
      const sinais = [
        'temporariamente bloqueado', 'temporarily banned', 'sua conta foi banida',
        'account was banned', 'muitas mensagens', 'too many messages',
        'limitamos', 'we limit', 'nao e possivel usar o whatsapp',
      ];
      return sinais.some(s => t.includes(s));
    })()
  `);
}

// Move o mouse em passos ate o elemento e clica via CDP (nao via JS .click(),
// que e instantaneo e sintetico demais). Inclui desvio humano no trajeto.
async function moverEClicarHumano(cdp, idx) {
  const rect = await cdp.eval(`
    (() => {
      let itens = document.querySelectorAll('[data-testid="cell-frame-container"]');
      if (!itens.length) itens = document.querySelectorAll('#pane-side div[role="listitem"]');
      if (!itens.length) {
        const lado = document.querySelector('#pane-side');
        if (lado) itens = lado.querySelectorAll('[role="row"], [role="listitem"], [role="button"]');
      }
      const el = itens[${idx}];
      if (!el) return null;
      el.scrollIntoView({block:'center'});
      const r = el.getBoundingClientRect();
      return { x: r.x + r.width/2, y: r.y + r.height/2 };
    })()
  `);
  if (!rect) return false;

  const startX = rand(200, 900), startY = rand(150, 600);
  const passos = rand(12, 25);
  for (let i = 1; i <= passos; i++) {
    const t = i / passos;
    // easing + desvio senoidal: nao vai em linha reta
    const ease = t * t * (3 - 2 * t);
    const desvio = Math.sin(t * Math.PI) * rand(-25, 25);
    const x = Math.round(startX + (rect.x - startX) * ease + desvio);
    const y = Math.round(startY + (rect.y - startY) * ease + desvio * 0.5);
    await cdp.send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y });
    await sleep(rand(8, 28));
  }

  // micro-hesitacao antes do clique, como humano
  await sleep(rand(120, 420));
  await cdp.send("Input.dispatchMouseEvent", { type: "mousePressed", x: Math.round(rect.x), y: Math.round(rect.y), button: "left", clickCount: 1 });
  await sleep(rand(40, 110));
  await cdp.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: Math.round(rect.x), y: Math.round(rect.y), button: "left", clickCount: 1 });
  return true;
}

async function abrirConversa(cdp, idx) {
  await moverEClicarHumano(cdp, idx);
  await sleep(900 + Math.random() * 600);
}

// Rola a LISTA de conversas (sidebar) para baixo, carregando contatos mais
// antigos. O WhatsApp so carrega o que aparece na tela, entao sem isso o
// extrator nunca alcanca as conversas do fim da lista.
async function rolarListaParaBaixo(cdp) {
  await forcarVisibilidade(cdp);

  // snapshot dos contatos renderizados AGORA (identidade, nao so scrollTop)
  const antes = await cdp.eval(`
    (() => {
      const lado = document.querySelector('#pane-side');
      if (!lado) return null;
      const rows = Array.from(document.querySelectorAll('[data-testid="cell-frame-container"]'));
      const nomes = rows.map(r => {
        const t = r.querySelector('[data-testid="cell-frame-title"], span[title]');
        return (t?.getAttribute('title') || t?.innerText || '').trim();
      });
      return { st: lado.scrollTop, sh: lado.scrollHeight, primeiro: nomes[0] || '', ultimo: nomes[nomes.length - 1] || '' };
    })()
  `);
  if (!antes) return { mudou: false };

  // rolagem em passos pequenos via scrollTop — confirmado que re-renderiza a lista
  // virtualizada quando a pagina reporta "visivel". Gestos de mouse (wheel) nao
  // disparam o carregamento lazy de forma confiavel aqui.
  for (let i = 0; i < 3; i++) {
    const ok = await cdp.eval(`
      (() => {
        const lado = document.querySelector('#pane-side');
        if (!lado) return false;
        const max = lado.scrollHeight - lado.clientHeight;
        const novo = Math.min(lado.scrollTop + Math.floor(lado.clientHeight * 0.6), max);
        if (novo <= lado.scrollTop) return false;
        lado.scrollTop = novo;
        return true;
      })()
    `);
    if (!ok) break;
    await sleep(rand(700, 1200));
  }
  // espera extra para o WhatsApp carregar e renderizar os novos contatos
  await sleep(rand(2000, 3500));

  const depois = await cdp.eval(`
    (() => {
      const lado = document.querySelector('#pane-side');
      const rows = Array.from(document.querySelectorAll('[data-testid="cell-frame-container"]'));
      const nomes = rows.map(r => {
        const t = r.querySelector('[data-testid="cell-frame-title"], span[title]');
        return (t?.getAttribute('title') || t?.innerText || '').trim();
      });
      return { st: lado ? lado.scrollTop : -1, sh: lado ? lado.scrollHeight : -1, primeiro: nomes[0] || '', ultimo: nomes[nomes.length - 1] || '' };
    })()
  `);

  // "mudou" = novos contatos renderizados (a janela trocou) ou a lista cresceu
  const mudou = depois.primeiro !== antes.primeiro || depois.ultimo !== antes.ultimo || depois.sh !== antes.sh;
  return { mudou };
}

async function rolarListaAteTopo(cdp) {
  await cdp.eval(`
    (() => {
      const lado = document.querySelector('#pane-side');
      if (lado) lado.scrollTop = 0;
      return true;
    })()
  `);
  await sleep(600);
}

async function rolarAteTopo(cdp, maxRolos = 12) {
  for (let i = 0; i < maxRolos; i++) {
    const parou = await cdp.eval(`
      (() => {
        const sc = document.querySelector('#main div.copyable-area')?.parentElement
          || document.querySelector('#main ._akbu, #main [data-tab="8"]');
        const alvo = sc || document.scrollingElement;
        if (!alvo) return true;
        if (alvo.scrollTop <= 0) return true;
        alvo.scrollTop = 0;
        return false;
      })()
    `);
    if (parou) break;
    await sleep(500 + Math.random() * 400);
  }
  return true;
}

async function extrairMensagens(cdp) {
  return cdp.eval(`
    (() => {
      // WhatsApp atual: cada bolha tem [data-id].
      //   id comeca com "3EB"  -> enviada pela clinica
      //   qualquer outro id    -> recebida do paciente (ex: "AC...", "3A...")
      // O wrapper externo repete a bolha interna; filtramos os aninhados.
      const todas = Array.from(document.querySelectorAll('[data-id]'))
        .filter(e => (e.className || '').toString().includes('x1n2onr6'));

      // descarta wrappers: se um [data-id] contem outro [data-id], fica so o interno
      const bolhas = todas.filter(el => !el.querySelector('[data-id]'));

      const out = [];
      for (const b of bolhas) {
        const id = b.getAttribute('data-id') || '';
        const de = /^3EB/i.test(id) ? 'clinica' : 'paciente';

        const texts = Array.from(b.querySelectorAll('.copyable-text'))
          .filter(t => !t.parentElement.closest('.copyable-text'));
        let texto = '';
        if (texts.length) texto = (texts[0].innerText || '').trim();
        else { const s = b.querySelector('span.selectable-text'); if (s) texto = (s.innerText || '').trim(); }
        // remove o prefixo "Voce\\n" que aparece em citacoes
        texto = texto.replace(/^Você\\n/, '').replace(/^Voce\\n/, '').trim();

        let ts = null;
        const pre = b.querySelector('[data-pre-plain-text]');
        if (pre) {
          const p = pre.getAttribute('data-pre-plain-text') || '';
          const mm = p.match(/\\[(\\d{1,2}):(\\d{2}),\\s*(\\d{1,2})\\/(\\d{1,2})\\/(\\d{4})\\]/);
          if (mm) { const [, hh, mi, dd, mo, yy] = mm; ts = Math.floor(new Date(+yy, +mo-1, +dd, +hh, +mi).getTime()/1000); }
        }

        const temMidia = !!b.querySelector('img[src^="blob:"], video, [data-icon="audio-play"], [data-icon="media-play"], [data-testid="media-play"]');
        if (texto || temMidia) out.push({ id, de, texto, ts, tem_midia: temMidia });
      }

      // remove duplicatas adjacentes (mesmo texto e mesmo remetente)
      const limpo = [];
      for (const m of out) {
        const ult = limpo[limpo.length - 1];
        if (ult && ult.de === m.de && ult.texto === m.texto && ult.ts === m.ts) continue;
        limpo.push(m);
      }
      return limpo;
    })()
  `);
}

// Extrai TODAS as mensagens da conversa: rola o chat para cima de forma incremental
// e acumula. O WhatsApp só renderiza uma janela por vez — pular direto pro topo
// (como o rolarAteTopo antigo) deixava o MEIO da conversa de fora (truncamento).
async function extrairMensagensCompleto(cdp) {
  const acumuladas = new Map(); // data-id -> mensagem
  let semNovidade = 0;

  for (let passo = 0; passo < 100; passo++) {
    const visiveis = await extrairMensagens(cdp);
    let novos = 0;
    for (const m of visiveis) {
      if (m.id && !acumuladas.has(m.id)) {
        acumuladas.set(m.id, m);
        novos++;
      }
    }

    // rola o chat para cima um passo, usando o contêiner de rolagem REAL
    // (descoberto dinamicamente — o WhatsApp troca os nomes de classe com frequência)
    const r = await cdp.eval(`
      (() => {
        const bolha = Array.from(document.querySelectorAll('[data-id]'))
          .filter(e => (e.className || '').toString().includes('x1n2onr6'))[0];
        if (!bolha) return { noTopo: true };
        let el = bolha.parentElement;
        while (el) {
          if (el.scrollHeight > el.clientHeight + 20) break;
          el = el.parentElement;
        }
        if (!el) return { noTopo: true };
        const novoTopo = Math.max(0, el.scrollTop - Math.floor(el.clientHeight * 0.7));
        const moveu = novoTopo < el.scrollTop;
        el.scrollTop = novoTopo;
        return { noTopo: novoTopo <= 0, moveu };
      })()
    `);

    if (r.noTopo) {
      // chegou ao topo: captura a última janela e encerra
      const finais = await extrairMensagens(cdp);
      for (const m of finais) {
        if (m.id && !acumuladas.has(m.id)) acumuladas.set(m.id, m);
      }
      break;
    }

    if (novos === 0) {
      semNovidade++;
      if (semNovidade >= 4) break; // nada novo após vários passos = topo
    } else {
      semNovidade = 0;
    }
    await sleep(600 + Math.random() * 700);
  }

  // ordena por timestamp (mais antigo -> mais novo) e remove o id interno
  const final = Array.from(acumuladas.values()).sort((a, b) => (a.ts || 0) - (b.ts || 0));
  return final.map(({ id, ...resto }) => resto);
}

async function nomeDaConversa(cdp) {
  return cdp.eval(`
    (() => {
      const h = document.querySelector('#main header [data-testid="conversation-info-header-chat-title"]')
        || document.querySelector('#main header span[title]')
        || document.querySelector('#main header [title]');
      return (h?.getAttribute('title') || h?.innerText || '').trim();
    })()
  `);
}

// ---------------------------------------------------------------- main

(async () => {
  console.log("== extrator bizz.ia ==");

  // reset opcional do progresso (--reset)
  if (args.reset === true) {
    try { require("fs").unlinkSync(PROGRESS_FILE); console.log("progresso resetado."); } catch {}
  }

  console.log(`conectando em 127.0.0.1:${PORT} (Edge com --remote-debugging-port)`);

  const targets = await httpJson("/json/list");
  const wa = targets.find(
    (t) => t.type === "page" && /web\.whatsapp\.com|whatsapp\.com/.test(t.url)
  );
  if (!wa) {
    console.error("ERRO: nenhuma aba do WhatsApp Web encontrada. Abra o WhatsApp Web no Edge de debug e logue.");
    process.exit(1);
  }
  console.log("aba encontrada:", wa.url);

  const cdp = await CDP.connect(wa.webSocketDebuggerUrl);
  await cdp.send("Runtime.enable");
  await cdp.send("Page.enable");
  await forcarVisibilidade(cdp);

  // volta a sidebar ao topo para varrer a lista inteira (mais recente -> antigo),
  // pulando os contatos ja extraidos em execucoes anteriores.
  await cdp.eval(`
    (() => {
      const lado = document.querySelector('#pane-side');
      if (lado) lado.scrollTop = 0;
      return true;
    })()
  `);
  await sleep(2500);

  // -- guardas de seguranca de comportamento -----------------------------
  const estado = lerEstado();
  const hoje = horaLocal().dia;
  if (estado.dia !== hoje) { estado.dia = hoje; estado.feitasHoje = 0; }

  const restanteDia = LIMITE_DIA - estado.feitasHoje;
  if (restanteDia <= 0) {
    console.log(`limite diario atingido (${LIMITE_DIA}). Volte amanha para proteger a conta do cliente.`);
    process.exit(0);
  }

  const { h, dow } = horaLocal();
  if (!dentroDoExpediente()) {
    console.log(
      `fora do expediente humano (agora ${h}h, dia ${dow}). ` +
      `O extrator so roda entre ${fmtHora(HORA_INICIO,HORA_INICIO_MIN)} e ${fmtHora(HORA_FIM,HORA_FIM_MIN)}, seg-sex, ` +
      `justamente para nao levantar suspeita.`
    );
    process.exit(0);
  }

  if (await detectarAvisoBloqueio(cdp)) {
    console.error("DETECTADO aviso de limitacao do WhatsApp. Encerrando imediatamente por seguranca.");
    process.exit(2);
  }

  const tetoSessao = Math.min(MAX, restanteDia);
  const progresso = lerProgresso();
  // indice normalizado dos nomes ja extraidos (ignora acento/espaco)
  const extraidasNorm = new Set(Object.keys(progresso.extraidas).map(normNome));
  // nomes ja vistos como fantasma (sem conversa efetiva) — nao reabrir
  const saltadasNorm = new Set(Object.keys(progresso.saltadas).map(normNome));

  console.log(`== extrator bizz.ia ==`);
  console.log(`teto desta sessao: ${tetoSessao}`);
  console.log(`limite diario: ${LIMITE_DIA} (ja feitas hoje: ${estado.feitasHoje}, restam ${restanteDia})`);
  console.log( `expediente: ${fmtHora(HORA_INICIO,HORA_INICIO_MIN)}-${fmtHora(HORA_FIM,HORA_FIM_MIN)} | delays ${MIN_DELAY}-${MAX_DELAY}ms`);
  console.log(`lotes aleatorios: ${LOTE_MIN}-${LOTE_MAX} conversas | pausa entre lotes: ${fmtMin(PAUSA_LOTE_MIN_MS)}-${fmtMin(PAUSA_LOTE_MAX_MS)}`);
  console.log(`filtro pacientes: ${SO_PACIENTES ? "LIGADO" : "desligado"}`);
  console.log(`ja extraidas em execucoes anteriores: ${Object.keys(progresso.extraidas).length}\n`);

  const fout = fs.createWriteStream(OUT, { flags: "a" });
  let feitas = 0;
  let parar = false;
  let rodada = 0;
  let lote = 0;
  let rolagensSemNovidade = 0;
  const MAX_RODADAS = 600;       // trava de seguranca (150 conversas + rolagens)
  const MAX_ROLAGENS_VAZIAS = 10; // se rolar N vezes sem contato novo, encerra

  while (!parar && feitas < tetoSessao && rodada < MAX_RODADAS) {
    lote++;
    const alvoLote = tamanhoLote();
    let feitasNoLote = 0;

    console.log(`\n=== LOTE ${lote} (alvo: ${alvoLote} conversas) ===`);

    // dentro do lote, percorre pendentes ate completar o alvo
    while (!parar && feitas < tetoSessao && feitasNoLote < alvoLote) {
      rodada++;
      if (rodada > MAX_RODADAS) { parar = true; break; }

      const lista = await pegarListaConversas(cdp);
      const pendentes = [];
      let puladas = 0, foraDoFiltro = 0;
      for (const c of lista) {
        if (extraidasNorm.has(normNome(c.nome)) || saltadasNorm.has(normNome(c.nome))) { puladas++; continue; }
        if (!parecePaciente(c.nome)) { foraDoFiltro++; continue; }
        pendentes.push(c);
      }

      if (!pendentes.length) {
        const r = await rolarListaParaBaixo(cdp);
        if (!r.mudou) {
          rolagensSemNovidade++;
          console.log(`   rolagem sem novos contatos (${rolagensSemNovidade}/${MAX_ROLAGENS_VAZIAS})`);
          if (rolagensSemNovidade >= MAX_ROLAGENS_VAZIAS) {
            console.log("\nNao ha mais conversas antigas para carregar. Encerrando.");
            parar = true;
          }
        } else {
          rolagensSemNovidade = 0;
        }
        await sleep(1500 + Math.random() * 1000);
        continue;
      }

      const c = pendentes[0];

      if (await detectarAvisoBloqueio(cdp)) {
        console.error("DETECTADO aviso de limitacao do WhatsApp. Encerrando por seguranca.");
        parar = true;
        break;
      }

      try {
        await abrirConversa(cdp, c.idx);
        const mensagens = await extrairMensagensCompleto(cdp);
        const nome = (await nomeDaConversa(cdp)) || c.nome;
        const temPaciente = mensagens.some((m) => m.de === "paciente");
        if (temPaciente) {
          const reg = {
            contato_nome: nome,
            operador: OPERADOR,
            mensagens: mensagens.map((m) => ({ ts: m.ts, de: m.de, texto: m.texto, tem_midia: m.tem_midia })),
            capturado_em: nowIso(),
          };
          fout.write(JSON.stringify(reg) + "\n");
          feitas++;
          feitasNoLote++;
          estado.feitasHoje++;
          progresso.extraidas[nome] = nowIso();
          extraidasNorm.add(normNome(nome));
          gravarEstado(estado);
          gravarProgresso(progresso);
          console.log(`  [${feitas}/${tetoSessao}] (lote ${feitasNoLote}/${alvoLote}) ${nome.slice(0, 26)} — ${mensagens.length} msgs`);
        } else {
          progresso.saltadas[nome] = nowIso();
          saltadasNorm.add(normNome(nome));
          gravarProgresso(progresso);
          console.log(`  [--] ${nome.slice(0, 26)} — fantasma (sem resposta do paciente), pulando`);
        }
      } catch (e) {
        console.warn(`  erro na conversa ${c.nome}: ${e.message}`);
      }

      await humano();

      // micro-pausa ocasional
      if (Math.random() < MICRO_PAUSA_CHANCE) {
        console.log(`  micro-pausa (${Math.round(MICRO_PAUSA_MS / 1000)}s)...`);
        await sleep(MICRO_PAUSA_MS);
      }

      // pausa CURTA dentro do lote (entre conversas)
      if (feitasNoLote < alvoLote && !parar) {
        const ms = pausaIntraLote();
        console.log(`  ... pausa curta ${fmtMin(ms)}`);
        await sleep(ms);
      }

      if (estado.feitasHoje >= LIMITE_DIA) {
        console.log(`  limite diario de ${LIMITE_DIA} atingido. Encerrando por seguranca.`);
        parar = true;
      }
      if (!dentroDoExpediente()) {
        console.log("  expediente encerrado. Parando por seguranca (retome no proximo dia util).");
        parar = true;
      }
    }

    // pausa LONGA entre lotes
    if (!parar && feitas < tetoSessao) {
      const ms = pausaEntreLotes();
      console.log(`\n>> fim do lote ${lote}. Pausa longa de ${fmtMin(ms)} antes do proximo lote...`);
      await sleep(ms);
      if (!dentroDoExpediente()) {
        console.log(">> expediente encerrado durante a pausa. Parando (retome amanha).");
        parar = true;
      }
    }
  }

  fout.end();
  console.log(`\npronto: ${feitas} conversas nesta sessao -> ${OUT}`);
  console.log(`total acumulado: ${Object.keys(progresso.extraidas).length} contatos`);
  console.log("proximo passo: python anonimizador.py --clinica <id> --entrada " + OUT);
  process.exit(0);
})().catch((e) => {
  console.error("falha:", e.message);
  console.error("verifique se o Edge esta aberto com --remote-debugging-port=9222 e o WhatsApp Web logado.");
  process.exit(1);
});
