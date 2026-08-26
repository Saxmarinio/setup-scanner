import numpy as np, pandas as pd, math

SQ2PI = math.sqrt(2) * math.pi

def ss(src, lower):
    """Ehlers 2-pole SuperSmoother, matching the Pine ss() incl. the (src+src[1])/2 anti-alias."""
    a1 = math.exp(-SQ2PI / lower)
    c2 = 2 * a1 * math.cos(SQ2PI / lower)
    c3 = -a1 * a1
    c1 = 1 - c2 - c3
    x = np.asarray(src, dtype=float)
    n = len(x)
    f = np.zeros(n)
    for i in range(n):
        prev = x[i-1] if i >= 1 else x[i]          # nz(src[1], src)
        f1 = f[i-1] if i >= 1 else 0.0             # nz(f[1])
        f2 = f[i-2] if i >= 2 else 0.0             # nz(f[2])
        f[i] = c1 * (x[i] + prev) / 2 + c2 * f1 + c3 * f2
    return f

def hp(src, upper):
    """Ehlers 2-pole high-pass, matching the Pine hp()."""
    w = SQ2PI / upper
    a1 = (math.cos(w) + math.sin(w) - 1) / math.cos(w)
    k1 = (1 - a1 / 2) ** 2
    k2 = 2 * (1 - a1)
    k3 = (1 - a1) ** 2
    x = np.asarray(src, dtype=float)
    n = len(x)
    h = np.zeros(n)
    for i in range(n):
        x1 = x[i-1] if i >= 1 else x[i]
        x2 = x[i-2] if i >= 2 else x[i]
        h1 = h[i-1] if i >= 1 else 0.0
        h2 = h[i-2] if i >= 2 else 0.0
        h[i] = k1 * (x[i] - 2 * x1 + x2) + k2 * h1 - k3 * h2
    return h

def rma(x, length):
    """Pine ta.rma: Wilder smoothing, seeded with an SMA of the first `length` values."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    out = np.full(n, np.nan)
    if n < length:
        return out
    alpha = 1.0 / length
    seed = np.mean(x[:length])
    out[length-1] = seed
    for i in range(length, n):
        out[i] = alpha * x[i] + (1 - alpha) * out[i-1]
    return out

def rsi(src, length):
    """Pine ta.rsi = 100 - 100/(1+rma(up,len)/rma(down,len))."""
    x = np.asarray(src, dtype=float)
    d = np.diff(x, prepend=x[0])
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    ru, rd = rma(up, length), rma(dn, length)
    with np.errstate(divide='ignore', invalid='ignore'):
        rs = ru / rd
        out = 100 - 100 / (1 + rs)
    out = np.where(rd == 0, 100.0, out)
    out = np.where(ru == 0, 0.0, out)
    return out

def atr(h, l, c, length):
    h, l, c = map(lambda z: np.asarray(z, float), (h, l, c))
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return rma(tr, length)

def pivotlow(low, left, right):
    """Pine ta.pivotlow: bar i is a pivot if it is <= left window and < right window.
    Returned on bar i+right (i.e. confirmed `right` bars late)."""
    low = np.asarray(low, float)
    n = len(low)
    out = np.full(n, np.nan)
    for i in range(left, n - right):
        v = low[i]
        if np.all(v <= low[i-left:i]) and np.all(v < low[i+1:i+right+1]):
            out[i+right] = v
    return out

def build(df, roofHi=130, roofLo=10, oscLen=21, hurstLen=60, hurstMult=3.0):
    close = df['close'].values
    roofed = ss(hp(close, roofHi), roofLo)
    cyc = rsi(roofed, oscLen) / 100.0
    mcl = max(2, int(round(hurstLen / 2.0)))
    disp = max(1, int(round(mcl / 2.0)))
    ma = rma(close, mcl)
    offs = hurstMult * atr(df['high'].values, df['low'].values, close, mcl)
    ma_d = pd.Series(ma).shift(disp).values
    ma_d = np.where(np.isnan(ma_d), close, ma_d)
    mct, mcb = ma_d + offs, ma_d - offs
    denom = mct - mcb
    braw = np.where(denom != 0, (close - mcb) / denom, 0.5)
    bcl = np.clip(braw, -0.4, 1.4)
    return pd.DataFrame({'roofed': roofed, 'cyc': cyc, 'braw': braw, 'bclamp': bcl}, index=df.index)

def divergences(df, ind, pivL, pivR, margC, margB, maxGap, pctb_field='braw', keep=25):
    """Replicates the bullish divergence block: searches back through stored pivots."""
    low = df['low'].values
    cyc = ind['cyc'].values
    pb  = ind[pctb_field].values
    pl = pivotlow(low, pivL, pivR)
    store = []   # (bar, low, cyc, pctb)
    sigC, sigB = [], []
    for i in range(len(low)):
        if np.isnan(pl[i]):
            continue
        pbar = i - pivR
        pLo, pCy, pPb = low[pbar], cyc[pbar], pb[pbar]
        dC = dB = False
        for k in range(len(store) - 1, -1, -1):
            qb, qLo, qCy, qPb = store[k]
            if pbar - qb > maxGap:
                break
            if pLo < qLo:
                if not dC and pCy > qCy + margC:
                    dC = True
                if not dB and pPb > qPb + margB:
                    dB = True
            if dC and dB:
                break
        store.append((pbar, pLo, pCy, pPb))
        if len(store) > keep:
            store.pop(0)
        if dC: sigC.append(i)
        if dB: sigB.append(i)
    return sigC, sigB
