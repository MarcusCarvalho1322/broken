// diag_chat_scroll.js — acha o contêiner de rolagem do PAINEL DE MENSAGENS (chat aberto).
const http = require("http");
const WebSocket = require("ws");

http.get({ host: "127.0.0.1", port: 9222, path: "/json/list" }, (r) => {
  let d = "";
  r.on("data", (c) => (d += c));
  r.on("end", () => {
    const t = JSON.parse(d).find((x) => x.type === "page" && x.url.includes("whatsapp"));
    if (!t) { console.log("Nenhuma aba do WhatsApp"); process.exit(1); }
    const ws = new WebSocket(t.webSocketDebuggerUrl);
    let id = 0; const pend = new Map();
    const send = (m, p = {}) => new Promise((res) => { const i = ++id; pend.set(i, res); ws.send(JSON.stringify({ id: i, method: m, params: p })); });
    const ev = async (e) => {
      const r = await send("Runtime.evaluate", { expression: e, returnByValue: true, awaitPromise: true });
      if (r.result.exceptionDetails) throw new Error(r.result.exceptionDetails.text || "erro");
      return r.result.result.value;
    };
    ws.on("message", (m) => { const r = JSON.parse(m); if (r.id && pend.has(r.id)) { pend.get(r.id)(r); pend.delete(r.id); } });
    ws.on("open", async () => {
      await send("Runtime.enable");
      await new Promise((rr) => setTimeout(rr, 1200));

      // força visibilidade (mesmo override do extrator)
      await ev(`(() => { try {
        Object.defineProperty(document,'visibilityState',{get:()=> 'visible',configurable:true});
        Object.defineProperty(document,'hidden',{get:()=> false,configurable:true});
        document.dispatchEvent(new Event('visibilitychange'));
      } catch(e){} return document.visibilityState; })()`);

      const out = await ev(`
        (() => {
          const res = {};
          // quantas bolhas de mensagem renderizadas agora
          const todas = Array.from(document.querySelectorAll('[data-id]'))
            .filter(e => (e.className || '').toString().includes('x1n2onr6'));
          res.bolhasRenderizadas = todas.length;
          // últimos 3 data-ids (pra ver o quão antigo carregou)
          res.ultimosIds = todas.slice(0, 3).map(e => e.getAttribute('data-id'));
          // procura contêiner rolável dentro de #main (painel direito)
          const main = document.querySelector('#main');
          const rolaveis = [];
          if (main) {
            const all = main.querySelectorAll('*');
            for (const el of all) {
              if (el.scrollHeight > el.clientHeight + 20) {
                const cs = getComputedStyle(el);
                rolaveis.push({ tag: el.tagName, cls: (el.className&&el.className.toString?el.className.toString().slice(0,50):''), sh: el.scrollHeight, ch: el.clientHeight, st: el.scrollTop, oy: cs.overflowY });
              }
            }
          }
          res.rolaveis = rolaveis.slice(0, 6);
          return res;
        })()`);
      console.log(JSON.stringify(out, null, 2));
      process.exit(0);
    });
  });
});
