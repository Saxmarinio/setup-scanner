#!/usr/bin/env python3
"""1H compression parameter sweep.

Tier B ships with PROVISIONAL parameters. This exists because the 4H
divergence work showed daily-tuned values inverting on 4H - there is no
reason to assume 4H compression values transfer to 1H either.

Scores each config on the forward-return distribution after 'compressed'
bars, against a same-symbol baseline. Run on a SAMPLE of symbols, hold out
a second sample, and only promote parameters that survive both.
"""
import argparse, itertools, os, sys
import numpy as np, pandas as pd, yaml
sys.path.insert(0, os.path.dirname(__file__))
from detectors.compression import compression_state
from fetch import store

GRID = {
    "ribbon_pct_max": [0.10, 0.20, 0.30],
    "max_gap_atr":    [0.5, 1.0, 1.5],
    "min_slope_atr":  [0.01, 0.02, 0.04],
    "pivot_left":     [5, 8, 12],
}

def forward(df, idx, horizon):
    c = df["close"].values
    return [(c[min(i + horizon, len(c) - 1)] / c[i] - 1) * 100 for i in idx]

def evaluate(dfs, base, horizon, step=4):
    hits, allfwd = [], []
    for df in dfs:
        c = df["close"].values
        allfwd += [(c[min(i + horizon, len(c) - 1)] / c[i] - 1) * 100
                   for i in range(300, len(c) - horizon, 20)]
        for end in range(300, len(df), step):
            r = compression_state(df.iloc[:end], base)
            if r and r["state"] == "compressed":
                hits.append(end - 1)
        if hits:
            allfwd += []
    return hits, allfwd

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1h")
    ap.add_argument("--symbols", nargs="+", required=True)
    ap.add_argument("--horizon", type=int, default=24)
    a = ap.parse_args()

    cfg = yaml.safe_load(open("config/tiers.yaml"))
    base = dict(cfg["compression"][a.tf])
    dfs = [d for d in (store.load(s, a.tf) for s in a.symbols) if d is not None and len(d) > 400]
    if not dfs:
        print("no cached data - run scan.py first to populate the store")
        return

    keys = list(GRID)
    rows = []
    for combo in itertools.product(*(GRID[k] for k in keys)):
        c = dict(base); c.update(dict(zip(keys, combo)))
        fwds, n = [], 0
        for df in dfs:
            for end in range(300, len(df) - a.horizon, 4):
                r = compression_state(df.iloc[:end], c)
                if r and r["state"] == "compressed":
                    px = df["close"].values
                    fwds.append((px[min(end - 1 + a.horizon, len(px) - 1)] / px[end - 1] - 1) * 100)
                    n += 1
        if n < 10:
            continue
        rows.append(dict(zip(keys, combo)) | {
            "n": n, "median": round(float(np.median(fwds)), 2),
            "hit": round(float(np.mean(np.array(fwds) > 0)) * 100, 1)})
    out = pd.DataFrame(rows).sort_values("median", ascending=False)
    print(out.to_string(index=False))
    out.to_csv(f"calibration_{a.tf}.csv", index=False)
    print("\nDo NOT adopt the top row. Pick a config in a STABLE region of the "
          "grid and re-run on held-out symbols.")

if __name__ == "__main__":
    main()
