"""Static HTML output for GitHub Pages.

One page per tier (docs/a.html, docs/b.html, docs/c.html) plus a landing
index (docs/index.html) that lists all three with their last-run time and
setup counts. Each tier run writes its own page and refreshes the index from
docs/status.json, so the tiers no longer overwrite one shared page.
"""
import json, os, datetime as dt

TV = "https://www.tradingview.com/chart/?symbol={sym}&interval={iv}"
IV = {"1h": "60", "4h": "240", "1d": "D"}

TIER_LABEL = {
    "A": "Tier A — top-10 crypto, 4H scan",
    "B": "Tier B — other crypto, 1H scan",
    "C": "Tier C — equities & ETFs, 1D scan",
}

CSS = """
body{background:#131722;color:#d1d4dc;font:14px/1.5 -apple-system,Segoe UI,sans-serif;margin:0;padding:24px}
h1{font-size:18px;font-weight:600;margin:0 0 4px}
h2{font-size:15px;font-weight:600;margin:24px 0 4px}
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

def _now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

def _head(title):
    return f"<!doctype html><meta charset=utf-8><title>{title}</title><style>{CSS}</style>"

def _tables(groups):
    h = []
    for title, rows in groups:
        h.append(f"<h2>{title}</h2>")
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
    return h

def _render_tier(tier, groups, notes, outdir, ts):
    out = os.path.join(outdir, f"{tier.lower()}.html")
    h = [_head(f"Setup scan — Tier {tier}"),
         f"<h1>{TIER_LABEL[tier]}</h1>",
         f"<div class=sub>last run {ts} &middot; <a href='index.html'>&larr; all tiers</a></div>"]
    for n in notes:
        h.append(f"<div class=warn>{n}</div>")
    h += _tables(groups)
    open(out, "w").write("\n".join(h))
    json.dump({"generated": ts, "groups": {t: r for t, r in groups}},
              open(os.path.join(outdir, f"{tier.lower()}.json"), "w"), indent=1)

def _render_index(outdir, status):
    h = [_head("Setup scan"),
         "<h1>Setup scan</h1>",
         f"<div class=sub>index updated {_now()}</div>",
         "<table><tr><th>tier</th><th>last run</th><th>compression</th>"
         "<th>divergence</th><th></th></tr>"]
    for t in ("A", "B", "C"):
        info = status.get(t)
        if info:
            h.append(
                f"<tr><td><b>{TIER_LABEL[t]}</b></td>"
                f"<td class=n>{info['ts']}</td>"
                f"<td>{info['compression']}</td>"
                f"<td>{info['divergence']}</td>"
                f"<td><a href='{t.lower()}.html'>view &rarr;</a></td></tr>")
        else:
            h.append(
                f"<tr><td><b>{TIER_LABEL[t]}</b></td>"
                "<td class=n>not run yet</td><td class=n>&ndash;</td>"
                "<td class=n>&ndash;</td><td class=n></td></tr>")
    h.append("</table>")
    open(os.path.join(outdir, "index.html"), "w").write("\n".join(h))

def publish(tier, groups, notes, outdir="docs"):
    """Write this tier's page + JSON, update the shared status, rebuild index.
    `groups` is [(compression_title, rows), (divergence_title, rows)]."""
    os.makedirs(outdir, exist_ok=True)
    ts = _now()
    _render_tier(tier, groups, notes, outdir, ts)
    status_path = os.path.join(outdir, "status.json")
    status = {}
    if os.path.exists(status_path):
        try:
            status = json.load(open(status_path))
        except Exception:
            status = {}
    status[tier] = {"ts": ts,
                    "compression": len(groups[0][1]),
                    "divergence": len(groups[1][1])}
    json.dump(status, open(status_path, "w"), indent=1)
    _render_index(outdir, status)
