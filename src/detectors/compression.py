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
from numpy.lib.stride_tricks import sliding_window_view


def ema(x, n):
    return pd.Series(x, dtype=float).ewm(span=n, adjust=False).mean().values


def atr(h, l, c, n=20):
    h, l, c = (np.asarray(z, float) for z in (h, l, c))
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).ewm(alpha=1.0 / n, adjust=False).mean().values


def fractal_pivots(series, left, right, kind="high"):
    """Indices of confirmed fractal pivots. Confirmed `right` bars late.

    Vectorised: the scanner calls this once per bar per symbol, and the
    backtest calls it a million times, so the per-bar Python loop it replaced
    was the dominant cost. Output is identical (ties break to the left, as
    before: >= against the left window, > against the right).
    """
    s = np.asarray(series, float)
    n = len(s)
    if n < left + right + 1:
        return []
    w = sliding_window_view(s, left + right + 1)
    centre = w[:, left]
    if kind == "high":
        ok = np.ones(len(centre), bool)
        if left:
            ok &= centre >= w[:, :left].max(axis=1)
        if right:
            ok &= centre > w[:, left + 1:].max(axis=1)
    else:
        ok = np.ones(len(centre), bool)
        if left:
            ok &= centre <= w[:, :left].min(axis=1)
        if right:
            ok &= centre < w[:, left + 1:].min(axis=1)
    return (np.nonzero(ok)[0] + left).tolist()


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


def compression_noodle(df, nd, cfg):
    """Noodle compression, matching the classic setup:

        expansion clear of the noodle  ->  consolidation back INTO it
        ->  higher lows hugging the noodle, highs capped by a straight line
        ->  the two converge  ->  expansion

    So this requires (a) a prior impulse that established the trend, (b) price
    now coiled back near the noodle, (c) ascending pullback lows riding the
    noodle, and (d) a resistance line that genuinely CAPS the highs (nothing
    pokes through it, and it is actually touched). Trend-gated by the caller.

    `nd` is the money_noodle DataFrame. Returns a state dict or None.
    States: forming -> compressed (also near resistance) -> triggered.
    """
    n = len(df)
    need = max(cfg["ema_slow"] * 3, cfg["structure_lookback"] + 20,
               cfg.get("expansion_lookback", 120), 120)
    if n < need:
        return None
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    a = atr(h, l, c, cfg["atr_len"])
    i = n - 1
    if not (np.isfinite(a[i]) and a[i] > 0):
        return None
    main, up_band, lo_band = nd["main"].values, nd["upper"].values, nd["lower"].values

    # 1. PRIOR EXPANSION - the impulse that establishes the trend. Somewhere in
    #    the lookback price must have run clear of the noodle; a consolidation
    #    with no preceding thrust is just chop.
    #
    #    Anchor to the MOST RECENT such impulse, not the largest one in the
    #    window. A market that runs, coils, then runs again would otherwise
    #    anchor to the first leg and treat everything since as one long
    #    "consolidation" - which then fits a resistance across both legs, sees
    #    ascending highs, and rejects a setup that is plainly there. (Measured:
    #    UNI 4H fitted 6.38 -> 6.51 -> 7.48 across three separate legs.)
    w0 = max(i - cfg.get("expansion_lookback", 120), 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        dist = (c - main) / a
    min_exp = cfg.get("min_expansion_atr", 2.5)
    min_consol = cfg.get("min_consolidation_bars", 10)
    # Collapse extended bars into contiguous RUNS - one run is one impulse -
    # and take each run's high-water mark. Anchoring to individual extended
    # bars instead would put the anchor at the tail of the last run and leave
    # a coil too short to hold any swing structure.
    flags = np.isfinite(dist) & (dist >= min_exp)
    peaks, k = [], w0
    while k <= i:
        if not flags[k]:
            k += 1
            continue
        j = k
        while j + 1 <= i and flags[j + 1]:
            j += 1
        peaks.append(k + int(np.nanargmax(dist[k:j + 1])))
        k = j + 1
    # The coil must be long enough to be a coil.
    peaks = [p for p in peaks if p <= i - min_consol]
    if not peaks:
        return None

    # 2. ...and price has since coiled back toward the noodle (not still extended).
    #
    #    A breakout bar is by definition NOT coiled - it thrusts clear of the
    #    noodle. Applying this gate to the current bar therefore rejects the
    #    very move the detector exists to catch, and `triggered` could almost
    #    never fire. So evaluate the COIL GEOMETRY at the last bar that was
    #    still coiled (`e`), and judge the break at the current bar. When price
    #    is still in the coil, e == i and this behaves exactly as before.
    max_now = cfg.get("max_now_atr", 1.8)
    if np.isfinite(dist[i]) and dist[i] <= max_now:
        e = i
    else:
        grace = cfg.get("breakout_grace_bars", 3)
        prev = [k for k in range(max(peaks[0], i - grace), i)
                if np.isfinite(dist[k]) and dist[k] <= max_now]
        if not prev:
            return None            # extended, with no recent coil behind it
        e = prev[-1]

    # Pick the most recent impulse that actually has swing structure behind it
    # in [peak, e]; fall back to the oldest candidate so the gates below can
    # reject it on their own terms rather than on an arithmetic accident.
    pl_all = fractal_pivots(l, cfg["pivot_left"], cfg["pivot_right"], "low")
    ph_all = fractal_pivots(h, cfg["pivot_left"], cfg["pivot_right"], "high")
    peak = peaks[0]
    for p in reversed(peaks):
        if (sum(1 for j in pl_all if p <= j <= e) >= 2
                and sum(1 for j in ph_all if p <= j <= e) >= 2):
            peak = p
            break
    if e - peak < min_consol:
        return None
    # Report the size of that impulse, not merely the bar that cleared the bar.
    expansion = float(np.nanmax(dist[peak:min(peak + 2, i + 1)]))

    # 3. Riding the noodle, cleanly - above its centre line (price consolidates
    #    INTO the band, so requiring it clear of the upper band would exclude
    #    the very shape we want), and no close through the band below.
    if c[e] <= main[e]:
        return None
    m0 = max(e - cfg["above_lookback"] + 1, 0)
    if not np.all(l[m0:e + 1] >= lo_band[m0:e + 1]):
        return None

    # 4. HIGHER LOWS HUGGING THE NOODLE - ascending pullback lows, each holding
    #    the band and none drifting far above it (they ride it up).
    rec_l = [j for j in pl_all if peak <= j <= e][-3:]
    if len(rec_l) < 2:
        return None
    if not all(l[rec_l[k]] < l[rec_l[k + 1]] for k in range(len(rec_l) - 1)):
        return None
    near = cfg.get("low_near_noodle_atr", 1.5)
    for j in rec_l:
        if not (np.isfinite(a[j]) and a[j] > 0) or l[j] < lo_band[j]:
            return None                                    # broke the noodle
        if (l[j] - main[j]) / a[j] > near:
            return None                                    # not hugging it

    # 5. A straight-line resistance that genuinely CAPS the highs.
    rec = [j for j in ph_all if peak <= j <= e][-cfg["res_points"]:]
    if len(rec) < 2:
        return None
    slope, intercept = np.polyfit(np.array(rec, float),
                                  np.array([h[j] for j in rec], float), 1)
    slope_atr = slope / a[e]
    # A compression coils UNDER a ceiling: resistance must be flat or gently
    # descending. Ascending highs mean price is making higher highs freely (not
    # a squeeze); a near-vertical drop is a bad two-point fit, not a real line.
    if slope_atr > cfg["res_flat"]:
        return None
    if slope_atr < -cfg.get("res_max_down_atr", 0.08):
        return None
    horizontal = slope_atr >= -cfg["res_flat"]   # within tolerance = flat; below = descending
    res_now = slope * e + intercept              # the ceiling as of the coil
    res_at_i = slope * i + intercept             # ...projected to the current bar
    if not (np.isfinite(res_now) and np.isfinite(res_at_i)):
        return None
    # nothing may poke meaningfully above the line across the span it caps
    # (from the first fitted swing high to the coil bar - not the whole
    # lookback, or a descending line would always "fail" against older, higher
    # bars; and not past `e`, or the breakout bar would fail against itself).
    wlo = max(min(rec), 0)
    line = slope * np.arange(wlo, e + 1) + intercept
    if float(np.nanmax(h[wlo:e + 1] - line)) / a[e] > cfg.get("res_poke_atr", 0.3):
        return None
    # ...and it must actually be touched, so it is a real line not a floating fit
    tol = cfg.get("res_touch_atr", 0.35)
    touches = sum(1 for j in rec
                  if abs(h[j] - (slope * j + intercept)) / a[e] <= tol)
    if touches < cfg.get("min_res_touches", 2):
        return None

    # 3. Geometry between the noodle upper band (lower rail) and resistance,
    #    measured in the coil.
    height = (res_now - up_band[e]) / a[e]       # channel height, ATR
    if height <= 0:
        return None
    main_slope = (main[e] - main[e - cfg["slope_lookback"]]) / cfg["slope_lookback"]
    conv = (main_slope - slope) / a[e]           # >0 = rails converging
    bars_to_apex = height / conv if conv > 0 else np.nan
    gap_atr = (res_now - c[e]) / a[e]            # how far below resistance price sits
    rng = (h[i] - l[i]) / a[i]                   # ...but the break is judged now

    # 4. State.
    tight = height <= cfg["max_channel_atr"]
    near = 0 <= gap_atr <= cfg["max_gap_atr"]
    broke = c[i] > res_at_i and rng >= cfg["breakout_range_atr"]
    if broke:
        state = "triggered"
    elif e < i:
        # Price has left the coil without a qualifying break - it is simply
        # extended now, not compressing. Do not report a stale coil as live.
        return None
    elif conv > 0 and tight and near:
        state = "compressed"
    elif conv > 0 and tight:
        state = "forming"
    else:
        return None

    # How long the tight, above-noodle channel has held.
    bis = 0
    for k in range(e, max(e - cfg["structure_lookback"], 0), -1):
        rk = slope * k + intercept
        hk = (rk - up_band[k]) / a[k] if a[k] > 0 else np.nan
        if np.isfinite(hk) and 0 < hk <= cfg["max_channel_atr"] and c[k] > up_band[k]:
            bis += 1
        else:
            break

    return {
        "state": state,
        "expansion_atr": round(float(expansion), 2),   # size of the prior impulse
        "consol_bars": int(e - peak),                  # coil length since that peak
        "consol_start": int(peak),                     # resistance is only valid from here
        "coil_end": int(e),                            # geometry measured here...
        "bars_since_coil": int(i - e),                 # ...this many bars before now
        "res_touches": int(touches),
        "channel_atr": round(float(height), 2),
        "gap_atr": round(float(gap_atr), 2),
        "bars_to_apex": None if not np.isfinite(bars_to_apex) else round(float(bars_to_apex), 1),
        "bars_in_state": bis,
        "res_kind": "horizontal" if horizontal else "angled",
        "resistance": round(float(res_now), 6),
        "res_slope": float(slope),
        "res_intercept": float(intercept),
        "invalidation": round(float(main[i]), 6),   # close back below the noodle main
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
