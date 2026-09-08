#!/usr/bin/env python3
"""Deep-history backtest for the compression detector.

  python src/backtest.py --tf 4h --start 2023-01-01 --symbols 150

The live scanner only ever fetches ~1000 bars, which on 4H is under six months.
That is a single regime, and a single regime cannot tell you whether a
continuation setup works - a long-only trend setup is *supposed* to lose in a
whipsaw and win in a trend. This pages the public Binance mirror back years so
detections can be scored against the market they actually occurred in.

What it reports, and why each piece is there:

  * detections vs BASELINE. A negative median means nothing on its own: if the
    average alt fell over the sample, everything fell. The comparison that
    matters is against all bars, and against trend-up bars (which isolates
    what the compression detector adds on top of the trend gate).
  * a PERMUTATION TEST. With few detections, the difference between the
    detector and the baseline is usually inside the noise band. This says
    whether it is.
  * a per-year BREAKDOWN, because the whole point is to see a bull leg.

Survivorship bias: the universe is what is listed TODAY, so coins that died are
absent. That flatters every number here. Read the levels with suspicion; the
detector-vs-baseline gap is the part that survives the bias, since both sides
are drawn from the same survivors.
"""
import argparse, os, sys, time
import numpy as np, pandas as pd, yaml

sys.path.insert(0, os.path.dirname(__file__))
from detectors.compression import compression_noodle
from detectors.noodle import money_noodle
from detectors import trend as trendmod
from fetch import crypto

CACHE = os.path.join("data", "backtest")
WIN = 400          # bars of context handed to the detector per evaluation
TF_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000,
         "12h": 43_200_000, "1d": 86_400_000}


def deep_history(symbol, tf, start_ms, cache=True):
    """Page the mirror forward from start_ms. Cached per symbol/tf."""
    d = os.path.join(CACHE, tf)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "%s.csv.gz" % symbol)
    if cache and os.path.exists(p):
        return pd.read_csv(p, parse_dates=["datetime"])
    out, cur = [], start_ms
    while True:
        try:
            df = crypto.klines(symbol, tf, start_ms=cur, limit=1000)
        except Exception:
            break
        if df is None or df.empty:
            break
        out.append(df)
        last = int(pd.Timestamp(df["datetime"].iloc[-1]).timestamp() * 1000)
        if len(df) < 900:              # caught up to the present
            break
        nxt = last + TF_MS[tf]
        if nxt <= cur:
            break
        cur = nxt
    if not out:
        return None
    df = (pd.concat(out).drop_duplicates("datetime", keep="last")
            .sort_values("datetime").reset_index(drop=True))
    if cache:
        df.to_csv(p, index=False, compression="gzip")
    return df


def simulate(h, l, c, i, stop, targets=(2.0, 3.0), max_bars=120):
    """Trade the setup as it would actually be traded: long at the close, stop
    at the detector's own invalidation (a close back under the noodle), target
    a multiple of that risk.

    Fixed-horizon returns answer the wrong question - a setup can have a poor
    30-bar median and still be profitable if the losers are cut at 1R, or vice
    versa. When a bar spans both stop and target, the stop is assumed hit
    first; without intrabar data that is the honest assumption, not the
    flattering one.
    """
    entry = c[i]
    risk = entry - stop
    out = {"r_stop": None}
    if risk <= 0:
        return {"r_%g" % k: None for k in targets}
    res = {}
    for k in targets:
        tgt = entry + k * risk
        r = 0.0
        for j in range(i + 1, min(i + 1 + max_bars, len(c))):
            if l[j] <= stop:
                r = -1.0
                break
            if h[j] >= tgt:
                r = k
                break
        else:
            r = (c[min(i + max_bars, len(c) - 1)] - entry) / risk
        res["r_%g" % k] = r
    return res


def run(tf, start, nsym, fwd, cfg):
    ccfg, ncfg, tcfg = cfg["compression"][tf], cfg["noodle"], cfg["trend"]
    start_ms = int(pd.Timestamp(start).timestamp() * 1000)
    syms = crypto.universe()[:nsym]
    dets, all_r, up_r, base_r = [], [], [], []
    rs = np.random.default_rng(0)

    for si, s in enumerate(syms):
        try:
            df = deep_history(s, tf, start_ms)
        except Exception:
            continue
        if df is None or len(df) < 400:
            continue
        nd = money_noodle(df, ncfg["ema_fast"], ncfg["ema_medium"], ncfg["ema_slow"],
                          ncfg["atr_len"], ncfg["band_mult"])
        states, _ = trendmod.trend_series(df, nd, left=tcfg["pivot_width"],
                                          right=tcfg["pivot_width"],
                                          n_swings=tcfg["n_swings"], tau=tcfg["tau"],
                                          break_k=tcfg["break_k"])
        c = df["close"].values
        mainline = nd["main"].values
        hi, lo_ = df["high"].values, df["low"].values
        dt = df["datetime"].values
        n = len(df)
        last_hit = -99
        for i in range(200, n - fwd):
            r = c[i + fwd] / c[i] - 1.0
            all_r.append(r)
            if states[i] != "up":
                continue
            up_r.append(r)
            # The same trade rule applied to an ordinary trend-up bar. The R
            # figures below are meaningless without knowing what simply being
            # in an uptrend would have paid.
            if rs.random() < 0.02:
                base_r.append(simulate(hi, lo_, c, i, mainline[i]))
            # Bounded window: the detector needs ~120 bars of context, so a
            # growing slice would make this O(n^2) for no gain.
            lo = max(0, i - WIN + 1)
            res = compression_noodle(df.iloc[lo:i + 1], nd.iloc[lo:i + 1], ccfg)
            if res is None or i - last_hit < 15:
                continue
            last_hit = i
            rec = {"sym": s, "dt": dt[i], "state": res["state"], "fwd": r,
                   "mfe": c[i + 1:i + 1 + fwd].max() / c[i] - 1.0,
                   "mae": c[i + 1:i + 1 + fwd].min() / c[i] - 1.0}
            rec.update(simulate(hi, lo_, c, i, res["invalidation"]))
            dets.append(rec)
        if (si + 1) % 20 == 0:
            print("[%d/%d] %d detections, %d bars"
                  % (si + 1, len(syms), len(dets), len(all_r)), flush=True)

    d = pd.DataFrame(dets)
    d.to_csv("backtest_%s.csv" % tf, index=False)
    report(d, np.asarray(all_r), np.asarray(up_r), tf, fwd,
           pd.DataFrame(base_r))
    return d


def report(d, all_r, up_r, tf, fwd, base=None):
    def line(name, v):
        v = np.asarray(v, float)
        if not len(v):
            return
        print("  %-26s n=%-7d median %+7.3f   mean %+7.3f   win %5.1f%%"
              % (name, len(v), np.median(v), v.mean(), 100 * (v > 0).mean()))

    print("\n" + "=" * 78)
    print("COMPRESSION BACKTEST  %s   forward %d bars" % (tf, fwd))
    print("=" * 78)
    line("all bars", all_r)
    line("trend-up bars", up_r)
    if len(d):
        line("compression detections", d.fwd.values)
        for st, g in d.groupby("state"):
            line("  state=%s" % st, g.fwd.values)

    if len(d) and len(up_r) > len(d):
        obs = float(np.median(d.fwd.values))
        rng = np.random.default_rng(0)
        meds = np.array([np.median(rng.choice(up_r, len(d), replace=False))
                         for _ in range(20000)])
        lo, hi = np.percentile(meds, [2.5, 97.5])
        print("\n  permutation vs trend-up baseline (%d draws of n=%d):" % (20000, len(d)))
        print("    observed median %+.3f, random band %+.3f .. %+.3f" % (obs, lo, hi))
        print("    P(random <= observed) = %.3f  ->  %s"
              % ((meds <= obs).mean(),
                 "INSIDE the noise band - not distinguishable"
                 if lo <= obs <= hi else "OUTSIDE the noise band"))

    for col in [x for x in getattr(d, "columns", []) if x.startswith("r_")]:
        v = pd.to_numeric(d[col], errors="coerce").dropna().values
        if len(v):
            print("")
            print("  traded at %sR target, stop = invalidation: n=%d"
                  % (col[2:], len(v)))
            print("    detections : expectancy %+.3fR   win %.1f%%" % (v.mean(), 100 * (v > 0).mean()))
            if base is not None and len(base) and col in base:
                bv = pd.to_numeric(base[col], errors="coerce").dropna().values
                if len(bv):
                    print("    trend-up   : expectancy %+.3fR   win %.1f%%   (n=%d)"
                          % (bv.mean(), 100 * (bv > 0).mean(), len(bv)))

    if len(d):
        d = d.copy()
        d["year"] = pd.to_datetime(d.dt).dt.year
        print("\n  by year:")
        g = d.groupby("year").agg(n=("fwd", "size"), median=("fwd", "median"),
                                  win=("fwd", lambda x: (x > 0).mean()),
                                  mfe=("mfe", "median"), mae=("mae", "median"))
        print(g.round(3).to_string())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="4h")
    ap.add_argument("--start", default="2023-01-01")
    ap.add_argument("--symbols", type=int, default=150)
    ap.add_argument("--fwd", type=int, default=30)
    ap.add_argument("--config", default="config/tiers.yaml")
    a = ap.parse_args()
    run(a.tf, a.start, a.symbols, a.fwd, yaml.safe_load(open(a.config)))
