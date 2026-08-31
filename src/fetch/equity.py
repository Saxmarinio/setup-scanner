"""Equities / ETFs via yfinance. Daily only - see tiers.yaml for why 4H is out."""
import pandas as pd

def klines(ticker, tf="1d", lookback=None):
    import yfinance as yf
    interval = {"1d": "1d", "1h": "60m", "1w": "1wk", "1M": "1mo"}[tf]
    if lookback is None:
        # Weekly/monthly need long history for a stable DSS reading.
        lookback = {"1h": "60d", "1d": "3y", "1w": "8y", "1M": "max"}[tf]
    df = yf.download(ticker, period=lookback, interval=interval,
                     progress=False, auto_adjust=False)
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    df.columns = [str(c).lower() for c in df.columns]
    tcol = "datetime" if "datetime" in df.columns else "date"
    df = df.rename(columns={tcol: "datetime"})
    return df[["datetime", "open", "high", "low", "close", "volume"]].dropna()
