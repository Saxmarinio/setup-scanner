#!/usr/bin/env python3
"""Build the relative-strength ("spaghetti") boards.

Each line is an EQUAL-WEIGHT basket: every member rebased to 0% at the window's
left edge, then averaged. Equal weight is the point - a cap-weighted crypto
sector is just its largest coin, and the question being asked is "is this theme
moving", not "is this one token moving".

Member stats are derived from a single 15m series rather than three fetches:
the last bar gives 15m, sixteen bars back gives 4H, and the first bar of the
current UTC day gives the daily candle. One request per coin instead of three.

  python src/build_spaghetti.py                 # everything
  python src/build_spaghetti.py --crypto-only
  python src/build_spaghetti.py --limit 40      # quick smoke test
"""
import argparse, json, os, sys, time
import numpy as np, pandas as pd, yaml

sys.path.insert(0, os.path.dirname(__file__))
import sectors as sectormod
from fetch import crypto, equity

OUT = os.path.join("docs", "spaghetti")
CACHE = os.path.join("data", "spaghetti")
KEEP = 1000
# Generous on purpose. A full crypto build takes ~30 minutes, so a 10-minute
# staleness window meant a restart re-fetched everything it had just fetched
# and could never finish. The boards rebuild every 4h anyway - a 45-minute-old
# 15m bar is not the problem a stalled build is.
STALE_MIN = {"15m": 45, "1h": 120, "4h": 240, "1d": 720}
_RUN_START = time.time()


# ---------------------------------------------------------------- data access
def bars(symbol, tf, kind):
    """Disk-cached bars. csv.gz rather than the shared parquet store: this
    builder has to run anywhere, and parquet needs pyarrow installed."""
    d = os.path.join(CACHE, tf)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "%s.csv.gz" % symbol.replace("/", "_"))
    if os.path.exists(p):
        mt = os.path.getmtime(p)
        age_min = (time.time() - mt) / 60.0
        # Anything this run already wrote is fresh by definition, whatever the
        # clock says - one build must never fetch the same symbol twice.
        if age_min < STALE_MIN.get(tf, 60) or mt >= _RUN_START:
            try:
                return pd.read_csv(p, parse_dates=["datetime"])
            except Exception:
                pass
    try:
        new = (crypto.klines(symbol, tf, limit=KEEP) if kind == "crypto"
               else equity.klines(symbol, tf,
                                  lookback={"1d": "5y"}.get(tf, "2y")))
    except Exception:
        new = None
    if new is None or new.empty:
        # Never lose a good cache because one fetch failed.
        return pd.read_csv(p, parse_dates=["datetime"]) if os.path.exists(p) else None
    new = new.tail(KEEP).reset_index(drop=True)
    new.to_csv(p, index=False, compression="gzip")
    return new


def window_slice(df, span_days):
    """span_days of 0 means year-to-date."""
    if df is None or df.empty:
        return None
    d = df.copy()
    d["datetime"] = pd.to_datetime(d["datetime"])
    end = d["datetime"].max()
    cut = pd.Timestamp(year=end.year, month=1, day=1) if span_days == 0 \
        else end - pd.Timedelta(days=span_days)
    out = d[d["datetime"] >= cut]
    return out if len(out) >= 3 else None


# ------------------------------------------------------------------ composite
def paths(members, tf, span_days, kind, cache):
    """Each member's % path over the window, on a shared time grid."""
    series = {}
    for m in members:
        sym = m + "USDT" if kind == "crypto" else m
        df = cache.get((sym, tf))
        if df is None:
            df = bars(sym, tf, kind)
            cache[(sym, tf)] = df
        w = window_slice(df, span_days)
        if w is None:
            continue
        c = w["close"].to_numpy(float)
        if c[0] <= 0:
            continue
        s = pd.Series((c / c[0] - 1.0) * 100.0,
                      index=pd.to_datetime(w["datetime"]).to_numpy())
        series[m] = s[~s.index.duplicated(keep="last")]
    if not series:
        return None, None
    # Union of timestamps, forward-filled: members listed mid-window simply have
    # no value before they existed, and must not drag the average to zero.
    grid = sorted(set().union(*[set(s.index) for s in series.values()]))
    frame = pd.DataFrame({k: v.reindex(grid).ffill() for k, v in series.items()},
                         index=pd.DatetimeIndex(grid))
    return frame, grid


def member_stats(members, kind, cache):
    """price, 15m, 4H and daily-candle change - all from one 15m series."""
    out = {}
    for m in members:
        sym = m + "USDT" if kind == "crypto" else m
        df = cache.get((sym, "15m")) if kind == "crypto" else None
        if df is None or len(df) < 100:
            continue
        d = df.copy()
        d["datetime"] = pd.to_datetime(d["datetime"])
        c = d["close"].to_numpy(float)
        last = float(c[-1])
        day = d[d["datetime"].dt.date == d["datetime"].iloc[-1].date()]
        stats = {"price": last}
        stats["m15"] = round((last / c[-2] - 1) * 100, 2) if len(c) >= 2 else None
        stats["h4"] = round((last / c[-17] - 1) * 100, 2) if len(c) >= 17 else None
        if len(day):
            o = float(day["open"].iloc[0])
            stats["d1"] = round((last / o - 1) * 100, 2) if o > 0 else None
            stats["d1abs"] = round(last - o, 10) if o > 0 else None
        out[m] = stats
    return out


def board(groups, baseline, tf, span_days, kind, cache, stats_cache):
    """One board, one window: a composite line per group, plus the baseline."""
    lines, members_out = {}, {}
    for name, mem in groups.items():
        frame, grid = paths(mem, tf, span_days, kind, cache)
        if frame is None:
            continue
        comp = frame.mean(axis=1)
        present = [c for c in frame.columns]
        end = {c: (float(frame[c].iloc[-1]) if pd.notna(frame[c].iloc[-1]) else None)
               for c in present}
        n = len(present)
        rows = []
        for c in present:
            st = stats_cache.get(c, {})
            rows.append({"sym": c, "pct": None if end[c] is None else round(end[c], 2),
                         # In an equal-weight basket a member moves the line by
                         # its own move divided by the member count. This is the
                         # column that answers "who is responsible".
                         "contrib": None if end[c] is None else round(end[c] / n, 3),
                         "price": st.get("price"), "m15": st.get("m15"),
                         "h4": st.get("h4"), "d1": st.get("d1"), "d1abs": st.get("d1abs")})
        rows.sort(key=lambda r: (r["contrib"] is None, -(r["contrib"] or 0)))
        lines[name] = {"path": [round(float(v), 3) if pd.notna(v) else None for v in comp],
                       "n": n}
        members_out[name] = rows
    if not lines:
        return None
    base_frame, grid = paths([baseline], tf, span_days, kind, cache)
    if base_frame is not None:
        lines["__baseline__"] = {"path": [round(float(v), 3) if pd.notna(v) else None
                                          for v in base_frame.mean(axis=1)],
                                 "n": 1, "label": baseline}
    ts = [int(pd.Timestamp(g).timestamp()) for g in (grid or [])]
    return {"t": ts, "lines": lines, "members": members_out, "baseline": baseline}


# ----------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--crypto-only", action="store_true")
    ap.add_argument("--tradfi-only", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="cap members per group")
    # A full crypto build exceeds a 30-minute budget on a cold cache. Chunking
    # by board keeps every invocation finishable, and the index merges.
    ap.add_argument("--boards", default="", help="comma-separated board id prefixes")
    a = ap.parse_args()

    cfg = sectormod.load_cfg()
    os.makedirs(OUT, exist_ok=True)
    # Merge rather than replace: a --crypto-only run must not delete the tradfi
    # boards from the index (and vice versa).
    ipath = os.path.join(OUT, "index.json")
    index = {"boards": [], "built": ""}
    if os.path.exists(ipath):
        try:
            index = json.load(open(ipath, encoding="utf-8"))
        except Exception:
            pass
    index["built"] = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    if a.crypto_only:
        keep = lambda b: b.get("kind") == "tradfi"
    elif a.tradfi_only:
        keep = lambda b: b.get("kind") == "crypto"
    else:
        keep = lambda b: False
    prior = [b for b in index.get("boards", []) if keep(b)]
    # A partial run must not delete the boards it simply did not touch.
    if a.boards:
        want = [x.strip() for x in a.boards.split(",") if x.strip()]
        prior += [b for b in index.get("boards", [])
                  if not keep(b) and not any(b["id"].startswith(w) for w in want)]
    index["boards"] = prior

    if not a.tradfi_only:
        uni = {s[:-4] for s in crypto.universe() if s.endswith("USDT")}
        m = sectormod.build(uni, cfg)
        cc = cfg["crypto"]
        cache = {}
        print("crypto universe %d, %d sectors, %d chains"
              % (len(uni), len(m["sectors"]), len(m["chains"])), flush=True)

        all_syms = sorted({s for v in m["sectors"].values() for s in v} | {cc["baseline"]})
        if a.limit:
            all_syms = all_syms[:a.limit]
        print("  prefetching 15m for member stats (%d symbols)..." % len(all_syms), flush=True)
        for i, s in enumerate(all_syms):
            cache[(s + "USDT", "15m")] = bars(s + "USDT", "15m", "crypto")
            if (i + 1) % 50 == 0:
                print("    %d/%d" % (i + 1, len(all_syms)), flush=True)
        stats = member_stats(all_syms, "crypto", cache)

        def trim(groups):
            return {k: (v[:a.limit] if a.limit else v) for k, v in groups.items()}

        boards = [("crypto-sector", "Crypto sectors", trim(m["sectors"]))]
        for ch in sorted({c for c, _ in m["cells"]}):
            g = {se: v for (c, se), v in m["cells"].items() if c == ch}
            if len(g) >= 2:
                boards.append(("crypto-chain-" + ch.lower(), "%s by sector" % ch, trim(g)))
        boards.append(("crypto-chain", "Crypto home chains", trim(m["chains"])))

        want = [x.strip() for x in a.boards.split(",") if x.strip()]
        if want:
            boards = [b for b in boards if any(b[0].startswith(w) for w in want)]
        for bid, title, groups in boards:
            wins = {}
            for wname, w in cfg["windows"]["crypto"].items():
                r = board(groups, cc["baseline"], w["tf"], w["span_days"],
                          "crypto", cache, stats)
                if r:
                    wins[wname] = r
                print("  %-26s %-4s %s" % (bid, wname, "ok" if r else "no data"), flush=True)
            if wins:
                json.dump(wins, open(os.path.join(OUT, bid + ".json"), "w"),
                          separators=(",", ":"))
                index["boards"].append({"id": bid, "title": title, "kind": "crypto",
                                        "windows": list(wins)})

    if not a.crypto_only:
        cache, stats = {}, {}
        for title, spec in cfg["tradfi"]["boards"].items():
            groups = {label: [tk] for tk, label in spec["members"].items()}
            if a.limit:
                groups = dict(list(groups.items())[:a.limit])
            bid = "tradfi-" + title.lower().replace(" & ", "-").replace(" ", "-")
            wins = {}
            for wname, w in cfg["windows"]["tradfi"].items():
                r = board(groups, spec["baseline"], w["tf"], w["span_days"],
                          "equity", cache, stats)
                if r:
                    wins[wname] = r
                print("  %-26s %-4s %s" % (bid, wname, "ok" if r else "no data"), flush=True)
            if wins:
                json.dump(wins, open(os.path.join(OUT, bid + ".json"), "w"),
                          separators=(",", ":"))
                index["boards"].append({"id": bid, "title": title, "kind": "tradfi",
                                        "windows": list(wins)})

    json.dump(index, open(os.path.join(OUT, "index.json"), "w"), indent=1)
    print("\nwrote %d boards to %s" % (len(index["boards"]), OUT))


if __name__ == "__main__":
    main()
