"""Money Noodle - EMA 12/21/35 ribbon with an ATR band around the main (35) line.

Direct port of the user's Pine "Money Noodle" indicator:
    main  = EMA(close, 35)
    offset = use_atr ? ATR(20) * band_mult * 40 : main * band_mult   (band_mult=0.0125)
    upper/lower = main +/- offset
With the ATR default, offset = 0.5 * ATR(20). The main line is the trend spine;
a close crossing the upper band is a bullish "noodle break", reclaiming the
lower band is a "bounce".
"""
import pandas as pd
from detectors.compression import ema, atr


def money_noodle(df, ema_fast=12, ema_medium=21, ema_slow=35,
                 atr_len=20, band_mult=0.0125, use_atr=True):
    c = df["close"].values
    h, l = df["high"].values, df["low"].values
    ef, em, es = ema(c, ema_fast), ema(c, ema_medium), ema(c, ema_slow)
    offset = atr(h, l, c, atr_len) * band_mult * 40.0 if use_atr else es * band_mult
    return pd.DataFrame(
        {"fast": ef, "medium": em, "main": es, "upper": es + offset, "lower": es - offset},
        index=df.index)


def break_flags(df, nd):
    """Latest-bar noodle events (bar-close): (break_up, break_down, bounce_up,
    bounce_down). break_up = close crossed above the upper band this bar."""
    c = df["close"].values
    up, lo = nd["upper"].values, nd["lower"].values
    if len(c) < 2:
        return {"break_up": False, "break_down": False, "bounce_up": False, "bounce_down": False}
    i = len(c) - 1
    return {
        "break_up":   c[i] > up[i] and c[i - 1] <= up[i - 1],
        "break_down": c[i] < lo[i] and c[i - 1] >= lo[i - 1],
        "bounce_up":  c[i] > lo[i] and c[i - 1] <= lo[i - 1],
        "bounce_down": c[i] < up[i] and c[i - 1] >= up[i - 1],
    }
