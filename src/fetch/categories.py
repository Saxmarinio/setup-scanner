#!/usr/bin/env python3
"""Refresh config/membership.json from CoinGecko.

Run occasionally, not per build. The free tier returns HTTP 429 after roughly
three rapid requests, so every call is paced ~14s apart and the whole refresh
takes a few minutes. The result is committed, which is the point: a coin
joining or leaving a sector then appears in a git diff rather than quietly
changing what the chart means.

  python src/fetch/categories.py
"""
import json, os, sys, time
import requests
import yaml

B = "https://api.coingecko.com/api/v3/coins/markets"
OUT = os.path.join("config", "membership.json")
CFG = os.path.join("config", "sectors.yaml")
PACE = 14          # seconds between calls; below ~10 the free tier 429s
RETRY_WAIT = 20


def fetch(cat, tries=5):
    for _ in range(tries):
        r = requests.get(B, params={"vs_currency": "usd", "category": cat,
                                    "order": "market_cap_desc",
                                    "per_page": 250, "page": 1}, timeout=45)
        if r.status_code == 200:
            return sorted({x["symbol"].upper() for x in r.json()})
        if r.status_code not in (429, 503):
            r.raise_for_status()
        time.sleep(RETRY_WAIT)
    return None


def main():
    cfg = yaml.safe_load(open(CFG, encoding="utf-8"))["crypto"]
    cats = sorted(set(cfg["sector_source"].values()) | set(cfg["chain_source"].values()))
    old = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    new = dict(old)
    for i, cat in enumerate(cats):
        got = fetch(cat)
        if got is None:
            print("  %-28s rate-limited out, keeping previous" % cat, flush=True)
            continue
        before = set(old.get(cat, []))
        added, gone = set(got) - before, before - set(got)
        note = ""
        if before and (added or gone):
            note = "  +%d -%d" % (len(added), len(gone))
        new[cat] = got
        print("  %-28s %3d%s" % (cat, len(got), note), flush=True)
        if i < len(cats) - 1:
            time.sleep(PACE)
    json.dump(new, open(OUT, "w", encoding="utf-8"), indent=0, sort_keys=True)
    print("wrote %s (%d categories)" % (OUT, len(new)))


if __name__ == "__main__":
    sys.exit(main())
