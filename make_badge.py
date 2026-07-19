#!/usr/bin/env python3
"""make_badge — a self-contained flat status badge (status.svg) from reserves.json, so the README and
dashboard show a live 'FXRP: SOLVENT' signal regenerated every run. No shields.io / no external host —
the SVG is fully self-contained. Colour reflects the real verdict; never hard-codes 'green'."""
import json

R = json.load(open("reserves.json"))
a = R["assets"][0]
v = a["verdict"]
COLOR = {"SOLVENT": "#0a7", "BACKING_SHORTFALL": "#c33", "UNDER_COLLATERALIZED": "#c33", "CANNOT_VERIFY": "#a60"}
color = COLOR.get(v, "#888")
label = "FXRP proof-of-solvency"
value = v + (" ✓" if v == "SOLVENT" else " ⚠")

# crude but stable text width (px) for the default 11px verdana-ish font
def w(s): return int(len(s) * 6.5) + 12
lw, vw = w(label), w(value)
total = lw + vw

def esc(s): return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

SVG = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{total}" height="20" role="img" aria-label="{esc(label)}: {esc(v)}">
<title>{esc(label)}: {esc(v)}</title>
<linearGradient id="s" x2="0" y2="100%"><stop offset="0" stop-color="#bbb" stop-opacity=".1"/><stop offset="1" stop-opacity=".1"/></linearGradient>
<clipPath id="r"><rect width="{total}" height="20" rx="3" fill="#fff"/></clipPath>
<g clip-path="url(#r)">
<rect width="{lw}" height="20" fill="#555"/>
<rect x="{lw}" width="{vw}" height="20" fill="{color}"/>
<rect width="{total}" height="20" fill="url(#s)"/>
</g>
<g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">
<text x="{lw/2}" y="14">{esc(label)}</text>
<text x="{lw + vw/2}" y="14">{esc(value)}</text>
</g>
</svg>
'''
open("status.svg", "w").write(SVG)
print(f"wrote status.svg ({v}, {total}x20)")
