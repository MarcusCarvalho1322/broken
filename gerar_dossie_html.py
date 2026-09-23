# -*- coding: utf-8 -*-
"""Converte os dossiês do motor forense (direcao + equipe) em HTML com a
identidade BIZZ.IA para geração de PDF via Edge headless.

Design System v3.1: títulos Cinzel, corpo Cormorant Garamond, paleta cobre/ouro.
"""
import re, base64, sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
LOGO = BASE / "assets" / "logo.png"

ALVOS = ["dossie_direcao", "dossie_equipe"]


def md_para_html(md: str, titulo: str, confidencial: bool) -> str:
    logo_b64 = base64.b64encode(LOGO.read_bytes()).decode()
    linhas = md.splitlines()
    html = []
    lista_aberta = False

    for ln in linhas:
        s = ln.rstrip()
        if s.startswith("### "):
            if lista_aberta: html.append("</ul>"); lista_aberta = False
            html.append(f"<h3>{s[4:]}</h3>")
        elif s.startswith("## "):
            if lista_aberta: html.append("</ul>"); lista_aberta = False
            html.append(f"<h2>{s[3:]}</h2>")
        elif s.startswith("# "):
            if lista_aberta: html.append("</ul>"); lista_aberta = False
            html.append(f"<h1>{s[2:]}</h1>")
        elif s.startswith("> "):
            if lista_aberta: html.append("</ul>"); lista_aberta = False
            cls = " class=\"conf\"" if confidencial and "confidencial" in s.lower() else ""
            html.append(f"<blockquote{cls}>{s[2:]}</blockquote>")
        elif s.startswith("- "):
            if not lista_aberta: html.append("<ul>"); lista_aberta = True
            html.append(f"<li>{s[2:]}</li>")
        elif s.strip() == "":
            if lista_aberta: html.append("</ul>"); lista_aberta = False
        else:
            if lista_aberta: html.append("</ul>"); lista_aberta = False
            html.append(f"<p>{s}</p>")
    if lista_aberta:
        html.append("</ul>")

    corpo = "\n".join(html)
    corpo = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", corpo)

    return f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">
<style>
@page {{ size: A4; margin: 16mm; }}
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@600;700&family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;1,400&display=swap');
body {{ font-family: 'Cormorant Garamond', Georgia, serif; color: #1a1a1a; font-size: 14px; line-height: 1.6; margin: 0; }}
.logo {{ text-align: center; margin-bottom: 6px; }}
.logo img {{ width: 240px; }}
.sub {{ text-align: center; color: #A8987F; letter-spacing: 3px; text-transform: uppercase; font-size: 9px; margin-bottom: 18px; font-family: 'Cinzel', Georgia, serif; }}
h1 {{ font-family: 'Cinzel', Georgia, serif; color: #B87333; font-size: 24px; text-align: center; margin: 10px 0 14px; }}
h2 {{ font-family: 'Cinzel', Georgia, serif; color: #B87333; font-size: 16px; border-bottom: 2px solid #B87333; padding-bottom: 4px; margin: 24px 0 10px; text-transform: uppercase; letter-spacing: 1px; }}
h3 {{ font-family: 'Cinzel', Georgia, serif; color: #36220F; font-size: 14px; margin: 16px 0 4px; }}
p {{ margin: 8px 0; }}
ul {{ margin: 6px 0 10px 20px; padding: 0; }}
li {{ margin: 5px 0; }}
blockquote {{ border-left: 4px solid #B87333; background: #faf6ef; padding: 10px 14px; margin: 10px 0; font-style: italic; color: #4a3a24; }}
blockquote.conf {{ border-left: 4px solid #D4A853; background: #fdf3e3; }}
b {{ color: #B87333; }}
footer {{ text-align: center; color: #999; font-size: 9px; margin-top: 28px; border-top: 1px solid #eee; padding-top: 10px; }}
</style></head><body>
<div class="logo"><img src="data:image/png;base64,{logo_b64}"></div>
<div class="sub">Inteligência para clínicas premium</div>
{corpo}
<footer>BIZZ.IA · Protocolo Blind-Audit™ · decisão final é médica · somente dados anônimos</footer>
</body></html>"""


def main() -> int:
    alvos = ALVOS
    if len(sys.argv) > 1:
        alvos = sys.argv[1:]
    for nome in alvos:
        src = BASE / "forense" / f"{nome}.md"
        if not src.exists():
            print(f"pular (nao existe): {src}")
            continue
        out = BASE / "forense" / f"{nome}.html"
        md = src.read_text(encoding="utf-8")
        pagina = md_para_html(md, nome, confidencial=("direcao" in nome))
        out.write_text(pagina, encoding="utf-8")
        print("OK:", out, out.stat().st_size, "bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
