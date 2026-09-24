"""Long daily close history for cycle composites.

Composites need decades, not the ~1000 bars the scanner fetches. They also need
only the CLOSE - every curve is a percentage path from the year's first bar -
which is what makes the early Bitcoin problem solvable: reference-rate sources
carry no OHLC, but we do not need any.

Bitcoin cannot start in 2009. No exchange existed: the first trades were
hand-arranged (the 10,000-BTC pizza was May 2010), so there is no market price
to plot. Coin Metrics' reference rate begins 2010-07-18 at $0.086, which is
effectively the birth of a tradeable price, and gives complete calendar years
from 2011. blockchain.info appears to reach 2009-01-03 but pads with zeros
until 2010-08-18, so it is strictly worse despite the earlier first date.
"""
import io, os, time
import pandas as pd
import requests

CACHE = os.path.join("data", "longhist")
CM_API = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"

# key -> (display name, source, source id)
SYMBOLS = {
    "BTC":    ("Bitcoin",        "coinmetrics", "btc"),
    "ETH":    ("Ethereum",       "coinmetrics", "eth"),
    "SPX":    ("S&P 500",        "yahoo",       "^GSPC"),
    "NDX":    ("Nasdaq 100",     "yahoo",       "^NDX"),
    "DJI":    ("Dow Jones",      "yahoo",       "^DJI"),
    "RUT":    ("Russell 2000",   "yahoo",       "^RUT"),
    "GOLD":   ("Gold",           "yahoo",       "GC=F"),
    "SILVER": ("Silver",         "yahoo",       "SI=F"),
    "OIL":    ("Crude Oil (WTI)", "yahoo",      "CL=F"),
    "COPPER": ("Copper",         "yahoo",       "HG=F"),
}


def _coinmetrics(asset, start="2010-01-01"):
    """Daily reference rate. Paginates; the community tier needs no key."""
    out, url, params = [], CM_API, {
        "assets": asset, "metrics": "PriceUSD", "frequency": "1d",
        "start_time": start, "page_size": 10000,
    }
    while True:
        r = requests.get(url, params=params, timeout=45)
        r.raise_for_status()
        d = r.json()
        out.extend(d.get("data", []))
        nxt = d.get("next_page_url")
        if not nxt:
            break
        url, params = nxt, None
        time.sleep(0.2)
    if not out:
        return pd.DataFrame()
    df = pd.DataFrame(out)
    df["datetime"] = pd.to_datetime(df["time"]).dt.tz_localize(None).dt.normalize()
    df["close"] = pd.to_numeric(df["PriceUSD"], errors="coerce")
    df = df.dropna(subset=["close"])
    return df[["datetime", "close"]].reset_index(drop=True)


def _yahoo(ticker):
    from fetch import equity
    df = equity.klines(ticker, "1d", lookback="max")
    if df is None or df.empty:
        return pd.DataFrame()
    df = df[["datetime", "close"]].dropna().copy()
    df["datetime"] = pd.to_datetime(df["datetime"]).dt.normalize()
    return df.reset_index(drop=True)


def load(key, refresh_days=1):
    """Daily close history for one key. Cached; refetched when stale."""
    if key not in SYMBOLS:
        raise KeyError("unknown symbol %r" % key)
    name, src, sid = SYMBOLS[key]
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, "%s.csv.gz" % key)
    if os.path.exists(p):
        age_days = (time.time() - os.path.getmtime(p)) / 86400.0
        if age_days < refresh_days:
            return pd.read_csv(p, parse_dates=["datetime"])
    df = _coinmetrics(sid) if src == "coinmetrics" else _yahoo(sid)
    if df is None or df.empty:
        # Never discard a good cache because today's fetch failed.
        return pd.read_csv(p, parse_dates=["datetime"]) if os.path.exists(p) else None
    df.to_csv(p, index=False, compression="gzip")
    return df
