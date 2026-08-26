"""
Trend-compression detector.

The setup is a CONVERGENCE, not merely a narrow ribbon: a rising EMA ribbon
underneath, a descending line through recent swing highs above, and price
squeezed between them. Detecting only "narrow ribbon" fires constantly in
dead ranges; requiring the descending boundary is what makes it selective.

Returns a state per bar, not a boolean:
    forming     - ribbon rising and stacked, higher lows, but not yet tight
    compressed  - ribbon width in its own low percentile AND price near the line
    triggered   - close broke the descending line on expanding range
    invalidated - close below EMA35, or a lower swing low

Ranking fields:
    bars_to_apex - projected bars until ribbon meets the descending line.
                   Urgency. Primary sort key.
    bars_in_state - how long compression has persisted. Long compressions that
                   suddenly tighten are the good ones; 2-bar readings are noise.
    ribbon_pct   - ribbon width as a percentile of its own history (0 = tightest)
    gap_atr      - distance from close to the descending line, in ATR
"""
import numpy as np
import pandas as pd


def ema(x, n):
    return pd.Series(x, dtype=float).ewm(span=n, adjust=False).mean().values


def atr(h, l, c, n=20):
    h, l, c = (np.asarray(z, float) for z in (h, l, c))
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).ewm(alpha=1.0 / n, adjust=False).mean().values


def fractal_pivots(series, left, right, kind="high"):
    """Indices of confirmed fractal pivots. Confirmed `right` bars late."""
    s = np.asarray(series, float)
    out = []
    for i in range(left, len(s) - right):
        v = s[i]
        if kind == "high":
            if np.all(v >= s[i - left:i]) and np.all(v > s[i + 1:i + right + 1]):
                out.append(i)
        else:
            if np.all(v <= s[i - left:i]) and np.all(v < s[i + 1:i + right + 1]):
                out.append(i)
    return out


def _fit_descending(idx, vals):
    """Least-squares line through pivot highs. Returns (slope, intercept) or None
    if the fit is not descending."""
    if len(idx) < 2:
        return None
    x = np.asarray(idx, float)
    y = np.asarray(vals, float)
    slope, intercept = np.polyfit(x, y, 1)
    if slope >= 0:
        return None
    return slope, intercept


def compression_state(df, cfg):
    """
    df: DataFrame with open/high/low/close (ascending time).
    cfg: dict of parameters (see config/tiers.yaml).
    Returns a dict describing the CURRENT bar, or None if not applicable.
    """
    n = len(df)
    warm = max(cfg["ribbon_lookback"], cfg["ema_slow"] * 3, 120)
    if n < warm:
        return None

    h, l, c = df["high"].values, df["low"].values, df["close"].values
    e_f = ema(c, cfg["ema_fast"])
    e_m = ema(c, cfg["ema_mid"])
    e_s = ema(c, cfg["ema_slow"])
    a = atr(h, l, c, cfg["atr_len"])

    i = n - 1  # evaluate on the last CLOSED bar; caller must drop the live bar

    # --- ribbon geometry -------------------------------------------------
    stack = np.minimum(np.minimum(e_f, e_m), e_s)
    band = np.maximum(np.maximum(e_f, e_m), e_s) - stack
    with np.errstate(divide="ignore", invalid="ignore"):
        ribbon_w = band / a
    lb = cfg["ribbon_lookback"]
    hist = ribbon_w[i - lb + 1:i + 1]
    hist = hist[np.isfinite(hist)]
    if len(hist) < lb // 2:
        return None
    ribbon_pct = float((hist < ribbon_w[i]).mean())

    stacked = bool(e_f[i] > e_m[i] > e_s[i])
    slope_bars = cfg["slope_lookback"]
    ribbon_slope = (e_s[i] - e_s[i - slope_bars]) / slope_bars
    ribbon_up = bool(ribbon_slope / a[i] > cfg["min_slope_atr"])

    # --- higher lows ------------------------------------------------------
    pl = fractal_pivots(l, cfg["pivot_left"], cfg["pivot_right"], "low")
    recent_l = [j for j in pl if i - j <= cfg["structure_lookback"]][-3:]
    higher_lows = len(recent_l) >= 2 and all(
        l[recent_l[k]] < l[recent_l[k + 1]] for k in range(len(recent_l) - 1)
    )

    # --- descending resistance -------------------------------------------
    ph = fractal_pivots(h, cfg["pivot_left"], cfg["pivot_right"], "high")
    recent_h = [j for j in ph if i - j <= cfg["structure_lookback"]][-3:]
    fit = _fit_descending(recent_h, [h[j] for j in recent_h]) if len(recent_h) >= 2 else None

    if fit is None:
        res_now = np.nan
        gap_atr = np.nan
        bars_to_apex = np.nan
        res_slope = np.nan
    else:
        res_slope, res_int = fit
        res_now = res_slope * i + res_int
        gap_atr = float((res_now - c[i]) / a[i])
        # ribbon top rises at ~slope of EMA_fast; apex where the two meet
        conv = (ema(c, cfg["ema_fast"])[i] - ema(c, cfg["ema_fast"])[i - slope_bars]) / slope_bars
        rel = conv - res_slope
        bars_to_apex = float((res_now - e_f[i]) / rel) if rel > 0 else np.nan

    # --- state ------------------------------------------------------------
    below_slow = c[i] < e_s[i]
    lower_low = len(recent_l) >= 2 and l[recent_l[-1]] < l[recent_l[-2]]

    tight = ribbon_pct <= cfg["ribbon_pct_max"]
    near = np.isfinite(gap_atr) and 0 <= gap_atr <= cfg["max_gap_atr"]
    rng = (h[i] - l[i]) / a[i]
    broke = np.isfinite(res_now) and c[i] > res_now and rng >= cfg["breakout_range_atr"]

    if below_slow or lower_low:
        state = "invalidated"
    elif broke:
        state = "triggered"
    elif stacked and ribbon_up and higher_lows and tight and near:
        state = "compressed"
    elif stacked and ribbon_up and higher_lows:
        state = "forming"
    else:
        return None

    # bars_in_state: how long the compressed conditions have held
    bis = 0
    if state in ("compressed", "triggered"):
        for k in range(i, max(i - cfg["structure_lookback"], 0), -1):
            hk = ribbon_w[k - lb + 1:k + 1]
            hk = hk[np.isfinite(hk)]
            if len(hk) < 2:
                break
            if (hk < ribbon_w[k]).mean() <= cfg["ribbon_pct_max"] and e_f[k] > e_m[k] > e_s[k]:
                bis += 1
            else:
                break

    return {
        "state": state,
        "ribbon_pct": round(ribbon_pct, 3),
        "ribbon_w_atr": round(float(ribbon_w[i]), 3),
        "gap_atr": None if not np.isfinite(gap_atr) else round(gap_atr, 2),
        "bars_to_apex": None if not np.isfinite(bars_to_apex) else round(bars_to_apex, 1),
        "bars_in_state": bis,
        "higher_lows": higher_lows,
        "resistance": None if not np.isfinite(res_now) else round(float(res_now), 6),
        "invalidation": round(float(e_s[i]), 6),
        "close": round(float(c[i]), 6),
        "atr": round(float(a[i]), 6),
    }


def htf_posture(df, cfg):
    """Cheap trend read for the confirmation timeframes. Compression is a
    continuation setup, so gating on this is appropriate (unlike divergence)."""
    if len(df) < cfg["ema_slow"] * 3:
        return None
    c = df["close"].values
    e_f, e_m, e_s = ema(c, cfg["ema_fast"]), ema(c, cfg["ema_mid"]), ema(c, cfg["ema_slow"])
    i = len(c) - 1
    sl = (e_s[i] - e_s[i - cfg["slope_lookback"]]) / cfg["slope_lookback"]
    return {
        "stacked": bool(e_f[i] > e_m[i] > e_s[i]),
        "above_slow": bool(c[i] > e_s[i]),
        "slope_up": bool(sl > 0),
        "favourable": bool(c[i] > e_s[i] and sl > 0),
    }
