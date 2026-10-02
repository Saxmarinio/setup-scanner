"""Exclusive sector and home-chain membership for the spaghetti charts.

Membership is resolved from a committed snapshot (config/membership.json)
rather than live API calls. CoinGecko's free tier returns HTTP 429 after about
three rapid requests, so a page that fetched membership on load would simply
fail; and a committed file means a sector gaining or losing a coin shows up in
a git diff instead of changing the chart silently overnight.

Refresh the snapshot with:  python src/fetch/categories.py
"""
import json, os
import yaml

MEMBERSHIP = os.path.join("config", "membership.json")
CONFIG = os.path.join("config", "sectors.yaml")


def load_cfg(path=CONFIG):
    return yaml.safe_load(open(path, encoding="utf-8"))


def _exclusive(groups, priority, universe, exclude=()):
    """Walk `priority` and let each group claim the members nobody above it
    took. Returns {symbol: group}. Order is the whole design: see sectors.yaml."""
    owner, claimed = {}, set(exclude)
    for name in priority:
        for sym in sorted(set(groups.get(name, ())) & universe):
            if sym not in claimed:
                owner[sym] = name
        claimed |= set(groups.get(name, ()))
    return owner


def build(universe, cfg=None, snapshot=None):
    """universe: iterable of base symbols (no quote), e.g. {"BTC","ETH",...}

    Returns a dict with:
      sector  {symbol: sector}      exclusive, every symbol present
      chain   {symbol: chain}       exclusive, absent when no chain is known
      sectors {sector: [symbols]}   ready-to-use baskets, min_members applied
      chains  {chain: [symbols]}
      cells   {(chain, sector): [symbols]}  for the per-chain breakdown
    """
    cfg = cfg or load_cfg()
    c = cfg["crypto"]
    snap = snapshot if snapshot is not None else json.load(open(MEMBERSHIP, encoding="utf-8"))
    uni = set(universe)
    exclude = set(c.get("exclude", []))

    raw_sec = {k: snap.get(v, []) for k, v in c["sector_source"].items()}
    for name, syms in (c.get("overrides") or {}).items():
        raw_sec[name] = syms                      # curation wins over the tag
    raw_ch = {k: snap.get(v, []) for k, v in c["chain_source"].items()}

    sector = _exclusive(raw_sec, c["sector_priority"], uni, exclude)
    chain = _exclusive(raw_ch, c["chain_priority"], uni, exclude)

    other = c.get("uncategorised", "Uncategorised")
    for s in uni - exclude:
        sector.setdefault(s, other)

    sectors, chains, cells = {}, {}, {}
    for s, name in sector.items():
        sectors.setdefault(name, []).append(s)
    for s, name in chain.items():
        chains.setdefault(name, []).append(s)
    for s, name in chain.items():
        cells.setdefault((name, sector[s]), []).append(s)

    lo = c.get("min_members", 4)
    sectors = {k: sorted(v) for k, v in sectors.items() if len(v) >= lo}
    chains = {k: sorted(v) for k, v in chains.items() if len(v) >= lo}
    cells = {k: sorted(v) for k, v in cells.items() if len(v) >= lo}
    return {"sector": sector, "chain": chain,
            "sectors": sectors, "chains": chains, "cells": cells}


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from fetch import crypto
    uni = {s[:-4] for s in crypto.universe() if s.endswith("USDT")}
    m = build(uni)
    print("universe %d symbols" % len(uni))
    print("\nSECTORS")
    for k, v in sorted(m["sectors"].items(), key=lambda x: -len(x[1])):
        print("  %-14s %3d" % (k, len(v)))
    print("\nHOME CHAINS")
    for k, v in sorted(m["chains"].items(), key=lambda x: -len(x[1])):
        print("  %-14s %3d" % (k, len(v)))
    print("\nCHAIN x SECTOR cells with >= %d members"
          % load_cfg()["crypto"]["min_members"])
    for (ch, se), v in sorted(m["cells"].items(), key=lambda x: (x[0][0], -len(x[1]))):
        print("  %-10s %-14s %3d" % (ch, se, len(v)))
