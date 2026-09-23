const http = require("http");
const WebSocket = require("ws");

http.get({ host: "127.0.0.1", port: 9222, path: "/json/list" }, (r) => {
  let d = "";
  r.on("data", (c) => (d += c));
  r.on("end", () => {
    const t = JSON.parse(d).find((x) => x.type === "page" && x.url.includes("whatsapp"));
    const ws = new WebSocket(t.webSocketDebuggerUrl);
    let id = 0; const pend = new Map();
    const send = (m, p = {}) => new Promise((res) => { const i = ++id; pend.set(i, res); ws.send(JSON.stringify({ id: i, method: m, params: p })); });
    const ev = async (e) => (await send("Runtime.evaluate", { expression: e, returnByValue: true })).result.result.value;
    ws.on("message", (m) => { const r = JSON.parse(m); if (r.id && pend.has(r.id)) { pend.get(r.id)(r); pend.delete(r.id); } });
    ws.on("open", async () => {
      await send("Runtime.enable");
      await new Promise((r) => setTimeout(r, 1500));
      const out = await ev(`
        (() => {
          const c = Array.from(document.querySelectorAll('[data-id]'))
            .filter(e => (e.className || '').toString().includes('x1n2onr6'));
          return c.map(e => {
            const id = e.getAttribute('data-id') || '';
            const cls = (e.className || '').toString();
            const txt = e.querySelector('.copyable-text');
            return { idFull: id, classe: cls, texto: txt ? txt.innerText.slice(0,35) : null };
          }).slice(0, 14);
        })()`);
      console.log(JSON.stringify(out, null, 1));
      process.exit(0);
    });
  });
});