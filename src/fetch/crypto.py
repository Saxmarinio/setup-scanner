"""Bybit USDT linear perpetuals: universe + incremental klines.

Data source is the Bybit v5 public market API. Binance's fapi returns HTTP 451
(geo-block) from cloud / CI IP ranges such as GitHub Actions runners, so the
scanner reads the same USDT-perp universe from Bybit, which does not geo-block.

Universe changes (listings, delistings, migrations) are diffed against the
committed universe.json and reported. Do NOT silently absorb changes - a
delisting that disappears quietly will show up later as a stale symbol with
frozen bars.
"""
import json, os, time, requests, pandas as pd

BASE = "https://api.bybit.com"
# Bybit kline interval codes, keyed by our timeframe labels.
TF = {"1h": "60", "4h": "240", "1d": "D"}
TF_MS = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}

def _get(path, params=None, tries=5):
    """GET a Bybit v5 endpoint and return its `result` dict. Retries on
    transport errors and Bybit rate-limit codes with exponential backoff."""
    url = f"{BASE}{path}"
    for k in range(tries):
        try:
            r = requests.get(url, params=params, timeout=25)
            if r.status_code in (403, 429):            # rate limited at HTTP layer
                time.sleep(2 ** k)
                continue
            r.raise_for_status()
            j = r.json()
            rc = j.get("retCode")
            if rc == 0:
                return j["result"]
            if rc in (10006, 10018):                   # too many visits / rate limit
                time.sleep(2 ** k)
                continue
            raise RuntimeError(f"bybit retCode {rc}: {j.get('retMsg')}")
        except requests.RequestException:
            if k == tries - 1:
                raise
            time.sleep(2 ** k)
    raise RuntimeError(f"failed: {url}")

def universe(quote="USDT"):
    """All tradable Bybit linear perpetuals with the given quote coin, sorted."""
    syms, cursor = [], None
    while True:
        p = {"category": "linear", "limit": 1000}
        if cursor:
            p["cursor"] = cursor
        res = _get("/v5/market/instruments-info", p)
        for s in res.get("list", []):
            if (s.get("contractType") == "LinearPerpetual"
                    and s.get("status") == "Trading"
                    and s.get("quoteCoin") == quote):
                syms.append(s["symbol"])
        cursor = res.get("nextPageCursor")
        if not cursor:
            break
    return sorted(set(syms))

def diff_universe(current, path="universe.json"):
    prev = []
    if os.path.exists(path):
        prev = json.load(open(path)).get("symbols", [])
    added = sorted(set(current) - set(prev))
    removed = sorted(set(prev) - set(current))
    json.dump({"symbols": current}, open(path, "w"), indent=1)
    return added, removed

def klines(symbol, tf, start_ms=None, limit=1000):
    p = {"category": "linear", "symbol": symbol,
         "interval": TF[tf], "limit": min(limit, 1000)}
    if start_ms:
        p["start"] = start_ms
    res = _get("/v5/market/kline", p)
    raw = res.get("list", [])
    if not raw:
        return pd.DataFrame()
    # Bybit lists klines newest-first; reverse to chronological order.
    raw = raw[::-1]
    df = pd.DataFrame(raw, columns=[
        "ot", "open", "high", "low", "close", "volume", "turnover"])
    df["ot"] = df["ot"].astype("int64")
    df["datetime"] = pd.to_datetime(df["ot"], unit="ms")
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    # Drop the still-forming bar. Bar-close discipline: never evaluate a live bar.
    now = int(time.time() * 1000)
    df = df[df["ot"] + TF_MS[tf] <= now]
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
