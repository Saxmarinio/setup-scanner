"""Static HTML output for GitHub Pages."""
import json, os, datetime as dt

TV = "https://www.tradingview.com/chart/?symbol={sym}&interval={iv}"
IV = {"1h": "60", "4h": "240", "1d": "D"}

CSS = """
body{background:#131722;color:#d1d4dc;font:14px/1.5 -apple-system,Segoe UI,sans-serif;margin:0;padding:24px}
h1{font-size:18px;font-weight:600;margin:0 0 4px}
.sub{color:#787b86;font-size:12px;margin-bottom:20px}
table{border-collapse:collapse;width:100%;margin-bottom:28px}
th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:#787b86;
   border-bottom:1px solid #2a2e39;padding:8px 10px;font-weight:500}
td{padding:9px 10px;border-bottom:1px solid #1e222d}
tr:hover td{background:#1a1e29}
a{color:#2962ff;text-decoration:none}
.s{display:inline-block;padding:2px 7px;border-radius:3px;font-size:11px}
.compressed{background:#1b3a2a;color:#26a69a}
.triggered{background:#3a2a1b;color:#ff9800}
.forming{background:#22263a;color:#787b86}
.div{background:#2a1b3a;color:#b388ff}
.warn{background:#3a1b1b;color:#ef5350;padding:10px 12px;border-radius:4px;margin-bottom:18px;font-size:12px}
.n{color:#787b86;font-size:12px}
"""

def render(groups, notes, out="docs/index.html"):
    os.makedirs(os.path.dirname(out), exist_ok=True)
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    h = [f"<!doctype html><meta charset=utf-8><title>Setup scan</title><style>{CSS}</style>",
         "<h1>Setup scan</h1>", f"<div class=sub>last run {ts}</div>"]
    for n in notes:
        h.append(f"<div class=warn>{n}</div>")
    for title, rows in groups:
        h.append(f"<h1>{title}</h1>")
        if not rows:
            h.append("<div class=sub>nothing</div>")
            continue
        h.append("<table><tr><th>symbol</th><th>tf</th><th>state</th><th>detail</th>"
                 "<th>htf</th><th>invalidation</th><th>score</th><th></th></tr>")
        for r in rows:
            iv = IV.get(r["tf"], "D")
            url = TV.format(sym=r.get("tv_symbol", r["symbol"]), iv=iv)
            cls = r.get("state", "div")
            h.append(
                f"<tr><td><b>{r['symbol']}</b></td><td class=n>{r['tf']}</td>"
                f"<td><span class='s {cls}'>{r.get('state','divergence')}</span></td>"
                f"<td class=n>{r.get('detail','')}</td>"
                f"<td class=n>{'ok' if r.get('htf_favourable') else '-'}</td>"
                f"<td class=n>{r.get('invalidation','')}</td>"
                f"<td>{r.get('score','')}</td>"
                f"<td><a href='{url}' target=_blank>chart</a></td></tr>")
        h.append("</table>")
    open(out, "w").write("\n".join(h))
    js = out.replace("index.html", "scan.json")
    json.dump({"generated": ts, "groups": {t: r for t, r in groups}}, open(js, "w"), indent=1)
