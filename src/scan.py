#!/usr/bin/env python3
"""Scanner entry point.

  python src/scan.py --tier A     # top-10 crypto, 4H scan + 1D confirm
  python src/scan.py --tier B     # rest of crypto, 1H scan + 4H/1D confirm
  python src/scan.py --tier C     # equities/ETFs, 1D
"""
import argparse, os, sys, time, traceback
import numpy as np, pandas as pd, yaml

sys.path.insert(0, os.path.dirname(__file__))
from detectors.compression import compression_state, htf_posture
from detectors import l1, dss
from fetch import crypto, store, equity
import rank as ranker
import render as renderer

BARS = {"1h": 900, "4h": 900, "1d": 700}


def load_cfg(p="config/tiers.yaml"):
    return yaml.safe_load(open(p))


def get_bars(symbol, tf, kind):
    """Incremental: fetch only what is missing, then upsert."""
    have = store.load(symbol, tf)
    start = None
    if have is not None and len(have):
        start = int(pd.Timestamp(have["datetime"].iloc[-1]).timestamp() * 1000) + 1
    if kind == "crypto":
        new = crypto.klines(symbol, tf, start_ms=start, limit=1000)
    else:
        from fetch import equity
        new = equity.klines(symbol, tf)
    if new is None or new.empty:
        return have
    return store.upsert(symbol, tf, new, keep_bars=BARS[tf])


def divergence_rows(df, dcfg, symbol, tf):
    """Latest bullish divergence, if it fired recently."""
    ind = l1.build(df, roofHi=dcfg["roof_hi"], roofLo=dcfg["roof_lo"],
                   oscLen=dcfg["osc_len"], hurstLen=dcfg["hurst_len"],
                   hurstMult=dcfg["hurst_mult"])
    sC, sB = l1.divergences(df, ind, pivL=dcfg["piv_l"], pivR=dcfg["piv_r"],
                            margC=dcfg["marg_c"], margB=dcfg["marg_b"],
                            maxGap=dcfg["max_gap"], pctb_field="braw")
    out = []
    n = len(df)
    for sig, name in ((sC, "roofed RSI"), (sB, "channel %B")):
        if not sig:
            continue
        last = sig[-1]
        since = n - 1 - last
        if since > 5:                      # only surface fresh signals
            continue
        out.append({
            "symbol": symbol, "tf": tf, "state": "divergence",
            "detail": f"{name}, fired {since} bars ago",
            "bars_since": since,
            "margin_excess": 0.0,
            "invalidation": round(float(df['low'].iloc[last - dcfg['piv_r']]), 6),
        })
    return out


def dss_dwm(sym, kind, dcfg):
    """Latest DSS Bressert (fast, slow) on daily / weekly / monthly for one
    symbol; None per timeframe when there aren't enough bars for a stable read."""
    out = {}
    for tf in ("1d", "1w", "1M"):
        try:
            bars = (crypto.klines(sym, tf, limit=1000) if kind == "crypto"
                    else equity.klines(sym, tf))
            out[tf] = dss.bressert(bars, stoch_len=dcfg.get("stoch_len", 13),
                                   ema_len=dcfg.get("ema_len", 8))
        except Exception:
            out[tf] = None
        if kind == "equity":
            time.sleep(0.2)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", required=True, choices=["A", "B", "C", "D", "E", "F"])
    ap.add_argument("--limit", type=int, default=0, help="debug: cap symbols")
    a = ap.parse_args()

    cfg = load_cfg()
    tier = cfg["tiers"][a.tier]
    scan_tf, confirm = tier["scan_tf"], tier["confirm_tf"]
    notes = []

    if a.tier == "C":
        syms = [s.strip() for s in open(cfg["universe"]["equity"]["tickers_file"])
                if s.strip()]
        kind = "equity"
        tvpfx = ""
    elif a.tier == "F":
        # Real NASDAQ/SPX stocks behind the tokenized names - full history, so a
        # normal setup scan (not a board). Auto-derived from tier D.
        syms = crypto.stock_underlyings(cfg["universe"]["crypto"]["quote"])
        kind = "equity"
        tvpfx = ""
    elif a.tier in ("D", "E"):
        # Tokenized stocks (D) and gold/commodity-pegged (E) - Binance spot,
        # scanned as their own lists, kept out of the pure-crypto tiers.
        cats = crypto.categorize(cfg["universe"]["crypto"]["quote"])
        syms = cats["stock"] if a.tier == "D" else cats["commodity"]
        kind = "crypto"
        tvpfx = "BINANCE:"
    else:
        allsyms = crypto.universe(cfg["universe"]["crypto"]["quote"])
        added, removed = crypto.diff_universe(allsyms)
        if added:
            notes.append(f"universe: {len(added)} new listings ({', '.join(added[:8])})")
        if removed:
            notes.append(f"universe: {len(removed)} delisted ({', '.join(removed[:8])})")
        top = crypto.top_by_volume(allsyms, cfg["universe"]["crypto"]["top_n_by_volume"],
                                   cfg["universe"]["crypto"]["volume_window_days"])
        syms = top if a.tier == "A" else [s for s in allsyms if s not in top]
        kind = "crypto"
        tvpfx = "BINANCE:"

    if a.limit:
        syms = syms[:a.limit]

    # Tiers D/E are DSS boards, not setup scans: the tokenized stocks are too
    # new (weeks of history) for the compression/divergence detectors, so list
    # every instrument with its D/W/M DSS instead, extremes sorted to the top.
    if a.tier in ("D", "E"):
        dcfg = cfg.get("dss", {})
        board = []
        for s in syms:
            board.append({"symbol": s, "tv_symbol": tvpfx + s,
                          "dss": dss_dwm(s, kind, dcfg)})
        g, r = renderer.DSS_GREEN, renderer.DSS_RED

        def _key(row):
            d = row["dss"]
            flagged = any(p and (p[0] <= g or p[0] >= r) for p in d.values())
            dd = d.get("1d")
            return (0 if flagged else 1, dd[0] if dd else 0.5)
        board.sort(key=_key)
        with_daily = sum(1 for row in board if row["dss"].get("1d"))
        notes.append(f"{with_daily}/{len(board)} have enough history for a daily DSS "
                     "(weekly/monthly fill in as these list longer).")
        renderer.publish_board(a.tier, board, notes, outdir=cfg["output"]["dir"])
        print(f"tier {a.tier}: {len(board)} tracked (DSS board)")
        return

    if a.tier == "B":
        notes.append("Tier B compression parameters are PROVISIONAL - the 1H sweep "
                     "in calibrate.py has not been run. Treat as observational.")

    comp_cfg = cfg["compression"][scan_tf]
    # Divergence runs on its own timeframe. Tier B scans 1H for compression but
    # takes the roofed-RSI divergence off 4H; defaults to the scan timeframe.
    div_tf = tier.get("divergence_tf", scan_tf)
    div_cfg = cfg["divergence"].get(div_tf)

    comp_rows, div_rows, rets, failed = [], [], {}, []
    for i, s in enumerate(syms):
        try:
            df = get_bars(s, scan_tf, kind)
            if df is None or len(df) < 300:
                continue
            rets[s] = np.diff(np.log(df["close"].values))[-120:]

            # HTF posture. Compression is a continuation setup, so gating on
            # this is correct. Divergence is counter-trend by construction -
            # HTF is recorded as a RANKING FIELD ONLY, never a gate.
            fav = True
            htf_bars = {}
            for ctf in confirm:
                hdf = get_bars(s, ctf, kind)
                htf_bars[ctf] = hdf
                if hdf is None or len(hdf) < 120:
                    continue
                p = htf_posture(hdf, cfg["compression"][ctf])
                if p and not p["favourable"]:
                    fav = False

            r = compression_state(df, comp_cfg)
            if r and r["state"] in ("compressed", "triggered", "forming"):
                if fav or r["state"] != "forming":
                    r.update(symbol=s, tf=scan_tf, tv_symbol=tvpfx + s,
                             htf_favourable=fav,
                             detail=(f"ribbon p{int(r['ribbon_pct']*100)}, "
                                     f"apex {r['bars_to_apex']}, held {r['bars_in_state']}"))
                    if r["state"] != "forming" or r["ribbon_pct"] < 0.35:
                        comp_rows.append(r)

            if div_cfg and "divergence" in tier["detectors"]:
                # Reuse already-fetched HTF bars when the divergence timeframe is
                # one of them (tier B fetches 4H for the compression gate).
                ddf = df if div_tf == scan_tf else htf_bars.get(div_tf)
                if ddf is None and div_tf != scan_tf:
                    ddf = get_bars(s, div_tf, kind)
                if ddf is not None and len(ddf) >= 300:
                    for d in divergence_rows(ddf, div_cfg, s, div_tf):
                        d.update(tv_symbol=tvpfx + s, htf_favourable=fav)
                        div_rows.append(d)
        except Exception as e:
            failed.append(f"{s}: {type(e).__name__}")
        time.sleep(0.05 if kind == "crypto" else 0.3)   # gentler on Yahoo

    if failed:
        notes.append(f"{len(failed)} symbols failed: {', '.join(failed[:6])}")

    w = cfg["ranking"]
    comp_rows = ranker.score_compression(comp_rows, w["compression"])
    div_rows = ranker.score_divergence(div_rows, w["divergence"])
    thr = w["cluster_correlation"]
    comp_rows, comp_dropped = ranker.collapse_clusters(comp_rows, rets, thr)
    div_rows, div_dropped = ranker.collapse_clusters(div_rows, rets, thr)
    if comp_dropped or div_dropped:
        notes.append(f"{len(comp_dropped)+len(div_dropped)} correlated duplicates "
                     f"collapsed (rho >= {thr}) - these are not independent bets")

    mx = w["max_rows"]
    # DSS Bressert confluence on daily/weekly/monthly, only for the rows that
    # will actually be displayed (a handful of symbols, deduped).
    dcfg = cfg.get("dss", {})
    dss_seen = {}
    for r in comp_rows[:mx] + div_rows[:mx]:
        sym = r["symbol"]
        if sym not in dss_seen:
            dss_seen[sym] = dss_dwm(sym, kind, dcfg)
        r["dss"] = dss_seen[sym]

    renderer.publish(a.tier, [
        (f"compression ({scan_tf})", comp_rows[:mx]),
        (f"divergence ({div_tf})", div_rows[:mx]),
    ], notes, outdir=cfg["output"]["dir"])
    print(f"tier {a.tier}: {len(syms)} symbols, "
          f"{len(comp_rows)} compression, {len(div_rows)} divergence")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
