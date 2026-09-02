#!/usr/bin/env python3
"""Scanner entry point.

  python src/scan.py --tier A     # top-10 crypto, 4H scan + 1D confirm
  python src/scan.py --tier B     # rest of crypto, 1H scan + 4H/1D confirm
  python src/scan.py --tier C     # equities/ETFs, 1D
"""
import argparse, os, sys, time, traceback
import numpy as np, pandas as pd, yaml

sys.path.insert(0, os.path.dirname(__file__))
from detectors.compression import compression_noodle
from detectors import l1, dss, noodle, trend as trendmod
from fetch import crypto, store, equity
import rank as ranker
import render as renderer

BARS = {"15m": 1000, "1h": 900, "4h": 900, "1d": 700, "1w": 500}


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


def _noodle(df, ncfg):
    return noodle.money_noodle(
        df, ema_fast=ncfg.get("ema_fast", 12), ema_medium=ncfg.get("ema_medium", 21),
        ema_slow=ncfg.get("ema_slow", 35), atr_len=ncfg.get("atr_len", 20),
        band_mult=ncfg.get("band_mult", 0.0125))


def trend_multi(sym, kind, cfg):
    """Current swing-structure trend state per timeframe (15m..1w) for one
    symbol. None per TF when there isn't enough history."""
    tcfg, ncfg = cfg.get("trend", {}), cfg.get("noodle", {})
    tfs = tcfg.get("timeframes", ["15m", "1h", "4h", "1d", "1w"])
    pw = tcfg.get("pivot_width", 6)
    out = {}
    for tf in tfs:
        try:
            bars = (crypto.klines(sym, tf, limit=1000) if kind == "crypto"
                    else equity.klines(sym, tf))
            if bars is None or len(bars) < 80:
                out[tf] = None
            else:
                _, info = trendmod.trend_series(
                    bars, _noodle(bars, ncfg), left=pw, right=pw,
                    n_swings=tcfg.get("n_swings", 4), tau=tcfg.get("tau", 0.04),
                    break_k=tcfg.get("break_k", 1.0))
                out[tf] = info["state"]
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
    scan_tf = tier["scan_tf"]
    notes = []

    tvmap = {}   # per-symbol TradingView chart symbol override (tier E)
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
    elif a.tier == "D":
        # Tokenized stocks (Binance spot) - too new for the detectors, so a board.
        syms = crypto.categorize(cfg["universe"]["crypto"]["quote"])["stock"]
        kind = "crypto"
        tvpfx = "BINANCE:"
    elif a.tier == "E":
        # Commodity futures via Yahoo (wheat, coffee, crude, gold, ...). Full
        # history -> a proper setup scan. Each line: Yahoo ticker + TV symbol.
        syms = []
        for line in open("config/commodities.txt"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            syms.append(parts[0])
            if len(parts) >= 2:
                tvmap[parts[0]] = parts[1]
        kind = "equity"
        tvpfx = ""
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

    # Tier D is a DSS board, not a setup scan: the tokenized stocks are too new
    # (weeks of history) for the compression/divergence detectors, so list every
    # instrument with its D/W/M DSS instead, extremes sorted to the top.
    if a.tier == "D":
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

    comp_tfs = tier.get("compression_tfs", [scan_tf])
    comp_cfgs = {tf: cfg["compression"][tf] for tf in comp_tfs}
    tcfg, ncfg = cfg.get("trend", {}), cfg.get("noodle", {})
    pw = tcfg.get("pivot_width", 6)
    # Divergence runs on its own timeframe (tier B scans intraday for compression
    # but takes the roofed-RSI divergence off 4H); defaults to the scan timeframe.
    div_tf = tier.get("divergence_tf", scan_tf)
    div_cfg = cfg["divergence"].get(div_tf)

    comp_rows, div_rows, rets, failed = [], [], {}, []
    for i, s in enumerate(syms):
        try:
            tf_bars, tf_trend = {}, {}
            # Compression on each timeframe, GATED on that TF's swing-trend == up:
            # price riding the Money Noodle, squeezed into a flat/descending line.
            for ctf in comp_tfs:
                df = get_bars(s, ctf, kind)
                tf_bars[ctf] = df
                if df is None or len(df) < 300:
                    continue
                nd = _noodle(df, ncfg)
                _, tinfo = trendmod.trend_series(
                    df, nd, left=pw, right=pw, n_swings=tcfg.get("n_swings", 4),
                    tau=tcfg.get("tau", 0.04), break_k=tcfg.get("break_k", 1.0))
                tf_trend[ctf] = tinfo["state"]
                if tinfo["state"] != "up":
                    continue
                r = compression_noodle(df, nd, comp_cfgs[ctf])
                if r and r["state"] in ("compressed", "triggered", "forming"):
                    r["ribbon_pct"] = r["channel_atr"]      # tightness key for ranking
                    r.update(symbol=s, tf=ctf, tv_symbol=tvmap.get(s, tvpfx + s),
                             htf_favourable=True,
                             detail=(f"{r['res_kind']} res, ch {r['channel_atr']}ATR, "
                                     f"apex {r['bars_to_apex']}, held {r['bars_in_state']}"))
                    comp_rows.append(r)

            # Returns for cluster-correlation, off the primary timeframe.
            pdf = tf_bars.get(scan_tf)
            if pdf is None:
                pdf = get_bars(s, scan_tf, kind)
                tf_bars[scan_tf] = pdf
            if pdf is not None and len(pdf) >= 120:
                rets[s] = np.diff(np.log(pdf["close"].values))[-120:]

            # Divergence (roofed RSI), ungated; the div-TF trend is a ranking field.
            if div_cfg and "divergence" in tier["detectors"]:
                ddf = tf_bars.get(div_tf)
                if ddf is None:
                    ddf = get_bars(s, div_tf, kind)
                favd = tf_trend.get(div_tf) == "up"
                if ddf is not None and len(ddf) >= 300:
                    for d in divergence_rows(ddf, div_cfg, s, div_tf):
                        d.update(tv_symbol=tvmap.get(s, tvpfx + s), htf_favourable=favd)
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
    dss_seen, trend_seen = {}, {}
    for r in comp_rows[:mx] + div_rows[:mx]:
        sym = r["symbol"]
        if sym not in dss_seen:
            dss_seen[sym] = dss_dwm(sym, kind, dcfg)
            trend_seen[sym] = trend_multi(sym, kind, cfg)
        r["dss"] = dss_seen[sym]
        r["trend"] = trend_seen[sym]

    renderer.publish(a.tier, [
        (f"compression ({'/'.join(comp_tfs)})", comp_rows[:mx]),
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
