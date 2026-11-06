#!/usr/bin/env python3
"""Generate data/chart.html — a self-contained SVG chart of monthly card
spending (bars) overlaid with money-in (line), from data/stats.json."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
stats = json.load(open(os.path.join(HERE, "data", "stats.json")))
mo = stats["monthly"]
ms = sorted(mo)
spend = [mo[m]["spend"] for m in ms]
income = [mo[m]["income"] for m in ms]
labs = [m[2:].replace("-", "/") for m in ms]

W, H = 960, 360
padL, padR, padT, padB = 46, 12, 16, 34
pw, ph = W - padL - padR, H - padT - padB
mx = max(spend + income + [1]) * 1.12


def x(i):
    return padL + pw * (i + 0.5) / len(ms)


def y(v):
    return padT + ph * (1 - v / mx)


bw = min(26, pw / len(ms) * 0.60)
bars = "".join(
    f'<rect x="{x(i)-bw/2:.1f}" y="{y(v):.1f}" width="{bw:.1f}" '
    f'height="{padT+ph-y(v):.1f}" rx="2" fill="var(--accent)" opacity="0.85">'
    f'<title>{labs[i]} — spend €{v:,.0f}</title></rect>'
    for i, v in enumerate(spend)
)
pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(income))
line = (f'<polyline points="{pts}" fill="none" stroke="var(--foreground)" '
        f'stroke-width="2" stroke-opacity="0.7"/>')

# horizontal gridlines
grid = ""
for g in range(0, 6):
    gv = mx * g / 5
    gy = y(gv)
    grid += (f'<line x1="{padL}" y1="{gy:.1f}" x2="{W-padR}" y2="{gy:.1f}" '
             f'stroke="var(--border)" stroke-width="1"/>'
             f'<text x="{padL-6}" y="{gy+4:.1f}" text-anchor="end" '
             f'font-size="10" fill="var(--muted-foreground)">€{gv/1000:.0f}k</text>')

# x labels (every 3rd to avoid crowding)
xlabs = "".join(
    f'<text x="{x(i):.1f}" y="{H-padB+16}" text-anchor="middle" font-size="10" '
    f'fill="var(--muted-foreground)">{labs[i]}</text>'
    for i in range(0, len(ms), 3)
)

html = f"""<!doctype html>
<html><head><meta charset="utf-8"></head>
<body style="font-family:inherit;">
<div style="font-size:13px;color:var(--muted-foreground);margin-bottom:6px;">
  Monthly card spending (bars) vs money added (line) — 2 years
</div>
<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="monthly spending chart">
  {grid}
  {bars}
  {line}
  {xlabs}
</svg>
<div style="display:flex;gap:18px;margin-top:8px;font-size:12px;color:var(--muted-foreground);">
  <span><span style="display:inline-block;width:10px;height:10px;background:var(--accent);border-radius:2px;"></span> spending</span>
  <span><span style="display:inline-block;width:14px;height:3px;background:var(--foreground);vertical-align:middle;"></span> money in</span>
</div>
</body></html>"""

out = os.path.join(HERE, "chart.html")
open(out, "w").write(html)
print("wrote", out)
