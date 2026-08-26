"""Incremental parquet store. One file per symbol/timeframe."""
import os, pandas as pd

ROOT = os.environ.get("SCANNER_DATA", "data")

def path(symbol, tf):
    d = os.path.join(ROOT, tf)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{symbol.replace('/', '_')}.parquet")

def load(symbol, tf):
    p = path(symbol, tf)
    if not os.path.exists(p):
        return None
    return pd.read_parquet(p)

def upsert(symbol, tf, new, keep_bars=1200):
    """Append new bars, drop the live (unclosed) bar, trim history."""
    old = load(symbol, tf)
    df = new if old is None else pd.concat([old, new])
    df = (df.drop_duplicates("datetime", keep="last")
            .sort_values("datetime")
            .tail(keep_bars)
            .reset_index(drop=True))
    df.to_parquet(path(symbol, tf), index=False)
    return df
