"""Bottoming / accumulation detector.

A different animal from compression: that one needs an established uptrend,
this one hunts coins that are still beaten down, BEFORE the trend exists.
The framework it encodes:

    bottomed out on the daily/weekly (price under the long EMAs, deep
    drawdown)  ->  rounding bottom in accumulation (lows stop falling and
    start rising)  ->  volume building through the base  ->  local trend
    reclaimed and flipped to support  ->  compression into the 100EMA
    and/or resistance  ->  break, with the 200EMA / 300EMA gaps as targets.

Stages are reported rather than a single boolean, because the framework is a
progression you can act on at different points (DCA the range vs long the
break):

    basing      - rounding base + volume, but the local trend is not reclaimed
    reclaimed   - back above the noodle and holding it as support
    compressing - reclaimed AND coiled into the 100EMA / base resistance
    breakout    - closed through the base resistance (or the 100EMA)

Targets (upside to the 200/300 EMA) are reported on every stage - the whole
point of the setup is the gap those EMAs left overhead.
"""
import numpy as np

from detectors.compression import ema, atr, fractal_pivots


def _slope(idx, vals):
    if len(idx) < 2:
        return 0.0
    return float(np.polyfit(np.asarray(idx, float), np.asarray(vals, float), 1)[0])


def bottoming_state(df, nd, cfg):
    """`nd` is the money_noodle frame (its EMA35 main is the 'local trend').
    Returns a stage dict or None."""
    lb = cfg.get("base_lookback", 180)
    e_long = cfg.get("ema_long", 300)
    n = len(df)
    if n < max(e_long + 60, lb + 60):
        return None

    h, l, c = df["high"].values, df["low"].values, df["close"].values
    v = df["volume"].values.astype(float)
    a = atr(h, l, c, cfg.get("atr_len", 20))
    i = n - 1
    if not (np.isfinite(a[i]) and a[i] > 0):
        return None

    e100 = ema(c, cfg.get("ema_mid", 100))
    e200 = ema(c, cfg.get("ema_far", 200))
    e300 = ema(c, e_long)
    main = nd["main"].values                      # the noodle = local trend

    # --- 1. BOTTOMED OUT --------------------------------------------------
    # Still under the overhead structure, and genuinely beaten down.
    if not (c[i] < e200[i] and c[i] < e300[i]):
        return None
    w0 = max(i - lb, 0)
    hi_w = float(np.nanmax(h[w0:i + 1]))
    lo_w = float(np.nanmin(l[w0:i + 1]))
    if hi_w <= 0:
        return None
    drawdown = (hi_w - c[i]) / hi_w
    if drawdown < cfg.get("min_drawdown", 0.45):
        return None

    # --- 2. ROUNDING BOTTOM -----------------------------------------------
    # Swing lows fall through the first half of the base and rise through the
    # second - that curvature IS the rounding.
    pl = fractal_pivots(l, cfg.get("pivot_left", 5), cfg.get("pivot_right", 5), "low")
    base = [j for j in pl if j >= w0]
    if len(base) < cfg.get("min_base_pivots", 4):
        return None
    mid = w0 + lb // 2
    first = [j for j in base if j < mid]
    second = [j for j in base if j >= mid]
    if len(first) < 2 or len(second) < 2:
        return None
    s_first = _slope(first, [l[j] for j in first]) / a[i]
    s_second = _slope(second, [l[j] for j in second]) / a[i]
    flat = cfg.get("round_flat_atr", 0.01)
    if not (s_first <= flat and s_second > flat):
        return None                                # not a rounding shape
    # and the most recent lows are genuinely higher
    if l[second[-1]] <= l[second[0]]:
        return None

    # --- 3. VOLUME BUILDING THROUGH THE BASE ------------------------------
    seg = max(lb // 3, 5)
    v_early = float(np.nanmedian(v[w0:w0 + seg]))
    v_late = float(np.nanmedian(v[max(i - seg, 0):i + 1]))
    if not np.isfinite(v_early) or v_early <= 0:
        return None
    vol_ratio = v_late / v_early
    if vol_ratio < cfg.get("min_vol_ratio", 1.2):
        return None

    # --- 4. LOCAL TREND RECLAIMED AND FLIPPED TO SUPPORT ------------------
    hold = cfg.get("reclaim_hold_bars", 5)
    m0 = max(i - hold + 1, 0)
    reclaimed = bool(c[i] > main[i]
                     and np.all(c[m0:i + 1] > nd["lower"].values[m0:i + 1]))

    # --- 5. COMPRESSION INTO THE 100EMA / BASE RESISTANCE -----------------
    # Base resistance = the highest swing high inside the base (the flat line
    # price keeps failing at), plus the 100EMA sitting overhead.
    # Resistance = the NEAREST swing high still overhead, not the tallest spike
    # in the base - the level price is actually compressing into.
    ph = fractal_pivots(h, cfg.get("pivot_left", 5), cfg.get("pivot_right", 5), "high")
    overhead = [h[j] for j in ph if j >= w0 and h[j] > c[i]]
    res = float(min(overhead)) if overhead else hi_w
    gap_res = (res - c[i]) / a[i]                  # ATR below base resistance
    gap_100 = (e100[i] - c[i]) / a[i]              # ATR below the 100EMA
    near = cfg.get("near_atr", 2.0)
    compressing = reclaimed and (0 <= gap_res <= near or 0 <= gap_100 <= near)
    broke = c[i] > res or c[i] > e100[i]

    if broke and reclaimed:
        stage = "breakout"
    elif compressing:
        stage = "compressing"
    elif reclaimed:
        stage = "reclaimed"
    else:
        stage = "basing"

    return {
        "state": stage,
        "drawdown_pct": round(drawdown * 100, 1),
        "vol_ratio": round(vol_ratio, 2),
        "base_bars": int(i - w0),
        "gap_100_atr": None if not np.isfinite(gap_100) else round(float(gap_100), 2),
        "gap_res_atr": None if not np.isfinite(gap_res) else round(float(gap_res), 2),
        # the whole point: how much room the long EMAs left overhead
        "target_200_pct": round(float(e200[i] / c[i] - 1) * 100, 1),
        "target_300_pct": round(float(e300[i] / c[i] - 1) * 100, 1),
        "resistance": round(res, 8),
        "invalidation": round(float(nd["lower"].values[i]), 8),   # lose the noodle
        "close": round(float(c[i]), 8),
        "atr": round(float(a[i]), 8),
    }
