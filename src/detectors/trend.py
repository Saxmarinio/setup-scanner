"""Swing-structure trend detector (bullish first).

Reads market structure over several swings rather than price vs a single line,
so it ignores chop:

  * swing pivots via fractal_pivots (wide pivots = significant swings only)
  * slope of a least-squares line through the last N swing lows and N swing
    highs, normalised by ATR - fitting a line through N pivots is the averaging
    that stops one aberrant swing from flipping the read
  * an uptrend needs CONFLUENCE: rising lows (slope_L > tau), highs not rolling
    over (slope_H >= 0), the most recent higher-low intact, and price above the
    noodle main line (not chopping across it)
  * a hysteresis state machine holds `up` until a DECISIVE break (a lower-low
    beyond the prior swing low by k*ATR, slope_L turning negative, or a close
    back under the noodle) - easy to hold, hard to break

State transitions are the loggable "trend change" signal. Downtrend is a
symmetric addition later; for now states are 'up' / 'none'.
"""
import numpy as np
from detectors.compression import atr, fractal_pivots


def _slope(idxs, vals):
    if len(idxs) < 2:
        return 0.0
    return float(np.polyfit(np.asarray(idxs, float), np.asarray(vals, float), 1)[0])


def trend_series(df, noodle, left=6, right=6, n_swings=4, tau=0.04, break_k=1.0):
    """Per-bar trend state ('up'/'none') with hysteresis, computed causally
    (each bar sees only pivots confirmed by then). Returns (states, info) where
    info describes the latest bar."""
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    a = atr(h, l, c, 20)
    main = noodle["main"].values
    SH = fractal_pivots(h, left, right, "high")
    SL = fractal_pivots(l, left, right, "low")

    states = np.empty(len(c), dtype=object)
    state = "none"
    last = {}
    for i in range(len(c)):
        sh = [j for j in SH if j + right <= i]      # pivots confirmed by bar i
        sl = [j for j in SL if j + right <= i]
        if len(sl) >= 2 and len(sh) >= 2 and np.isfinite(a[i]) and a[i] > 0:
            shi, sli = sh[-n_swings:], sl[-n_swings:]
            slope_L = _slope(sli, [l[j] for j in sli]) / a[i]
            slope_H = _slope(shi, [h[j] for j in shi]) / a[i]
            hl_intact = l[sli[-1]] > l[sli[-2]]
            above = c[i] > main[i]
            up_now = slope_L > tau and slope_H >= 0 and hl_intact and above
            if state != "up":
                if up_now:
                    state = "up"
            else:
                lower_low = l[sli[-1]] < l[sli[-2]] - break_k * a[i]
                if slope_L < -tau or lower_low or c[i] < main[i]:
                    state = "none"
            if i == len(c) - 1:
                last = {"slope_L": round(slope_L, 3), "slope_H": round(slope_H, 3),
                        "hl_intact": bool(hl_intact), "above_noodle": bool(above),
                        "up_now": bool(up_now)}
        states[i] = state

    # last transition = most recent bar whose state differs from the one before
    change_idx = None
    for i in range(len(states) - 1, 0, -1):
        if states[i] != states[i - 1]:
            change_idx = i
            break
    return states, {"state": states[-1], "change_idx": change_idx, **last}


def summarize(df, noodle, **kw):
    """Convenience: current state, and the datetime/bars-ago of the last change."""
    states, info = trend_series(df, noodle, **kw)
    out = {"state": info["state"], "slope_L": info.get("slope_L"),
           "slope_H": info.get("slope_H")}
    ci = info["change_idx"]
    if ci is not None:
        out["changed_to"] = states[ci]
        out["changed_bars_ago"] = len(states) - 1 - ci
        if "datetime" in df.columns:
            out["changed_at"] = str(df["datetime"].iloc[ci])
    return out
