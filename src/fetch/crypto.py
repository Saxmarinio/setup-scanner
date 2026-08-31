"""Binance USDT spot pairs: universe + incremental klines.

Data source is Binance's public market-data mirror, data-api.binance.vision.
Binance's live fapi/api hosts return HTTP 451 (geo-block) from cloud / CI IP
ranges such as GitHub Actions runners, and other perp venues (Bybit, OKX)
403 the same IPs. The .vision mirror is the auth-free public-data CDN Binance
publishes for exactly this case - it is not geo-blocked.

The mirror serves SPOT candles, not perpetual futures. The compression and
divergence detectors run on plain OHLCV and use nothing perp-specific, so spot
BTCUSDT etc. is a faithful stand-in and TradingView links resolve to the same
symbols. Leveraged tokens (…UP/DOWN/BULL/BEARUSDT) are excluded.

Universe changes (listings, delistings) are diffed against the committed
universe.json and reported. Do NOT silently absorb changes - a delisting that
disappears quietly will show up later as a stale symbol with frozen bars.
"""
import json, os, time, requests, pandas as pd

BASE = "https://data-api.binance.vision"
TF_MS = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
_LEVERAGED = ("UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT")
# Stablecoin / fiat bases: high volume, ~flat price - pure noise for the
# compression and divergence detectors, and they otherwise dominate the
# 24h-volume tier-A ranking (USDCUSDT, FDUSDUSDT, ...). Kept out entirely.
_STABLE_BASES = {
    "USDC", "FDUSD", "TUSD", "USD1", "RLUSD", "DAI", "USDP", "BUSD", "USDD",
    "PYUSD", "USTC", "AEUR", "EUR", "EURI", "GBP", "TRY", "BRL", "ARS", "JPY",
    "MXN", "PLN", "RON", "ZAR", "CZK", "COP", "UAH", "NGN", "IDRT", "BIDR",
}
# Commodity-pegged tokens (gold): their own list, kept out of the crypto tiers.
_COMMODITY_BASES = {"XAUT", "PAXG", "XAU"}
# Binance's tokenized US stocks (AAPLB, NVDAB, ...) share one exact trading-
# permission fingerprint that real crypto never has. We read that fingerprint
# off these blue-chip references (any present is enough), so newly-listed
# tokenized stocks are classified automatically without a hardcoded roster.
_TOK_REFS = ("AAPLB", "MSFTB", "NVDAB", "TSLAB", "SPYB", "QQQB", "GOOGLB", "METAB")

def _fingerprint(s):
    ps = s.get("permissionSets") or [s.get("permissions", [])]
    return tuple(sorted(ps[0])) if ps and ps[0] else ()

def categorize(quote="USDT"):
    """Split tradable spot pairs into crypto / tokenized-stock / commodity.
    Stablecoins and leveraged tokens are dropped entirely."""
    info = _get(f"{BASE}/api/v3/exchangeInfo")
    syms = [s for s in info["symbols"]
            if s.get("status") == "TRADING"
            and s.get("quoteAsset") == quote
            and s.get("isSpotTradingAllowed")]
    bym = {s["baseAsset"]: s for s in syms}
    tok_fps = {_fingerprint(bym[r]) for r in _TOK_REFS if r in bym}
    crypto, stock, commodity = [], [], []
    for s in syms:
        base = s.get("baseAsset")
        if base in _STABLE_BASES or s["symbol"].endswith(_LEVERAGED):
            continue
        if base in _COMMODITY_BASES:
            commodity.append(s["symbol"])
        elif tok_fps and _fingerprint(s) in tok_fps:
            stock.append(s["symbol"])
        else:
            crypto.append(s["symbol"])
    return {"crypto": sorted(set(crypto)),
            "stock": sorted(set(stock)),
            "commodity": sorted(set(commodity))}

def stock_underlyings(quote="USDT"):
    """Real equity tickers behind the tokenized stocks (Binance tags them with a
    trailing 'B': AAPLB -> AAPL). Auto-tracks tier D; a few obscure ones won't
    resolve on Yahoo and are simply skipped downstream."""
    out = []
    for sym in categorize(quote)["stock"]:
        base = sym[:-len(quote)]          # AAPLBUSDT -> AAPLB
        if base.endswith("B"):
            out.append(base[:-1])         # AAPLB -> AAPL
    return sorted(set(out))

def _get(url, params=None, tries=4):
    for k in range(tries):
        try:
            r = requests.get(url, params=params, timeout=25)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (418, 429, 403):       # rate limited / throttled
                time.sleep(2 ** k)
                continue
            r.raise_for_status()
        except requests.RequestException:
            if k == tries - 1:
                raise
            time.sleep(2 ** k)
    raise RuntimeError(f"failed: {url}")

def universe(quote="USDT"):
    """Pure-crypto spot pairs (tokenized stocks and commodities excluded)."""
    return categorize(quote)["crypto"]

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
    raw = _get(f"{BASE}/api/v3/klines", p)
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

def top_by_volume(symbols, n=10, window=30, shortlist=40):
    """Top-n crypto by `window`-day MEDIAN quote volume. Rule-based tier A
    membership, recomputed each run.

    Ranking is by median daily volume, not 24h: a one-day volume spike (an alt
    mid-pump) must NOT buy its way into tier A - membership should be the names
    that are *sustainably* liquid. To stay cheap, this is a two-pass shortlist:
    one bulk 24h-ticker call picks the top `shortlist` candidates, then only
    those get a daily-klines fetch for the true median. That is ~50 requests
    instead of one-per-symbol across the whole ~470-name universe (which was
    far too slow / rate-limit-prone against the public mirror), while giving
    the same stable ranking as scanning everyone.
    """
    wanted = set(symbols)
    data = _get(f"{BASE}/api/v3/ticker/24hr")
    by24 = sorted(((d["symbol"], float(d.get("quoteVolume") or 0.0))
                   for d in data if d["symbol"] in wanted), key=lambda x: -x[1])
    candidates = [s for s, _ in by24[:shortlist]]
    scored = []
    for s in candidates:
        try:
            d = klines(s, "1d", limit=window + 2)
            if len(d) < window // 2:
                continue
            scored.append((s, float((d["close"] * d["volume"]).median())))
        except Exception:
            continue
        time.sleep(0.03)
    scored.sort(key=lambda x: -x[1])
    return [s for s, _ in scored[:n]]
