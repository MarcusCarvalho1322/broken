// testar-seletores.js — abre 1 conversa e mostra o que o extrator enxerga.
// Uso: node testar-seletores.js [indice]
const http = require("http");
const WebSocket = require("ws");

const IDX = parseInt(process.argv[2] || "0", 10);

http.get({ host: "127.0.0.1", port: 9222, path: "/json/list" }, (r) => {
  let d = "";
  r.on("data", (c) => (d += c));
  r.on("end", () => {
    const t = JSON.parse(d).find((x) => x.type === "page" && x.url.includes("whatsapp"));
    if (!t) { console.log("Nenhuma aba do WhatsApp encontrada"); process.exit(1); }
    const ws = new WebSocket(t.webSocketDebuggerUrl);
    let id = 0;
    const pend = new Map();
    const send = (method, params = {}) =>
      new Promise((res) => { const i = ++id; pend.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
    const evaluate = async (expression) => {
      const r = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
      if (r.error) throw new Error(JSON.stringify(r.error));
      if (!r.result || !r.result.result) return null;
      if (r.result.exceptionDetails) throw new Error(r.result.exceptionDetails.text || "erro na expressao");
      return r.result.result.value;
    };

    ws.on("message", (m) => { const r = JSON.parse(m); if (r.id && pend.has(r.id)) { pend.get(r.id)(r); pend.delete(r.id); } });

    ws.on("open", async () => {
      await send("Runtime.enable");

      const lista = await evaluate(`
        (() => {
          let itens = document.querySelectorAll('[data-testid="cell-frame-container"]');
          if (!itens.length) itens = document.querySelectorAll('#pane-side div[role="listitem"]');
          if (!itens.length) {
            const lado = document.querySelector('#pane-side');
            if (lado) itens = lado.querySelectorAll('[role="row"], [role="listitem"], [role="button"]');
          }
          return Array.from(itens).map((el, i) => {
            const t = el.querySelector('[data-testid="cell-frame-title"], span[title]');
            return { idx: i, nome: (t?.getAttribute('title') || t?.innerText || '').trim() };
          }).filter(c => c.nome);
        })()`);
      console.log(`\n== LISTA (${lista.length} conversas) ==`);
      lista.slice(0, 10).forEach((c) => console.log(`  ${c.idx}: ${c.nome}`));

      const alvo = lista[IDX];
      if (!alvo) { console.log(`\nindice ${IDX} nao existe`); process.exit(1); }
      console.log(`\n== abrindo [${IDX}] ${alvo.nome} ==`);

      const rect = await evaluate(`
        (() => {
          let itens = document.querySelectorAll('[data-testid="cell-frame-container"]');
          if (!itens.length) itens = document.querySelectorAll('#pane-side div[role="listitem"]');
          if (!itens.length) {
            const lado = document.querySelector('#pane-side');
            if (lado) itens = lado.querySelectorAll('[role="row"], [role="listitem"], [role="button"]');
          }
          const el = itens[${IDX}];
          if (!el) return null;
          el.scrollIntoView({block:'center'});
          const r = el.getBoundingClientRect();
          return { x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2) };
        })()`);
      if (rect) {
        await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: rect.x, y: rect.y });
        await new Promise((r) => setTimeout(r, 150));
        await send("Input.dispatchMouseEvent", { type: "mousePressed", x: rect.x, y: rect.y, button: "left", clickCount: 1 });
        await new Promise((r) => setTimeout(r, 80));
        await send("Input.dispatchMouseEvent", { type: "mouseReleased", x: rect.x, y: rect.y, button: "left", clickCount: 1 });
      }
      await new Promise((r) => setTimeout(r, 2500));

      const msgs = await evaluate(`
        (() => {
          const todas = Array.from(document.querySelectorAll('[data-id]'))
            .filter(e => (e.className || '').toString().includes('x1n2onr6'));
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
            texto = texto.replace(/^Você\\n/, '').replace(/^Voce\\n/, '').trim();
            let ts = null;
            const pre = b.querySelector('[data-pre-plain-text]');
            if (pre) {
              const p = pre.getAttribute('data-pre-plain-text') || '';
              const mm = p.match(/\\[(\\d{1,2}):(\\d{2}),\\s*(\\d{1,2})\\/(\\d{1,2})\\/(\\d{4})\\]/);
              if (mm) { const [, hh, mi, dd, mo, yy] = mm; ts = Math.floor(new Date(+yy, +mo-1, +dd, +hh, +mi).getTime()/1000); }
            }
            const temMidia = !!b.querySelector('img[src^="blob:"], video, [data-icon="audio-play"], [data-icon="media-play"], [data-testid="media-play"]');
            if (texto || temMidia) out.push({ de, texto: texto.slice(0,70), ts, tem_midia: temMidia });
          }
          const limpo = [];
          for (const m of out) {
            const u = limpo[limpo.length - 1];
            if (u && u.de === m.de && u.texto === m.texto && u.ts === m.ts) continue;
            limpo.push(m);
          }
          return limpo;
        })()`);

      console.log(`\n== MENSAGENS EXTRAIDAS (${msgs.length}) ==`);
      msgs.forEach((m, i) => console.log(`  ${i+1}. [${m.de}] ${m.ts ? new Date(m.ts*1000).toLocaleString("pt-BR") : "sem-hora"} :: ${m.texto}${m.tem_midia ? " [MIDIA]" : ""}`));
      if (!msgs.length) console.log("  (nenhuma — veja se a conversa abriu na tela)");
      process.exit(0);
    });
  });
});
