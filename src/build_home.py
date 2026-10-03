#!/usr/bin/env python3
"""Write docs/index.html - the dashboard front page.

Deliberately standalone rather than part of render.py: the scan workflows, the
boards workflow and the cycles build all write into docs/, and the front page
must exist whether or not any of them has run yet. It reads whatever status
files happen to be there and simply omits what is missing.

  python src/build_home.py
"""
import json, os, time

OUT = "docs"

CARDS = [
    {"href": "spaghetti.html", "title": "Relative Strength",
     "blurb": "Which sector, chain or asset class is leading. Equal-weight "
              "baskets against BTC and SPY, 15m through YTD.",
     "status": ("spaghetti/index.json", "boards"),
     "accent": "#26a69a"},
    {"href": "cycles.html", "title": "Cycle Composites",
     "blurb": "The average shape of a year, from up to 99 years of history. "
              "Election cycles, decade offsets, bull and bear years.",
     "status": None, "accent": "#b388ff"},
    {"href": "scans.html", "title": "Setup Scans",
     "blurb": "Noodle compression, roofed-RSI divergence and bottoming "
              "patterns across crypto, equities and commodities.",
     "status": ("status.json", "tiers"),
     "accent": "#ff9800"},
]

CSS = """
*{box-sizing:border-box}
body{background:#131722;color:#d1d4dc;font:14px/1.6 -apple-system,Segoe UI,sans-serif;
     margin:0;padding:48px 24px 80px}
.page{max-width:900px;margin:0 auto}
h1{font-size:26px;font-weight:600;margin:0 0 6px;letter-spacing:-.01em}
.sub{color:#787b86;font-size:13px;margin-bottom:34px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(252px,1fr));gap:14px}
a.card{display:block;background:#1a1e29;border:1px solid #2a2e39;border-radius:6px;
       padding:20px 20px 18px;text-decoration:none;color:inherit;position:relative;
       overflow:hidden;transition:border-color .12s,transform .12s}
a.card:hover{border-color:#3d4452;transform:translateY(-1px)}
a.card:focus-visible{outline:2px solid #2196f3;outline-offset:2px}
a.card .rail{position:absolute;left:0;top:0;bottom:0;width:3px}
a.card h2{font-size:15px;font-weight:600;margin:0 0 7px;color:#eceff4}
a.card p{margin:0;color:#9aa0ab;font-size:12.5px;line-height:1.55}
a.card .stat{margin-top:13px;font-size:11px;color:#787b86;font-variant-numeric:tabular-nums}
.foot{margin-top:40px;color:#5d6270;font-size:11.5px}
.foot a{color:#787b86}
"""


def _status():
    out = {}
    p = os.path.join(OUT, "status.json")
    if os.path.exists(p):
        try:
            st = json.load(open(p, encoding="utf-8"))
            tiers = [k for k in st if k != "S"]
            last = sorted((st[k].get("ts", "") for k in tiers), reverse=True)
            out["tiers"] = "%d tiers tracked%s" % (
                len(tiers), (" · last run %s" % last[0]) if last and last[0] else "")
        except Exception:
            pass
    p = os.path.join(OUT, "spaghetti", "index.json")
    if os.path.exists(p):
        try:
            idx = json.load(open(p, encoding="utf-8"))
            out["boards"] = "%d boards · built %s" % (
                len(idx.get("boards", [])), idx.get("built", "?"))
        except Exception:
            pass
    return out


def main():
    st = _status()
    h = ["<!doctype html><meta charset=utf-8>",
         "<meta name=viewport content='width=device-width,initial-scale=1'>",
         "<title>Saxmarinio Dashboard</title>",
         "<style>%s</style>" % CSS,
         "<div class=page>",
         "<h1>Saxmarinio Dashboard</h1>",
         "<div class=sub>Market structure, relative strength and seasonality &mdash; "
         "rebuilt automatically from public data.</div>",
         "<div class=grid>"]
    for c in CARDS:
        line = ""
        if c["status"] and c["status"][1] in st:
            line = "<div class=stat>%s</div>" % st[c["status"][1]]
        h.append(
            "<a class=card href='%s'><span class=rail style='background:%s'></span>"
            "<h2>%s</h2><p>%s</p>%s</a>"
            % (c["href"], c["accent"], c["title"], c["blurb"], line))
    h.append("</div>")
    h.append("<div class=foot>Page generated %s &middot; "
             "<a href='https://github.com/Saxmarinio/setup-scanner'>source</a></div>"
             % time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()))
    h.append("</div>")
    with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as f:
        f.write("\n".join(h))
    print("wrote %s/index.html" % OUT)


if __name__ == "__main__":
    main()
