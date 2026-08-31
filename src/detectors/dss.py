"""DSS Bressert - Walter Bressert's Double Smoothed Stochastic.

A stochastic is taken over price, EMA-smoothed, then a stochastic is taken of
*that* smoothed line and EMA-smoothed again -> the DSS (fast) line. The slow
line is a further EMA of the fast line (the signal). Output is scaled 0-1.

Used here only as a confluence readout on daily/weekly/monthly for symbols the
scanner already surfaced - low values (<=0.1) mark bottoming swings, high
values (>=0.9) mark tops. Bars are the closed bars the fetchers return (the
live bar is dropped upstream), so a reading is "as of last close" of its TF.
"""
import numpy as np
import pandas as pd


def bressert(df, stoch_len=13, ema_len=8):
    """Return (fast, slow) in 0-1 for the latest bar, or None if too little
    history for a stable reading (e.g. a young monthly series)."""
    if df is None or len(df) < stoch_len + 2 * ema_len + stoch_len:
        return None
    c = df["close"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)

    # First stochastic on price.
    ll = l.rolling(stoch_len).min()
    hh = h.rolling(stoch_len).max()
    k1 = (100 * (c - ll) / (hh - ll).replace(0, np.nan)).dropna()
    if len(k1) < stoch_len + 2 * ema_len:
        return None
    s1 = k1.ewm(span=ema_len, adjust=False).mean()

    # Stochastic of the smoothed line (a single series: hi = lo = the line).
    ll2 = s1.rolling(stoch_len).min()
    hh2 = s1.rolling(stoch_len).max()
    k2 = (100 * (s1 - ll2) / (hh2 - ll2).replace(0, np.nan)).dropna()
    if len(k2) < ema_len:
        return None

    fast = k2.ewm(span=ema_len, adjust=False).mean()
    slow = fast.ewm(span=ema_len, adjust=False).mean()
    f, s = fast.iloc[-1] / 100.0, slow.iloc[-1] / 100.0
    if pd.isna(f) or pd.isna(s):
        return None
    return round(float(f), 3), round(float(s), 3)
