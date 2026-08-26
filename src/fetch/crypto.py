"""Binance USD-M perpetuals: universe + incremental klines.

Universe changes (listings, delistings, migrations) are diffed against the
committed universe.json and reported, matching the pattern in the sector
pipeline. Do NOT silently absorb changes - a delisting that disappears
quietly will show up later as a stale symbol with frozen bars.
"""
import json, os, time, requests, pandas as pd

FAPI = "https://fapi.binance.com"
TF_MS = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}

def _get(url, params=None, tries=4):
    for k in range(tries):
        try:
            r = requests.get(url, params=params, timeout=25)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (418, 429):
                time.sleep(2 ** k)
                continue
            r.raise_for_status()
        except requests.RequestException:
            if k == tries - 1:
                raise
            time.sleep(2 ** k)
    raise RuntimeError(f"failed: {url}")

def universe(quote="USDT"):
    info = _get(f"{FAPI}/fapi/v1/exchangeInfo")
    return sorted(
        s["symbol"] for s in info["symbols"]
        if s.get("contractType") == "PERPETUAL"
        and s.get("status") == "TRADING"
        and s.get("quoteAsset") == quote
    )

def diff_universe(current, path="universe.json"):
    prev = []
    if os.path.exists(path):
        prev = json.load(open(path)).get("symbols", [])
    added = sorted(set(current) - set(prev))
    removed = sorted(set(prev) - set(current))
    json.dump({"symbols": current}, open(path, "w"), indent=1)
    return added, removed

def klines(symbol, tf, start_ms=None, limit=1000):
    p = {"symbol": symbol, "interval": tf, "limit": limit}
    if start_ms:
        p["startTime"] = start_ms
    raw = _get(f"{FAPI}/fapi/v1/klines", p)
    if not raw:
        return pd.DataFrame()
    df = pd.DataFrame(raw, columns=[
        "ot", "open", "high", "low", "close", "volume",
        "ct", "qv", "trades", "tb", "tq", "ig"])
    df["datetime"] = pd.to_datetime(df["ot"].astype("int64"), unit="ms")
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    # Drop the still-forming bar. Bar-close discipline: never evaluate a live bar.
    now = int(time.time() * 1000)
    df = df[df["ct"].astype("int64") < now]
    return df[["datetime", "open", "high", "low", "close", "volume"]]

def top_by_volume(symbols, n=10, window=30):
    """30d median quote volume from daily bars. Rule-based tier A membership."""
    scored = []
    for s in symbols:
        try:
            d = klines(s, "1d", limit=window + 2)
            if len(d) < window // 2:
                continue
            scored.append((s, float((d["close"] * d["volume"]).median())))
        except Exception:
            continue
        time.sleep(0.05)
    scored.sort(key=lambda x: -x[1])
    return [s for s, _ in scored[:n]]
