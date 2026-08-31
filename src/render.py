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
    "D": "Tier D — tokenized stocks, 1D scan",
    "E": "Tier E — gold & commodities, 1D scan",
}
INDEX_TIERS = ("A", "B", "C", "D", "E")

# DSS Bressert traffic-light thresholds (0-1): <=green bottoming, >=red topping.
DSS_GREEN, DSS_RED = 0.1, 0.9

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
.dss{font-variant-numeric:tabular-nums;white-space:nowrap}
.dg{color:#26a69a;font-weight:600}
.dr{color:#ef5350;font-weight:600}
.dw{color:#d1d4dc}
"""

def _now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

def _head(title):
    return f"<!doctype html><meta charset=utf-8><title>{title}</title><style>{CSS}</style>"

def _dss_val(v):
    cls = "dg" if v <= DSS_GREEN else "dr" if v >= DSS_RED else "dw"
    return f"<span class='{cls}'>{v:.2f}</span>"

def _dss_cell(pair):
    """One D/W/M cell showing 'fast / slow', each coloured by threshold."""
    if not pair:
        return "<td class='dss n'>&ndash;</td>"
    f, s = pair
    return f"<td class=dss>{_dss_val(f)}<span class=n> / </span>{_dss_val(s)}</td>"

def _tables(groups):
    h = []
    for title, rows in groups:
        h.append(f"<h2>{title}</h2>")
        if not rows:
            h.append("<div class=sub>nothing</div>")
            continue
        h.append("<div style='overflow-x:auto'>"
                 "<table><tr><th>symbol</th><th>tf</th><th>state</th><th>detail</th>"
                 "<th>htf</th><th>invalidation</th><th>score</th>"
                 "<th>dss D</th><th>dss W</th><th>dss M</th><th></th></tr>")
        for r in rows:
            iv = IV.get(r["tf"], "D")
            url = TV.format(sym=r.get("tv_symbol", r["symbol"]), iv=iv)
            cls = r.get("state", "div")
            d = r.get("dss") or {}
            h.append(
                f"<tr><td><b>{r['symbol']}</b></td><td class=n>{r['tf']}</td>"
                f"<td><span class='s {cls}'>{r.get('state','divergence')}</span></td>"
                f"<td class=n>{r.get('detail','')}</td>"
                f"<td class=n>{'ok' if r.get('htf_favourable') else '-'}</td>"
                f"<td class=n>{r.get('invalidation','')}</td>"
                f"<td>{r.get('score','')}</td>"
                f"{_dss_cell(d.get('1d'))}{_dss_cell(d.get('1w'))}{_dss_cell(d.get('1M'))}"
                f"<td><a href='{url}' target=_blank>chart</a></td></tr>")
        h.append("</table></div>")
    return h

def _render_tier(tier, groups, notes, outdir, ts):
    out = os.path.join(outdir, f"{tier.lower()}.html")
    h = [_head(f"Setup scan — Tier {tier}"),
         f"<h1>{TIER_LABEL[tier]}</h1>",
         f"<div class=sub>last run {ts} &middot; <a href='index.html'>&larr; all tiers</a></div>"]
    for n in notes:
        h.append(f"<div class=warn>{n}</div>")
    h.append("<div class=sub>DSS Bressert (fast / slow) on daily / weekly / monthly &middot; "
             f"<span class=dg>&le;{DSS_GREEN:g} bottoming</span> &middot; "
             f"<span class=dr>&ge;{DSS_RED:g} topping</span></div>")
    h += _tables(groups)
    open(out, "w", encoding="utf-8").write("\n".join(h))
    json.dump({"generated": ts, "groups": {t: r for t, r in groups}},
              open(os.path.join(outdir, f"{tier.lower()}.json"), "w"), indent=1)

def _index_signals(info):
    if "board" in info:
        return (f"{info['board']} tracked &middot; "
                f"<span class=dg>{info.get('bottoming', 0)}</span> bottoming &middot; "
                f"<span class=dr>{info.get('topping', 0)}</span> topping")
    return f"{info.get('compression', 0)} compression &middot; {info.get('divergence', 0)} divergence"

def _render_index(outdir, status):
    h = [_head("Setup scan"),
         "<h1>Setup scan</h1>",
         f"<div class=sub>index updated {_now()}</div>",
         "<table><tr><th>tier</th><th>last run</th><th>signals</th><th></th></tr>"]
    for t in INDEX_TIERS:
        info = status.get(t)
        if info:
            h.append(
                f"<tr><td><b>{TIER_LABEL[t]}</b></td>"
                f"<td class=n>{info['ts']}</td>"
                f"<td class=n>{_index_signals(info)}</td>"
                f"<td><a href='{t.lower()}.html'>view &rarr;</a></td></tr>")
        else:
            h.append(
                f"<tr><td><b>{TIER_LABEL[t]}</b></td>"
                "<td class=n>not run yet</td><td class=n>&ndash;</td>"
                "<td class=n></td></tr>")
    h.append("</table>")
    open(os.path.join(outdir, "index.html"), "w", encoding="utf-8").write("\n".join(h))

def _board_table(rows):
    h = ["<div style='overflow-x:auto'><table><tr><th>symbol</th>"
         "<th>dss D</th><th>dss W</th><th>dss M</th><th></th></tr>"]
    for r in rows:
        url = TV.format(sym=r.get("tv_symbol", r["symbol"]), iv=IV["1d"])
        d = r.get("dss") or {}
        h.append(
            f"<tr><td><b>{r['symbol']}</b></td>"
            f"{_dss_cell(d.get('1d'))}{_dss_cell(d.get('1w'))}{_dss_cell(d.get('1M'))}"
            f"<td><a href='{url}' target=_blank>chart</a></td></tr>")
    h.append("</table></div>")
    return h

def _board_counts(rows):
    """Rows with any fast DSS <=green (bottoming) / >=red (topping)."""
    bottoming = topping = 0
    for r in rows:
        fasts = [p[0] for p in (r.get("dss") or {}).values() if p]
        if any(f <= DSS_GREEN for f in fasts):
            bottoming += 1
        if any(f >= DSS_RED for f in fasts):
            topping += 1
    return bottoming, topping

def publish_board(tier, rows, notes, outdir="docs"):
    """Publish a DSS board page (one row per instrument, no setup required) and
    refresh the shared index. Used for the tokenized-stock and commodity tiers."""
    os.makedirs(outdir, exist_ok=True)
    ts = _now()
    out = os.path.join(outdir, f"{tier.lower()}.html")
    h = [_head(f"Setup scan — Tier {tier}"),
         f"<h1>{TIER_LABEL[tier]}</h1>",
         f"<div class=sub>last run {ts} &middot; <a href='index.html'>&larr; all tiers</a></div>"]
    for n in notes:
        h.append(f"<div class=warn>{n}</div>")
    h.append("<div class=sub>DSS Bressert (fast / slow) on daily / weekly / monthly &middot; "
             f"<span class=dg>&le;{DSS_GREEN:g} bottoming</span> &middot; "
             f"<span class=dr>&ge;{DSS_RED:g} topping</span> &middot; sorted extremes-first</div>")
    h += _board_table(rows) if rows else ["<div class=sub>nothing</div>"]
    open(out, "w", encoding="utf-8").write("\n".join(h))
    json.dump({"generated": ts,
               "rows": [{"symbol": r["symbol"], "dss": r.get("dss")} for r in rows]},
              open(os.path.join(outdir, f"{tier.lower()}.json"), "w"), indent=1)
    status_path = os.path.join(outdir, "status.json")
    status = {}
    if os.path.exists(status_path):
        try:
            status = json.load(open(status_path))
        except Exception:
            status = {}
    bottoming, topping = _board_counts(rows)
    status[tier] = {"ts": ts, "board": len(rows),
                    "bottoming": bottoming, "topping": topping}
    json.dump(status, open(status_path, "w"), indent=1)
    _render_index(outdir, status)

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
